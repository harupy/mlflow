# Trace Performance Analysis

**Problem:** Users report noticeable overhead from tracing and slow trace search. We lack benchmarks to quantify performance or identify bottlenecks, which is a growing risk as products like Gateway depend more on tracing.

**Why now:** No existing performance baselines exist. We're flying blind on regressions.

## Methodology

- **What's measured:** `SqlAlchemyStore` Python methods directly - no HTTP server, no network overhead. This isolates the storage layer.
- **Database:** SQLite in a temporary directory, fresh per run. Results may differ on PostgreSQL / MySQL.
- **Test data:** Synthetic traces with realistic span distributions (30% LLM, 20% retriever, 15% tool, etc.). LLM spans include token usage, cost, and model attributes. Each trace has tags (`env`, `model`) for filter benchmarks.
- **Ingestion:** Each iteration calls `start_trace()` + `log_spans()` for one trace. Data is pre-generated before measurement so timing reflects only the store path.
- **Search queries:**
  - `no_filter` - `search_traces()` with `max_results=100`, no filter
  - `by_status` - filter `status = 'OK'` (indexed column)
  - `by_tag` - filter `tag.env = 'prod'` (tag table join)
  - `timestamp_order` - order by `timestamp DESC`
  - `by_span_name` - filter `span.name = 'llm_0'` (RLIKE on JSON `content`)
  - `deep_page` - paginate to page 10 with `max_results=10`
- **Timing:** `time.perf_counter()` per iteration. GC disabled during measurement. 3 warmup iterations, then 10 measured iterations (ingestion) or 30 measured iterations (search).
- **Memory:** `tracemalloc` for Python allocations, `resource.getrusage` for peak RSS delta.
- **Profiling:** cProfile on 100 traces x 100 spans ingestion, analyzed with `snakeviz`.

## Benchmark Results (SQLite, local)

### Ingestion

| spans/trace | mean (ms) | p95 (ms) | traces/s | spans/s |
| ----------- | --------- | -------- | -------- | ------- |
| 10          | 33        | 42       | 30.0     | 300     |
| 25          | 57        | 63       | 17.6     | 441     |
| 50          | 101       | 109      | 9.9      | 496     |
| 100         | 178       | 192      | 5.6      | 563     |
| 250         | 452       | 498      | 2.2      | 553     |
| 500         | 826       | 874      | 1.2      | 606     |
| 1,000       | 1,686     | 1,784    | 0.6      | 593     |

Ingestion scales linearly with span count (~1.7 ms per span). Throughput ramps from ~300 spans/s at small traces to a plateau around 550–600 spans/s at 100+ spans/trace.

### Search (p50 latency in ms)

| query           | 500 traces | 1K traces | 2K traces | 5K traces | 10K traces |
| --------------- | ---------- | --------- | --------- | --------- | ---------- |
| no_filter       | 93         | 94        | 93        | 101       | 105        |
| by_status       | 91         | 101       | 93        | 95        | 104        |
| by_tag          | 91         | 94        | 98        | 116       | 144        |
| timestamp_order | 93         | 99        | 96        | 100       | 95         |
| by_span_name    | 4          | 10        | 20        | 50        | 105        |
| deep_page       | 107        | 115       | 116       | 144       | 186        |

Key observations:

- **`by_span_name`** scales linearly: 4 ms -> 105 ms from 500 to 10K traces (~26x), because it uses RLIKE on the unindexed JSON `content` column.
- **`deep_page`** grows steadily: 107 ms -> 186 ms (~74%), reflecting offset-based pagination overhead.
- **`by_tag`** shows moderate degradation: 91 ms -> 144 ms (~58%), as tag filtering requires joining and scanning the tags table.
- **`no_filter`**, **`by_status`**, **`timestamp_order`** remain relatively flat (~90–105 ms), dominated by the N+1 lazy loading cost rather than the query itself.

### Resource Usage

- **DB size:** 217 MB for ~18.5K traces (~12 KB/trace average)
- **Memory:** Peak RSS delta ~1.7 MB, tracemalloc peak ~2 MB - memory is not a concern

## Bottlenecks Identified

### 1. Ingestion: `session.merge()` per span (top bottleneck)

