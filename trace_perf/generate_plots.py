"""
Generate plots for the trace performance analysis.

Usage:
    uv run python trace_perf/generate_plots.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

PLOTS_DIR = Path(__file__).resolve().parent.parent / "plots"
PLOTS_DIR.mkdir(exist_ok=True)

# Common style
plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.grid": True,
    "grid.alpha": 0.3,
    "font.size": 11,
    "figure.dpi": 300,
})

COLORS = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2"]


# ---------------------------------------------------------------------------
# 1. Ingestion: latency vs span count
# ---------------------------------------------------------------------------


def plot_ingestion_latency():
    spans = [10, 25, 50, 100, 250, 500, 1000]
    mean_ms = [33, 57, 101, 178, 452, 826, 1686]
    p95_ms = [42, 63, 109, 192, 498, 874, 1784]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # Left: latency
    ax1.plot(spans, mean_ms, "o-", color=COLORS[0], label="mean", linewidth=2, markersize=6)
    ax1.plot(spans, p95_ms, "s--", color=COLORS[1], label="p95", linewidth=2, markersize=6)
    ax1.set_xlabel("Spans per trace")
    ax1.set_ylabel("Latency (ms)")
    ax1.set_title("Ingestion latency vs span count")
    ax1.legend()
    ax1.set_xscale("log")
    ax1.set_yscale("log")
    ax1.set_xticks(spans)
    ax1.set_xticklabels([str(s) for s in spans])

    # Right: throughput (spans/s)
    spans_per_sec = [300, 441, 496, 563, 553, 606, 593]
    ax2.bar([str(s) for s in spans], spans_per_sec, color=COLORS[0], alpha=0.8)
    ax2.axhline(y=560, color=COLORS[1], linestyle="--", alpha=0.7, label="plateau ~560 spans/s")
    ax2.set_xlabel("Spans per trace")
    ax2.set_ylabel("Throughput (spans/s)")
    ax2.set_title("Ingestion throughput vs span count")
    ax2.legend()

    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "ingestion_latency.png", bbox_inches="tight")
    plt.close(fig)
    print("  saved ingestion_latency.png")


# ---------------------------------------------------------------------------
# 2. Search: latency vs trace count
# ---------------------------------------------------------------------------


def plot_search_latency():
    trace_counts = [500, 1000, 2000, 5000, 10000]
    queries = {
        "no_filter": [93, 94, 93, 101, 105],
        "by_status": [91, 101, 93, 95, 104],
        "by_tag": [91, 94, 98, 116, 144],
        "timestamp_order": [93, 99, 96, 100, 95],
        "by_span_name": [4, 10, 20, 50, 105],
        "deep_page": [107, 115, 116, 144, 186],
    }

    fig, ax = plt.subplots(figsize=(10, 6))
    for i, (name, latencies) in enumerate(queries.items()):
        style = "-" if name != "by_span_name" else "-"
        marker = "o" if name not in ("by_span_name", "deep_page") else "s"
        lw = 2.5 if name in ("by_span_name", "deep_page", "by_tag") else 1.5
        ax.plot(
            trace_counts,
            latencies,
            f"{marker}{style}",
            label=name,
            color=COLORS[i],
            linewidth=lw,
            markersize=6,
        )

    ax.set_xlabel("Number of traces in corpus")
    ax.set_ylabel("p50 latency (ms)")
    ax.set_title("Search latency by query type")
    ax.legend(loc="upper left")
    ax.set_xticks(trace_counts)
    ax.set_xticklabels(["500", "1K", "2K", "5K", "10K"])

    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "search_latency.png", bbox_inches="tight")
    plt.close(fig)
    print("  saved search_latency.png")


# ---------------------------------------------------------------------------
# 3. Client-side serialization breakdown
# ---------------------------------------------------------------------------


def plot_client_serialization():
    payloads = ["1KB", "10KB", "100KB", "1MB", "10MB"]
    json_dumps = [0.01, 0.04, 0.39, 3.77, 39.34]
    to_dict = [0.22, 0.08, 0.07, 0.07, 0.07]
    to_proto = [0.39, 0.15, 0.52, 4.56, 45.17]
    proto_ser = [0.37, 0.17, 0.67, 5.61, 59.24]
    size_stats = [0.22, 0.18, 0.52, 3.40, 32.53]

    # For the stacked bar, use the individual costs (proto_ser includes to_proto,
    # so use the delta)
    proto_only = [ps - tp for ps, tp in zip(proto_ser, to_proto)]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))
    x = np.arange(len(payloads))
    width = 0.55

    # Left: stacked bar
    bars = []
    bottom = np.zeros(len(payloads))
    components = [
        ("json_dumps", json_dumps, COLORS[0]),
        ("to_dict", to_dict, COLORS[2]),
        ("to_otel_proto", to_proto, COLORS[3]),
        ("SerializeToString", proto_only, COLORS[4]),
        ("size_stats", size_stats, COLORS[1]),
    ]
    for label, values, color in components:
        b = ax1.bar(x, values, width, bottom=bottom, label=label, color=color, alpha=0.85)
        bars.append(b)
        bottom += np.array(values)

    ax1.set_xlabel("Payload size (per input/output)")
    ax1.set_ylabel("Total latency (ms)")
    ax1.set_title("Client serialization breakdown by payload size")
    ax1.set_xticks(x)
    ax1.set_xticklabels(payloads)
    ax1.legend(loc="upper left", fontsize=9)

    # Right: log-scale line showing linear scaling
    totals = [j + d + p + s for j, d, p, s in zip(json_dumps, to_dict, proto_ser, size_stats)]
    payload_kb = [1, 10, 100, 1000, 10000]
    ax2.plot(payload_kb, totals, "o-", color=COLORS[0], linewidth=2, markersize=8, label="total")
    ax2.plot(
        payload_kb,
        json_dumps,
        "s--",
        color=COLORS[3],
        linewidth=1.5,
        markersize=5,
        label="json_dumps",
    )
    ax2.plot(
        payload_kb,
        proto_ser,
        "^--",
        color=COLORS[4],
        linewidth=1.5,
        markersize=5,
        label="proto_serialize",
    )
    ax2.plot(
        payload_kb,
        size_stats,
        "d--",
        color=COLORS[1],
        linewidth=1.5,
        markersize=5,
        label="size_stats",
    )
    ax2.set_xlabel("Payload size (KB)")
    ax2.set_ylabel("Latency (ms)")
    ax2.set_title("Serialization latency scaling (log-log)")
    ax2.set_xscale("log")
    ax2.set_yscale("log")
    ax2.legend(fontsize=9)

    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "client_serialization.png", bbox_inches="tight")
    plt.close(fig)
    print("  saved client_serialization.png")


# ---------------------------------------------------------------------------
# 4. Sustained load: max throughput vs span count
# ---------------------------------------------------------------------------


def plot_sustained_throughput():
    spans = [10, 50, 100]

    small_qps = [65.6, 18.6, 10.6]
    large_qps = [57.6, 19.3, 10.4]
    small_spans_s = [656, 932, 1063]
    large_spans_s = [576, 967, 1036]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    x = np.arange(len(spans))
    width = 0.3

    # Left: traces/s
    ax1.bar(x - width / 2, small_qps, width, label="small payload", color=COLORS[0], alpha=0.85)
    ax1.bar(x + width / 2, large_qps, width, label="100KB payload", color=COLORS[1], alpha=0.85)
    ax1.set_xlabel("Spans per trace")
    ax1.set_ylabel("Max throughput (traces/s)")
    ax1.set_title("Max ingestion throughput")
    ax1.set_xticks(x)
    ax1.set_xticklabels([str(s) for s in spans])
    ax1.legend()

    # Right: spans/s
    ax2.bar(x - width / 2, small_spans_s, width, label="small payload", color=COLORS[0], alpha=0.85)
    ax2.bar(x + width / 2, large_spans_s, width, label="100KB payload", color=COLORS[1], alpha=0.85)
    ax2.axhline(y=1000, color="gray", linestyle="--", alpha=0.5, label="~1K spans/s plateau")
    ax2.set_xlabel("Spans per trace")
    ax2.set_ylabel("Max throughput (spans/s)")
    ax2.set_title("Max span throughput")
    ax2.set_xticks(x)
    ax2.set_xticklabels([str(s) for s in spans])
    ax2.legend()

    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "sustained_throughput.png", bbox_inches="tight")
    plt.close(fig)
    print("  saved sustained_throughput.png")


# ---------------------------------------------------------------------------
# 5. Sustained load: CPU utilization vs target QPS
# ---------------------------------------------------------------------------


def plot_sustained_cpu():
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5), sharey=True)
    span_configs = [
        (10, {"small": {5: 11, 10: 21, 20: 34, 66: 94}, "100KB": {5: 11, 10: 22, 20: 37, 58: 91}}),
        (50, {"small": {5: 26, 10: 51, 20: 85, 19: 95}, "100KB": {5: 26, 10: 51, 20: 89, 19: 94}}),
        (100, {"small": {5: 42, 10: 88, 12: 95}, "100KB": {5: 44, 10: 90, 12: 96}}),
    ]

    for ax, (num_spans, data) in zip(axes, span_configs):
        for i, (label, qps_cpu) in enumerate(data.items()):
            qps_vals = sorted(qps_cpu.keys())
            cpu_vals = [qps_cpu[q] for q in qps_vals]
            ax.plot(
                qps_vals, cpu_vals, "o-", color=COLORS[i], label=label, linewidth=2, markersize=6
            )

        ax.axhline(y=95, color="gray", linestyle="--", alpha=0.4)
        ax.set_xlabel("QPS (traces/s)")
        ax.set_title(f"{num_spans} spans/trace")
        if ax == axes[0]:
            ax.set_ylabel("CPU utilization (%)")
        ax.legend(fontsize=9)
        ax.set_ylim(0, 105)

    fig.suptitle("CPU utilization vs ingestion rate", fontsize=13, y=1.02)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "sustained_cpu.png", bbox_inches="tight")
    plt.close(fig)
    print("  saved sustained_cpu.png")


# ---------------------------------------------------------------------------
# 6. Sustained load: DB size
# ---------------------------------------------------------------------------


def plot_db_size():
    # DB sizes at end of max-throughput 60s runs (cumulative across configs)
    # From the benchmark: each config adds to the same DB
    configs = [
        ("10s\nsmall", 46.2),
        ("10s\n100KB", 786.0),
        ("50s\nsmall", 1280.1),
        ("50s\n100KB", 1674.4),
        ("100s\nsmall", 2258.3),
        ("100s\n100KB", 2604.1),
    ]

    # Per-trace size: DB_size / traces
    traces = [3934, 3459, 1118, 1161, 638, 622]
    per_trace_kb = [sz * 1024 / t for (_, sz), t in zip(configs, traces)]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    labels = [c[0] for c in configs]
    sizes = [c[1] for c in configs]
    colors_bar = [COLORS[0], COLORS[1]] * 3

    ax1.bar(labels, sizes, color=colors_bar, alpha=0.85)
    ax1.set_ylabel("DB size (MB)")
    ax1.set_title("DB size after 60s max-throughput run")
    ax1.axhline(y=1000, color="gray", linestyle="--", alpha=0.3)

    # Per-trace size
    ax2.bar(labels, per_trace_kb, color=colors_bar, alpha=0.85)
    ax2.set_ylabel("Size per trace (KB)")
    ax2.set_title("Average DB size per trace")

    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "db_size.png", bbox_inches="tight")
    plt.close(fig)
    print("  saved db_size.png")


# ---------------------------------------------------------------------------
# 7. Ingestion profile: session.merge() dominance
# ---------------------------------------------------------------------------


def plot_profile_breakdown():
    labels = ["session.merge()\n(PK load + flush\n+ INSERT)", "Other ORM\noverhead", "Remaining"]
    sizes = [79, 12, 9]
    colors_pie = [COLORS[1], COLORS[4], COLORS[2]]
    explode = (0.05, 0, 0)

    fig, ax = plt.subplots(figsize=(6, 6))
    wedges, texts, autotexts = ax.pie(
        sizes,
        labels=labels,
        colors=colors_pie,
        explode=explode,
        autopct="%1.0f%%",
        startangle=90,
        textprops={"fontsize": 11},
    )
    autotexts[0].set_fontweight("bold")
    autotexts[0].set_fontsize(14)
    ax.set_title("Ingestion CPU time breakdown\n(100 traces x 100 spans)", fontsize=13)

    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "profile_breakdown.png", bbox_inches="tight")
    plt.close(fig)
    print("  saved profile_breakdown.png")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print(f"Generating plots in {PLOTS_DIR}/")
    plot_ingestion_latency()
    plot_search_latency()
    plot_client_serialization()
    plot_sustained_throughput()
    plot_sustained_cpu()
    plot_db_size()
    plot_profile_breakdown()
    print("Done!")


if __name__ == "__main__":
    main()
