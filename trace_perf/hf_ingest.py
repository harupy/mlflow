"""Hyperfine target: ingest one trace (start_trace + log_spans)."""

from __future__ import annotations

import json
import random
import tempfile
import uuid
from pathlib import Path

from utils import generate_spans, generate_trace_info

from mlflow.store.tracking.sqlalchemy_store import SqlAlchemyStore

STATE_FILE = Path(tempfile.gettempdir()) / "mlflow_hf_state.json"


def main() -> None:
    state = json.loads(STATE_FILE.read_text())
    store = SqlAlchemyStore(state["db_uri"], "file:///dev/null")

    rng = random.Random()
    tid = f"tr-{uuid.uuid4().hex}"
    ti = generate_trace_info(tid, state["experiment_id"], 1_700_000_000_000, rng)
    spans = generate_spans(tid, state["spans_per_trace"], rng)
    store.start_trace(ti)
    store.log_spans(state["experiment_id"], spans)


if __name__ == "__main__":
    main()