[`log_spans()`](https://github.com/mlflow/mlflow/blob/eb00322351e9338d0535c6d64694616bf1ac2ce5/mlflow/store/tracking/sqlalchemy_store.py#L4315) calls `session.merge()` individually for every span and every span metric. A 100-span trace triggers **19K+ merge calls** for 100 ingestions - each one does a PK identity load + autoflush + INSERT.

cProfile of 100 traces x 100 spans (12.8s total):

```
         ncalls  tottime  cumtime  function
            100    0.120   12.681  sqlalchemy_store.py:log_spans
          19459    0.034   10.102  session.py:merge            ← 79% of total
          19459    0.134    5.620  session.py:_merge
          19459    0.146    4.698  session.py:_get_impl        ← PK lookup per merge
          39518    0.012    4.482  session.py:_autoflush       ← flush before every get
          19459    0.134    4.267  loading.py:load_on_pk_identity
          19559    0.035    3.529  unitofwork.py:execute
          19659    0.084    2.429  persistence.py:save_obj     ← INSERT per span
          19659    0.111    1.966  persistence.py:_emit_insert_statements
```

`session.merge()` accounts for **79% of wall time** (10.1s of 12.8s). Each of the 19,459 merge calls does: PK identity load (SELECT) -> autoflush -> INSERT. This directly explains why throughput plateaus at ~550–600 spans/s and scales linearly (33 ms for 10 spans -> 178 ms for 100 -> 1,686 ms for 1,000 spans).

Potential fix: bulk `session.bulk_save_objects()` or `INSERT ... ON CONFLICT` via core instead of ORM merge.

### 2. Ingestion: redundant metadata queries

Three separate queries per [`log_spans()`](https://github.com/mlflow/mlflow/blob/eb00322351e9338d0535c6d64694616bf1ac2ce5/mlflow/store/tracking/sqlalchemy_store.py#L4489-L4554) call for token usage, cost, and session ID metadata - could be a single query with `IN` clause. Per cProfile, these add ~3 round-trips per trace on top of the merge overhead.

### 3. Search: N+1 lazy loading

[`SqlTraceInfo.to_mlflow_entity()`](https://github.com/mlflow/mlflow/blob/eb00322351e9338d0535c6d64694616bf1ac2ce5/mlflow/store/tracking/dbmodels/models.py#L755) lazy-loads tags, metadata, and assessments per trace. For N results this is 3N+1 queries. This is likely why even simple queries (`no_filter`, `by_status`) stay at **~90–105 ms regardless of trace count** (500 to 10K) - the cost is dominated by the 300+ lazy-load round-trips for `max_results=100`, not the actual search query.

Potential fix: add `joinedload()` / `subqueryload()` options to the [`search_traces()`](https://github.com/mlflow/mlflow/blob/eb00322351e9338d0535c6d64694616bf1ac2ce5/mlflow/store/tracking/sqlalchemy_store.py#L3316) query.

### 4. Search: RLIKE on JSON blobs

[Span attribute filtering](https://github.com/mlflow/mlflow/blob/eb00322351e9338d0535c6d64694616bf1ac2ce5/mlflow/store/tracking/sqlalchemy_store.py#L6317) uses regex on the raw `content` column (LONGTEXT JSON). No index can accelerate this - it's a full scan of the spans table within the experiment. `by_span_name` went from **4 ms at 500 traces -> 10 ms -> 20 ms -> 50 ms -> 105 ms at 10K traces (~26x)**, growing linearly with trace count - the worst degradation of any query type.

### 5. Search: offset-based pagination

[Deep pagination](https://github.com/mlflow/mlflow/blob/eb00322351e9338d0535c6d64694616bf1ac2ce5/mlflow/store/tracking/sqlalchemy_store.py#L3369) (page 10+) degrades because the DB must scan and discard all preceding rows. `deep_page` went from **107 ms at 500 traces -> 115 ms -> 116 ms -> 144 ms -> 186 ms at 10K traces (~74%)**. Keyset pagination would be more efficient.

## Should We Run Benchmarks in CI?

- **CI runners are noisy.** GitHub Actions uses shared hardware with variable load. A 20% swing from runner noise is indistinguishable from a real regression at the latencies we're measuring (~10–100 ms).
- **The bottlenecks are structural, not marginal.** `session.merge()` at 79% of wall time and 3N+1 lazy-load queries are algorithmic problems - they won't silently regress.
- **Per-bottleneck scripts give clearer signal.** Running `bench_n_plus_one.py` before and after a fix gives a definitive answer (e.g., 301 queries -> 4 queries) that no amount of CI variance can obscure.

Revisit once the major bottlenecks are fixed and we need to protect against regressions from low baselines - at that point a dedicated runner with stable hardware would make sense.

## Reproducing

```bash
# Full benchmark
uv run python trace_perf/trace_benchmark.py

# Ingestion only with cProfile
uv run python trace_perf/trace_benchmark.py --benchmarks ingest --profile

# Visualize profile
uvx snakeviz trace_benchmark.prof
```
