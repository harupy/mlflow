"""Benchmark overhead of @mlflow.trace when tracing is disabled vs enabled.

Measures three scenarios:
  1. Raw function (no decorator) — baseline
  2. @mlflow.trace with tracing disabled (mlflow.tracing.disable())
  3. @mlflow.trace with tracing enabled (SQLite store)

Shows the per-call cost of the tracing wrapper in each state.
"""

from __future__ import annotations

import gc
import logging
import os
import tempfile
import time

from utils import percentile

SEP = "=" * 80
DASH = "-" * 80

CALLS = 10_000
WARMUP = 500


def _raw_add(a: int, b: int) -> int:
    return a + b


def _bench_calls(fn, calls: int) -> list[float]:
    for _ in range(WARMUP):
        fn(1, 2)

    gc.disable()
    times = []
    for _ in range(calls):
        t0 = time.perf_counter()
        fn(1, 2)
        times.append((time.perf_counter() - t0) * 1_000_000)  # microseconds
    gc.enable()
    return times


def main() -> None:
    os.environ.pop("MLFLOW_TRACKING_URI", None)

    # Suppress noisy warnings during benchmark
    logging.getLogger("mlflow").setLevel(logging.ERROR)

    import mlflow

    print(f"\n{SEP}")
    print(f"  Tracing Overhead Benchmark ({CALLS} calls per scenario)")
    print(SEP)

    header = f"{'scenario':<22} | {'p50(μs)':>8} | {'p95(μs)':>8} | {'mean(μs)':>8} | {'vs raw':>7}"
    print(header)
    print(DASH)

    # 1. Raw function — baseline
    times_raw = _bench_calls(_raw_add, CALLS)
    raw_p50 = percentile(times_raw, 50)
    raw_mean = sum(times_raw) / len(times_raw)
    print(
        f"{'raw (no decorator)':<22} | {raw_p50:>8.2f} | "
        f"{percentile(times_raw, 95):>8.2f} | {raw_mean:>8.2f} | {'1.0x':>7}"
    )

    # 2. Tracing disabled
    mlflow.tracing.disable()

    @mlflow.trace
    def _traced_add_disabled(a: int, b: int) -> int:
        return a + b

    times_disabled = _bench_calls(_traced_add_disabled, CALLS)
    dis_p50 = percentile(times_disabled, 50)
    dis_mean = sum(times_disabled) / len(times_disabled)
    ratio_dis = dis_p50 / raw_p50 if raw_p50 > 0 else 0
    print(
        f"{'tracing disabled':<22} | {dis_p50:>8.2f} | "
        f"{percentile(times_disabled, 95):>8.2f} | {dis_mean:>8.2f} | {ratio_dis:>6.1f}x"
    )

    mlflow.tracing.enable()

    # 3. Tracing enabled with SQLite store (local, no network)
    tmpdir = tempfile.mkdtemp()
    mlflow.set_tracking_uri(f"sqlite:///{tmpdir}/mlflow.db")
    mlflow.set_experiment("bench_tracing")

    @mlflow.trace
    def _traced_add_enabled(a: int, b: int) -> int:
        return a + b

    times_enabled = _bench_calls(_traced_add_enabled, CALLS)
    en_p50 = percentile(times_enabled, 50)
    en_mean = sum(times_enabled) / len(times_enabled)
    ratio_en = en_p50 / raw_p50 if raw_p50 > 0 else 0
    print(
        f"{'tracing enabled':<22} | {en_p50:>8.2f} | "
        f"{percentile(times_enabled, 95):>8.2f} | {en_mean:>8.2f} | {ratio_en:>6.1f}x"
    )

    # Micro-benchmark: is_tracing_enabled() alone
    from mlflow.tracing.provider import is_tracing_enabled

    gc.disable()
    t0 = time.perf_counter()
    for _ in range(CALLS):
        is_tracing_enabled()
    t_check = (time.perf_counter() - t0) * 1_000_000_000  # nanoseconds
    gc.enable()

    ns_per_call = t_check / CALLS
    total_ms = t_check / 1_000_000
    print("\n  is_tracing_enabled() micro-benchmark:")
    print(f"    {CALLS} calls in {total_ms:.2f} ms → {ns_per_call:.0f} ns/call")

    # Cleanup
    mlflow.tracing.reset()
    print(SEP)


if __name__ == "__main__":
    main()
