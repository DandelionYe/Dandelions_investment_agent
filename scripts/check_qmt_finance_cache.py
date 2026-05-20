"""Check QMT peer cache coverage for industry valuation.

Despite the filename (kept for backward compatibility), this script checks
three categories of peer data readiness: finance, price, and share capital.

Usage:
    python scripts/check_qmt_finance_cache.py --symbols 600410.SH,002624.SZ
    python scripts/check_qmt_finance_cache.py --symbols 600410.SH --threshold 0.8 --markdown-output report.md
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check QMT peer cache readiness for industry valuation. "
            "Covers finance (net_profit_ttm, revenue_ttm, bps), "
            "price (close), and share capital (total_volume)."
        ),
    )
    parser.add_argument(
        "--symbols",
        required=True,
        help="Comma-separated peer symbols, e.g. 600410.SH,002624.SZ,000419.SZ",
    )
    parser.add_argument(
        "--as-of",
        default=None,
        help="As-of date (YYYY-MM-DD or YYYYMMDD). Default: today.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Coverage threshold (0-1). Default: QMT_PEER_CACHE_MIN_COVERAGE env or 0.8.",
    )
    parser.add_argument(
        "--json-output",
        default=None,
        help="Write full JSON result to this path.",
    )
    parser.add_argument(
        "--markdown-output",
        default=None,
        help="Write human-readable Markdown report to this path.",
    )
    parser.add_argument(
        "--fail-under-threshold",
        action="store_true",
        default=False,
        help="Exit code 1 when ready=false. Default: exit 0.",
    )
    return parser.parse_args()


def _print_summary(result: dict) -> None:
    print(f"Checked: {result['checked_count']}")
    print(f"Threshold: {result['threshold']}")
    print(f"Ready: {result['ready']}")
    print(f"  finance_ready: {result['finance_ready']}")
    print(f"  price_ready: {result['price_ready']}")
    print(f"  share_capital_ready: {result['share_capital_ready']}")
    print()
    print("Coverage:")
    for field, value in result["coverage"].items():
        count = result["counts"].get(field, 0)
        print(f"  {field}: {value:.1%} ({count}/{result['checked_count']})")
    if result["warnings"]:
        print()
        print("Warnings:")
        for warning in result["warnings"]:
            print(f"  - {warning}")


def _write_json(path: str, result: dict) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nJSON written to {path}")


def _write_markdown(path: str, result: dict) -> None:
    lines = [
        "# QMT Peer Cache Preflight Report",
        "",
        f"- **Checked count**: {result['checked_count']}",
        f"- **Threshold**: {result['threshold']}",
        f"- **Ready**: {result['ready']}",
        f"- **Finance ready**: {result['finance_ready']}",
        f"- **Price ready**: {result['price_ready']}",
        f"- **Share capital ready**: {result['share_capital_ready']}",
        "",
        "## Coverage",
        "",
        "| Field | Coverage | Count |",
        "|-------|----------|-------|",
    ]
    for field, value in result["coverage"].items():
        count = result["counts"].get(field, 0)
        lines.append(f"| {field} | {value:.1%} | {count}/{result['checked_count']} |")

    if result["warnings"]:
        lines.extend(["", "## Warnings", ""])
        for warning in result["warnings"]:
            lines.append(f"- {warning}")

    lines.extend(["", "## Sample Missing", ""])
    for field, samples in result["sample_missing"].items():
        if samples:
            lines.append(f"### {field}")
            for symbol in samples:
                lines.append(f"- {symbol}")
            lines.append("")

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nMarkdown written to {path}")


def main() -> None:
    from services.data.providers.qmt_peer_cache_preflight import QMTPeerCachePreflight

    args = _parse_args()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

    preflight = QMTPeerCachePreflight()
    result = preflight.check(
        symbols=symbols,
        as_of=args.as_of,
        threshold=args.threshold,
    )

    _print_summary(result)

    if args.json_output:
        _write_json(args.json_output, result)
    if args.markdown_output:
        _write_markdown(args.markdown_output, result)

    if args.fail_under_threshold and not result["ready"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
