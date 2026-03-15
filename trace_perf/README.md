# trace_perf

Benchmarks and diagnostic scripts for MLflow trace ingestion and search performance.

See [trace-perf-analysis.md](trace-perf-analysis.md) for results and analysis.

## Scripts

### Core benchmarks

| Script                          | What it measures                                                             |
| ------------------------------- | ---------------------------------------------------------------------------- |
| `trace_benchmark.py`            | Full benchmark suite: ingestion throughput, search latency, memory, cProfile |
| `bench_client_serialization.py` | Client-side serialization pipeline (JSON → protobuf)                         |
| `bench_sustained_load.py`       | Sustained load: throughput, latency, CPU, DB growth over 60s                 |

### Store-layer bottleneck scripts

| Script                        | What it measures                                                  |
| ----------------------------- | ----------------------------------------------------------------- |
| `bench_merge_per_span.py`     | Bottleneck #1: `session.merge()` call count and cost per span     |
| `bench_metadata_queries.py`   | Bottleneck #2: redundant metadata SELECT queries in `log_spans()` |
| `bench_n_plus_one.py`         | Bottleneck #3: N+1 lazy loading in `search_traces()`              |
| `bench_rlike_json.py`         | Bottleneck #4: RLIKE on JSON `content` column vs indexed filters  |
| `bench_offset_pagination.py`  | Bottleneck #5: offset-based pagination degradation                |
| `bench_deletion.py`           | Trace deletion with CASCADE across related tables                 |
| `bench_assessments.py`        | Assessment CRUD and search filtering overhead                     |
| `bench_large_content.py`      | Ingestion and search with multi-MB span content (1MB-10MB)        |
| `bench_text_search.py`        | Full-text search (trace.text ILIKE) on span content               |
| `bench_trace_loading.py`      | get_trace() deserialization cost by span count and payload size   |
| `bench_span_size.py`          | How serialized span size (attribute count) affects performance    |
| `bench_explain_queries.py`    | SQL EXPLAIN analysis to verify index usage                        |
| `bench_concurrent_writers.py` | Multi-threaded write contention and scaling                       |

### Client-side runtime benchmarks

| Script                        | What it measures                                                |
| ----------------------------- | --------------------------------------------------------------- |
| `bench_tracing_disabled.py`   | Overhead of `@mlflow.trace` when tracing is disabled vs enabled |
| `bench_streaming_overhead.py` | Per-chunk event recording cost for generator/streaming traces   |
| `bench_span_processor.py`     | Span processor `on_end()` overhead and lock contention          |
| `bench_async_export.py`       | Async export queue throughput and span batching efficiency      |
| `bench_e2e_http.py`           | End-to-end HTTP path overhead vs direct store calls             |

### Shared utilities

| File       | Description                                                               |
| ---------- | ------------------------------------------------------------------------- |
| `utils.py` | Shared data generation, store helpers, query counting, payload generation |

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

# New store-layer benchmarks
uv run python trace_perf/bench_deletion.py
uv run python trace_perf/bench_assessments.py
uv run python trace_perf/bench_large_content.py
uv run python trace_perf/bench_text_search.py
uv run python trace_perf/bench_trace_loading.py
uv run python trace_perf/bench_span_size.py
uv run python trace_perf/bench_explain_queries.py
uv run python trace_perf/bench_concurrent_writers.py

# Client-side runtime benchmarks
uv run python trace_perf/bench_tracing_disabled.py
uv run python trace_perf/bench_streaming_overhead.py
uv run python trace_perf/bench_span_processor.py
uv run python trace_perf/bench_async_export.py
uv run python trace_perf/bench_e2e_http.py

# PostgreSQL variants (where supported)
uv run --with psycopg2-binary python trace_perf/bench_concurrent_writers.py --db-uri "$PG_URI"
uv run --with psycopg2-binary python trace_perf/bench_explain_queries.py --db-uri "$PG_URI"
```
