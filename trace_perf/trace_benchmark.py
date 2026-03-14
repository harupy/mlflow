"""
Benchmark script for MLflow trace ingestion and search performance.

Measures throughput, latency percentiles, memory usage, and optionally
profiles the hot path via cProfile.

Usage:
    uv run python trace_perf/trace_benchmark.py
    uv run python trace_perf/trace_benchmark.py --benchmarks ingest --profile
    uv run python trace_perf/trace_benchmark.py --db-uri postgresql://user:pass@localhost/mlflow
"""

from __future__ import annotations

import argparse
import cProfile
import gc
import os
import pstats
import random
import resource
import statistics
import sys
import tempfile
import time
import tracemalloc
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from utils import generate_spans, generate_trace_info, get_db_size_mb, populate_corpus

from mlflow.entities.span import Span
from mlflow.entities.trace_info import TraceInfo
from mlflow.store.tracking.sqlalchemy_store import SqlAlchemyStore

# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkResult:
    name: str
    params: dict[str, str]
    wall_times: list[float]
    memory_peak_rss_mb: float
    tracemalloc_peak_mb: float
    extra: dict[str, float] = field(default_factory=dict)

    @property
    def p50(self) -> float:
        return _percentile(self.wall_times, 50)

    @property
    def p95(self) -> float:
        return _percentile(self.wall_times, 95)

    @property
    def p99(self) -> float:
        return _percentile(self.wall_times, 99)

    @property
    def mean(self) -> float:
        return statistics.mean(self.wall_times)

    @property
    def stddev(self) -> float:
        return statistics.stdev(self.wall_times) if len(self.wall_times) > 1 else 0.0


def _percentile(data: list[float], pct: float) -> float:
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * pct / 100
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[-1]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def _get_rss_mb() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return rss / (1024 * 1024)  # bytes → MB
    return rss / 1024  # KB → MB


# ---------------------------------------------------------------------------
# Ingestion benchmark
# ---------------------------------------------------------------------------


def bench_ingest(
    store: SqlAlchemyStore,
    experiment_id: str,
    spans_per_trace: int,
    warmup: int,
    iterations: int,
    verbose: bool,
) -> BenchmarkResult:
    rng = random.Random(42)
    total = warmup + iterations
    base_time_ms = 1_700_000_000_000

    # Pre-generate all data
    dataset: list[tuple[TraceInfo, list[Span]]] = []
    for i in range(total):
        tid = f"tr-{uuid.uuid4().hex}"
        trace_info = generate_trace_info(tid, experiment_id, base_time_ms + i * 1000, rng)
        spans = generate_spans(tid, spans_per_trace, rng)
        dataset.append((trace_info, spans))

    # Warmup
    for i in range(warmup):
        ti, sp = dataset[i]
        store.start_trace(ti)
        store.log_spans(experiment_id, sp)

    # Measure
    gc.collect()
    gc.disable()
    rss_before = _get_rss_mb()
    tracemalloc.start()

    wall_times: list[float] = []
    for i in range(warmup, total):
        ti, sp = dataset[i]
        t0 = time.perf_counter()
        store.start_trace(ti)
        store.log_spans(experiment_id, sp)
        t1 = time.perf_counter()
        elapsed = t1 - t0
        wall_times.append(elapsed)
        if verbose:
            print(f"  ingest [{spans_per_trace} spans] iter {i - warmup}: {elapsed * 1000:.1f} ms")

    _, tracemalloc_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss_after = _get_rss_mb()
    gc.enable()

    total_time = sum(wall_times)
    return BenchmarkResult(
        name="ingest",
        params={"spans_per_trace": str(spans_per_trace)},
        wall_times=wall_times,
        memory_peak_rss_mb=rss_after - rss_before,
        tracemalloc_peak_mb=tracemalloc_peak / (1024 * 1024),
        extra={
            "traces_per_sec": iterations / total_time if total_time > 0 else 0,
            "spans_per_sec": (iterations * spans_per_trace) / total_time if total_time > 0 else 0,
        },
    )


# ---------------------------------------------------------------------------
# Search benchmark
# ---------------------------------------------------------------------------


SEARCH_QUERIES = [
    ("no_filter", {}, None),
    ("by_status", {"filter_string": "status = 'OK'"}, None),
    ("by_tag", {"filter_string": "tag.env = 'prod'"}, None),
    ("timestamp_order", {}, ["timestamp DESC"]),
    ("by_span_name", {"filter_string": "span.name = 'llm_0'"}, None),
    ("deep_page", {"max_results": 10}, None),  # paginate to page 10
]


