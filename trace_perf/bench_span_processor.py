"""Benchmark span processor on_end() overhead.

Measures per-span processing cost in the MLflow span processor,
including lock acquisition, trace manager access, and metadata updates.
Compares single-thread vs multi-thread contention.
"""

from __future__ import annotations

import gc
import logging
import os
import tempfile
import threading
import time

from utils import percentile

SEP = "=" * 90
DASH = "-" * 90

SPAN_COUNTS = [10, 50, 100]
ITERATIONS = 10
WARMUP = 2


def _run_traced_function(trace_fn, num_spans: int):
    """Execute a traced function that creates num_spans child spans."""

    @trace_fn
    def parent():
        for i in range(num_spans - 1):

            @trace_fn(name=f"child_{i}")
            def child():
                pass

            child()

    parent()


def _bench_single_thread(trace_fn, num_spans: int) -> list[float]:
    for _ in range(WARMUP):
        _run_traced_function(trace_fn, num_spans)

    gc.disable()
    times = []
    for _ in range(ITERATIONS):
        t0 = time.perf_counter()
        _run_traced_function(trace_fn, num_spans)
        times.append((time.perf_counter() - t0) * 1000)
    gc.enable()
    return times


def _bench_multi_thread(trace_fn, num_spans: int, num_threads: int) -> list[float]:
    for _ in range(WARMUP):
        _run_traced_function(trace_fn, num_spans)

    barrier = threading.Barrier(num_threads)
    all_latencies: list[float] = []
    lock = threading.Lock()

    def _worker():
        barrier.wait()
        local_times = []
        for _ in range(ITERATIONS):
            t0 = time.perf_counter()
            _run_traced_function(trace_fn, num_spans)
            local_times.append((time.perf_counter() - t0) * 1000)
        with lock:
            all_latencies.extend(local_times)

    threads = [threading.Thread(target=_worker) for _ in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return all_latencies


def main() -> None:
    os.environ.pop("MLFLOW_TRACKING_URI", None)
    logging.getLogger("mlflow").setLevel(logging.ERROR)

    import mlflow

    tmpdir = tempfile.mkdtemp()
    mlflow.set_tracking_uri(f"sqlite:///{tmpdir}/mlflow.db")
    mlflow.set_experiment("bench_processor")

    print(f"\n{SEP}")
    print("  Span Processor on_end() Overhead")
    print(SEP)

    # Single-thread
    print(f"\n  SINGLE THREAD ({ITERATIONS} iterations)")
    print(DASH)
    header = f"{'spans':>6} | {'total p50(ms)':>13} | {'per-span(μs)':>12} | {'p95(ms)':>8}"
    print(header)
    print(DASH)

    for num_spans in SPAN_COUNTS:
        times = _bench_single_thread(mlflow.trace, num_spans)
        p50 = percentile(times, 50)
        per_span_us = (p50 / num_spans) * 1000
        print(
            f"{num_spans:>6} | {p50:>13.2f} | {per_span_us:>12.1f} | {percentile(times, 95):>8.2f}"
        )

    # Multi-thread contention
    print(f"\n  MULTI-THREAD CONTENTION (4 threads, {ITERATIONS} iterations each)")
    print(DASH)
    header = (
        f"{'spans':>6} | {'total p50(ms)':>13} | {'per-span(μs)':>12} | "
        f"{'p95(ms)':>8} | {'vs 1-thread':>11}"
    )
    print(header)
    print(DASH)

    for num_spans in SPAN_COUNTS:
        single_times = _bench_single_thread(mlflow.trace, num_spans)
        multi_times = _bench_multi_thread(mlflow.trace, num_spans, 4)

        single_p50 = percentile(single_times, 50)
        multi_p50 = percentile(multi_times, 50)
        per_span_us = (multi_p50 / num_spans) * 1000
        ratio = multi_p50 / single_p50 if single_p50 > 0 else 0

        print(
            f"{num_spans:>6} | {multi_p50:>13.2f} | {per_span_us:>12.1f} | "
            f"{percentile(multi_times, 95):>8.2f} | {ratio:>10.1f}x"
        )

    # Cleanup
    mlflow.tracing.reset()
    print("\n  Lock contention from _deduplication_lock shows as higher per-span cost")
    print("  under multi-threaded load")
    print(SEP)


if __name__ == "__main__":
    main()
