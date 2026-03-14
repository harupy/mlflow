"""Shared utilities for trace benchmarks."""

from __future__ import annotations

import json
import random
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Generator
from unittest import mock

from opentelemetry import trace as trace_api
from opentelemetry.sdk.resources import Resource as _OTelResource
from opentelemetry.sdk.trace import ReadableSpan as OTelReadableSpan
from sqlalchemy import event, text

from mlflow.entities.assessment import Feedback
from mlflow.entities.assessment_source import AssessmentSource, AssessmentSourceType
from mlflow.entities.span import Span, SpanType, create_mlflow_span
from mlflow.entities.trace_info import TraceInfo
from mlflow.entities.trace_location import TraceLocation
from mlflow.entities.trace_state import TraceState
from mlflow.store.tracking.sqlalchemy_store import SqlAlchemyStore
from mlflow.tracing.constant import CostKey, SpanAttributeKey, TraceTagKey
from mlflow.tracing.utils import TraceJSONEncoder

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SPAN_TYPE_WEIGHTS = [
    (SpanType.LLM, 0.30),
    (SpanType.RETRIEVER, 0.20),
    (SpanType.TOOL, 0.15),
    (SpanType.CHAIN, 0.15),
    (SpanType.EMBEDDING, 0.10),
    (SpanType.PARSER, 0.10),
]
SPAN_TYPES = [t for t, _ in SPAN_TYPE_WEIGHTS]
SPAN_TYPE_CUM_WEIGHTS = [w for _, w in SPAN_TYPE_WEIGHTS]

MODELS = ["gpt-4", "gpt-4-turbo", "claude-3-sonnet", "claude-3-opus", "llama-3-70b"]
PROVIDERS = ["openai", "anthropic", "meta"]
TAG_ENVS = ["prod", "staging"]
TAG_MODELS = ["gpt-4", "claude-3"]

# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------


def _make_span_context(trace_num: int, span_num: int) -> mock.Mock:
    ctx = mock.Mock()
    ctx.trace_id = trace_num
    ctx.span_id = span_num
    ctx.is_remote = False
    ctx.trace_flags = trace_api.TraceFlags(1)
    ctx.trace_state = trace_api.TraceState()
    return ctx


def _pick_span_type(rng: random.Random) -> str:
    return rng.choices(SPAN_TYPES, weights=SPAN_TYPE_CUM_WEIGHTS, k=1)[0]


def generate_spans(trace_id: str, num_spans: int, rng: random.Random) -> list[Span]:
    trace_num = rng.randint(1, 2**63)
    base_ns = 1_000_000_000_000
    span_ids = list(range(1, num_spans + 1))

    spans: list[Span] = []
    for i, sid in enumerate(span_ids):
        is_root = i == 0
        span_type = SpanType.AGENT if is_root else _pick_span_type(rng)

        if is_root:
            parent_id = None
        else:
            candidates = span_ids[max(0, i - 4) : i]
            parent_id = rng.choice(candidates)

        start_ns = base_ns + i * 10_000_000
        end_ns = start_ns + rng.randint(5_000_000, 50_000_000)

        attrs: dict[str, object] = {}
        if is_root:
            attrs[SpanAttributeKey.INPUTS] = {"query": "What is machine learning?"}
            attrs[SpanAttributeKey.OUTPUTS] = {"response": "Machine learning is a subset of AI."}
        if span_type == SpanType.LLM:
            input_tokens = rng.randint(50, 500)
            output_tokens = rng.randint(20, 200)
            attrs[SpanAttributeKey.CHAT_USAGE] = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            }
            input_cost = input_tokens * 0.00003
            output_cost = output_tokens * 0.00006
            attrs[SpanAttributeKey.LLM_COST] = {
                CostKey.INPUT_COST: input_cost,
                CostKey.OUTPUT_COST: output_cost,
                CostKey.TOTAL_COST: input_cost + output_cost,
            }
            attrs[SpanAttributeKey.MODEL] = rng.choice(MODELS)
            attrs[SpanAttributeKey.MODEL_PROVIDER] = rng.choice(PROVIDERS)

        parent_ctx = _make_span_context(trace_num, parent_id) if parent_id else None
        otel_span = OTelReadableSpan(
            name=f"{span_type.lower()}_{i}" if not is_root else "agent_run",
            context=_make_span_context(trace_num, sid),
            parent=parent_ctx,
            attributes={
                "mlflow.traceRequestId": json.dumps(trace_id),
                "mlflow.spanType": json.dumps(span_type, cls=TraceJSONEncoder),
                **{k: json.dumps(v, cls=TraceJSONEncoder) for k, v in attrs.items()},
            },
            start_time=start_ns,
            end_time=end_ns,
            status=trace_api.Status(trace_api.StatusCode.OK),
            resource=_OTelResource.get_empty(),
        )
        spans.append(create_mlflow_span(otel_span, trace_id, span_type))

    return spans


