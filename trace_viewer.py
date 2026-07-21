"""
Dreamer AI Phase 1 — Trace Viewer
CLI tool to inspect OTel traces stored in SQLite.

Usage:
    python trace_viewer.py <db_path>
        Show all traces

    python trace_viewer.py <db_path> <trace_id>
        Show full trace tree for a specific trace

    python trace_viewer.py <db_path> --errors
        Show all ERROR spans
"""

import sys
import os
from otel_exporter import query_trace_summary, query_trace_tree, query_errors


def format_duration(us: int) -> str:
    if us < 1000:
        return f"{us}µs"
    elif us < 1_000_000:
        return f"{us / 1000:.1f}ms"
    else:
        return f"{us / 1_000_000:.2f}s"


def print_trace_summary(db_path: str):
    traces = query_trace_summary(db_path)
    if not traces:
        print("No traces found.")
        return

    print(f"{'Trace ID':<34} {'Spans':>5} {'Max Dur':>10} {'Total':>10} {'First Seen'}")
    print("-" * 85)
    for t in traces:
        tid = t["trace_id"][:32]
        print(
            f"{tid:<34} "
            f"{t['span_count']:>5} "
            f"{format_duration(t['max_duration_us']):>10} "
            f"{format_duration(t['total_duration_us']):>10} "
            f"{t['first_seen']}"
        )


def print_trace_tree(db_path: str, trace_id: str):
    spans = query_trace_tree(db_path, trace_id)
    if not spans:
        print(f"No spans found for trace {trace_id}")
        return

    # Build tree: parent_span_id → children
    children: dict[str, list[dict]] = {}
    roots: list[dict] = []
    span_map: dict[str, dict] = {}

    for s in spans:
        span_map[s["span_id"]] = s
        pid = s.get("parent_span_id")
        if pid and pid in span_map:
            children.setdefault(pid, []).append(s)
        elif not pid:
            roots.append(s)
        else:
            # Parent not yet seen — still root for display
            roots.append(s)

    # Sort roots by start_time
    roots.sort(key=lambda s: s["start_time"])

    # Print tree
    print(f"\nTrace: {trace_id}")
    print(f"Spans: {len(spans)}")
    print("=" * 70)

    def print_node(span: dict, indent: int = 0, is_last: bool = True):
        prefix = "  " * indent
        connector = "└─ " if is_last else "├─ "

        dur = format_duration(span["duration_us"])
        status_icon = {"OK": "✓", "ERROR": "✗", "UNSET": "○"}.get(span["status"], "?")
        name = span["name"]
        source = span["source"] or ""

        print(f"{prefix}{connector}{status_icon} {name}  [{dur}]  {source}")

        if span["status_message"]:
            print(f"{prefix}  {'  ' if is_last else '│ '}⚠ {span['status_message']}")

        child_spans = children.get(span["span_id"], [])
        child_spans.sort(key=lambda s: s["start_time"])
        for i, child in enumerate(child_spans):
            is_last_child = (i == len(child_spans) - 1)
            print_node(child, indent + 1, is_last_child)

    for i, root in enumerate(roots):
        print_node(root, 0, i == len(roots) - 1)

    # Timeline summary
    print("\n" + "-" * 70)
    print("Span Timeline:")
    print(f"{'Name':<35} {'Start':>10} {'Duration':>10} {'Status':>8}")
    print("-" * 70)
    base_time = min(s["start_time"] for s in spans)
    for s in spans:
        offset_ns = s["start_time"] - base_time
        offset_str = f"+{offset_ns / 1_000_000:.2f}ms"
        print(
            f"{s['name']:<35} "
            f"{offset_str:>10} "
            f"{format_duration(s['duration_us']):>10} "
            f"{s['status']:>8}"
        )


def print_errors(db_path: str):
    errors = query_errors(db_path)
    if not errors:
        print("No ERROR spans found.")
        return

    print(f"{'Trace ID':<34} {'Span':<30} {'Message':<40}")
    print("-" * 110)
    for e in errors:
        msg = (e["status_message"] or "")[:40]
        print(f"{e['trace_id'][:32]:<34} {e['name']:<30} {msg:<40}")


# ── CLI ──────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    db_path = sys.argv[1]

    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        sys.exit(1)

    if len(sys.argv) >= 3 and sys.argv[2] == "--errors":
        print_errors(db_path)
    elif len(sys.argv) >= 3:
        trace_id = sys.argv[2]
        print_trace_tree(db_path, trace_id)
    else:
        print_trace_summary(db_path)


if __name__ == "__main__":
    main()
