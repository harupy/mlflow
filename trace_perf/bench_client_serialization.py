"""
Benchmark client-side trace/span serialization for large inputs/outputs.

Profiles each step of the serialization pipeline:
  1. JSON serialization  (dump_span_attribute_value)
  2. Span -> dict         (Span.to_dict)
  3. Span -> protobuf     (Span.to_otel_proto)
  4. Protobuf -> bytes    (ExportTraceServiceRequest.SerializeToString)
  5. Size stats           (add_size_stats_to_trace_metadata)

Usage:
    uv run python trace_perf/bench_client_serialization.py
    uv run python trace_perf/bench_client_serialization.py --profile
"""

from __future__ import annotations

import argparse
import cProfile
import gc
import json
import pstats
import random
import statistics
import time
import uuid
from dataclasses import dataclass, field

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk.resources import Resource as OTelResource
from utils import generate_spans, generate_trace_info

from mlflow.entities.span import Span
from mlflow.entities.trace import Trace
from mlflow.entities.trace_data import TraceData
from mlflow.tracing.utils import (
    TraceJSONEncoder,
    add_size_stats_to_trace_metadata,
    dump_span_attribute_value,
)
from mlflow.tracing.utils.otlp import resource_to_otel_proto

# ---------------------------------------------------------------------------
# Payload generators
# ---------------------------------------------------------------------------

# Simulates realistic LLM-style payloads at various sizes
PAYLOAD_SIZES = {
    "1KB": 1_000,
    "10KB": 10_000,
    "100KB": 100_000,
    "1MB": 1_000_000,
    "10MB": 10_000_000,
}


