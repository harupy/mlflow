"""Benchmark how serialized span object size affects performance.

Measures ingestion, get_trace() deserialization, and search latency
as the number of attributes per span grows, which increases the
serialized span size in the JSON content column.
"""

from __future__ import annotations

import json
import random
import time
import uuid
from unittest import mock

from opentelemetry import trace as trace_api
from opentelemetry.sdk.resources import Resource as OTelResource
from opentelemetry.sdk.trace import ReadableSpan as OTelReadableSpan
from utils import create_store, generate_trace_info, percentile

from mlflow.entities.span import SpanType, create_mlflow_span
from mlflow.tracing.utils import TraceJSONEncoder

SEP = "=" * 90
DASH = "-" * 90

# Attribute counts control span size: each attribute adds ~50-200 bytes of JSON
ATTR_COUNTS = [5, 20, 50, 100, 200]
SPANS_PER_TRACE = 10
INGEST_ITERATIONS = 10
LOAD_ITERATIONS = 20
SEARCH_CORPUS = 100
SEARCH_ITERATIONS = 15
WARMUP = 3


def _make_span_context(trace_num, span_num):
    ctx = mock.Mock()
    ctx.trace_id = trace_num
    ctx.span_id = span_num
    ctx.is_remote = False
    ctx.trace_flags = trace_api.TraceFlags(1)
    ctx.trace_state = trace_api.TraceState()
    return ctx


def _generate_spans_with_attrs(trace_id, num_spans, num_attrs, rng):
    trace_num = rng.randint(1, 2**63)
    base_ns = 1_000_000_000_000
    spans = []

    for i in range(num_spans):
        is_root = i == 0
        parent_id = None if is_root else rng.choice(range(1, i + 1))

        attrs = {
            "mlflow.traceRequestId": json.dumps(trace_id),
            "mlflow.spanType": json.dumps(SpanType.LLM, cls=TraceJSONEncoder),
        }

        # Add N custom attributes to inflate span size
        for j in range(num_attrs):
            key = f"custom.attr_{j}"
            value = {
                "value": f"attribute_value_{j}_" + "x" * rng.randint(10, 100),
                "metadata": {"index": j, "type": "benchmark"},
            }
            attrs[key] = json.dumps(value, cls=TraceJSONEncoder)

        parent_ctx = _make_span_context(trace_num, parent_id) if parent_id else None
        otel_span = OTelReadableSpan(
            name=f"span_{i}" if not is_root else "root",
            context=_make_span_context(trace_num, i + 1),
            parent=parent_ctx,
            attributes=attrs,
            start_time=base_ns + i * 10_000_000,
            end_time=base_ns + i * 10_000_000 + rng.randint(5_000_000, 50_000_000),
            status=trace_api.Status(trace_api.StatusCode.OK),
            resource=OTelResource.get_empty(),
        )
        spans.append(create_mlflow_span(otel_span, trace_id, SpanType.LLM))

    return spans


def _measure_span_size(spans):
    """Measure average serialized JSON size of spans."""
    total = sum(len(json.dumps(s.to_dict(), cls=TraceJSONEncoder).encode()) for s in spans)
    return total / len(spans)


