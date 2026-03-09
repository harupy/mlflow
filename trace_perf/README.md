# trace_perf

Benchmarks and diagnostic scripts for MLflow trace ingestion and search performance.

See [trace-perf-analysis.md](../trace-perf-analysis.md) for results and analysis.

## Scripts

| Script                       | What it measures                                                             |
| ---------------------------- | ---------------------------------------------------------------------------- |
| `trace_benchmark.py`         | Full benchmark suite: ingestion throughput, search latency, memory, cProfile |
| `bench_merge_per_span.py`    | Bottleneck #1: `session.merge()` call count and cost per span                |
| `bench_metadata_queries.py`  | Bottleneck #2: redundant metadata SELECT queries in `log_spans()`            |
| `bench_n_plus_one.py`        | Bottleneck #3: N+1 lazy loading in `search_traces()`                         |
| `bench_rlike_json.py`        | Bottleneck #4: RLIKE on JSON `content` column vs indexed filters             |
| `bench_offset_pagination.py` | Bottleneck #5: offset-based pagination degradation                           |
| `utils.py`                   | Shared data generation and test infrastructure                               |

## Quick start

```bash
# Full benchmark
uv run python trace_perf/trace_benchmark.py

# Ingestion only with cProfile
uv run python trace_perf/trace_benchmark.py --benchmarks ingest --profile

# Individual bottleneck scripts (run before and after a fix)
uv run python trace_perf/bench_n_plus_one.py
uv run python trace_perf/bench_merge_per_span.py
uv run python trace_perf/bench_metadata_queries.py
uv run python trace_perf/bench_rlike_json.py
uv run python trace_perf/bench_offset_pagination.py
```