def generate_trace_info(
    trace_id: str,
    experiment_id: str,
    request_time_ms: int,
    rng: random.Random,
) -> TraceInfo:
    state = rng.choice([TraceState.OK, TraceState.OK, TraceState.OK, TraceState.ERROR])
    return TraceInfo(
        trace_id=trace_id,
        trace_location=TraceLocation.from_experiment_id(experiment_id),
        request_time=request_time_ms,
        state=state,
        execution_duration=rng.randint(100, 5000),
        tags={
            TraceTagKey.TRACE_NAME: f"trace_{trace_id[-8:]}",
            "env": rng.choice(TAG_ENVS),
            "model": rng.choice(TAG_MODELS),
        },
    )


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------


def create_store(db_uri: str | None = None) -> tuple[SqlAlchemyStore, Path]:
    tmpdir = Path(tempfile.mkdtemp())
    db_uri = db_uri or f"sqlite:///{tmpdir / 'mlflow.db'}"
    artifact_root = (tmpdir / "artifacts").as_uri()
    (tmpdir / "artifacts").mkdir(exist_ok=True)
    store = SqlAlchemyStore(db_uri, artifact_root)
    return store, tmpdir


def populate_corpus(
    store: SqlAlchemyStore,
    experiment_id: str,
    num_traces: int,
    spans_per_trace: int = 10,
    seed: int = 123,
    verbose: bool = True,
) -> None:
    rng = random.Random(seed)
    base_time_ms = 1_700_000_000_000
    for i in range(num_traces):
        tid = f"tr-{uuid.uuid4().hex}"
        ti = generate_trace_info(tid, experiment_id, base_time_ms + i * 1000, rng)
        spans = generate_spans(tid, spans_per_trace, rng)
        store.start_trace(ti)
        store.log_spans(experiment_id, spans)
        if verbose and (i + 1) % 100 == 0:
            pct = (i + 1) / num_traces * 100
            print(f"\r  {i + 1}/{num_traces} ({pct:.0f}%)", end="", flush=True)
    if verbose and num_traces >= 100:
        print()


# ---------------------------------------------------------------------------
# SQL query counter
# ---------------------------------------------------------------------------


def get_db_size_mb(store: SqlAlchemyStore, db_path: Path | None = None) -> float | None:
    url = str(store.engine.url)
    if "sqlite" in url:
        if db_path and db_path.exists():
            return db_path.stat().st_size / (1024 * 1024)
        return None
    if "postgresql" in url:
        db_name = store.engine.url.database
        with store.engine.connect() as conn:
            row = conn.execute(text("SELECT pg_database_size(:db)"), {"db": db_name}).fetchone()
            return row[0] / (1024 * 1024) if row else None
    return None


