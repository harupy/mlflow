"""Benchmark end-to-end HTTP path overhead vs direct store calls.

Measures the full OTLP HTTP pipeline:
  protobuf serialize → HTTP POST → server deserialize → store write

Compares against direct store.start_trace() + store.log_spans() to
isolate transport/serialization overhead.

Uses FastAPI TestClient (no real network) for deterministic measurement.
"""

from __future__ import annotations

import os
import random
import time
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from utils import (
    build_otlp_request,
    create_store,
    generate_spans,
    generate_trace_info,
    percentile,
)

from mlflow.server.fastapi_app import create_fastapi_app
from mlflow.tracing.utils.otlp import MLFLOW_EXPERIMENT_ID_HEADER, OTLP_TRACES_PATH

SEP = "=" * 90
DASH = "-" * 90

SPAN_COUNTS = [10, 50, 100]
ITERATIONS = 20
WARMUP = 3


def _setup_server(store):

    # Disable security middleware (host validation) for test client
    os.environ["MLFLOW_SERVER_DISABLE_SECURITY_MIDDLEWARE"] = "true"

    # Patch _get_tracking_store in both handlers and otel_api modules
    # (otel_api imports the function at module level)
    patcher1 = patch(
        "mlflow.server.handlers._get_tracking_store",
        return_value=store,
    )
    patcher2 = patch(
        "mlflow.server.otel_api._get_tracking_store",
        return_value=store,
    )
    patcher1.start()
    patcher2.start()
    app = create_fastapi_app()
    client = TestClient(app)
    return client, (patcher1, patcher2)


def bench_direct(store, exp_id, num_spans, rng):
    base_time_ms = 1_700_000_000_000
    # Warmup
    for i in range(WARMUP):
        tid = f"tr-{uuid.uuid4().hex}"
        ti = generate_trace_info(tid, exp_id, base_time_ms + i * 1000, rng)
        spans = generate_spans(tid, num_spans, rng)
        store.start_trace(ti)
        store.log_spans(exp_id, spans)

    # Measure
    times = []
    for i in range(ITERATIONS):
        tid = f"tr-{uuid.uuid4().hex}"
        ti = generate_trace_info(tid, exp_id, base_time_ms + (WARMUP + i) * 1000, rng)
        spans = generate_spans(tid, num_spans, rng)
        # Pre-generate data, then time only the store calls
        t0 = time.perf_counter()
        store.start_trace(ti)
        store.log_spans(exp_id, spans)
        times.append((time.perf_counter() - t0) * 1000)
    return times


def bench_http(client, store, exp_id, num_spans, rng):
    base_time_ms = 1_700_000_000_000
    headers = {
        "Content-Type": "application/x-protobuf",
        MLFLOW_EXPERIMENT_ID_HEADER: exp_id,
    }

    # Warmup
    for i in range(WARMUP):
        tid = f"tr-{uuid.uuid4().hex}"
        ti = generate_trace_info(tid, exp_id, base_time_ms + i * 1000, rng)
        spans = generate_spans(tid, num_spans, rng)
        store.start_trace(ti)
        body = build_otlp_request(spans)
        client.post(OTLP_TRACES_PATH, content=body, headers=headers)

    # Measure
    times = []
    for i in range(ITERATIONS):
        tid = f"tr-{uuid.uuid4().hex}"
        ti = generate_trace_info(tid, exp_id, base_time_ms + (WARMUP + i) * 1000, rng)
        spans = generate_spans(tid, num_spans, rng)
        store.start_trace(ti)
        # Pre-serialize, then time only the HTTP round-trip
        body = build_otlp_request(spans)
        t0 = time.perf_counter()
        resp = client.post(OTLP_TRACES_PATH, content=body, headers=headers)
        times.append((time.perf_counter() - t0) * 1000)
        if resp.status_code != 200:
            print(f"  WARNING: HTTP {resp.status_code}: {resp.text[:100]}")
    return times


def bench_serialize_only(num_spans, rng):
    """Time just the protobuf serialization step."""
    times = []
    for _ in range(WARMUP):
        tid = f"tr-{uuid.uuid4().hex}"
        spans = generate_spans(tid, num_spans, rng)
        build_otlp_request(spans)

    for _ in range(ITERATIONS):
        tid = f"tr-{uuid.uuid4().hex}"
        spans = generate_spans(tid, num_spans, rng)
        t0 = time.perf_counter()
        build_otlp_request(spans)
        times.append((time.perf_counter() - t0) * 1000)
    return times


def main() -> None:
    store, _tmpdir = create_store()
    client, patchers = _setup_server(store)

    print(f"\n{SEP}")
    print("  End-to-End HTTP Path Benchmark (FastAPI TestClient, no network)")
    print(SEP)

    header = (
        f"{'spans':>6} | {'direct p50':>10} | {'HTTP p50':>9} | "
        f"{'serialize':>9} | {'overhead':>8} | {'direct p95':>10} | {'HTTP p95':>9}"
    )
    print(header)
    print(DASH)

    for num_spans in SPAN_COUNTS:
        rng_d = random.Random(42)
        rng_h = random.Random(42)
        rng_s = random.Random(42)

        exp_id_d = str(store.create_experiment(f"direct_{num_spans}"))
        exp_id_h = str(store.create_experiment(f"http_{num_spans}"))

        direct_times = bench_direct(store, exp_id_d, num_spans, rng_d)
        http_times = bench_http(client, store, exp_id_h, num_spans, rng_h)
        ser_times = bench_serialize_only(num_spans, rng_s)

        dp50 = percentile(direct_times, 50)
        hp50 = percentile(http_times, 50)
        sp50 = percentile(ser_times, 50)
        ratio = hp50 / dp50 if dp50 > 0 else 0

        print(
            f"{num_spans:>6} | {dp50:>9.1f}ms | {hp50:>8.1f}ms | "
            f"{sp50:>8.1f}ms | {ratio:>7.1f}x | "
            f"{percentile(direct_times, 95):>9.1f}ms | {percentile(http_times, 95):>8.1f}ms"
        )

    for p in patchers:
        p.stop()

    print("\n  direct = store.start_trace() + store.log_spans()")
    print("  HTTP = POST protobuf to OTLP endpoint → server deserialize → store")
    print("  serialize = protobuf build + SerializeToString only")
    print("  overhead = HTTP_p50 / direct_p50")
    print(SEP)


if __name__ == "__main__":
    main()
