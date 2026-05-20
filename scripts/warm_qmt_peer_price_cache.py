"""Check and warm QMT peer price cache for industry valuation.

Default mode: dry-run (check only).  Pass --download --yes to actually
download missing peer K-line data from QMT.

Usage:
    # Dry-run check
    python scripts/warm_qmt_peer_price_cache.py --symbols 600410.SH

    # Download missing peer prices (requires explicit --yes)
    python scripts/warm_qmt_peer_price_cache.py --symbols 600410.SH --download --yes
"""

from __future__ import annotations

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
            "Check and optionally warm QMT peer price cache for industry valuation. "
            "Default is dry-run; pass --download --yes to download."
        ),
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="Target stock symbols (comma-separated), e.g. 600410.SH,002624.SZ",
    )
    parser.add_argument(
        "--peer-symbols",
        default=None,
        help="Direct peer symbols (comma-separated), skipping industry resolution.",
    )
    parser.add_argument(
        "--level",
        default=None,
        help="Industry level. Default: LOCAL_CSMAR_INDUSTRY_LEVEL or CSMAR_ZX.",
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
        help="Coverage threshold (0-1). Default: QMT_PEER_CACHE_MIN_COVERAGE or 0.8.",
    )
    parser.add_argument(
        "--history-days",
        type=int,
        default=30,
        help="Days of history to download. Default: 30.",
    )
    parser.add_argument(
        "--period",
        default="1d",
        help="K-line period. Default: 1d.",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        default=False,
        help="Actually download missing price data (default: dry-run).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        default=False,
        help="Confirm download. Required with --download.",
    )
    parser.add_argument(
        "--max-downloads",
        type=int,
        default=100,
        help="Max symbols to download. Default: 100.",
    )
    parser.add_argument(
        "--allow-large",
        action="store_true",
        default=False,
        help="Allow downloading more than --max-downloads symbols.",
    )
    parser.add_argument(
        "--json-output",
        default=None,
        help="Write JSON result to this path.",
    )
    parser.add_argument(
        "--markdown-output",
        default=None,
        help="Write Markdown report to this path.",
    )
    parser.add_argument(
        "--fail-under-threshold",
        action="store_true",
        default=False,
        help="Exit code 1 when price_ready=false after all steps.",
    )
    return parser.parse_args()


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [s.strip() for s in value.split(",") if s.strip()]


def main() -> None:
    from services.data.providers.qmt_peer_price_cache_maintenance import (
        QMTPeerPriceCacheMaintenance,
    )

    args = _parse_args()
    target_symbols = _parse_csv(args.symbols)
    peer_symbols = _parse_csv(args.peer_symbols)

    if not target_symbols and not peer_symbols:
        print("Error: provide --symbols or --peer-symbols.", file=sys.stderr)
        sys.exit(1)

    maintenance = QMTPeerPriceCacheMaintenance()

    # Step 1: Build peer universe
    universe = maintenance.build_peer_universe(
        target_symbols=target_symbols or None,
        peer_symbols=peer_symbols or None,
        level=args.level,
        as_of=args.as_of,
    )
    all_peers = universe["peer_symbols"]
    print(f"Target symbols: {universe['target_symbols']}")
    for ind in universe["industries"]:
        print(f"  {ind['target_symbol']}: {ind['industry_name']} ({ind['peer_count']} peers)")
    print(f"Total peer pool (deduplicated): {len(all_peers)}")

    # Step 2: Before preflight
    before = maintenance.check_price_cache(
        peer_symbols=all_peers,
        as_of=args.as_of,
        threshold=args.threshold,
    )
    print(f"\nBefore: close coverage = {before['coverage']['close']:.1%} "
          f"({before['counts']['close']}/{before['checked_count']})")
    print(f"  price_ready: {before['price_ready']}")
    missing_close = before.get("missing_symbols", {}).get("close", [])
    print(f"  missing close: {len(missing_close)}")
    if missing_close:
        sample = missing_close[:10]
        print(f"  sample: {', '.join(sample)}")

    download_result = None
    after = None

    # Step 3: Download if requested
    if args.download:
        if not args.yes:
            print("\nError: --download requires --yes to confirm.", file=sys.stderr)
            sys.exit(1)

        if not missing_close:
            print("\nNo missing close symbols — nothing to download.")
        else:
            print(f"\nDownloading {len(missing_close)} symbols "
                  f"(period={args.period}, days={args.history_days})...")
            try:
                download_result = maintenance.warm_missing_price_cache(
                    missing_symbols=missing_close,
                    as_of=args.as_of,
                    history_days=args.history_days,
                    period=args.period,
                    max_downloads=args.max_downloads,
                    allow_large=args.allow_large,
                )
            except ValueError as exc:
                print(f"\nError: {exc}", file=sys.stderr)
                sys.exit(1)

            print(f"  attempted: {download_result['attempted']}")
            print(f"  succeeded: {download_result['succeeded']}")
            print(f"  failed: {download_result['failed']}")
            if download_result["errors"]:
                for err in download_result["errors"][:5]:
                    print(f"    {err['symbol']}: {err['error']}")

            # Step 4: After preflight
            after = maintenance.check_price_cache(
                peer_symbols=all_peers,
                as_of=args.as_of,
                threshold=args.threshold,
            )
            print(f"\nAfter: close coverage = {after['coverage']['close']:.1%} "
                  f"({after['counts']['close']}/{after['checked_count']})")
            print(f"  price_ready: {after['price_ready']}")

    # Output files
    output = {
        "universe": universe,
        "before": before,
        "download": download_result,
        "after": after,
    }

    if args.json_output:
        _write_json(args.json_output, output)
    if args.markdown_output:
        _write_markdown(args.markdown_output, universe, before, download_result, after)

    # Final exit code
    final = after or before
    if args.fail_under_threshold and not final["price_ready"]:
        sys.exit(1)


