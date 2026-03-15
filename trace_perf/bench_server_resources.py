"""Monitor server memory and CPU usage over time under sustained load.

Sends traces at a target QPS and samples RSS/CPU every second,
producing a time series to show how resources evolve during the test.

Usage:
    uv run python trace_perf/bench_server_resources.py
    uv run python trace_perf/bench_server_resources.py --qps 20 --duration 120
    uv run python trace_perf/bench_server_resources.py --qps 5,10,20 --spans 10,50,100
    uv run python trace_perf/bench_server_resources.py --span-size 5KB --spans 50 --plot
"""

from __future__ import annotations

import argparse
import json
import random
import resource
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from itertools import groupby
from pathlib import Path
from unittest import mock

from opentelemetry import trace as trace_api
from opentelemetry.sdk.resources import Resource as OTelResource
from opentelemetry.sdk.trace import ReadableSpan as OTelReadableSpan
from utils import create_store, generate_spans, generate_trace_info, get_db_size_mb, percentile

from mlflow.entities.span import SpanType, create_mlflow_span
from mlflow.tracing.utils import TraceJSONEncoder

SEP = "=" * 100
DASH = "-" * 100

# Span size presets: number of extra attributes to add per span
# Each attribute adds ~80-150 bytes of JSON
SPAN_SIZE_PRESETS = {
    "default": 0,  # ~0.5 KB/span (just basic attrs)
    "1KB": 5,  # ~1.2 KB/span
    "5KB": 30,  # ~5 KB/span
    "10KB": 60,  # ~10 KB/span
    "20KB": 130,  # ~20 KB/span
}


def _make_span_context(trace_num: int, span_num: int) -> mock.Mock:
    ctx = mock.Mock()
    ctx.trace_id = trace_num
    ctx.span_id = span_num
    ctx.is_remote = False
    ctx.trace_flags = trace_api.TraceFlags(1)
    ctx.trace_state = trace_api.TraceState()
    return ctx


def _generate_inflated_spans(trace_id, num_spans, extra_attrs, rng):
    if extra_attrs == 0:
        return generate_spans(trace_id, num_spans, rng)

    trace_num = rng.randint(1, 2**63)
    base_ns = 1_000_000_000_000
    spans = []

    for i in range(num_spans):
        is_root = i == 0
        parent_id = None if is_root else rng.choice(range(1, i + 1))

        attrs = {
            "mlflow.traceRequestId": json.dumps(trace_id),
            "mlflow.spanType": json.dumps(SpanType.LLM, cls=TraceJSONEncoder),
        }
        for j in range(extra_attrs):
            attrs[f"custom.attr_{j}"] = json.dumps(
                {"value": f"attr_{j}_" + "x" * rng.randint(10, 80), "meta": {"i": j}},
                cls=TraceJSONEncoder,
            )

        parent_ctx = _make_span_context(trace_num, parent_id) if parent_id else None
        otel_span = OTelReadableSpan(
            name=f"span_{i}" if not is_root else "root",
            context=_make_span_context(trace_num, i + 1),
            parent=parent_ctx,
            attributes=attrs,
            start_time=base_ns + i * 10_000_000,
            end_time=base_ns + i * 10_000_000 + rng.randint(5_000_000, 50_000_000),
            status=trace_api.Status(trace_api.StatusCode.OK),
            resource=OTelResource.get_empty(),
        )
        spans.append(create_mlflow_span(otel_span, trace_id, SpanType.LLM))
    return spans


def _get_rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":  # pragma: no branch
        return usage.ru_maxrss / (1024 * 1024)
    return usage.ru_maxrss / 1024  # Linux: already in KB


def _get_cpu_times() -> tuple[float, float]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime, usage.ru_stime


@dataclass
class Sample:
    elapsed_s: float
    rss_mb: float
    cpu_pct: float
    traces_so_far: int
    qps_instant: float
    latency_p50_ms: float
    db_size_mb: float = 0.0


@dataclass
class ResourceTestResult:
    spans_per_trace: int
    target_qps: int
    duration_s: float
    span_size_label: str = "default"
    samples: list[Sample] = field(default_factory=list)
    final_traces: int = 0
    final_qps: float = 0.0
    final_rss_mb: float = 0.0
    rss_start_mb: float = 0.0


