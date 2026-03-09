"""Bottleneck #2: 3 separate metadata queries per log_spans() call.

Captures all SQL statements during log_spans() and highlights the
redundant SELECT queries for token_usage, cost, and session_id.
Run before/after a fix to validate improvement.
"""

from __future__ import annotations

import random
import uuid

from utils import count_queries, create_store, generate_spans, generate_trace_info

SEP = "=" * 80
DASH = "-" * 80

METADATA_KEYWORDS = [
    ("token_usage", "mlflow.trace.tokenUsage"),
    ("cost", "mlflow.trace.cost"),
    ("session_id", "mlflow.trace.session"),
]


def _params_contain(params, keyword: str) -> bool:
    if isinstance(params, dict):
        return any(keyword in str(v) for v in params.values())
    if isinstance(params, (list, tuple)):
        return any(keyword in str(v) for v in params)
    return False


def main() -> None:
    store, tmpdir = create_store()
    exp_id = str(store.create_experiment("bench_metadata"))

    rng = random.Random(42)
    tid = f"tr-{uuid.uuid4().hex}"
    ti = generate_trace_info(tid, exp_id, 1_700_000_000_000, rng)
    # Use 20 spans to ensure LLM spans with token usage + cost exist
    spans = generate_spans(tid, 20, rng)
    store.start_trace(ti)

    with count_queries(store) as queries:
        store.log_spans(exp_id, spans)

    print(f"\n{SEP}")
    print("  Bottleneck #2: redundant metadata queries in log_spans()")
    print(SEP)
    print(f"\n  Total SQL statements during log_spans(): {len(queries)}")

    # Classify queries
    selects = [(q, p) for q, p in queries if q.strip().upper().startswith("SELECT")]
    inserts = [(q, p) for q, p in queries if q.strip().upper().startswith("INSERT")]
    updates = [(q, p) for q, p in queries if q.strip().upper().startswith("UPDATE")]

    print(f"    SELECT: {len(selects)}")
    print(f"    INSERT: {len(inserts)}")
    print(f"    UPDATE: {len(updates)}")

    # Find metadata SELECTs by checking both statement text and bind parameters
    print("\n  Metadata SELECT queries (the redundant ones):")
    print(DASH)

    total_metadata_selects = 0
    for label, key in METADATA_KEYWORDS:
        matching = [(q, p) for q, p in selects if key in q or _params_contain(p, key)]
        total_metadata_selects += len(matching)
        print(f"    {label}: {len(matching)} query(ies)")
        for q, p in matching:
            short = q.replace("\n", " ")[:100]
            print(f"      SQL: {short}...")

    # Also show all SELECTs on trace_request_metadata table
    metadata_table_selects = [(q, p) for q, p in selects if "trace_request_metadata" in q]
    if metadata_table_selects:
        print(f"\n  All SELECTs on trace_request_metadata: {len(metadata_table_selects)}")
        for q, p in metadata_table_selects:
            short = q.replace("\n", " ")[:100]
            print(f"    SQL: {short}...")
            if p:
                print(f"    params: {p}")

    print(
        f"\n  Summary: {max(total_metadata_selects, len(metadata_table_selects))} separate "
        f"metadata SELECTs could be 1 query with IN clause"
    )
    print(SEP)


if __name__ == "__main__":
    main()