def _write_json(path: str, output: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nJSON written to {path}")


def _write_markdown(
    path: str,
    universe: dict,
    before: dict,
    download_result: dict | None,
    after: dict | None,
) -> None:
    lines = [
        "# QMT Peer Price Cache Warm Report",
        "",
        "## Peer Universe",
        "",
        f"- **Target symbols**: {', '.join(universe['target_symbols']) or '(none)'}",
        f"- **Total peer pool**: {len(universe['peer_symbols'])}",
        "",
    ]
    for ind in universe["industries"]:
        lines.append(
            f"- {ind['target_symbol']}: {ind['industry_name']} "
            f"({ind['industry_level']}, {ind['peer_count']} peers)"
        )

    _append_preflight_section(lines, "Before Download", before)

    if download_result is not None:
        lines.extend([
            "",
            "## Download",
            "",
            f"- **Attempted**: {download_result['attempted']}",
            f"- **Succeeded**: {download_result['succeeded']}",
            f"- **Failed**: {download_result['failed']}",
            f"- **Period**: {download_result['period']}",
            f"- **Range**: {download_result['start']} ~ {download_result['end']}",
        ])
        if download_result["errors"]:
            lines.extend(["", "### Errors", ""])
            for err in download_result["errors"][:10]:
                lines.append(f"- {err['symbol']}: {err['error']}")

    if after is not None:
        _append_preflight_section(lines, "After Download", after)

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nMarkdown written to {path}")


def _append_preflight_section(lines: list[str], title: str, preflight: dict) -> None:
    lines.extend([
        "",
        f"## {title}",
        "",
        f"- **Checked**: {preflight['checked_count']}",
        f"- **Threshold**: {preflight['threshold']}",
        f"- **Price ready**: {preflight['price_ready']}",
        "",
        "### Coverage",
        "",
        "| Field | Coverage | Count |",
        "|-------|----------|-------|",
    ])
    for field, value in preflight["coverage"].items():
        count = preflight["counts"].get(field, 0)
        lines.append(f"| {field} | {value:.1%} | {count}/{preflight['checked_count']} |")

    if preflight.get("warnings"):
        lines.extend(["", "### Warnings", ""])
        for w in preflight["warnings"]:
            lines.append(f"- {w}")

    sample = preflight.get("sample_missing", {}).get("close", [])
    if sample:
        lines.extend(["", "### Sample Missing Close", ""])
        for symbol in sample:
            lines.append(f"- {symbol}")


if __name__ == "__main__":
    main()
