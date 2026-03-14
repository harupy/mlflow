"""Benchmark trace deletion with CASCADE across related tables.

Measures deletion performance for three modes:
  - Single trace delete (trace_ids=[single_id])
  - Batch delete (trace_ids=[100 ids])
  - Delete by timestamp (max_timestamp_millis)

Run before/after schema or cascade changes to validate impact.
"""

from __future__ import annotations

import time

from utils import count_queries, create_store, percentile, populate_corpus_with_ids

SEP = "=" * 90
DASH = "-" * 90

CORPUS_SIZES = [500, 2000, 5000]
SPANS_PER_TRACE = 10
ITERATIONS = 5


def bench_single_delete(store, exp_id, trace_ids):
    times = []
    for tid in trace_ids[:ITERATIONS]:
        t0 = time.perf_counter()
        store._delete_traces(exp_id, trace_ids=[tid])
        times.append((time.perf_counter() - t0) * 1000)
    return times


def bench_batch_delete(store, exp_id, trace_ids, batch_size=100):
    times = []
    for start in range(0, min(len(trace_ids), batch_size * ITERATIONS), batch_size):
        batch = trace_ids[start : start + batch_size]
        if not batch:
            break
        t0 = time.perf_counter()
        store._delete_traces(exp_id, trace_ids=batch)
        times.append((time.perf_counter() - t0) * 1000)
    return times


def bench_timestamp_delete(store, exp_id, timestamps, count=100):
    times = []
    for i in range(min(ITERATIONS, len(timestamps) // count)):
        cutoff = timestamps[count * (i + 1) - 1]
        t0 = time.perf_counter()
        store._delete_traces(exp_id, max_timestamp_millis=cutoff, max_traces=count)
        times.append((time.perf_counter() - t0) * 1000)
    return times


def main() -> None:
    print(f"\n{SEP}")
    print("  Trace Deletion Benchmark (CASCADE across spans, tags, metadata, assessments)")
    print(SEP)

    header = f"{'corpus':>7} | {'mode':<18} | {'p50(ms)':>8} | {'p95(ms)':>8} | {'queries':>8}"
    print(header)
    print(DASH)

    for corpus_size in CORPUS_SIZES:
        # Single delete
        store, _tmpdir = create_store()
        exp_id = str(store.create_experiment(f"del_single_{corpus_size}"))
        print(f"  Populating {corpus_size} traces...", end="", flush=True)
        ids_ts = populate_corpus_with_ids(
            store, exp_id, corpus_size, SPANS_PER_TRACE, verbose=False
        )
        print(" done")
        trace_ids = [t[0] for t in ids_ts]

        with count_queries(store) as queries:
            store._delete_traces(exp_id, trace_ids=[trace_ids[-1]])
        single_queries = len(queries)

        times = bench_single_delete(store, exp_id, trace_ids[:-1])
        if times:
            print(
                f"{corpus_size:>7} | {'single':18} | "
                f"{percentile(times, 50):>8.1f} | {percentile(times, 95):>8.1f} | "
                f"{single_queries:>8}"
            )

        # Batch delete
        store, _tmpdir = create_store()
        exp_id = str(store.create_experiment(f"del_batch_{corpus_size}"))
        ids_ts = populate_corpus_with_ids(
            store, exp_id, corpus_size, SPANS_PER_TRACE, verbose=False
        )
        trace_ids = [t[0] for t in ids_ts]

        with count_queries(store) as queries:
            store._delete_traces(exp_id, trace_ids=trace_ids[:100])
        batch_queries = len(queries)

        times = bench_batch_delete(store, exp_id, trace_ids[100:])
        if times:
            print(
                f"{corpus_size:>7} | {'batch(100)':18} | "
                f"{percentile(times, 50):>8.1f} | {percentile(times, 95):>8.1f} | "
                f"{batch_queries:>8}"
            )

        # Timestamp delete
        store, _tmpdir = create_store()
        exp_id = str(store.create_experiment(f"del_ts_{corpus_size}"))
        ids_ts = populate_corpus_with_ids(
            store, exp_id, corpus_size, SPANS_PER_TRACE, verbose=False
        )
        timestamps = sorted(t[1] for t in ids_ts)

        with count_queries(store) as queries:
            store._delete_traces(exp_id, max_timestamp_millis=timestamps[99], max_traces=100)
        ts_queries = len(queries)

        if times := bench_timestamp_delete(store, exp_id, timestamps[100:]):
            print(
                f"{corpus_size:>7} | {'by_timestamp(100)':18} | "
                f"{percentile(times, 50):>8.1f} | {percentile(times, 95):>8.1f} | "
                f"{ts_queries:>8}"
            )

    print("\n  Deletion cascades to: spans, tags, metadata, assessments, span_metrics")
    print(SEP)


if __name__ == "__main__":
    main()
