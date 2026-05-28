"""观察池条件触发器真实行情验收脚本。

读取观察池配置，调用实时行情接口，判断条件触发器是否能正确评估。
输出验收报告到 storage/artifacts/verification/。

Usage:
    python scripts/verify_watchlist_triggers.py
    python scripts/verify_watchlist_triggers.py --data-source qmt
    python scripts/verify_watchlist_triggers.py --data-source akshare
    python scripts/verify_watchlist_triggers.py --ensure-sample
    python scripts/verify_watchlist_triggers.py --require-triggered-and-untriggered
    python scripts/verify_watchlist_triggers.py --output-dir storage/artifacts/verification
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class TriggerCheckResult:
    symbol: str
    asset_type: str
    folder_name: str
    condition_triggers: dict[str, Any]
    quote: dict[str, Any] | None
    latest_result: dict[str, Any] | None
    triggered: bool
    trigger_reasons: list[str]
    missing_reasons: list[str]
    categories_evaluated: list[str]
    status: str  # pass | fail | skipped | error | warning
    message: str


@dataclass
class VerificationReport:
    run_id: str
    generated_at: str
    data_source: str
    overall_status: str
    total_items: int
    configured_items: int
    triggered_count: int
    non_triggered_count: int
    skipped_count: int
    quote_error_count: int
    categories_seen: list[str]
    acceptance_status: str
    acceptance_failures: list[str]
    checks: list[dict[str, Any]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def get_quote_qmt(symbol: str) -> dict[str, Any] | None:
    """通过 QMT 获取实时行情。"""
    try:
        from services.data.qmt_realtime_quote import get_latest_price_data
        return get_latest_price_data(symbol)
    except Exception as exc:
        return {"error": str(exc)}


def get_quote_akshare(symbol: str) -> dict[str, Any] | None:
    """通过 AKShare 获取行情（使用最近日线数据）。"""
    try:
        import akshare as ak
        code = symbol.split(".")[0]
        df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
        if df is None or len(df) < 2:
            return None
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        close = float(latest["收盘"])
        prev_close = float(prev["收盘"])
        volume = float(latest["成交量"])
        prev_volume = float(prev["成交量"]) if prev["成交量"] > 0 else 1
        return {
            "close": close,
            "prev_close": prev_close,
            "volume": volume,
            "change_pct": (close / prev_close - 1) * 100,
            "volume_ratio": volume / prev_volume if prev_volume > 0 else 1.0,
        }
    except Exception as exc:
        return {"error": str(exc)}


def verify_watchlist(
    data_source: str = "qmt",
    ensure_sample: bool = False,
    require_triggered_and_untriggered: bool = False,
) -> VerificationReport:
    """执行观察池条件触发器验收。"""
    from apps.api.task_manager.store import get_watchlist_store
    from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers

    store = get_watchlist_store()

    if ensure_sample:
        _ensure_sample_items(store)

    items = store.get_all_enabled_items()

    checks: list[TriggerCheckResult] = []
    triggered_count = 0
    non_triggered_count = 0
    skipped_count = 0
    quote_error_count = 0
    categories_seen: set[str] = set()
    configured_items = 0

    for item in items:
        symbol = item["symbol"]
        sc = item.get("schedule_config") or {}
        ct = sc.get("condition_triggers") or {}

        has_any = any(v is not None and v != [] for v in ct.values())
        if not has_any:
            checks.append(TriggerCheckResult(
                symbol=symbol,
                asset_type=item.get("asset_type", "stock"),
                folder_name=item.get("folder_name", ""),
                condition_triggers=ct,
                quote=None,
                latest_result=None,
                triggered=False,
                trigger_reasons=[],
                missing_reasons=[],
                categories_evaluated=[],
                status="skipped",
                message="未配置条件触发器",
            ))
            skipped_count += 1
            continue

        configured_items += 1

        quote = None
        need_quote = any(
            ct.get(k) is not None
            for k in ("price_change_pct", "volume_spike_ratio")
        )
        if need_quote:
            if data_source == "qmt":
                quote = get_quote_qmt(symbol)
            elif data_source == "akshare":
                quote = get_quote_akshare(symbol)
            if quote and "error" in quote:
                quote_error_count += 1

        eval_result = evaluate_condition_triggers(
            item, quote=quote,
            latest_result=item.get("last_trigger_snapshot"),
        )

        if eval_result.triggered:
            triggered_count += 1
        else:
            non_triggered_count += 1

        categories_seen.update(eval_result.categories_evaluated)

        has_quote_error = quote and "error" in quote
        has_missing = len(eval_result.missing_reasons) > 0
        status = "pass"
        if has_quote_error:
            status = "warning"
        if has_missing and not eval_result.triggered:
            status = "warning"

        all_reasons = eval_result.reasons + eval_result.missing_reasons
        checks.append(TriggerCheckResult(
            symbol=symbol,
            asset_type=item.get("asset_type", "stock"),
            folder_name=item.get("folder_name", ""),
            condition_triggers=ct,
            quote=quote,
            latest_result=item.get("last_trigger_snapshot"),
            triggered=eval_result.triggered,
            trigger_reasons=eval_result.reasons,
            missing_reasons=eval_result.missing_reasons,
            categories_evaluated=eval_result.categories_evaluated,
            status=status,
            message="; ".join(all_reasons),
        ))

    acceptance_status = "pass"
    acceptance_failures: list[str] = []
    if require_triggered_and_untriggered:
        if configured_items == 0:
            acceptance_failures.append("no configured watchlist items with condition triggers")
        if triggered_count == 0:
            acceptance_failures.append("no configured item evaluated as triggered")
        if non_triggered_count == 0:
            acceptance_failures.append("no configured item evaluated as non-triggered")

    if acceptance_failures:
        acceptance_status = "fail"

    if any(c.status == "fail" for c in checks):
        acceptance_status = "fail"
    elif any(c.status == "warning" for c in checks) and acceptance_status != "fail":
        acceptance_status = "warning"

    overall = "pass" if acceptance_status == "pass" else acceptance_status

    return VerificationReport(
        run_id=_timestamp(),
        generated_at=_now_iso(),
        data_source=data_source,
        overall_status=overall,
        total_items=len(items),
        configured_items=configured_items,
        triggered_count=triggered_count,
        non_triggered_count=non_triggered_count,
        skipped_count=skipped_count,
        quote_error_count=quote_error_count,
        categories_seen=sorted(categories_seen),
        acceptance_status=acceptance_status,
        acceptance_failures=acceptance_failures,
        checks=[asdict(c) for c in checks],
    )


def _ensure_sample_items(store) -> None:
    """Create or update sample watchlist items for verification."""
    owner_username = "default"
    folders = store.list_folders(owner_username=owner_username)
    sample_folder = next((f for f in folders if f["name"] == "验收样本"), None)
    if sample_folder:
        folder_id = sample_folder["id"]
    else:
        folder = store.create_folder(
            "验收样本",
            description="自动创建的验收观察池样本",
            owner_username=owner_username,
        )
        folder_id = folder["id"]

    samples = [
        {
            "symbol": "600519.SH",
            "asset_type": "stock",
            "asset_name": "贵州茅台",
            "schedule_config": {
                "mode": "manual_only",
                "condition_triggers": {
                    "price_change_pct": 5.0,
                    "pe_ttm_max": 30.0,
                },
            },
        },
        {
            "symbol": "000001.SZ",
            "asset_type": "stock",
            "asset_name": "平安银行",
            "schedule_config": {
                "mode": "manual_only",
                "condition_triggers": {
                    "score_threshold": 90.0,
                    "volume_spike_ratio": 5.0,
                },
            },
        },
    ]

    existing_items = store.get_all_enabled_items()
    owner_items = [
        i for i in existing_items
        if i.get("owner_username", "default") == owner_username
    ]
    existing_sample_items = {
        i["symbol"]: i for i in owner_items
        if i.get("folder_id") == folder_id
    }
    existing_symbols = {i["symbol"] for i in owner_items}

    for sample in samples:
        existing_sample = existing_sample_items.get(sample["symbol"])
        if existing_sample:
            store.update_item(
                existing_sample["id"],
                owner_username=owner_username,
                asset_type=sample["asset_type"],
                asset_name=sample.get("asset_name", ""),
                schedule_config=sample["schedule_config"],
            )
        elif sample["symbol"] not in existing_symbols:
            try:
                store.add_item(
                    symbol=sample["symbol"],
                    asset_type=sample["asset_type"],
                    folder_id=folder_id,
                    schedule_config=sample["schedule_config"],
                    asset_name=sample.get("asset_name", ""),
                    owner_username=owner_username,
                )
            except Exception:
                pass


def write_artifacts(
    report: VerificationReport,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Write report artifacts to output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = report.run_id
    report_dict = asdict(report)

    json_path = output_dir / f"watchlist_triggers_{timestamp}.json"
    json_path.write_text(
        json.dumps(report_dict, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    latest_json = output_dir / "watchlist_triggers_latest.json"
    latest_json.write_text(
        json.dumps(report_dict, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    md_lines = [
        "# Watchlist Triggers Verification Report",
        f"- Generated: {report.generated_at}",
        f"- Data Source: {report.data_source}",
        f"- Overall: **{report.overall_status.upper()}**",
        f"- Acceptance: **{report.acceptance_status.upper()}**",
        "",
        "## Summary",
        f"- Total items: {report.total_items}",
        f"- Configured items: {report.configured_items}",
        f"- Triggered: {report.triggered_count}",
        f"- Non-triggered: {report.non_triggered_count}",
        f"- Skipped: {report.skipped_count}",
        f"- Quote errors: {report.quote_error_count}",
        f"- Categories seen: {', '.join(report.categories_seen) or 'none'}",
        "",
        "## Checks",
        "",
    ]
    if report.acceptance_failures:
        check_header_index = md_lines.index("## Checks")
        md_lines[check_header_index:check_header_index] = [
            "## Acceptance Failures",
            "",
            *[f"- {failure}" for failure in report.acceptance_failures],
            "",
        ]
    for c in report.checks:
        icon = {"pass": "PASS", "fail": "FAIL", "warning": "WARN", "skipped": "SKIP",
                "error": "ERR"}.get(c["status"], "?")
        trig = "TRIGGERED" if c["triggered"] else ""
        md_lines.append(f"- [{icon}] {c['symbol']} ({c['folder_name']}) {trig}")
        md_lines.append(f"  - Config: {c['condition_triggers']}")
        if c["trigger_reasons"]:
            md_lines.append(f"  - Reasons: {'; '.join(c['trigger_reasons'])}")
        if c["missing_reasons"]:
            md_lines.append(f"  - Missing: {'; '.join(c['missing_reasons'])}")

    md_path = output_dir / f"watchlist_triggers_{timestamp}.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    latest_md = output_dir / "watchlist_triggers_latest.md"
    latest_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    return json_path, md_path


def main():
    parser = argparse.ArgumentParser(description="观察池条件触发器验收")
    parser.add_argument("--data-source", default="qmt", choices=["qmt", "akshare"],
                        help="数据源（默认 qmt）")
    parser.add_argument("--output-dir", default="storage/artifacts/verification",
                        help="输出目录")
    parser.add_argument("--ensure-sample", action="store_true",
                        help="创建/更新验收观察池样本")
    parser.add_argument("--require-triggered-and-untriggered", action="store_true",
                        help="要求至少 1 个触发和 1 个未触发的已配置观察项")
    args = parser.parse_args()

    report = verify_watchlist(
        data_source=args.data_source,
        ensure_sample=args.ensure_sample,
        require_triggered_and_untriggered=args.require_triggered_and_untriggered,
    )

    print(f"\n{'='*60}")
    print("观察池条件触发器验收报告")
    print(f"{'='*60}")
    print(f"数据源: {report.data_source}")
    print(f"观察项总数: {report.total_items}")
    print(f"已配置: {report.configured_items}")
    print(f"触发: {report.triggered_count}")
    print(f"未触发: {report.non_triggered_count}")
    print(f"跳过: {report.skipped_count}")
    print(f"行情错误: {report.quote_error_count}")
    print(f"评估类别: {', '.join(report.categories_seen) or 'none'}")
    print(f"总体状态: {report.overall_status}")
    print(f"验收状态: {report.acceptance_status}")
    if report.acceptance_failures:
        print(f"验收失败原因: {'; '.join(report.acceptance_failures)}")
    print()

    for check in report.checks:
        icon = {"pass": "PASS", "warning": "WARN", "fail": "FAIL",
                "skipped": "SKIP"}.get(check["status"], "?")
        trig = "TRIGGERED" if check["triggered"] else ""
        print(f"[{icon}] {check['symbol']} ({check['folder_name']}) {trig}")
        print(f"   Config: {check['condition_triggers']}")
        if check["trigger_reasons"]:
            print(f"   Reasons: {'; '.join(check['trigger_reasons'])}")
        if check["missing_reasons"]:
            print(f"   Missing: {'; '.join(check['missing_reasons'])}")
        print()

    output_dir = Path(args.output_dir)
    json_path, md_path = write_artifacts(report, output_dir)

    print(f"报告已保存: {json_path}")
    print(f"最新报告: {output_dir / 'watchlist_triggers_latest.json'}")

    if report.acceptance_status == "fail":
        sys.exit(1)


if __name__ == "__main__":
    main()