def run_resource_test(
    store,
    experiment_id: str,
    spans_per_trace: int,
    target_qps: int,
    duration_s: float,
    extra_attrs: int = 0,
    span_size_label: str = "default",
    sample_interval_s: float = 1.0,
    db_path: str | None = None,
) -> ResourceTestResult:
    rng = random.Random(42)
    base_time_ms = 1_700_000_000_000
    interval = 1.0 / target_qps if target_qps > 0 else None

    # Pre-generate traces
    pool_size = int(target_qps * duration_s * 1.5) + 50
    pool = [
        (
            generate_trace_info(
                tid := f"tr-{uuid.uuid4().hex}",
                experiment_id,
                base_time_ms + i * 1000,
                rng,
            ),
            _generate_inflated_spans(tid, spans_per_trace, extra_attrs, rng),
        )
        for i in range(pool_size)
    ]

    # Warmup
    for i in range(min(3, len(pool))):
        ti, sp = pool[i]
        store.start_trace(ti)
        store.log_spans(experiment_id, sp)

    result = ResourceTestResult(
        spans_per_trace=spans_per_trace,
        target_qps=target_qps,
        duration_s=duration_s,
        span_size_label=span_size_label,
    )

    # Shared state between writer and sampler
    trace_count = 0
    recent_latencies: list[float] = []
    latency_lock = threading.Lock()
    stop_event = threading.Event()

    rss_start = _get_rss_mb()
    cpu_start = _get_cpu_times()
    wall_start = time.perf_counter()
    result.rss_start_mb = rss_start

    def _sampler():
        prev_cpu = cpu_start
        prev_wall = wall_start
        while not stop_event.wait(sample_interval_s):
            now = time.perf_counter()
            elapsed = now - wall_start
            rss = _get_rss_mb()
            cpu_now = _get_cpu_times()

            dt = now - prev_wall
            cpu_delta = (cpu_now[0] - prev_cpu[0]) + (cpu_now[1] - prev_cpu[1])
            cpu_pct = (cpu_delta / dt * 100) if dt > 0 else 0.0

            with latency_lock:
                lat_snapshot = list(recent_latencies)
                recent_latencies.clear()

            lat_p50 = percentile(lat_snapshot, 50) if lat_snapshot else 0.0
            qps_instant = len(lat_snapshot) / dt if dt > 0 else 0.0

            db_sz = get_db_size_mb(store, Path(db_path) if db_path else None) or 0.0

            result.samples.append(
                Sample(
                    elapsed_s=elapsed,
                    rss_mb=rss,
                    cpu_pct=cpu_pct,
                    traces_so_far=trace_count,
                    qps_instant=qps_instant,
                    latency_p50_ms=lat_p50,
                    db_size_mb=db_sz,
                )
            )

            prev_cpu = cpu_now
            prev_wall = now

    sampler_thread = threading.Thread(target=_sampler, daemon=True)
    sampler_thread.start()

    # Writer
    pool_idx = 3
    next_send = wall_start
    deadline = wall_start + duration_s

    while True:
        now = time.perf_counter()
        if now >= deadline:
            break

        if interval is not None:
            sleep_for = next_send - now
            if sleep_for > 0:
                time.sleep(sleep_for)
            next_send += interval

        if pool_idx >= len(pool):
            tid = f"tr-{uuid.uuid4().hex}"
            ti = generate_trace_info(tid, experiment_id, base_time_ms + pool_idx * 1000, rng)
            sp = _generate_inflated_spans(tid, spans_per_trace, extra_attrs, rng)
            pool.append((ti, sp))

        ti, sp = pool[pool_idx]
        pool_idx += 1

        t0 = time.perf_counter()
        store.start_trace(ti)
        store.log_spans(experiment_id, sp)
        lat = (time.perf_counter() - t0) * 1000

        with latency_lock:
            recent_latencies.append(lat)
        trace_count += 1

    stop_event.set()
    sampler_thread.join(timeout=2)

    wall_elapsed = time.perf_counter() - wall_start
    result.final_traces = trace_count
    result.final_qps = trace_count / wall_elapsed if wall_elapsed > 0 else 0
    result.final_rss_mb = _get_rss_mb()

    return result


def print_time_series(result: ResourceTestResult) -> None:
    size_note = (
        f", span size={result.span_size_label}" if result.span_size_label != "default" else ""
    )
    print(
        f"\n  Config: {result.spans_per_trace} spans/trace, "
        f"target {result.target_qps} QPS, {result.duration_s:.0f}s{size_note}"
    )
    print(
        f"  Result: {result.final_traces} traces, "
        f"{result.final_qps:.1f} achieved QPS, "
        f"RSS {result.rss_start_mb:.1f} → {result.final_rss_mb:.1f} MB"
    )
    print(DASH)

    header = (
        f"{'time(s)':>8} | {'RSS(MB)':>8} | {'CPU %':>6} | "
        f"{'traces':>7} | {'QPS':>6} | {'p50(ms)':>8} | {'DB(MB)':>7}"
    )
    print(header)
    print(DASH)

    for s in result.samples:
        print(
            f"{s.elapsed_s:>8.1f} | {s.rss_mb:>8.1f} | {s.cpu_pct:>5.1f}% | "
            f"{s.traces_so_far:>7} | {s.qps_instant:>6.1f} | {s.latency_p50_ms:>8.1f} | "
            f"{s.db_size_mb:>7.1f}"
        )


