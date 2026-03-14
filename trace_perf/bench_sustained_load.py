"""
Sustained-load benchmark: measures how QPS x trace size impacts latency,
CPU utilization, and DB size.

For each (spans_per_trace, payload_size, target_qps) combination, submits
traces at the target rate for a fixed duration and records:
  - Achieved QPS (actual throughput)
  - Latency distribution (p50, p95, p99)
  - CPU utilization (user + system time / wall time)
  - DB size

Usage:
    uv run python trace_perf/bench_sustained_load.py
    uv run python trace_perf/bench_sustained_load.py --duration 30
    uv run python trace_perf/bench_sustained_load.py --spans 10,50,100 --qps 5,10,20
"""

from __future__ import annotations

import argparse
import json
import random
import resource
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from opentelemetry.sdk.resources import Resource as OTelResource
from opentelemetry.sdk.trace import ReadableSpan as OTelReadableSpan
from utils import generate_spans, generate_trace_info, get_db_size_mb

from mlflow.entities.span import Span, SpanType, create_mlflow_span
from mlflow.store.tracking.sqlalchemy_store import SqlAlchemyStore
from mlflow.tracing.constant import SpanAttributeKey
from mlflow.tracing.utils import TraceJSONEncoder

# ---------------------------------------------------------------------------
# Payload generation (reused from bench_client_serialization.py)
# ---------------------------------------------------------------------------

WORDS = [
    "the",
    "machine",
    "learning",
    "model",
    "processes",
    "input",
    "data",
    "neural",
    "network",
    "training",
    "inference",
    "transformer",
    "attention",
    "embedding",
    "gradient",
    "optimization",
    "loss",
    "function",
    "parameter",
]


