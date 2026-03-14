"""Benchmark per-chunk overhead of tracing on generator/streaming functions.

Compares iteration time of an untraced generator vs a @mlflow.trace
decorated generator to isolate the per-chunk event recording cost.
"""

from __future__ import annotations

import gc
import logging
import os
import tempfile
import time

from utils import percentile

SEP = "=" * 90
DASH = "-" * 90

CHUNK_COUNTS = [100, 1_000, 10_000]
ITERATIONS = 10
WARMUP = 2


def _untraced_generator(n: int):
    for i in range(n):
        yield {"token": f"word_{i}", "index": i}


def _consume(gen):
    for _ in gen:
        pass


def main() -> None:
    os.environ.pop("MLFLOW_TRACKING_URI", None)
    logging.getLogger("mlflow").setLevel(logging.ERROR)

    import mlflow

    # Use SQLite store to avoid network overhead
    tmpdir = tempfile.mkdtemp()
    mlflow.set_tracking_uri(f"sqlite:///{tmpdir}/mlflow.db")
    mlflow.set_experiment("bench_streaming")

    @mlflow.trace
    def _traced_generator(n: int):
        for i in range(n):
            yield {"token": f"word_{i}", "index": i}

    print(f"\n{SEP}")
    print(f"  Streaming/Generator Tracing Overhead ({ITERATIONS} iterations per config)")
    print(SEP)

    header = (
        f"{'chunks':>7} | {'untraced(ms)':>12} | {'traced(ms)':>11} | "
        f"{'overhead(ms)':>12} | {'per-chunk(μs)':>13} | {'overhead%':>9}"
    )
    print(header)
    print(DASH)

    for num_chunks in CHUNK_COUNTS:
        # Warmup
        for _ in range(WARMUP):
            _consume(_untraced_generator(num_chunks))
            _consume(_traced_generator(num_chunks))

        # Measure untraced
        gc.disable()
        untraced_times = []
        for _ in range(ITERATIONS):
            t0 = time.perf_counter()
            _consume(_untraced_generator(num_chunks))
            untraced_times.append((time.perf_counter() - t0) * 1000)

        # Measure traced
        traced_times = []
        for _ in range(ITERATIONS):
            t0 = time.perf_counter()
            _consume(_traced_generator(num_chunks))
            traced_times.append((time.perf_counter() - t0) * 1000)
        gc.enable()

        untraced_p50 = percentile(untraced_times, 50)
        traced_p50 = percentile(traced_times, 50)
        overhead_ms = traced_p50 - untraced_p50
        per_chunk_us = (overhead_ms / num_chunks) * 1000 if num_chunks > 0 else 0
        overhead_pct = (overhead_ms / untraced_p50 * 100) if untraced_p50 > 0 else 0

        print(
            f"{num_chunks:>7} | {untraced_p50:>12.2f} | {traced_p50:>11.2f} | "
            f"{overhead_ms:>12.2f} | {per_chunk_us:>13.2f} | {overhead_pct:>8.1f}%"
        )

    print("\n  Each chunk records a SpanEvent with json.dumps() serialization")
    print("  Overhead is cumulative: more chunks = more events on the span")

    # Cleanup
    mlflow.tracing.reset()
    print(SEP)


if __name__ == "__main__":
    main()
