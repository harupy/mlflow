"""Bottleneck #1: session.merge() called per span in log_spans().

Counts and times merge calls at varying span counts to show linear scaling.
Run before/after a fix to validate improvement.
"""

from __future__ import annotations

import random
import time
import uuid

from utils import create_store, generate_spans, generate_trace_info

SPAN_COUNTS = [10, 100, 1000]
SEP = "=" * 80
DASH = "-" * 80


def main() -> None:
    store, tmpdir = create_store()
    exp_id = str(store.create_experiment("bench_merge"))

    print(f"\n{SEP}")
    print("  Bottleneck #1: session.merge() per span")
    print(SEP)

    header = (
        f"{'spans':>6} | {'merge calls':>11} | {'total merge (ms)':>16} "
        f"| {'% of log_spans':>14} | {'per merge (μs)':>14}"
    )
    print(header)
    print(DASH)

    for num_spans in SPAN_COUNTS:
        rng = random.Random(42)
        tid = f"tr-{uuid.uuid4().hex}"
        ti = generate_trace_info(tid, exp_id, 1_700_000_000_000, rng)
        spans = generate_spans(tid, num_spans, rng)
        store.start_trace(ti)

        # Patch session.merge to count calls and accumulate time
        merge_count = 0
        merge_time = 0.0
        orig_merge = None

        def _counting_merge(instance, *args, **kwargs):
            nonlocal merge_count, merge_time
            merge_count += 1
            t0 = time.perf_counter()
            result = orig_merge(instance, *args, **kwargs)
            merge_time += time.perf_counter() - t0
            return result

        # Get the session class used by the store
        from sqlalchemy.orm import Session

        orig_merge = Session.merge

        Session.merge = _counting_merge
        t_start = time.perf_counter()
        store.log_spans(exp_id, spans)
        t_total = time.perf_counter() - t_start
        Session.merge = orig_merge

        total_ms = t_total * 1000
        merge_ms = merge_time * 1000
        pct = (merge_time / t_total * 100) if t_total > 0 else 0
        per_merge_us = (merge_time / merge_count * 1_000_000) if merge_count > 0 else 0

        print(
            f"{num_spans:>6} | {merge_count:>11} | {merge_ms:>16.1f} "
            f"| {pct:>13.0f}% | {per_merge_us:>14.0f}"
        )

    print("\n  Total log_spans() wall time for last run:")
    print(f"    {SPAN_COUNTS[-1]} spans → ~{total_ms:.0f} ms")
    print(SEP)


if __name__ == "__main__":
    main()
