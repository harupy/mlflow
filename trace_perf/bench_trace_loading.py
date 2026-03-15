"""Benchmark get_trace() and batch_get_traces() deserialization cost.

When a user clicks on a trace in the UI, the server calls get_trace()
which deserializes the full span content: json.loads(content) +
translate_loaded_span() + Span.from_dict() for every span.

Measures how this cost scales with span count and content size.
"""

from __future__ import annotations

import random
import time
import uuid

from utils import (
    create_store,
    generate_large_payload,
    generate_trace_info,
    make_spans_with_payload,
    percentile,
)

SEP = "=" * 90
DASH = "-" * 90

SPAN_COUNTS = [10, 50, 100, 250]
ITERATIONS = 20
WARMUP = 3


def _populate_trace(store, exp_id, num_spans, input_payload, output_payload, rng):
    tid = f"tr-{uuid.uuid4().hex}"
    ti = generate_trace_info(tid, exp_id, 1_700_000_000_000, rng)
    spans = make_spans_with_payload(tid, num_spans, input_payload, output_payload, rng)
    store.start_trace(ti)
    store.log_spans(exp_id, spans)
    return tid


def _bench_get_trace(store, trace_id):
    for _ in range(WARMUP):
        store.get_trace(trace_id)

    times = []
    for _ in range(ITERATIONS):
        t0 = time.perf_counter()
        store.get_trace(trace_id)
        times.append((time.perf_counter() - t0) * 1000)
    return times


def _bench_batch_get(store, trace_ids):
    for _ in range(WARMUP):
        store.batch_get_traces(trace_ids)

    times = []
    for _ in range(ITERATIONS):
        t0 = time.perf_counter()
        store.batch_get_traces(trace_ids)
        times.append((time.perf_counter() - t0) * 1000)
    return times


def main() -> None:
    rng = random.Random(42)
    store, _tmpdir = create_store()

    print(f"\n{SEP}")
    print("  Trace Loading / Deserialization Benchmark")
    print("  get_trace(): json.loads(content) + Span.from_dict() per span")
    print(SEP)

    # --- get_trace() by span count (small payloads) ---
    print(f"\n  GET_TRACE by span count (small payload, {ITERATIONS} iterations)")
    print(DASH)
    header = f"{'spans':>6} | {'p50(ms)':>8} | {'p95(ms)':>8} | {'per-span(μs)':>13}"
    print(header)
    print(DASH)

    for num_spans in SPAN_COUNTS:
        exp_id = str(store.create_experiment(f"load_spans_{num_spans}"))
        tid = _populate_trace(store, exp_id, num_spans, None, None, rng)
        times = _bench_get_trace(store, tid)
        p50 = percentile(times, 50)
        per_span = (p50 / num_spans) * 1000
        print(f"{num_spans:>6} | {p50:>8.2f} | {percentile(times, 95):>8.2f} | {per_span:>13.1f}")

    # --- get_trace() by payload size (10 spans) ---
    print(f"\n  GET_TRACE by payload size (10 spans, {ITERATIONS} iterations)")
    print(DASH)

    payload_sizes = {
        "small": 0,
        "100KB": 100_000,
        "1MB": 1_000_000,
        "10MB": 10_000_000,
    }

    header = f"{'payload':<8} | {'p50(ms)':>8} | {'p95(ms)':>8} | {'vs small':>8}"
    print(header)
    print(DASH)

    baseline_p50 = None
    for label, target in payload_sizes.items():
        exp_id = str(store.create_experiment(f"load_payload_{label}"))
        if target == 0:
            inp, outp = None, None
        else:
            inp = generate_large_payload(target, rng)
            outp = generate_large_payload(target, rng)
        tid = _populate_trace(store, exp_id, 10, inp, outp, rng)
        times = _bench_get_trace(store, tid)
        p50 = percentile(times, 50)
        if baseline_p50 is None:
            baseline_p50 = p50
        ratio = p50 / baseline_p50 if baseline_p50 > 0 else 0
        print(f"{label:<8} | {p50:>8.2f} | {percentile(times, 95):>8.2f} | {ratio:>7.1f}x")

    # --- batch_get_traces() ---
    print(f"\n  BATCH_GET_TRACES (10 spans/trace, small payload, {ITERATIONS} iterations)")
    print(DASH)

    batch_sizes = [1, 10, 50, 100]
    header = f"{'traces':>7} | {'p50(ms)':>8} | {'p95(ms)':>8} | {'per-trace(ms)':>14}"
    print(header)
    print(DASH)

    exp_id = str(store.create_experiment("load_batch"))
    all_tids = [
        _populate_trace(store, exp_id, 10, None, None, rng) for _ in range(max(batch_sizes))
    ]

    for batch_size in batch_sizes:
        tids = all_tids[:batch_size]
        times = _bench_batch_get(store, tids)
        p50 = percentile(times, 50)
        per_trace = p50 / batch_size
        print(f"{batch_size:>7} | {p50:>8.2f} | {percentile(times, 95):>8.2f} | {per_trace:>14.2f}")

    print("\n  Deserialization: json.loads(content) + translate_loaded_span() + Span.from_dict()")
    print("  This is the path when a user clicks a trace in the UI")
    print(SEP)


if __name__ == "__main__":
    main()
