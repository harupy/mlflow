"""Single-operation benchmark targets for hyperfine.

Each subcommand performs one operation against a pre-populated DB
(created by the `setup` subcommand). Designed to be called by hyperfine.

Usage:
    # 1. Create the shared DB
    uv run python trace_perf/hf_bench.py setup

    # 2. Run with hyperfine
    hyperfine \
      --warmup 3 \
      "uv run python trace_perf/hf_bench.py ingest" \
      "uv run python trace_perf/hf_bench.py search" \
      "uv run python trace_perf/hf_bench.py get-trace" \
      "uv run python trace_perf/hf_bench.py text-search"

    # 3. Compare two versions
    hyperfine \
      "uv run --with 'mlflow==2.20.0' python trace_perf/hf_bench.py search" \
      "uv run python trace_perf/hf_bench.py search"
"""

from __future__ import annotations

import argparse
import json
import random
import tempfile
import uuid
from pathlib import Path

STATE_FILE = Path(tempfile.gettempdir()) / "mlflow_hf_state.json"


def _load_state() -> dict[str, object]:
    return json.loads(STATE_FILE.read_text())


def _make_store(state: dict[str, object]):
    from mlflow.store.tracking.sqlalchemy_store import SqlAlchemyStore

    return SqlAlchemyStore(state["db_uri"], "file:///dev/null")


def cmd_setup(args: argparse.Namespace) -> None:
    from utils import generate_assessment, populate_corpus_with_ids

    from mlflow.store.tracking.sqlalchemy_store import SqlAlchemyStore

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

    rng = random.Random(42)
    for tid, _ in ids_ts[:200]:
        store.create_assessment(generate_assessment(tid, rng=rng))

    state = {
        "db_uri": db_uri,
        "experiment_id": exp_id,
        "trace_ids": [t[0] for t in ids_ts[:10]],
        "spans_per_trace": args.spans,
    }
    STATE_FILE.write_text(json.dumps(state))
    print(f"DB: {db_uri}")
    print(f"State: {STATE_FILE}")


def cmd_ingest(_args: argparse.Namespace) -> None:
    from utils import generate_spans, generate_trace_info

    state = _load_state()
    store = _make_store(state)
    rng = random.Random()
    tid = f"tr-{uuid.uuid4().hex}"
    ti = generate_trace_info(tid, state["experiment_id"], 1_700_000_000_000, rng)
    spans = generate_spans(tid, state["spans_per_trace"], rng)
    store.start_trace(ti)
    store.log_spans(state["experiment_id"], spans)


def cmd_search(_args: argparse.Namespace) -> None:
    state = _load_state()
    store = _make_store(state)
    store.search_traces(locations=[state["experiment_id"]], max_results=100)


def cmd_get_trace(_args: argparse.Namespace) -> None:
    state = _load_state()
    store = _make_store(state)
    store.get_trace(state["trace_ids"][0])


def cmd_text_search(_args: argparse.Namespace) -> None:
    state = _load_state()
    store = _make_store(state)
    store.search_traces(
        locations=[state["experiment_id"]],
        filter_string="trace.text ILIKE '%machine%'",
        max_results=100,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Hyperfine benchmark targets")
    sub = parser.add_subparsers(dest="command", required=True)

    setup_p = sub.add_parser("setup", help="Create shared DB")
    setup_p.add_argument("--traces", type=int, default=1000)
    setup_p.add_argument("--spans", type=int, default=10)

    sub.add_parser("ingest", help="Ingest one trace")
    sub.add_parser("search", help="Search traces (no filter)")
    sub.add_parser("get-trace", help="Load single trace")
    sub.add_parser("text-search", help="Full-text search (ILIKE)")

    args = parser.parse_args()
    {
        "setup": cmd_setup,
        "ingest": cmd_ingest,
        "search": cmd_search,
        "get-trace": cmd_get_trace,
        "text-search": cmd_text_search,
    }[args.command](args)


if __name__ == "__main__":
    main()
