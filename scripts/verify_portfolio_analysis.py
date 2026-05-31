"""Portfolio analysis offline verification script.

Runs portfolio analyzer against a fixture file and verifies:
- target weights + cash ≈ 100%
- Industry exposure present
- Risk summary present
- Rebalance suggestions present
- Missing reasons present
- No auto-trade language

Usage:
    python scripts/verify_portfolio_analysis.py --offline-fixture tests/fixtures/portfolio_analysis_samples.json --output-dir storage/artifacts/verification/portfolio_analysis
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def verify(fixtures_path: Path, output_dir: Path) -> dict:
    from services.portfolio.portfolio_analyzer import Constraints, analyze_portfolio
    from services.portfolio.report_builder import save_portfolio_report

    data = json.loads(fixtures_path.read_text(encoding="utf-8"))
    positions = data["positions"]
    research_results = data["research_results"]

    # Run analyzer with each risk profile
    results = {}
    for profile in ("conservative", "balanced", "aggressive"):
        analysis = analyze_portfolio(
            positions, research_results,
            risk_profile=profile,
            constraints=Constraints(max_single_weight=0.25, max_industry_weight=0.35, min_cash_weight=0.05),
        )
        artifacts = save_portfolio_report(analysis)
        results[profile] = {
            "analysis": dataclasses.asdict(analysis),
            "artifacts": artifacts,
        }

    # Verification checks
    checks = []
    balanced = results["balanced"]["analysis"]

    # Check 1: weights sum to ~100%
    total_weight = sum(h["target_weight"] for h in balanced["holdings"])
    cash = balanced["target_cash_weight"]
    weight_ok = abs(total_weight + cash - 1.0) < 0.02
    checks.append({
        "check": "weights_sum_to_100pct",
        "status": "pass" if weight_ok else "fail",
        "detail": f"holdings={total_weight:.4f} + cash={cash:.4f} = {total_weight + cash:.4f}",
    })

    # Check 2: industry exposure present
    ind_ok = len(balanced["industry_exposure"]) > 0
    checks.append({
        "check": "industry_exposure_present",
        "status": "pass" if ind_ok else "fail",
        "detail": f"{len(balanced['industry_exposure'])} industries",
    })

    # Check 3: risk summary present
    risk_ok = balanced["risk_level"] is not None
    checks.append({
        "check": "risk_summary_present",
        "status": "pass" if risk_ok else "fail",
        "detail": f"risk_level={balanced['risk_level']}",
    })

    # Check 4: rebalance suggestions present
    rebal_ok = len(balanced["rebalance_suggestions"]) > 0
    checks.append({
        "check": "rebalance_suggestions_present",
        "status": "pass" if rebal_ok else "warning",
        "detail": f"{len(balanced['rebalance_suggestions'])} suggestions",
    })

    # Check 5: missing reasons present (fixture has no missing data for balanced)
    # But we should check the field exists
    checks.append({
        "check": "missing_reasons_field_exists",
        "status": "pass",
        "detail": f"{len(balanced['missing_reasons'])} missing reasons",
    })

    # Check 6: no auto-trade language
    analysis_str = json.dumps(balanced, ensure_ascii=False)
    forbidden = ["自动下单", "自动交易", "交易指令", "auto trade", "auto order"]
    trade_found = [w for w in forbidden if w in analysis_str]
    checks.append({
        "check": "no_auto_trade_language",
        "status": "pass" if not trade_found else "fail",
        "detail": f"found: {trade_found}" if trade_found else "clean",
    })

    # Check 7: artifacts exist
    for profile, r in results.items():
        for fmt, path in r["artifacts"].items():
            exists = Path(path).exists()
            checks.append({
                "check": f"artifact_{profile}_{fmt}_exists",
                "status": "pass" if exists else "fail",
                "detail": path,
            })

    # Check 8: risk profile differences — business-level assertions.
    # Conservative should be more cautious than aggressive:
    #   - high-risk holdings get lower weight in conservative
    #   - cash weight is higher in conservative
    #   - differences must exceed rounding noise (> 0.2%)
    _RISK_DIFF_THRESHOLD = 0.002  # 0.2% minimum meaningful difference

    conservative = results["conservative"]["analysis"]
    aggressive = results["aggressive"]["analysis"]

    cons_weights = {h["symbol"]: h["target_weight"] for h in conservative["holdings"]}
    aggr_weights = {h["symbol"]: h["target_weight"] for h in aggressive["holdings"]}
    cons_risk_map = {h["symbol"]: h.get("risk_level") for h in conservative["holdings"]}

    # 8a: High-risk holdings should have lower (or equal) weight in conservative
    high_risk_violations = []
    for symbol, risk in cons_risk_map.items():
        if risk == "high":
            cw = cons_weights.get(symbol, 0.0)
            aw = aggr_weights.get(symbol, 0.0)
            if cw > aw + _RISK_DIFF_THRESHOLD:
                high_risk_violations.append(
                    f"{symbol}: conservative={cw:.1%} > aggressive={aw:.1%}"
                )
    checks.append({
        "check": "high_risk_lower_in_conservative",
        "status": "pass" if not high_risk_violations else "fail",
        "detail": "; ".join(high_risk_violations) if high_risk_violations else "ok",
    })

    # 8b: Conservative cash weight should be >= aggressive cash weight
    # Tolerance on conservative side: conservative may be slightly below
    # aggressive due to rounding, but not by more than the threshold.
    cons_cash = conservative["target_cash_weight"]
    aggr_cash = aggressive["target_cash_weight"]
    cash_ok = cons_cash + _RISK_DIFF_THRESHOLD >= aggr_cash
    checks.append({
        "check": "conservative_cash_geq_aggressive",
        "status": "pass" if cash_ok else "fail",
        "detail": f"conservative={cons_cash:.1%} vs aggressive={aggr_cash:.1%}",
    })

    # 8c: At least one symbol should have a meaningful weight difference.
    # Iterate union of both portfolios' symbols to catch composition differences.
    all_symbols = cons_weights.keys() | aggr_weights.keys()
    changed_symbols = [
        symbol
        for symbol in all_symbols
        if abs(cons_weights.get(symbol, 0.0) - aggr_weights.get(symbol, 0.0)) > _RISK_DIFF_THRESHOLD
    ]
    checks.append({
        "check": "risk_profiles_differ",
        "status": "pass" if changed_symbols else "warning",
        "detail": f"changed_symbols={changed_symbols or 'none'}",
    })

    overall = "pass"
    if any(c["status"] == "fail" for c in checks):
        overall = "fail"
    elif any(c["status"] == "warning" for c in checks):
        overall = "warning"

    return {
        "run_id": _timestamp(),
        "generated_at": _now_iso(),
        "overall_status": overall,
        "checks": checks,
        "risk_profiles": {
            profile: {
                "portfolio_score": r["analysis"]["portfolio_score"],
                "portfolio_rating": r["analysis"]["portfolio_rating"],
                "risk_level": r["analysis"]["risk_level"],
                "cash_weight": r["analysis"]["cash_weight"],  # backward compat alias
                "target_cash_weight": r["analysis"]["target_cash_weight"],
                "current_cash_weight": r["analysis"]["current_cash_weight"],
                "holdings_count": r["analysis"]["total_holdings"],
                "artifact_paths": r["artifacts"],
            }
            for profile, r in results.items()
        },
    }


def write_artifacts(report: dict, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = report["run_id"]

    json_path = output_dir / f"portfolio_analysis_{timestamp}.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    latest_json = output_dir / "latest.json"
    latest_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md_lines = [
        "# Portfolio Analysis Verification Report",
        f"- Generated: {report['generated_at']}",
        f"- Overall: **{report['overall_status'].upper()}**",
        "",
        "## Checks",
        "",
    ]
    for c in report["checks"]:
        icon = {"pass": "PASS", "fail": "FAIL", "warning": "WARN"}.get(c["status"], "?")
        md_lines.append(f"- [{icon}] **{c['check']}**: {c['detail']}")

    md_lines.append("")
    md_lines.append("## Risk Profile Results")
    md_lines.append("")
    for profile, r in report["risk_profiles"].items():
        md_lines.append(f"### {profile}")
        md_lines.append(f"- Score: {r['portfolio_score']}")
        md_lines.append(f"- Rating: {r['portfolio_rating']}")
        md_lines.append(f"- Risk: {r['risk_level']}")
        md_lines.append(f"- Target Cash: {r['target_cash_weight']:.1%}")
        current_cw = r.get('current_cash_weight')
        md_lines.append(f"- Current Cash: {current_cw:.1%}" if current_cw is not None else "- Current Cash: N/A")
        md_lines.append(f"- Holdings: {r['holdings_count']}")
        md_lines.append("")

    md_path = output_dir / f"portfolio_analysis_{timestamp}.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    latest_md = output_dir / "latest.md"
    latest_md.write_text("\n".join(md_lines), encoding="utf-8")

    return json_path, md_path


def main():
    parser = argparse.ArgumentParser(description="Portfolio analysis offline verification")
    parser.add_argument("--offline-fixture", required=True, help="Path to fixture JSON")
    parser.add_argument("--output-dir", default="storage/artifacts/verification/portfolio_analysis",
                        help="Output directory")
    args = parser.parse_args()

    fixture_path = Path(args.offline_fixture)
    if not fixture_path.exists():
        print(f"ERROR: Fixture not found: {fixture_path}")
        sys.exit(1)

    report = verify(fixture_path, Path(args.output_dir))
    json_path, md_path = write_artifacts(report, Path(args.output_dir))

    print(f"\n{'='*60}")
    print("Portfolio Analysis Verification")
    print(f"{'='*60}")
    print(f"Overall: {report['overall_status'].upper()}")
    for c in report["checks"]:
        icon = {"pass": "PASS", "fail": "FAIL", "warning": "WARN"}.get(c["status"], "?")
        print(f"  [{icon}] {c['check']}: {c['detail']}")
    print(f"\nArtifacts: {json_path}")
    print(f"Latest:    {Path(args.output_dir) / 'latest.json'}")

    if report["overall_status"] == "fail":
        sys.exit(1)


if __name__ == "__main__":
    main()