def main() -> None:
    rng = random.Random(42)

    print(f"\n{SEP}")
    print("  Span Size Benchmark (attributes per span → serialized size → performance)")
    print(SEP)

    # --- Measure span sizes ---
    print(f"\n  SPAN SIZES ({SPANS_PER_TRACE} spans/trace)")
    print(DASH)
    header = f"{'attrs/span':>10} | {'avg span size':>14} | {'trace content':>14}"
    print(header)
    print(DASH)

    size_info = {}
    for num_attrs in ATTR_COUNTS:
        tid = f"tr-{uuid.uuid4().hex}"
        spans = _generate_spans_with_attrs(tid, SPANS_PER_TRACE, num_attrs, rng)
        avg_size = _measure_span_size(spans)
        total_size = avg_size * len(spans)
        size_info[num_attrs] = avg_size
        print(f"{num_attrs:>10} | {avg_size / 1024:>12.1f} KB | {total_size / 1024:>12.1f} KB")

    # --- Ingestion ---
    print(f"\n  INGESTION ({INGEST_ITERATIONS} iterations)")
    print(DASH)
    header = (
        f"{'attrs/span':>10} | {'avg span':>10} | {'p50(ms)':>8} | "
        f"{'p95(ms)':>8} | {'vs baseline':>11}"
    )
    print(header)
    print(DASH)

    baseline_p50 = None
    for num_attrs in ATTR_COUNTS:
        store, _tmpdir = create_store()
        exp_id = str(store.create_experiment(f"ingest_{num_attrs}"))

        # Warmup
        for _ in range(WARMUP):
            tid = f"tr-{uuid.uuid4().hex}"
            ti = generate_trace_info(tid, exp_id, 1_700_000_000_000, rng)
            spans = _generate_spans_with_attrs(tid, SPANS_PER_TRACE, num_attrs, rng)
            store.start_trace(ti)
            store.log_spans(exp_id, spans)

        # Measure
        times = []
        for i in range(INGEST_ITERATIONS):
            tid = f"tr-{uuid.uuid4().hex}"
            ti = generate_trace_info(tid, exp_id, 1_700_000_000_000 + i * 1000, rng)
            spans = _generate_spans_with_attrs(tid, SPANS_PER_TRACE, num_attrs, rng)
            t0 = time.perf_counter()
            store.start_trace(ti)
            store.log_spans(exp_id, spans)
            times.append((time.perf_counter() - t0) * 1000)

        p50 = percentile(times, 50)
        if baseline_p50 is None:
            baseline_p50 = p50
        ratio = p50 / baseline_p50 if baseline_p50 > 0 else 0
        avg_kb = size_info[num_attrs] / 1024
        print(
            f"{num_attrs:>10} | {avg_kb:>8.1f} KB | {p50:>8.1f} | "
            f"{percentile(times, 95):>8.1f} | {ratio:>10.1f}x"
        )

    # --- get_trace() deserialization ---
    print(f"\n  GET_TRACE deserialization ({LOAD_ITERATIONS} iterations)")
    print(DASH)
    header = (
        f"{'attrs/span':>10} | {'avg span':>10} | {'p50(ms)':>8} | "
        f"{'p95(ms)':>8} | {'vs baseline':>11}"
    )
    print(header)
    print(DASH)

    baseline_p50 = None
    for num_attrs in ATTR_COUNTS:
        store, _tmpdir = create_store()
        exp_id = str(store.create_experiment(f"load_{num_attrs}"))
        tid = f"tr-{uuid.uuid4().hex}"
        ti = generate_trace_info(tid, exp_id, 1_700_000_000_000, rng)
        spans = _generate_spans_with_attrs(tid, SPANS_PER_TRACE, num_attrs, rng)
        store.start_trace(ti)
        store.log_spans(exp_id, spans)

        # Warmup
        for _ in range(WARMUP):
            store.get_trace(tid)

        # Measure
        times = []
        for _ in range(LOAD_ITERATIONS):
            t0 = time.perf_counter()
            store.get_trace(tid)
            times.append((time.perf_counter() - t0) * 1000)

        p50 = percentile(times, 50)
        if baseline_p50 is None:
            baseline_p50 = p50
        ratio = p50 / baseline_p50 if baseline_p50 > 0 else 0
        avg_kb = size_info[num_attrs] / 1024
        print(
            f"{num_attrs:>10} | {avg_kb:>8.1f} KB | {p50:>8.2f} | "
            f"{percentile(times, 95):>8.2f} | {ratio:>10.1f}x"
        )

    # --- Search ---
    print(
        f"\n  SEARCH_TRACES ({SEARCH_CORPUS} traces, "
        f"max_results=100, {SEARCH_ITERATIONS} iterations)"
    )
    print(DASH)
    header = (
        f"{'attrs/span':>10} | {'avg span':>10} | {'p50(ms)':>8} | "
        f"{'p95(ms)':>8} | {'vs baseline':>11}"
    )
    print(header)
    print(DASH)

    baseline_p50 = None
    for num_attrs in ATTR_COUNTS:
        store, _tmpdir = create_store()
        exp_id = str(store.create_experiment(f"search_{num_attrs}"))

        for i in range(SEARCH_CORPUS):
            tid = f"tr-{uuid.uuid4().hex}"
            ti = generate_trace_info(tid, exp_id, 1_700_000_000_000 + i * 1000, rng)
            spans = _generate_spans_with_attrs(tid, SPANS_PER_TRACE, num_attrs, rng)
            store.start_trace(ti)
            store.log_spans(exp_id, spans)

        # Warmup
        for _ in range(WARMUP):
            store.search_traces(locations=[exp_id], max_results=100)

        # Measure
        times = []
        for _ in range(SEARCH_ITERATIONS):
            t0 = time.perf_counter()
            store.search_traces(locations=[exp_id], max_results=100)
            times.append((time.perf_counter() - t0) * 1000)

        p50 = percentile(times, 50)
        if baseline_p50 is None:
            baseline_p50 = p50
        ratio = p50 / baseline_p50 if baseline_p50 > 0 else 0
        avg_kb = size_info[num_attrs] / 1024
        print(
            f"{num_attrs:>10} | {avg_kb:>8.1f} KB | {p50:>8.1f} | "
            f"{percentile(times, 95):>8.1f} | {ratio:>10.1f}x"
        )

    print("\n  Span size is controlled by attribute count (each adds ~50-200B of JSON)")
    print("  Ingestion and deserialization scale with span size; search does not")
    print(SEP)


if __name__ == "__main__":
    main()
