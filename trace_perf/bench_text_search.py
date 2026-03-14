"""Benchmark trace.text ILIKE full-text search on span content.

The UI search bar sends `trace.text ILIKE '%query%'` which maps to
`span.content ILIKE '%query%'` — an unindexed scan of the full JSON
content column across all spans in the experiment.

Benchmarks this against indexed filters to show degradation.
"""

from __future__ import annotations

import time

from utils import create_store, percentile, populate_corpus

SEP = "=" * 90
DASH = "-" * 90

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
        times.append((time.perf_counter() - t0) * 1000)
    return times


def main() -> None:
    store, _tmpdir = create_store()

    print(f"\n{SEP}")
    print("  trace.text ILIKE Benchmark (UI search bar → span.content ILIKE)")
    print(SEP)

    header = (
        f"{'traces':>7} | {'text ILIKE p50':>15} | {'status p50':>10} | "
        f"{'span.name p50':>13} | {'text vs status':>14}"
    )
    print(header)
    print(DASH)

    for size in CORPUS_SIZES:
        exp_id = str(store.create_experiment(f"bench_text_{size}"))
        print(f"  Populating {size} traces...", end="", flush=True)
        populate_corpus(store, exp_id, size, verbose=False)
        print(" done")

        # trace.text ILIKE '%machine%' — maps to span.content ILIKE '%machine%'
        # This searches the full JSON content of every span
        text_times = _bench_query(store, exp_id, "trace.text ILIKE '%machine%'")

        # Baseline: indexed status filter
        status_times = _bench_query(store, exp_id, "status = 'OK'")

        # Comparison: span.name (RLIKE on JSON, but narrower pattern)
        span_times = _bench_query(store, exp_id, "span.name = 'llm_0'")

        text_p50 = percentile(text_times, 50)
        status_p50 = percentile(status_times, 50)
        span_p50 = percentile(span_times, 50)
        ratio = text_p50 / status_p50 if status_p50 > 0 else 0

        print(
            f"{size:>7} | {text_p50:>14.1f}ms | {status_p50:>9.1f}ms | "
            f"{span_p50:>12.1f}ms | {ratio:>13.1f}x"
        )

    print("\n  trace.text ILIKE maps to span.content ILIKE (full JSON blob scan)")
    print("  This is the UI search bar query — hits every user who searches")
    print("  Degrades linearly with corpus size, similar to span.name RLIKE")
    print(SEP)


if __name__ == "__main__":
    main()
