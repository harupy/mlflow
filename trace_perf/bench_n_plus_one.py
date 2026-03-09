"""Bottleneck #3: N+1 lazy loading in search_traces().

Counts SQL queries for varying max_results to show the 3N+1 pattern.
Run before/after a fix to validate improvement.
"""

from __future__ import annotations

from utils import count_queries, create_store, populate_corpus

SEP = "=" * 80
DASH = "-" * 80

MAX_RESULTS_VALUES = [10, 25, 50, 100]
CORPUS_SIZE = 200


def main() -> None:
    store, tmpdir = create_store()
    exp_id = str(store.create_experiment("bench_n_plus_one"))

    print(f"\n  Populating {CORPUS_SIZE} traces...")
    populate_corpus(store, exp_id, CORPUS_SIZE)

    print(f"\n{SEP}")
    print("  Bottleneck #3: N+1 lazy loading in search_traces()")
    print(SEP)

    header = (
        f"{'max_results':>11} | {'total queries':>13} | {'expected 3N+1':>13} | {'overhead':>8}"
    )
    print(header)
    print(DASH)

    for n in MAX_RESULTS_VALUES:
        with count_queries(store) as queries:
            store.search_traces(locations=[exp_id], max_results=n)

        total = len(queries)  # each entry is (statement, params)
        expected = 3 * n + 1
        overhead = total - expected

        print(f"{n:>11} | {total:>13} | {expected:>13} | {overhead:>+8}")

    print("\n  Pattern: each trace result triggers ~3 lazy loads (tags, metadata, assessments)")
    print("  Fix: add joinedload()/subqueryload() to the search query")
    print(SEP)


if __name__ == "__main__":
    main()
