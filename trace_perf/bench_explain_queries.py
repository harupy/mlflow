"""SQL EXPLAIN analysis for trace search queries.

Runs EXPLAIN QUERY PLAN (SQLite) or EXPLAIN ANALYZE (PostgreSQL) on key
search queries to verify index usage and identify full table scans.
"""

from __future__ import annotations

import argparse
import random

from sqlalchemy import text
from utils import count_queries, create_store, generate_assessment, populate_corpus_with_ids

SEP = "=" * 100
DASH = "-" * 100

CORPUS_SIZE = 1000

SEARCH_QUERIES = [
    ("no_filter", {}),
    ("by_status", {"filter_string": "status = 'OK'"}),
    ("by_tag", {"filter_string": "tag.env = 'prod'"}),
    ("timestamp_order", {"order_by": ["timestamp DESC"]}),
    ("by_span_name", {"filter_string": "span.name = 'llm_0'"}),
]


def _get_explain_prefix(db_uri: str) -> str:
    if "postgresql" in db_uri:
        return "EXPLAIN ANALYZE "
    return "EXPLAIN QUERY PLAN "


def _classify_plan(lines: list[str], db_uri: str) -> tuple[str, str, str]:
    """Classify an EXPLAIN output into (scan_type, index_used, notes)."""
    full = " ".join(lines)

    if "postgresql" in db_uri:
        if "Seq Scan" in full:
            return "Seq Scan", "No", "full table scan"
        if "Index Scan" in full or "Index Only Scan" in full:
            idx = next((l for l in lines if "Index" in l), "")
            return "Index Scan", "Yes", idx.strip()[:60]
        if "Bitmap" in full:
            return "Bitmap Scan", "Yes", ""
        return "Other", "?", full[:60]

    # SQLite: look at the primary query line (first SCAN or SEARCH on the main table)
    for l in lines:
        line = str(l).strip()
        if "SCAN" in line and "USING INDEX" not in line:
            return "SCAN TABLE", "No", line[:60]
        if "SCAN" in line and "USING INDEX" in line:
            return "SCAN (index)", "Partial", line[:60]
        if "SEARCH" in line and "USING INDEX" in line:
            return "SEARCH (index)", "Yes", line[:60]
        if "SEARCH" in line:
            return "SEARCH", "Yes", line[:60]
    return "Other", "?", full[:60]


def main() -> None:
    parser = argparse.ArgumentParser(description="SQL EXPLAIN analysis for trace queries")
    parser.add_argument("--db-uri", default=None, help="SQLAlchemy DB URI (default: SQLite)")
    args = parser.parse_args()

    store, _tmpdir = create_store(args.db_uri)
    db_uri = args.db_uri or "sqlite"
    exp_id = str(store.create_experiment("bench_explain"))

    print(f"\n  Populating {CORPUS_SIZE} traces...")
    ids_ts = populate_corpus_with_ids(store, exp_id, CORPUS_SIZE, verbose=True)

    # Add assessments to some traces for completeness
    rng = random.Random(42)
    for tid, _ in ids_ts[:200]:
        store.create_assessment(generate_assessment(tid, rng=rng))

    explain_prefix = _get_explain_prefix(db_uri)

    print(f"\n{SEP}")
    print(f"  SQL EXPLAIN Analysis ({db_uri.split('://')[0] if '://' in db_uri else db_uri})")
    print(SEP)

    header = f"{'query':<18} | {'scan type':<16} | {'index':>5} | {'plan detail':<55}"
    print(header)
    print(DASH)

    for label, kwargs in SEARCH_QUERIES:
        # Capture the SQL from an actual search_traces call
        with count_queries(store) as queries:
            store.search_traces(locations=[exp_id], max_results=100, **kwargs)

        # Find the main search query (first SELECT, usually the biggest one)
        select_queries = [(q, p) for q, p in queries if q.strip().upper().startswith("SELECT")]
        if not select_queries:
            print(f"{label:<18} | {'no SELECT':16} | {'':>5} | {'(no queries captured)'}")
            continue

        # EXPLAIN the first (main) query
        main_sql, params = select_queries[0]

        # Build parameter dict for bind parameters
        if isinstance(params, dict):
            bind_params = params
        elif isinstance(params, (list, tuple)):
            bind_params = {f"param_{i}": v for i, v in enumerate(params)}
            # Replace positional ? with named :param_N
            for i in range(len(params)):
                main_sql = main_sql.replace("?", f":param_{i}", 1)
        else:
            bind_params = {}

        explain_sql = explain_prefix + main_sql

        try:
            with store.engine.connect() as conn:
                result = conn.execute(text(explain_sql), bind_params)
                lines = [str(row) for row in result.fetchall()]

            scan_type, index_used, notes = _classify_plan(lines, db_uri)
            print(f"{label:<18} | {scan_type:<16} | {index_used:>5} | {notes}")
        except Exception as e:
            print(f"{label:<18} | {'ERROR':16} | {'':>5} | {str(e)[:55]}")

    # Show raw EXPLAIN for the most interesting queries
    print("\n  Detailed EXPLAIN for span.name filter:")
    print(DASH)

    with count_queries(store) as queries:
        store.search_traces(
            locations=[exp_id],
            filter_string="span.name = 'llm_0'",
            max_results=100,
        )

    select_queries = [(q, p) for q, p in queries if q.strip().upper().startswith("SELECT")]
    for i, (sql, params) in enumerate(select_queries[:3]):
        if isinstance(params, (list, tuple)):
            for j in range(len(params)):
                sql = sql.replace("?", f":param_{j}", 1)
            params = {f"param_{j}": v for j, v in enumerate(params)}
        elif not isinstance(params, dict):
            params = {}

        try:
            with store.engine.connect() as conn:
                result = conn.execute(text(explain_prefix + sql), params)
                lines = [str(row) for row in result.fetchall()]
            print(f"  Query {i + 1}:")
            for line in lines:
                print(f"    {line}")
        except Exception as e:
            print(f"  Query {i + 1}: ERROR - {e}")

    print(SEP)


if __name__ == "__main__":
    main()
