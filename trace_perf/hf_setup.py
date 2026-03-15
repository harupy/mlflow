"""Prepare a shared SQLite database for hyperfine benchmarks.

Creates a temporary DB with a corpus of traces, then writes the DB path
and experiment ID to a file so the hf_*.py scripts can use them.

Usage:
    uv run python trace_perf/hf_setup.py
    uv run python trace_perf/hf_setup.py --traces 5000 --spans 50
"""

from __future__ import annotations

import argparse
import json
import random
import tempfile
from pathlib import Path

from utils import generate_assessment, populate_corpus_with_ids

from mlflow.store.tracking.sqlalchemy_store import SqlAlchemyStore

STATE_FILE = Path(tempfile.gettempdir()) / "mlflow_hf_state.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Setup DB for hyperfine benchmarks")
    parser.add_argument("--traces", type=int, default=1000, help="Number of traces (default: 1000)")
    parser.add_argument("--spans", type=int, default=10, help="Spans per trace (default: 10)")
    args = parser.parse_args()

    tmpdir = Path(tempfile.mkdtemp(prefix="mlflow_hf_"))
    db_path = tmpdir / "mlflow.db"
    db_uri = f"sqlite:///{db_path}"
    artifact_root = (tmpdir / "artifacts").as_uri()
    (tmpdir / "artifacts").mkdir(exist_ok=True)

    store = SqlAlchemyStore(db_uri, artifact_root)
    exp_id = str(store.create_experiment("hf_bench"))

    print(f"Populating {args.traces} traces ({args.spans} spans each)...")
    ids_ts = populate_corpus_with_ids(
        store, exp_id, args.traces, spans_per_trace=args.spans, verbose=True
    )

    # Add assessments to first 200 traces
    rng = random.Random(42)
    for tid, _ in ids_ts[:200]:
        store.create_assessment(generate_assessment(tid, rng=rng))

    trace_ids = [t[0] for t in ids_ts]

    state = {
        "db_uri": db_uri,
        "db_path": str(db_path),
        "experiment_id": exp_id,
        "trace_ids": trace_ids[:10],
        "num_traces": args.traces,
        "spans_per_trace": args.spans,
    }
    STATE_FILE.write_text(json.dumps(state))
    print(f"State written to {STATE_FILE}")
    print(f"DB: {db_uri}")


if __name__ == "__main__":
    main()