def bench_search(
    store: SqlAlchemyStore,
    experiment_id: str,
    corpus_size: int,
    warmup: int,
    iterations: int,
    verbose: bool,
) -> list[BenchmarkResult]:
    print(f"\n  Populating {corpus_size} traces for search benchmark...")
    populate_corpus(store, experiment_id, corpus_size)

    results: list[BenchmarkResult] = []

    for query_name, kwargs, order_by in SEARCH_QUERIES:
        search_kwargs: dict[str, object] = {
            "locations": [experiment_id],
            "max_results": kwargs.get("max_results", 100),
            **{k: v for k, v in kwargs.items() if k != "max_results"},
        }
        if order_by:
            search_kwargs["order_by"] = order_by

        is_deep_page = query_name == "deep_page"

        # Warmup
        for _ in range(warmup):
            if is_deep_page:
                _paginate_to_page(store, search_kwargs, target_page=10)
            else:
                store.search_traces(**search_kwargs)

        # Measure
        gc.collect()
        gc.disable()
        rss_before = _get_rss_mb()
        tracemalloc.start()

        wall_times: list[float] = []
        for j in range(iterations):
            t0 = time.perf_counter()
            if is_deep_page:
                _paginate_to_page(store, search_kwargs, target_page=10)
            else:
                store.search_traces(**search_kwargs)
            t1 = time.perf_counter()
            elapsed = t1 - t0
            wall_times.append(elapsed)
            if verbose:
                print(f"  search [{query_name}] iter {j}: {elapsed * 1000:.1f} ms")

        _, tracemalloc_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        rss_after = _get_rss_mb()
        gc.enable()

        total_time = sum(wall_times)
        results.append(
            BenchmarkResult(
                name=f"search_{query_name}",
                params={"corpus_size": str(corpus_size)},
                wall_times=wall_times,
                memory_peak_rss_mb=rss_after - rss_before,
                tracemalloc_peak_mb=tracemalloc_peak / (1024 * 1024),
                extra={"qps": iterations / total_time if total_time > 0 else 0},
            )
        )

    return results


def _paginate_to_page(
    store: SqlAlchemyStore,
    search_kwargs: dict[str, object],
    target_page: int,
) -> None:
    token = None
    for _ in range(target_page):
        _, token = store.search_traces(**{**search_kwargs, "page_token": token})
        if token is None:
            break


# ---------------------------------------------------------------------------
# Profiling
# ---------------------------------------------------------------------------


def bench_profile(
    store: SqlAlchemyStore,
    experiment_id: str,
    spans_per_trace: int,
    num_traces: int,
) -> cProfile.Profile:
    rng = random.Random(99)
    base_time_ms = 1_700_000_000_000

    dataset: list[tuple[TraceInfo, list[Span]]] = []
    for i in range(num_traces):
        tid = f"tr-{uuid.uuid4().hex}"
        ti = generate_trace_info(tid, experiment_id, base_time_ms + i * 1000, rng)
        spans = generate_spans(tid, spans_per_trace, rng)
        dataset.append((ti, spans))

    profiler = cProfile.Profile()
    profiler.enable()
    for ti, sp in dataset:
        store.start_trace(ti)
        store.log_spans(experiment_id, sp)
    profiler.disable()
    return profiler


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

SEP = "=" * 70
DASH = "-" * 70


