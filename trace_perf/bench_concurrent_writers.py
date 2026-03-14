"""Benchmark concurrent writer contention.

Measures throughput and latency when multiple threads write traces
simultaneously to the same store, showing how contention scales.
"""

from __future__ import annotations

import argparse
import random
import threading
import time
import uuid

from utils import create_store, generate_spans, generate_trace_info, percentile

SEP = "=" * 95
DASH = "-" * 95

THREAD_COUNTS = [1, 2, 4, 8]
TRACES_PER_THREAD = 100
SPANS_PER_TRACE = 10


def _writer(
    store,
    exp_id: str,
    traces: list[tuple[object, ...]],
    barrier: threading.Barrier,
    latencies: list[float],
    lock: threading.Lock,
):
    barrier.wait()
    local_latencies = []
    for ti, spans in traces:
        t0 = time.perf_counter()
        store.start_trace(ti)
        store.log_spans(exp_id, spans)
        local_latencies.append((time.perf_counter() - t0) * 1000)
    with lock:
        latencies.extend(local_latencies)


def run_with_threads(store, exp_id: str, num_threads: int, rng: random.Random) -> dict[str, object]:
    # Pre-generate data per thread
    base_time_ms = 1_700_000_000_000
    all_traces = [
        [
            (
                generate_trace_info(
                    tid := f"tr-{uuid.uuid4().hex}",
                    exp_id,
                    base_time_ms + (t * TRACES_PER_THREAD + i) * 1000,
                    rng,
                ),
                generate_spans(tid, SPANS_PER_TRACE, rng),
            )
            for i in range(TRACES_PER_THREAD)
        ]
        for t in range(num_threads)
    ]

    barrier = threading.Barrier(num_threads)
    latencies: list[float] = []
    lock = threading.Lock()

    threads = [
        threading.Thread(
            target=_writer,
            args=(store, exp_id, all_traces[t], barrier, latencies, lock),
        )
        for t in range(num_threads)
    ]

    wall_start = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    wall_elapsed = time.perf_counter() - wall_start

    total_traces = num_threads * TRACES_PER_THREAD
    return {
        "threads": num_threads,
        "total_traces": total_traces,
        "wall_s": wall_elapsed,
        "traces_per_s": total_traces / wall_elapsed,
        "spans_per_s": total_traces * SPANS_PER_TRACE / wall_elapsed,
        "p50": percentile(latencies, 50),
        "p95": percentile(latencies, 95),
        "p99": percentile(latencies, 99),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Concurrent writer contention benchmark")
    parser.add_argument("--db-uri", default=None, help="SQLAlchemy DB URI (default: SQLite)")
    parser.add_argument(
        "--threads",
        default=",".join(str(t) for t in THREAD_COUNTS),
        help=f"Comma-separated thread counts (default: {','.join(str(t) for t in THREAD_COUNTS)})",
    )
    args = parser.parse_args()

    thread_counts = [int(x) for x in args.threads.split(",")]

    store, _tmpdir = create_store(args.db_uri)
    db_label = args.db_uri.split("://")[0] if args.db_uri else "sqlite"

    print(f"\n{SEP}")
    print(
        f"  Concurrent Writer Benchmark ({db_label}, "
        f"{TRACES_PER_THREAD} traces/thread, {SPANS_PER_TRACE} spans/trace)"
    )
    print(SEP)

    header = (
        f"{'threads':>7} | {'traces/s':>9} | {'spans/s':>8} | "
        f"{'p50(ms)':>8} | {'p95(ms)':>8} | {'p99(ms)':>8} | {'scaling':>8}"
    )
    print(header)
    print(DASH)

    baseline_tps = None
    for num_threads in thread_counts:
        rng = random.Random(42 + num_threads)
        exp_id = str(store.create_experiment(f"concurrent_{num_threads}t"))

        result = run_with_threads(store, exp_id, num_threads, rng)

        if baseline_tps is None:
            baseline_tps = result["traces_per_s"]

        # Scaling efficiency: how well throughput scales vs linear
        ideal = baseline_tps * num_threads
        scaling = result["traces_per_s"] / ideal if ideal > 0 else 0

        print(
            f"{result['threads']:>7} | {result['traces_per_s']:>9.1f} | "
            f"{result['spans_per_s']:>8.0f} | "
            f"{result['p50']:>8.1f} | {result['p95']:>8.1f} | {result['p99']:>8.1f} | "
            f"{scaling:>7.0%}"
        )

    print("\n  Scaling = achieved_throughput / (single_thread_throughput × num_threads)")
    print("  SQLite has a global write lock; PostgreSQL allows row-level concurrency")
    print(SEP)


if __name__ == "__main__":
    main()
