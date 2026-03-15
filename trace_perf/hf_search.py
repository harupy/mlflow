"""Hyperfine target: search traces (default view, no filter)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from mlflow.store.tracking.sqlalchemy_store import SqlAlchemyStore

STATE_FILE = Path(tempfile.gettempdir()) / "mlflow_hf_state.json"


def main() -> None:
    state = json.loads(STATE_FILE.read_text())
    store = SqlAlchemyStore(state["db_uri"], "file:///dev/null")
    store.search_traces(locations=[state["experiment_id"]], max_results=100)


if __name__ == "__main__":
    main()