def print_results(
    ingest_results: list[BenchmarkResult],
    search_results: list[BenchmarkResult],
    db_uri: str,
) -> None:
    print(f"\n{SEP}")
    print("          MLflow Trace Benchmark Results")
    print(SEP)
    print(f"DB:     {db_uri}")
    print(f"Python: {sys.version.split()[0]}")

    if ingest_results:
        print(f"\n{'INGESTION':^70}")
        print(DASH)
        header = (
            f"{'spans/trace':>11} | {'mean(ms)':>8} | {'p50':>7} | {'p95':>7} "
            f"| {'p99':>7} | {'stddev':>7} | {'traces/s':>8} | {'spans/s':>8}"
        )
        print(header)
        print(DASH)
        for r in ingest_results:
            spt = r.params["spans_per_trace"]
            print(
                f"{spt:>11} | {r.mean * 1000:>8.1f} | {r.p50 * 1000:>7.1f} "
                f"| {r.p95 * 1000:>7.1f} | {r.p99 * 1000:>7.1f} | {r.stddev * 1000:>7.1f} "
                f"| {r.extra['traces_per_sec']:>8.1f} | {r.extra['spans_per_sec']:>8.1f}"
            )

    if search_results:
        # Group by corpus size
        corpus_sizes = sorted({r.params["corpus_size"] for r in search_results})
        for cs in corpus_sizes:
            group = [r for r in search_results if r.params["corpus_size"] == cs]
            print(f"\n{'SEARCH (corpus=' + cs + ')':^70}")
            print(DASH)
            header = (
                f"{'query':>20} | {'mean(ms)':>8} | {'p50':>7} | {'p95':>7} "
                f"| {'p99':>7} | {'qps':>7}"
            )
            print(header)
            print(DASH)
            for r in group:
                qname = r.name.removeprefix("search_")
                print(
                    f"{qname:>20} | {r.mean * 1000:>8.1f} | {r.p50 * 1000:>7.1f} "
                    f"| {r.p95 * 1000:>7.1f} | {r.p99 * 1000:>7.1f} "
                    f"| {r.extra['qps']:>7.1f}"
                )

    if all_results := ingest_results + search_results:
        peak_rss = max(r.memory_peak_rss_mb for r in all_results)
        peak_traced = max(r.tracemalloc_peak_mb for r in all_results)
        print(f"\n{'MEMORY':^70}")
        print(DASH)
        print(f"  Peak RSS delta: {peak_rss:.1f} MB | tracemalloc peak: {peak_traced:.1f} MB")

    print(f"\n{SEP}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark MLflow trace ingestion and search")
    parser.add_argument(
        "--db-uri",
        default=os.environ.get("BENCHMARK_DB_URI"),
        help="SQLAlchemy DB URI (default: sqlite in tmpdir)",
    )
    parser.add_argument(
        "--benchmarks",
        default="all",
        help="Comma-separated list: ingest, search, all (default: all)",
    )
    parser.add_argument(
        "--spans-per-trace",
        default="10,100,1000",
        help="Comma-separated span counts for ingestion (default: 10,100,1000)",
    )
    parser.add_argument(
        "--corpus-sizes",
        default="1000,10000",
        help="Comma-separated corpus sizes for search (default: 1000,10000)",
    )
    parser.add_argument("--warmup", type=int, default=3, help="Warmup iterations (default: 3)")
    parser.add_argument(
        "--iterations", type=int, default=10, help="Measured iterations for ingest (default: 10)"
    )
    parser.add_argument(
        "--search-iterations",
        type=int,
        default=50,
        help="Measured iterations per search query (default: 50)",
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Enable cProfile (writes .prof file and prints top-30)",
    )
    parser.add_argument("--verbose", action="store_true", help="Print per-iteration timings")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    args = parse_args()

    benchmarks = set(args.benchmarks.split(","))
    run_ingest = "ingest" in benchmarks or "all" in benchmarks
    run_search = "search" in benchmarks or "all" in benchmarks

    spans_per_trace_list = [int(x) for x in args.spans_per_trace.split(",")]
    corpus_sizes = [int(x) for x in args.corpus_sizes.split(",")]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        db_uri = args.db_uri or f"sqlite:///{tmpdir_path / 'mlflow.db'}"
        artifact_root = (tmpdir_path / "artifacts").as_uri()
        (tmpdir_path / "artifacts").mkdir(exist_ok=True)

        print(f"DB URI: {db_uri}")
        store = SqlAlchemyStore(db_uri, artifact_root)

        ingest_results: list[BenchmarkResult] = []
        search_results: list[BenchmarkResult] = []

        # --- Ingestion benchmarks ---
        if run_ingest:
            print("\nRunning ingestion benchmarks...")
            for spt in spans_per_trace_list:
                exp_id = str(store.create_experiment(f"bench_ingest_{spt}"))
                print(f"\n  spans_per_trace={spt}")
                result = bench_ingest(
                    store, exp_id, spt, args.warmup, args.iterations, args.verbose
                )
                ingest_results.append(result)

        # --- Search benchmarks ---
        if run_search:
            print("\nRunning search benchmarks...")
            for cs in corpus_sizes:
                exp_id = str(store.create_experiment(f"bench_search_{cs}"))
                results = bench_search(
                    store, exp_id, cs, args.warmup, args.search_iterations, args.verbose
                )
                search_results.extend(results)

        # --- Profiling ---
        if args.profile:
            print("\nRunning profiled ingestion (100 traces x 100 spans)...")
            exp_id = str(store.create_experiment("bench_profile"))
            profiler = bench_profile(store, exp_id, spans_per_trace=100, num_traces=100)

            prof_path = Path("trace_benchmark.prof")
            profiler.dump_stats(str(prof_path))
            print(f"\n  Profile saved to {prof_path}")
            print(f"  Visualize with: snakeviz {prof_path}\n")

            stats = pstats.Stats(profiler)
            stats.sort_stats("cumulative")
            stats.print_stats(30)

        # --- Print results ---
        print_results(ingest_results, search_results, db_uri)

        # --- DB size ---
        db_path = tmpdir_path / "mlflow.db" if "sqlite" in db_uri else None
        size_mb = get_db_size_mb(store, db_path)
        if size_mb is not None:
            print(f"\n{'DB SIZE':^70}")
            print(DASH)
            print(f"  {size_mb:.1f} MB")
            print(SEP)


if __name__ == "__main__":
    main()
