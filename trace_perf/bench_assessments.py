"""Benchmark assessment CRUD and search filtering.

Measures:
  - create_assessment() throughput
  - search_traces() with assessment-based filters vs no filter
  - SQL query count for assessment-filtered search
"""

from __future__ import annotations

import random
import time

from utils import (
    count_queries,
    create_store,
    generate_assessment,
    percentile,
    populate_corpus_with_ids,
)

SEP = "=" * 90
DASH = "-" * 90

CORPUS_SIZE = 1000
ASSESSMENTS_PER_TRACE = 3
WARMUP = 3
ITERATIONS = 20


def _bench_query(store, exp_id, filter_string=None):
    for _ in range(WARMUP):
        store.search_traces(
            locations=[exp_id],
            filter_string=filter_string,
            max_results=100,
        )

    times = []
    for _ in range(ITERATIONS):
        t0 = time.perf_counter()
        store.search_traces(
            locations=[exp_id],
            filter_string=filter_string,
            max_results=100,
        )
        times.append((time.perf_counter() - t0) * 1000)
    return times


def main() -> None:
    store, _tmpdir = create_store()
    exp_id = str(store.create_experiment("bench_assessments"))

    # Populate traces
    print(f"\n  Populating {CORPUS_SIZE} traces...")
    ids_ts = populate_corpus_with_ids(store, exp_id, CORPUS_SIZE, verbose=True)
    trace_ids = [t[0] for t in ids_ts]

    # Create assessments
    print(f"  Creating {ASSESSMENTS_PER_TRACE} assessments per trace...")
    rng = random.Random(42)
    assessment_names = ["correctness", "relevance", "fluency"]

    t_start = time.perf_counter()
    for tid in trace_ids:
        for name in assessment_names[:ASSESSMENTS_PER_TRACE]:
            a = generate_assessment(tid, name=name, rng=rng)
            store.create_assessment(a)
    t_total = (time.perf_counter() - t_start) * 1000
    total_assessments = CORPUS_SIZE * ASSESSMENTS_PER_TRACE

    print(f"\n{SEP}")
    print("  Assessment Benchmark")
    print(SEP)

    # Creation stats
    print("\n  ASSESSMENT CREATION")
    print(f"    {total_assessments} assessments in {t_total:.0f} ms")
    print(f"    {t_total / total_assessments:.2f} ms/assessment")
    print(f"    {total_assessments / (t_total / 1000):.0f} assessments/s")

    # Search comparison
    print(f"\n  SEARCH WITH ASSESSMENT FILTERS ({CORPUS_SIZE} traces, {ITERATIONS} iterations)")
    print(DASH)

    queries_config = [
        ("no_filter", None),
        ("feedback.correctness = 'true'", "feedback.correctness IS NOT NULL"),
        ("feedback.relevance exists", "feedback.relevance IS NOT NULL"),
    ]

    header = f"{'filter':<30} | {'p50(ms)':>8} | {'p95(ms)':>8} | {'queries':>8} | {'vs base':>7}"
    print(header)
    print(DASH)

    baseline_p50 = None
    for label, filter_string in queries_config:
        times = _bench_query(store, exp_id, filter_string)
        p50 = percentile(times, 50)
        p95 = percentile(times, 95)

        with count_queries(store) as queries:
            store.search_traces(
                locations=[exp_id],
                filter_string=filter_string,
                max_results=100,
            )
        num_queries = len(queries)

        if baseline_p50 is None:
            baseline_p50 = p50

        ratio = p50 / baseline_p50 if baseline_p50 > 0 else 0
        print(f"{label:<30} | {p50:>8.1f} | {p95:>8.1f} | {num_queries:>8} | {ratio:>6.1f}x")

    print("\n  Assessment filters create DISTINCT subqueries on the assessments table")
    print(SEP)


if __name__ == "__main__":
    main()