@contextmanager
def count_queries(
    store: SqlAlchemyStore,
) -> Generator[list[tuple[str, tuple[object, ...]]], None, None]:
    """Context manager that captures SQL statements and parameters executed by the store.

    Usage:
        with count_queries(store) as queries:
            store.search_traces(...)
        print(len(queries))  # number of SQL statements
        # Each entry is (statement, parameters)
    """
    queries: list[tuple[str, tuple[object, ...]]] = []
    engine = store.engine

    def _listener(_conn, _cursor, statement, parameters, _context, _executemany):
        queries.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", _listener)
    try:
        yield queries
    finally:
        event.remove(engine, "before_cursor_execute", _listener)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def percentile(data: list[float], pct: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * pct / 100
    f = int(k)
    return s[f] + (k - f) * (s[min(f + 1, len(s) - 1)] - s[f])


# ---------------------------------------------------------------------------
# Payload generation
# ---------------------------------------------------------------------------

WORDS = [
    "the",
    "machine",
    "learning",
    "model",
    "processes",
    "input",
    "data",
    "neural",
    "network",
    "training",
    "inference",
    "transformer",
    "attention",
    "embedding",
    "gradient",
    "optimization",
    "loss",
    "function",
    "parameter",
]


def generate_large_payload(target_bytes: int, rng: random.Random) -> dict[str, object]:
    messages = []
    current_size = 0
    roles = ["user", "assistant"]
    idx = 0
    while current_size < target_bytes:
        remaining = target_bytes - current_size
        content_len = min(remaining, rng.randint(200, 2000))
        content = " ".join(rng.choices(WORDS, k=content_len // 6))[:content_len]
        msg = {"role": roles[idx % 2], "content": content}
        messages.append(msg)
        current_size += len(json.dumps(msg))
        idx += 1
    return {"messages": messages, "model": "gpt-4", "temperature": 0.7}


def make_spans_with_payload(
    trace_id: str,
    num_spans: int,
    input_payload: dict[str, object] | None,
    output_payload: dict[str, object] | None,
    rng: random.Random,
) -> list[Span]:
    spans = generate_spans(trace_id, num_spans, rng)
    if input_payload is None and output_payload is None:
        return spans

    root = spans[0]
    attrs = dict(root._span.attributes)
    if input_payload is not None:
        attrs[SpanAttributeKey.INPUTS] = json.dumps(input_payload, cls=TraceJSONEncoder)
    if output_payload is not None:
        attrs[SpanAttributeKey.OUTPUTS] = json.dumps(output_payload, cls=TraceJSONEncoder)

    otel_span = OTelReadableSpan(
        name=root.name,
        context=root._span.context,
        parent=root._span.parent,
        attributes=attrs,
        start_time=root.start_time_ns,
        end_time=root.end_time_ns,
        status=root._span.status,
        resource=_OTelResource.get_empty(),
    )
    spans[0] = create_mlflow_span(otel_span, trace_id, SpanType.AGENT)
    return spans


# ---------------------------------------------------------------------------
# Assessment generation
# ---------------------------------------------------------------------------

ASSESSMENT_NAMES = ["correctness", "relevance", "fluency"]


def generate_assessment(
    trace_id: str,
    name: str | None = None,
    value: float | None = None,
    rng: random.Random | None = None,
) -> Feedback:
    rng = rng or random.Random()
    return Feedback(
        name=name or rng.choice(ASSESSMENT_NAMES),
        value=value if value is not None else round(rng.uniform(0.0, 1.0), 2),
        source=AssessmentSource(
            source_type=AssessmentSourceType.LLM_JUDGE,
            source_id="bench-evaluator",
        ),
        trace_id=trace_id,
        rationale="benchmark assessment",
    )


# ---------------------------------------------------------------------------
# Populate with trace IDs returned
# ---------------------------------------------------------------------------


def populate_corpus_with_ids(
    store: SqlAlchemyStore,
    experiment_id: str,
    num_traces: int,
    spans_per_trace: int = 10,
    seed: int = 123,
    verbose: bool = True,
) -> list[tuple[str, int]]:
    """Like populate_corpus but returns (trace_id, timestamp_ms) pairs."""
    rng = random.Random(seed)
    base_time_ms = 1_700_000_000_000
    results: list[tuple[str, int]] = []
    for i in range(num_traces):
        tid = f"tr-{uuid.uuid4().hex}"
        ts = base_time_ms + i * 1000
        ti = generate_trace_info(tid, experiment_id, ts, rng)
        spans = generate_spans(tid, spans_per_trace, rng)
        store.start_trace(ti)
        store.log_spans(experiment_id, spans)
        results.append((tid, ts))
        if verbose and (i + 1) % 100 == 0:
            pct = (i + 1) / num_traces * 100
            print(f"\r  {i + 1}/{num_traces} ({pct:.0f}%)", end="", flush=True)
    if verbose and num_traces >= 100:
        print()
    return results


# ---------------------------------------------------------------------------
# OTLP protobuf helpers
# ---------------------------------------------------------------------------


def build_otlp_request(spans: list[Span]) -> bytes:
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )

    from mlflow.tracing.utils.otlp import resource_to_otel_proto

    request = ExportTraceServiceRequest()
    resource_spans = request.resource_spans.add()
    resource = getattr(spans[0]._span, "resource", None)
    resource_spans.resource.CopyFrom(resource_to_otel_proto(resource))
    scope_spans = resource_spans.scope_spans.add()
    scope_spans.spans.extend(s.to_otel_proto() for s in spans)
    return request.SerializeToString()