def plot_results(results: list[ResourceTestResult], title_suffix: str, out_path: str) -> None:
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(4, 1, figsize=(12, 13), sharex=True)
    fig.suptitle(f"Server Resources Over Time ({title_suffix})", fontsize=14)

    for result in results:
        times = [s.elapsed_s for s in result.samples]
        label = f"{result.target_qps} QPS"
        if result.span_size_label != "default":
            label += f" ({result.span_size_label})"

        axes[0].plot(times, [s.cpu_pct for s in result.samples], label=label, marker=".")
        axes[1].plot(times, [s.rss_mb for s in result.samples], label=label, marker=".")
        axes[2].plot(times, [s.qps_instant for s in result.samples], label=label, marker=".")
        axes[3].plot(times, [s.db_size_mb for s in result.samples], label=label, marker=".")

    axes[0].set_ylabel("CPU %")
    axes[0].set_title("CPU Utilization")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    axes[1].set_ylabel("RSS (MB)")
    axes[1].set_title("Memory (RSS)")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    axes[2].set_ylabel("QPS")
    axes[2].set_title("Achieved Throughput")
    axes[2].legend()
    axes[2].grid(True, alpha=0.3)

    axes[3].set_ylabel("DB Size (MB)")
    axes[3].set_xlabel("Time (s)")
    axes[3].set_title("Database Size")
    axes[3].legend()
    axes[3].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"\n  Plot saved to {out_path}")
    plt.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor server resources under sustained load")
    parser.add_argument("--qps", default="10", help="Target QPS, comma-separated (default: 10)")
    parser.add_argument(
        "--spans",
        default="10",
        help="Spans per trace, comma-separated (default: 10)",
    )
    parser.add_argument(
        "--span-size",
        default="default",
        help=f"Span size preset: {', '.join(SPAN_SIZE_PRESETS.keys())} (default: default)",
    )
    parser.add_argument(
        "--duration", type=float, default=60.0, help="Duration in seconds (default: 60)"
    )
    parser.add_argument(
        "--sample-interval",
        type=float,
        default=1.0,
        help="Sampling interval in seconds (default: 1.0)",
    )
    parser.add_argument("--db-uri", default=None, help="SQLAlchemy DB URI (default: SQLite)")
    parser.add_argument("--plot", action="store_true", help="Generate plots/server_resources.png")
    args = parser.parse_args()

    qps_targets = [int(x) for x in args.qps.split(",")]
    span_counts = [int(x) for x in args.spans.split(",")]
    span_size_label = args.span_size
    extra_attrs = SPAN_SIZE_PRESETS.get(span_size_label, 0)

    store, tmpdir = create_store(args.db_uri)
    db_label = args.db_uri.split("://")[0] if args.db_uri else "sqlite"
    db_path = str(tmpdir / "mlflow.db") if not args.db_uri else None

    configs = [(s, q) for s in span_counts for q in qps_targets]
    size_note = f", span size={span_size_label}" if span_size_label != "default" else ""

    print(f"\n{SEP}")
    print(
        f"  Server Resource Monitor ({db_label}, "
        f"{len(configs)} configs, {args.duration:.0f}s each{size_note})"
    )
    print(f"  Spans: {span_counts} | QPS targets: {qps_targets}")
    print(SEP)

    all_results: list[ResourceTestResult] = []
    for i, (num_spans, target_qps) in enumerate(configs, 1):
        exp_id = str(store.create_experiment(f"resources_{num_spans}s_{target_qps}qps"))
        print(
            f"\n  [{i}/{len(configs)}] {num_spans} spans, {target_qps} QPS...",
            flush=True,
        )

        result = run_resource_test(
            store=store,
            experiment_id=exp_id,
            spans_per_trace=num_spans,
            target_qps=target_qps,
            duration_s=args.duration,
            extra_attrs=extra_attrs,
            span_size_label=span_size_label,
            sample_interval_s=args.sample_interval,
            db_path=db_path,
        )
        all_results.append(result)
        print_time_series(result)

    if args.plot:
        # Group by span count → one plot per span count
        for num_spans, group in groupby(all_results, key=lambda r: r.spans_per_trace):
            group_results = list(group)
            title = f"{num_spans} spans/trace, {db_label}{size_note}"
            out_path = f"plots/server_resources_{num_spans}sp.png"
            plot_results(group_results, title, out_path)

    print(SEP)


if __name__ == "__main__":
    main()
