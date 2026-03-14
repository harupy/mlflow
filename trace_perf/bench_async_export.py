"""Benchmark async export queue and span batching mechanics.

Measures:
  - AsyncTraceExportQueue put() throughput and flush() latency
  - SpanBatcher efficiency at varying batch sizes
"""

from __future__ import annotations

import os
import random
import threading
import time
import uuid

from utils import generate_spans

from mlflow.tracing.export.async_export_queue import AsyncTraceExportQueue, Task

SEP = "=" * 90
DASH = "-" * 90

NUM_TASKS = 1000
BATCH_SIZES = [1, 10, 50, 128]


def bench_queue_throughput():
    counter = {"value": 0}
    lock = threading.Lock()

    def _noop_handler(*_args):
        with lock:
            counter["value"] += 1

    queue = AsyncTraceExportQueue()

    # Warmup
    for _ in range(10):
        queue.put(Task(handler=_noop_handler, args=(), error_msg=""))
    queue.flush()
    counter["value"] = 0

    # Measure put throughput
    t0 = time.perf_counter()
    for i in range(NUM_TASKS):
        queue.put(Task(handler=_noop_handler, args=(i,), error_msg=""))
    put_elapsed = (time.perf_counter() - t0) * 1000

    # Measure flush latency
    t0 = time.perf_counter()
    queue.flush()
    flush_elapsed = (time.perf_counter() - t0) * 1000

    processed = counter["value"]
    queue.flush(terminate=True)

    return {
        "tasks": NUM_TASKS,
        "put_ms": put_elapsed,
        "flush_ms": flush_elapsed,
        "put_rate": NUM_TASKS / (put_elapsed / 1000) if put_elapsed > 0 else 0,
        "processed": processed,
    }


def bench_batcher(batch_size: int):
    # Override env vars before constructing SpanBatcher (reads config at init time)
    os.environ["MLFLOW_ASYNC_TRACE_LOGGING_MAX_SPAN_BATCH_SIZE"] = str(batch_size)
    os.environ["MLFLOW_ASYNC_TRACE_LOGGING_MAX_INTERVAL_MILLIS"] = "50"

    # Must import after env vars are set so config values are picked up
    from mlflow.tracing.export.span_batcher import SpanBatcher  # noqa: lazy-import

    counter = {"spans": 0}
    lock = threading.Lock()

    def _count_spans(_location, spans):
        with lock:
            counter["spans"] += len(spans)

    queue = AsyncTraceExportQueue()
    batcher = SpanBatcher(queue, _count_spans)

    # Generate spans
    rng = random.Random(42)
    trace_id = f"tr-{uuid.uuid4().hex}"
    spans = generate_spans(trace_id, NUM_TASKS, rng)

    # Measure
    t0 = time.perf_counter()
    for span in spans:
        batcher.add_span("exp-1", span)
    add_elapsed = (time.perf_counter() - t0) * 1000

    # Flush and measure
    t0 = time.perf_counter()
    batcher.shutdown()
    queue.flush(terminate=True)
    flush_elapsed = (time.perf_counter() - t0) * 1000

    total_ms = add_elapsed + flush_elapsed
    per_span_us = (total_ms / NUM_TASKS) * 1000 if NUM_TASKS > 0 else 0

    # Clean up env vars
    os.environ.pop("MLFLOW_ASYNC_TRACE_LOGGING_MAX_SPAN_BATCH_SIZE", None)
    os.environ.pop("MLFLOW_ASYNC_TRACE_LOGGING_MAX_INTERVAL_MILLIS", None)

    return {
        "batch_size": batch_size,
        "spans": NUM_TASKS,
        "add_ms": add_elapsed,
        "flush_ms": flush_elapsed,
        "total_ms": total_ms,
        "per_span_us": per_span_us,
        "processed": counter["spans"],
    }


def main() -> None:
    print(f"\n{SEP}")
    print("  Async Export Queue & Batching Benchmark")
    print(SEP)

    # Queue throughput
    print(f"\n  QUEUE THROUGHPUT ({NUM_TASKS} tasks)")
    print(DASH)
    result = bench_queue_throughput()
    print(f"    put():  {result['put_ms']:.1f} ms ({result['put_rate']:.0f} tasks/s)")
    print(f"    flush(): {result['flush_ms']:.1f} ms")
    print(f"    processed: {result['processed']}/{result['tasks']}")

    # Batching efficiency
    print(f"\n  BATCHING EFFICIENCY ({NUM_TASKS} spans)")
    print(DASH)
    header = (
        f"{'batch_size':>10} | {'add(ms)':>8} | {'flush(ms)':>9} | "
        f"{'total(ms)':>9} | {'per-span(μs)':>12} | {'processed':>9}"
    )
    print(header)
    print(DASH)

    baseline_total = None
    for batch_size in BATCH_SIZES:
        result = bench_batcher(batch_size)
        if baseline_total is None:
            baseline_total = result["total_ms"]

        print(
            f"{result['batch_size']:>10} | {result['add_ms']:>8.1f} | "
            f"{result['flush_ms']:>9.1f} | {result['total_ms']:>9.1f} | "
            f"{result['per_span_us']:>12.1f} | {result['processed']:>9}"
        )

    print("\n  batch_size=1 means no batching (immediate export)")
    print("  Larger batches reduce per-span overhead by amortizing queue operations")
    print(SEP)


if __name__ == "__main__":
    main()
