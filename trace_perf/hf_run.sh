#!/usr/bin/env bash
#
# Run hyperfine benchmarks for core trace operations.
#
# Usage:
#   bash trace_perf/hf_run.sh
#   bash trace_perf/hf_run.sh --before "mlflow==2.20.0" --after "."
#   bash trace_perf/hf_run.sh --traces 5000 --spans 50
#
set -euo pipefail

TRACES=1000
SPANS=10
BEFORE=""
AFTER=""
WARMUP=3
RUNS=10

while [[ $# -gt 0 ]]; do
    case $1 in
        --traces) TRACES="$2"; shift 2 ;;
        --spans) SPANS="$2"; shift 2 ;;
        --before) BEFORE="$2"; shift 2 ;;
        --after) AFTER="$2"; shift 2 ;;
        --warmup) WARMUP="$2"; shift 2 ;;
        --runs) RUNS="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

HF="trace_perf/hf_bench.py"
CMDS=("ingest" "search" "get-trace" "text-search")

echo "=== Hyperfine Trace Benchmarks ==="
echo "Corpus: ${TRACES} traces, ${SPANS} spans/trace"
echo ""

uv run python "$HF" setup --traces "$TRACES" --spans "$SPANS"
echo ""

if [[ -n "$BEFORE" && -n "$AFTER" ]]; then
    for cmd in "${CMDS[@]}"; do
        echo ">>> ${cmd}"
        hyperfine \
            --warmup "$WARMUP" --runs "$RUNS" \
            --command-name "before" "uv run --with '${BEFORE}' python ${HF} ${cmd}" \
            --command-name "after"  "uv run --with '${AFTER}'  python ${HF} ${cmd}" \
            2>&1
        echo ""
    done
else
    hf_args=(--warmup "$WARMUP" --runs "$RUNS")
    for cmd in "${CMDS[@]}"; do
        hf_args+=(--command-name "$cmd" "uv run python ${HF} ${cmd}")
    done
    hyperfine "${hf_args[@]}" 2>&1
fi
