"""Bottleneck #5: Offset-based pagination degrades with page depth.

Benchmarks paginating to varying depths against a fixed corpus to show
that latency grows with page number.
Run before/after a fix to validate improvement.
"""

from __future__ import annotations

import time

from utils import create_store, populate_corpus

SEP = "=" * 80
DASH = "-" * 80

CORPUS_SIZE = 5000
PAGE_SIZE = 10
TARGET_PAGES = [1, 5, 10, 25, 50]
ITERATIONS = 10
WARMUP = 2


def _paginate_to_page(store, exp_id: str, target_page: int) -> float:
    t0 = time.perf_counter()
    token = None
    for _ in range(target_page):
        _, token = store.search_traces(locations=[exp_id], max_results=PAGE_SIZE, page_token=token)
        if token is None:
            break
    return time.perf_counter() - t0


def _p50(data: list[float]) -> float:
    s = sorted(data)
    k = (len(s) - 1) * 0.5
    f = int(k)
    return s[f] + (k - f) * (s[min(f + 1, len(s) - 1)] - s[f])


def main() -> None:
    store, tmpdir = create_store()
    exp_id = str(store.create_experiment("bench_pagination"))

    print(f"\n  Populating {CORPUS_SIZE} traces...")
    populate_corpus(store, exp_id, CORPUS_SIZE)

    print(f"\n{SEP}")
    print("  Bottleneck #5: offset-based pagination degradation")
    print(f"  Corpus: {CORPUS_SIZE} traces, page size: {PAGE_SIZE}")
    print(SEP)

    header = f"{'page':>6} | {'offset':>7} | {'p50 (ms)':>9} | {'vs page 1':>9}"
    print(header)
    print(DASH)

    baseline_p50 = None
    for page in TARGET_PAGES:
        # Warmup
        for _ in range(WARMUP):
            _paginate_to_page(store, exp_id, page)

        # Measure
        times = [_paginate_to_page(store, exp_id, page) for _ in range(ITERATIONS)]

        p50 = _p50(times) * 1000
        if baseline_p50 is None:
            baseline_p50 = p50

        ratio = p50 / baseline_p50 if baseline_p50 > 0 else 0
        offset = (page - 1) * PAGE_SIZE

        print(f"{page:>6} | {offset:>7} | {p50:>9.1f} | {ratio:>8.1f}x")

    print("\n  Offset pagination scans and discards all preceding rows")
    print("  Fix: keyset (cursor-based) pagination")
    print(SEP)


if __name__ == "__main__":
    main()
