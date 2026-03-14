"""Benchmark ingestion and search with large span content (1MB-10MB).

Measures how multi-MB inputs/outputs in span attributes affect:
  - Ingestion latency (start_trace + log_spans)
  - Search latency
  - DB size per trace
"""

from __future__ import annotations

import random
import time
import uuid

from utils import (
    create_store,
    generate_large_payload,
    generate_trace_info,
    get_db_size_mb,
    make_spans_with_payload,
    percentile,
)

SEP = "=" * 90
DASH = "-" * 90

PAYLOAD_SIZES = {
    "small": 0,
    "1MB": 1_000_000,
    "5MB": 5_000_000,
    "10MB": 10_000_000,
}
SPANS_PER_TRACE = 10
INGEST_ITERATIONS = 10
SEARCH_CORPUS = 20
SEARCH_ITERATIONS = 10
WARMUP = 2


def main() -> None:
    rng = random.Random(42)

    # Pre-generate payloads
    payloads: dict[str, tuple[dict[str, object] | None, dict[str, object] | None]] = {}
    for label, target in PAYLOAD_SIZES.items():
        if target == 0:
            payloads[label] = (None, None)
        else:
            payloads[label] = (
                generate_large_payload(target, rng),
                generate_large_payload(target, rng),
            )

    print(f"\n{SEP}")
    print("  Large Content Benchmark (multi-MB span inputs/outputs)")
    print(SEP)

    # --- Ingestion ---
    print(f"\n  INGESTION ({INGEST_ITERATIONS} iterations, {SPANS_PER_TRACE} spans/trace)")
    print(DASH)
    header = f"{'payload':<8} | {'p50(ms)':>8} | {'p95(ms)':>8} | {'DB/trace(MB)':>12}"
    print(header)
    print(DASH)

    for label, (inp, outp) in payloads.items():
        store, tmpdir = create_store()
        exp_id = str(store.create_experiment(f"large_{label}"))
        db_path = tmpdir / "mlflow.db"

        # Warmup
        for _ in range(WARMUP):
            tid = f"tr-{uuid.uuid4().hex}"
            ti = generate_trace_info(tid, exp_id, 1_700_000_000_000, rng)
            spans = make_spans_with_payload(tid, SPANS_PER_TRACE, inp, outp, rng)
            store.start_trace(ti)
            store.log_spans(exp_id, spans)

        # Measure
        times = []
        for i in range(INGEST_ITERATIONS):
            tid = f"tr-{uuid.uuid4().hex}"
            ti = generate_trace_info(tid, exp_id, 1_700_000_000_000 + i * 1000, rng)
            spans = make_spans_with_payload(tid, SPANS_PER_TRACE, inp, outp, rng)
            t0 = time.perf_counter()
            store.start_trace(ti)
            store.log_spans(exp_id, spans)
            times.append((time.perf_counter() - t0) * 1000)

        total_traces = WARMUP + INGEST_ITERATIONS
        db_mb = get_db_size_mb(store, db_path) or 0.0
        per_trace_mb = db_mb / total_traces if total_traces > 0 else 0.0

        print(
            f"{label:<8} | {percentile(times, 50):>8.1f} | "
            f"{percentile(times, 95):>8.1f} | {per_trace_mb:>12.3f}"
        )

    # --- Search ---
    print(f"\n  SEARCH ({SEARCH_CORPUS} traces per payload, {SEARCH_ITERATIONS} iterations)")
    print(DASH)
    header = f"{'payload':<8} | {'p50(ms)':>8} | {'p95(ms)':>8} | {'vs small':>8}"
    print(header)
    print(DASH)

    baseline_p50 = None
    for label, (inp, outp) in payloads.items():
        store, tmpdir = create_store()
        exp_id = str(store.create_experiment(f"search_{label}"))

        # Populate
        for i in range(SEARCH_CORPUS):
            tid = f"tr-{uuid.uuid4().hex}"
            ti = generate_trace_info(tid, exp_id, 1_700_000_000_000 + i * 1000, rng)
            spans = make_spans_with_payload(tid, SPANS_PER_TRACE, inp, outp, rng)
            store.start_trace(ti)
            store.log_spans(exp_id, spans)

        # Warmup
        for _ in range(WARMUP):
            store.search_traces(locations=[exp_id], max_results=20)

        # Measure
        times = []
        for _ in range(SEARCH_ITERATIONS):
            t0 = time.perf_counter()
            store.search_traces(locations=[exp_id], max_results=20)
            times.append((time.perf_counter() - t0) * 1000)

        p50 = percentile(times, 50)
        if baseline_p50 is None:
            baseline_p50 = p50
        ratio = p50 / baseline_p50 if baseline_p50 > 0 else 0

        print(f"{label:<8} | {p50:>8.1f} | {percentile(times, 95):>8.1f} | {ratio:>7.1f}x")

    print(SEP)


if __name__ == "__main__":
    main()