def _generate_large_payload(target_bytes: int, rng: random.Random) -> dict[str, object]:
    messages = []
    current_size = 0
    roles = ["user", "assistant"]
    idx = 0
    while current_size < target_bytes:
        remaining = target_bytes - current_size
        content_len = min(remaining, rng.randint(200, 2000))
        content = " ".join(rng.choices(WORDS, k=content_len // 6))[:content_len]
        msg = {"role": roles[idx % 2], "content": content}
        messages.append(msg)
        current_size += len(json.dumps(msg))
        idx += 1
    return {"messages": messages, "model": "gpt-4", "temperature": 0.7}


def _make_spans_with_payload(
    trace_id: str,
    num_spans: int,
    input_payload: dict[str, object] | None,
    output_payload: dict[str, object] | None,
    rng: random.Random,
) -> list[Span]:
    spans = generate_spans(trace_id, num_spans, rng)
    if input_payload is None and output_payload is None:
        return spans

    root = spans[0]
    attrs = dict(root._span.attributes)
    if input_payload is not None:
        attrs[SpanAttributeKey.INPUTS] = json.dumps(input_payload, cls=TraceJSONEncoder)
    if output_payload is not None:
        attrs[SpanAttributeKey.OUTPUTS] = json.dumps(output_payload, cls=TraceJSONEncoder)

    otel_span = OTelReadableSpan(
        name=root.name,
        context=root._span.context,
        parent=root._span.parent,
        attributes=attrs,
        start_time=root.start_time_ns,
        end_time=root.end_time_ns,
        status=root._span.status,
        resource=OTelResource.get_empty(),
    )
    spans[0] = create_mlflow_span(otel_span, trace_id, SpanType.AGENT)
    return spans


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class LoadTestResult:
    spans_per_trace: int
    payload_label: str
    target_qps: str  # "max" or numeric
    duration_s: float
    traces_submitted: int
    achieved_qps: float
    latencies_ms: list[float]
    p50_ms: float
    p95_ms: float
    p99_ms: float
    cpu_user_s: float
    cpu_sys_s: float
    cpu_utilization: float
    db_size_mb: float


def _percentile(data: list[float], pct: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * pct / 100
    f = int(k)
    return s[f] + (k - f) * (s[min(f + 1, len(s) - 1)] - s[f])


def _get_cpu_times() -> tuple[float, float]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime, usage.ru_stime


# ---------------------------------------------------------------------------
# Load test runner
# ---------------------------------------------------------------------------


def run_load_test(
    store: SqlAlchemyStore,
    experiment_id: str,
    spans_per_trace: int,
    payload_label: str,
    input_payload: dict[str, object] | None,
    output_payload: dict[str, object] | None,
    target_qps: float | None,  # None = max throughput
    duration_s: float,
    db_path: Path | None,
) -> LoadTestResult:
    rng = random.Random(42)
    base_time_ms = 1_700_000_000_000
    interval = 1.0 / target_qps if target_qps else None
    target_label = "max" if target_qps is None else str(int(target_qps))

    # Pre-generate a pool of traces to avoid data generation cost during measurement.
    # Pool size: enough for the expected duration + headroom.
    pool_size = int((target_qps or 100) * duration_s * 1.5) + 50
    pool = []
    for i in range(pool_size):
        tid = f"tr-{uuid.uuid4().hex}"
        ti = generate_trace_info(tid, experiment_id, base_time_ms + i * 1000, rng)
        spans = _make_spans_with_payload(tid, spans_per_trace, input_payload, output_payload, rng)
        pool.append((ti, spans))

    # Warmup: 3 traces
    for i in range(min(3, len(pool))):
        ti, sp = pool[i]
        store.start_trace(ti)
        store.log_spans(experiment_id, sp)

    # Measured run
    cpu_before = _get_cpu_times()
    wall_start = time.perf_counter()
    deadline = wall_start + duration_s

    latencies: list[float] = []
    pool_idx = 3
    next_send = wall_start

    while True:
        now = time.perf_counter()
        if now >= deadline:
            break

        # Rate limiting: sleep until next scheduled send
        if interval is not None:
            sleep_for = next_send - now
            if sleep_for > 0:
                time.sleep(sleep_for)
            next_send += interval

        if pool_idx >= len(pool):
            # Extend pool if we run out
            tid = f"tr-{uuid.uuid4().hex}"
            ti = generate_trace_info(tid, experiment_id, base_time_ms + pool_idx * 1000, rng)
            spans = _make_spans_with_payload(
                tid, spans_per_trace, input_payload, output_payload, rng
            )
            pool.append((ti, spans))

        ti, sp = pool[pool_idx]
        pool_idx += 1

        t0 = time.perf_counter()
        store.start_trace(ti)
        store.log_spans(experiment_id, sp)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000)

    wall_end = time.perf_counter()
    cpu_after = _get_cpu_times()

    wall_elapsed = wall_end - wall_start
    cpu_user = cpu_after[0] - cpu_before[0]
    cpu_sys = cpu_after[1] - cpu_before[1]
    cpu_total = cpu_user + cpu_sys
    cpu_util = cpu_total / wall_elapsed if wall_elapsed > 0 else 0.0

    db_size_mb = get_db_size_mb(store, db_path) or 0.0

    return LoadTestResult(
        spans_per_trace=spans_per_trace,
        payload_label=payload_label,
        target_qps=target_label,
        duration_s=wall_elapsed,
        traces_submitted=len(latencies),
        achieved_qps=len(latencies) / wall_elapsed if wall_elapsed > 0 else 0,
        latencies_ms=latencies,
        p50_ms=_percentile(latencies, 50),
        p95_ms=_percentile(latencies, 95),
        p99_ms=_percentile(latencies, 99),
        cpu_user_s=cpu_user,
        cpu_sys_s=cpu_sys,
        cpu_utilization=cpu_util,
        db_size_mb=db_size_mb,
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

SEP = "=" * 110
DASH = "-" * 110


def print_results(results: list[LoadTestResult]) -> None:
    print(f"\n{SEP}")
    print("          Sustained Load Benchmark Results")
    print(SEP)

    header = (
        f"{'spans':>5} {'payload':>10} {'target':>7} | "
        f"{'traces':>6} {'QPS':>7} | "
        f"{'p50(ms)':>8} {'p95(ms)':>8} {'p99(ms)':>8} | "
        f"{'CPU usr':>7} {'CPU sys':>7} {'CPU %':>6} | "
        f"{'DB (MB)':>8}"
    )
    print(header)
    print(DASH)

    for r in results:
        print(
            f"{r.spans_per_trace:>5} {r.payload_label:>10} {r.target_qps:>7} | "
            f"{r.traces_submitted:>6} {r.achieved_qps:>7.1f} | "
            f"{r.p50_ms:>8.1f} {r.p95_ms:>8.1f} {r.p99_ms:>8.1f} | "
            f"{r.cpu_user_s:>7.2f} {r.cpu_sys_s:>7.2f} {r.cpu_utilization * 100:>5.1f}% | "
            f"{r.db_size_mb:>8.1f}"
        )

    print(SEP)

    # Saturation analysis
    print("\nSaturation analysis:")
    print(DASH)
    configs = sorted({(r.spans_per_trace, r.payload_label) for r in results})
    for spans, payload in configs:
        group = [r for r in results if r.spans_per_trace == spans and r.payload_label == payload]
        if max_run := next((r for r in group if r.target_qps == "max"), None):
            print(
                f"  {spans} spans, {payload}: max throughput = {max_run.achieved_qps:.1f} traces/s "
                f"({max_run.achieved_qps * spans:.0f} spans/s)"
            )
            for r in group:
                if r.target_qps == "max":
                    continue
                target = int(r.target_qps)
                if r.achieved_qps < target * 0.95:
                    print(
                        f"    ⚠ target {target} QPS: achieved only {r.achieved_qps:.1f} "
                        f"(saturated, p99={r.p99_ms:.0f} ms)"
                    )
                else:
                    headroom = (max_run.achieved_qps - r.achieved_qps) / max_run.achieved_qps * 100
                    print(
                        f"    ✓ target {target} QPS: achieved {r.achieved_qps:.1f} "
                        f"(p99={r.p99_ms:.0f} ms, ~{headroom:.0f}% headroom)"
                    )
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Sustained-load trace benchmark")
    parser.add_argument(
        "--spans",
        default="10,50,100",
        help="Comma-separated span counts (default: 10,50,100)",
    )
    parser.add_argument(
        "--payloads",
        default="small,100KB",
        help="Comma-separated payload sizes: small, 1KB, 10KB, 100KB, 1MB (default: small,100KB)",
    )
    parser.add_argument(
        "--qps",
        default="max,5,10,20",
        help="Comma-separated target QPS values, use 'max' for unlimited (default: max,5,10,20)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=60.0,
        help="Duration per test in seconds (default: 60)",
    )
    parser.add_argument(
        "--db-uri",
        default=None,
        help="SQLAlchemy DB URI (default: sqlite in tmpdir)",
    )
    args = parser.parse_args()

    span_counts = [int(x) for x in args.spans.split(",")]
    payload_labels = [x.strip() for x in args.payloads.split(",")]
    qps_targets = [x.strip() for x in args.qps.split(",")]

    payload_bytes = {
        "small": 0,
        "1KB": 1_000,
        "10KB": 10_000,
        "100KB": 100_000,
        "1MB": 1_000_000,
    }

    rng = random.Random(99)
    # Pre-generate payloads
    payloads: dict[str, tuple[dict[str, object] | None, dict[str, object] | None]] = {}
    for label in payload_labels:
        if label == "small":
            payloads[label] = (None, None)
        else:
            target = payload_bytes[label]
            payloads[label] = (
                _generate_large_payload(target, rng),
                _generate_large_payload(target, rng),
            )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        db_path = tmpdir_path / "mlflow.db"
        db_uri = args.db_uri or f"sqlite:///{db_path}"
        artifact_root = (tmpdir_path / "artifacts").as_uri()
        (tmpdir_path / "artifacts").mkdir(exist_ok=True)

        store = SqlAlchemyStore(db_uri, artifact_root)
        is_sqlite = "sqlite" in db_uri
        resolved_db_path = db_path if is_sqlite else None

        total_cells = len(span_counts) * len(payload_labels) * len(qps_targets)
        print(f"Sustained load benchmark: {total_cells} configurations, {args.duration}s each")
        print(f"DB: {db_uri}")
        print(f"Spans: {span_counts} | Payloads: {payload_labels} | QPS targets: {qps_targets}")
        print()

        all_results: list[LoadTestResult] = []
        cell_num = 0

        for num_spans in span_counts:
            for payload_label in payload_labels:
                input_payload, output_payload = payloads[payload_label]
                for qps_str in qps_targets:
                    cell_num += 1
                    target_qps = None if qps_str == "max" else float(qps_str)

                    exp_name = f"load_{num_spans}s_{payload_label}_{qps_str}qps"
                    exp_id = str(store.create_experiment(exp_name))

                    print(
                        f"[{cell_num}/{total_cells}] "
                        f"spans={num_spans}, payload={payload_label}, "
                        f"target_qps={qps_str}, duration={args.duration}s ...",
                        end="",
                        flush=True,
                    )

                    result = run_load_test(
                        store=store,
                        experiment_id=exp_id,
                        spans_per_trace=num_spans,
                        payload_label=payload_label,
                        input_payload=input_payload,
                        output_payload=output_payload,
                        target_qps=target_qps,
                        duration_s=args.duration,
                        db_path=resolved_db_path,
                    )
                    all_results.append(result)

                    print(
                        f" done: {result.traces_submitted} traces, "
                        f"{result.achieved_qps:.1f} QPS, "
                        f"p50={result.p50_ms:.0f} ms, "
                        f"CPU={result.cpu_utilization * 100:.0f}%"
                    )

        print_results(all_results)


if __name__ == "__main__":
    main()
