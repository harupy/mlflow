"""Bottleneck #4: RLIKE on JSON content column for span attribute filtering.

Benchmarks span.name filter vs indexed status filter at varying corpus sizes
to show the unindexed scan degradation.
Run before/after a fix to validate improvement.
"""

from __future__ import annotations

import time

from utils import create_store, populate_corpus

SEP = "=" * 80
DASH = "-" * 80

CORPUS_SIZES = [500, 1000, 2000, 5000]
ITERATIONS = 20
WARMUP = 3


def _bench_query(store, exp_id: str, filter_string: str) -> list[float]:
    for _ in range(WARMUP):
        store.search_traces(locations=[exp_id], filter_string=filter_string, max_results=100)

    times: list[float] = []
    for _ in range(ITERATIONS):
        t0 = time.perf_counter()
        store.search_traces(locations=[exp_id], filter_string=filter_string, max_results=100)
        times.append(time.perf_counter() - t0)
    return times


def _p50(data: list[float]) -> float:
    s = sorted(data)
    k = (len(s) - 1) * 0.5
    f = int(k)
    return s[f] + (k - f) * (s[min(f + 1, len(s) - 1)] - s[f])


def main() -> None:
    store, tmpdir = create_store()

    print(f"\n{SEP}")
    print("  Bottleneck #4: RLIKE on JSON blobs (span attribute filtering)")
    print(SEP)

    header = f"{'traces':>7} | {'span.name p50 (ms)':>18} | {'status p50 (ms)':>15} | {'ratio':>6}"
    print(header)
    print(DASH)

    for size in CORPUS_SIZES:
        exp_id = str(store.create_experiment(f"bench_rlike_{size}"))
        print(f"  Populating {size} traces...", end="", flush=True)
        populate_corpus(store, exp_id, size, verbose=False)
        print(" done")

        span_times = _bench_query(store, exp_id, "span.name = 'llm_0'")
        status_times = _bench_query(store, exp_id, "status = 'OK'")

        span_p50 = _p50(span_times) * 1000
        status_p50 = _p50(status_times) * 1000
        ratio = span_p50 / status_p50 if status_p50 > 0 else float("inf")

        print(f"{size:>7} | {span_p50:>18.1f} | {status_p50:>15.1f} | {ratio:>5.1f}x")

    print("\n  span.name filter does RLIKE on JSON content (full scan, no index)")
    print("  status filter uses indexed column → stays flat")
    print(SEP)


if __name__ == "__main__":
    main()