def _generate_chat_messages(target_bytes: int, rng: random.Random) -> list[dict[str, str]]:
    """Generate chat messages approximating the target byte size when JSON-serialized."""
    words = [
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
        "weight",
        "bias",
        "activation",
        "layer",
        "batch",
        "epoch",
        "accuracy",
    ]
    messages = []
    current_size = 0
    role_cycle = ["user", "assistant"]
    idx = 0

    while current_size < target_bytes:
        # Each message: ~50 bytes overhead for role/keys, rest is content
        remaining = target_bytes - current_size
        content_len = min(remaining, rng.randint(200, 2000))
        content = " ".join(rng.choices(words, k=content_len // 6))[:content_len]
        msg = {"role": role_cycle[idx % 2], "content": content}
        messages.append(msg)
        current_size += len(json.dumps(msg))
        idx += 1

    return messages


def generate_large_payload(target_bytes: int, rng: random.Random) -> dict[str, object]:
    """Generate a realistic LLM-style payload at the target size."""
    messages = _generate_chat_messages(target_bytes, rng)
    return {
        "messages": messages,
        "model": "gpt-4",
        "temperature": 0.7,
        "max_tokens": 4096,
    }


# ---------------------------------------------------------------------------
# Span generation with large payloads
# ---------------------------------------------------------------------------


def generate_spans_with_large_io(
    trace_id: str,
    num_spans: int,
    input_payload: dict[str, object],
    output_payload: dict[str, object],
    rng: random.Random,
) -> list[Span]:
    """Generate spans where the root span carries large input/output payloads."""
    spans = generate_spans(trace_id, num_spans, rng)

    # Replace root span with one carrying large inputs/outputs
    root = spans[0]
    from opentelemetry.sdk.trace import ReadableSpan as OTelReadableSpan

    from mlflow.entities.span import SpanType, create_mlflow_span
    from mlflow.tracing.constant import SpanAttributeKey

    attrs = dict(root._span.attributes)
    attrs[SpanAttributeKey.INPUTS] = json.dumps(input_payload, cls=TraceJSONEncoder)
    attrs[SpanAttributeKey.OUTPUTS] = json.dumps(output_payload, cls=TraceJSONEncoder)

    otel_span = OTelReadableSpan(
        name=root.name,
        context=root._span.context,
        parent=root._span.parent,
        attributes=attrs,
        start_time=root.start_time_ns,
        end_time=root.end_time_ns,
        status=root._span.status,
        resource=OTelResource.get_empty(),
    )
    spans[0] = create_mlflow_span(otel_span, trace_id, SpanType.AGENT)
    return spans


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------

WARMUP = 2
ITERATIONS = 10


@dataclass
class StepResult:
    name: str
    times_ms: list[float] = field(default_factory=list)

    @property
    def mean(self) -> float:
        return statistics.mean(self.times_ms)

    @property
    def p95(self) -> float:
        s = sorted(self.times_ms)
        k = (len(s) - 1) * 0.95
        f = int(k)
        return s[f] + (k - f) * (s[min(f + 1, len(s) - 1)] - s[f])

    @property
    def stddev(self) -> float:
        return statistics.stdev(self.times_ms) if len(self.times_ms) > 1 else 0.0


def _time_fn(fn, warmup: int = WARMUP, iterations: int = ITERATIONS) -> StepResult:
    """Time a callable, returning StepResult with measured times."""
    for _ in range(warmup):
        fn()

    gc.disable()
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)
    gc.enable()

    result = StepResult(name="")
    result.times_ms = times
    return result


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------


def bench_serialization(
    payload_label: str,
    target_bytes: int,
    num_spans: int,
    rng: random.Random,
) -> dict[str, StepResult]:
    trace_id = f"tr-{uuid.uuid4().hex}"
    input_payload = generate_large_payload(target_bytes, rng)
    output_payload = generate_large_payload(target_bytes, rng)

    spans = generate_spans_with_large_io(trace_id, num_spans, input_payload, output_payload, rng)
    trace_info = generate_trace_info(trace_id, "0", 1_700_000_000_000, rng)

    results: dict[str, StepResult] = {}

    # 1. JSON serialization of the large payload (what happens in set_inputs/set_outputs)
    r = _time_fn(lambda: dump_span_attribute_value(input_payload))
    r.name = "json_dumps"
    results["json_dumps"] = r

    # 2. Span.to_dict() for all spans
    r = _time_fn(lambda: [s.to_dict() for s in spans])
    r.name = "to_dict"
    results["to_dict"] = r

    # 3. Span.to_otel_proto() for all spans
    r = _time_fn(lambda: [s.to_otel_proto() for s in spans])
    r.name = "to_otel_proto"
    results["to_otel_proto"] = r

    # 4. Full protobuf serialization (ExportTraceServiceRequest.SerializeToString)
    def build_and_serialize():
        request = ExportTraceServiceRequest()
        resource_spans = request.resource_spans.add()
        resource = getattr(spans[0]._span, "resource", None)
        resource_spans.resource.CopyFrom(resource_to_otel_proto(resource))
        scope_spans = resource_spans.scope_spans.add()
        scope_spans.spans.extend(s.to_otel_proto() for s in spans)
        request.SerializeToString()

    r = _time_fn(build_and_serialize)
    r.name = "proto_serialize"
    results["proto_serialize"] = r

    # 5. add_size_stats_to_trace_metadata (re-serializes every span to JSON)
    def compute_size_stats():
        trace = Trace(info=trace_info, data=TraceData(spans=spans))
        add_size_stats_to_trace_metadata(trace)

    r = _time_fn(compute_size_stats)
    r.name = "size_stats"
    results["size_stats"] = r

    # Measure serialized sizes for context
    input_json = dump_span_attribute_value(input_payload)
    output_json = dump_span_attribute_value(output_payload)
    proto_request = ExportTraceServiceRequest()
    rs = proto_request.resource_spans.add()
    resource = getattr(spans[0]._span, "resource", None)
    rs.resource.CopyFrom(resource_to_otel_proto(resource))
    ss = rs.scope_spans.add()
    ss.spans.extend(s.to_otel_proto() for s in spans)
    proto_bytes = proto_request.SerializeToString()

    results["_sizes"] = StepResult(name="sizes")
    results["_sizes"].times_ms = [
        len(input_json) / 1024,  # input KB
        len(output_json) / 1024,  # output KB
        len(proto_bytes) / 1024,  # proto KB
    ]

    return results


def run_benchmarks(num_spans: int = 10, do_profile: bool = False):
    rng = random.Random(42)

    print(f"Client-side serialization benchmark ({num_spans} spans/trace)")
    print("=" * 90)

    # Header
    print(
        f"{'payload':<10} {'input KB':>10} {'output KB':>10} {'proto KB':>10} | "
        f"{'json_dumps':>12} {'to_dict':>12} {'to_proto':>12} {'proto_ser':>12} {'size_stats':>12}"
    )
    print(
        f"{'':10} {'':>10} {'':>10} {'':>10} | "
        f"{'mean (ms)':>12} {'mean (ms)':>12} "
        f"{'mean (ms)':>12} {'mean (ms)':>12} {'mean (ms)':>12}"
    )
    print("-" * 90)

    all_results = {}
    for label, target_bytes in PAYLOAD_SIZES.items():
        results = bench_serialization(label, target_bytes, num_spans, rng)
        all_results[label] = results

        sizes = results["_sizes"]
        print(
            f"{label:<10} "
            f"{sizes.times_ms[0]:>10.1f} "
            f"{sizes.times_ms[1]:>10.1f} "
            f"{sizes.times_ms[2]:>10.1f} | "
            f"{results['json_dumps'].mean:>12.2f} "
            f"{results['to_dict'].mean:>12.2f} "
            f"{results['to_otel_proto'].mean:>12.2f} "
            f"{results['proto_serialize'].mean:>12.2f} "
            f"{results['size_stats'].mean:>12.2f}"
        )

    # Detailed breakdown for largest payload
    print()
    print("Detailed breakdown for 10MB payload:")
    print("-" * 60)
    largest = all_results["10MB"]
    total = 0.0
    for key in ["json_dumps", "to_dict", "to_otel_proto", "proto_serialize", "size_stats"]:
        r = largest[key]
        total += r.mean
        print(
            f"  {r.name:<20} mean={r.mean:>10.2f} ms  "
            f"p95={r.p95:>10.2f} ms  std={r.stddev:>8.2f} ms"
        )
    print(f"  {'TOTAL':<20} mean={total:>10.2f} ms")

    # Profile the largest case
    if do_profile:
        print()
        print("Profiling 10MB payload (50 iterations)...")
        trace_id = f"tr-{uuid.uuid4().hex}"
        input_payload = generate_large_payload(10_000_000, rng)
        output_payload = generate_large_payload(10_000_000, rng)
        spans = generate_spans_with_large_io(
            trace_id, num_spans, input_payload, output_payload, rng
        )
        trace_info = generate_trace_info(trace_id, "0", 1_700_000_000_000, rng)

        prof = cProfile.Profile()
        prof.enable()
        for _ in range(50):
            # Full pipeline
            dump_span_attribute_value(input_payload)
            dump_span_attribute_value(output_payload)
            for s in spans:
                s.to_dict()
            request = ExportTraceServiceRequest()
            rs = request.resource_spans.add()
            resource = getattr(spans[0]._span, "resource", None)
            rs.resource.CopyFrom(resource_to_otel_proto(resource))
            ss = rs.scope_spans.add()
            ss.spans.extend(s.to_otel_proto() for s in spans)
            request.SerializeToString()
            trace = Trace(info=trace_info, data=TraceData(spans=spans))
            add_size_stats_to_trace_metadata(trace)
        prof.disable()

        prof_path = "client_serialization.prof"
        prof.dump_stats(prof_path)
        print(f"Profile saved to {prof_path}")
        print()

        stats = pstats.Stats(prof)
        stats.strip_dirs()
        stats.sort_stats("cumulative")
        stats.print_stats(30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark client-side span serialization")
    parser.add_argument("--spans", type=int, default=10, help="Spans per trace (default: 10)")
    parser.add_argument("--profile", action="store_true", help="Run cProfile on 10MB case")
    args = parser.parse_args()

    run_benchmarks(num_spans=args.spans, do_profile=args.profile)
