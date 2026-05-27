"""观察池条件触发器真实行情验收脚本。

读取观察池配置，调用实时行情接口，判断条件触发器是否能正确评估。
输出验收报告到 storage/artifacts/verification/。

Usage:
    python scripts/verify_watchlist_triggers.py
    python scripts/verify_watchlist_triggers.py --data-source qmt
    python scripts/verify_watchlist_triggers.py --data-source akshare
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
    triggered: bool
    trigger_reasons: list[str]
    status: str  # pass | fail | skipped | error
    message: str


@dataclass
class VerificationReport:
    run_id: str
    generated_at: str
    data_source: str
    overall_status: str
    total_items: int
    triggered_count: int
    checks: list[dict[str, Any]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


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
        # 将 600519.SH 转为 akshare 格式
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


def evaluate_triggers(
    condition_triggers: dict[str, Any],
    quote: dict[str, Any] | None,
    last_score: float | None,
) -> tuple[bool, list[str]]:
    """评估条件触发器是否满足。

    Returns:
        (triggered, reasons)
    """
    triggered = False
    reasons = []

    ct = condition_triggers
    if not ct or all(v is None for v in ct.values()):
        return False, ["无条件触发器配置"]

    # 价格变动触发
    if ct.get("price_change_pct") is not None:
        if quote and "change_pct" in quote:
            if abs(quote["change_pct"]) >= ct["price_change_pct"]:
                triggered = True
                reasons.append(
                    f"涨跌幅 {quote['change_pct']:.2f}% >= 阈值 {ct['price_change_pct']}%"
                )
            else:
                reasons.append(
                    f"涨跌幅 {quote['change_pct']:.2f}% < 阈值 {ct['price_change_pct']}%"
                )
        elif quote and "error" in quote:
            reasons.append(f"行情获取失败: {quote['error']}")
        else:
            reasons.append("行情数据不可用")

    # 成交量异动触发
    if ct.get("volume_spike_ratio") is not None:
        if quote and "volume_ratio" in quote:
            if quote["volume_ratio"] >= ct["volume_spike_ratio"]:
                triggered = True
                reasons.append(
                    f"量比 {quote['volume_ratio']:.2f} >= 阈值 {ct['volume_spike_ratio']}"
                )
            else:
                reasons.append(
                    f"量比 {quote['volume_ratio']:.2f} < 阈值 {ct['volume_spike_ratio']}"
                )
        elif quote and "error" in quote:
            reasons.append(f"行情获取失败: {quote['error']}")
        else:
            reasons.append("行情数据不可用")

    # 评分阈值触发
    if ct.get("score_threshold") is not None:
        if last_score is not None:
            if last_score >= ct["score_threshold"]:
                triggered = True
                reasons.append(
                    f"评分 {last_score:.1f} >= 阈值 {ct['score_threshold']}"
                )
            else:
                reasons.append(
                    f"评分 {last_score:.1f} < 阈值 {ct['score_threshold']}"
                )
        else:
            reasons.append("无历史评分（首次扫描前无法触发）")

    return triggered, reasons


def verify_watchlist(data_source: str = "qmt") -> VerificationReport:
    """执行观察池条件触发器验收。"""
    from apps.api.task_manager.store import get_watchlist_store

    store = get_watchlist_store()
    items = store.get_all_enabled_items()

    checks: list[TriggerCheckResult] = []
    triggered_count = 0

    for item in items:
        symbol = item["symbol"]
        sc = item.get("schedule_config") or {}
        ct = sc.get("condition_triggers") or {}
        last_score = item.get("last_score")

        # 获取行情
        if data_source == "qmt":
            quote = get_quote_qmt(symbol)
        elif data_source == "akshare":
            quote = get_quote_akshare(symbol)
        else:
            quote = None

        # 评估触发器
        if not ct or all(v is None for v in ct.values()):
            checks.append(TriggerCheckResult(
                symbol=symbol,
                asset_type=item.get("asset_type", "stock"),
                folder_name=item.get("folder_name", ""),
                condition_triggers=ct,
                quote=quote,
                triggered=False,
                trigger_reasons=["无条件触发器配置"],
                status="skipped",
                message="未配置条件触发器",
            ))
            continue

        triggered, reasons = evaluate_triggers(ct, quote, last_score)
        if triggered:
            triggered_count += 1

        has_quote_error = quote and "error" in quote
        status = "pass" if not has_quote_error else "warning"

        checks.append(TriggerCheckResult(
            symbol=symbol,
            asset_type=item.get("asset_type", "stock"),
            folder_name=item.get("folder_name", ""),
            condition_triggers=ct,
            quote=quote,
            triggered=triggered,
            trigger_reasons=reasons,
            status=status,
            message="; ".join(reasons),
        ))

    overall = "pass"
    if any(c.status == "fail" for c in checks):
        overall = "fail"
    elif any(c.status == "warning" for c in checks):
        overall = "warning"

    return VerificationReport(
        run_id=_new_id(),
        generated_at=_now_iso(),
        data_source=data_source,
        overall_status=overall,
        total_items=len(items),
        triggered_count=triggered_count,
        checks=[asdict(c) for c in checks],
    )


def main():
    parser = argparse.ArgumentParser(description="观察池条件触发器验收")
    parser.add_argument("--data-source", default="qmt", choices=["qmt", "akshare"],
                        help="数据源（默认 qmt）")
    parser.add_argument("--output-dir", default="storage/artifacts/verification",
                        help="输出目录")
    args = parser.parse_args()

    report = verify_watchlist(data_source=args.data_source)

    # 输出到终端
    print(f"\n{'='*60}")
    print(f"观察池条件触发器验收报告")
    print(f"{'='*60}")
    print(f"数据源: {report.data_source}")
    print(f"观察项总数: {report.total_items}")
    print(f"触发数量: {report.triggered_count}")
    print(f"总体状态: {report.overall_status}")
    print()

    for check in report.checks:
        icon = {"pass": "✅", "warning": "⚠️", "fail": "❌", "skipped": "⏭"}.get(check["status"], "?")
        trigger_icon = "🔔" if check["triggered"] else "  "
        print(f"{icon} {trigger_icon} {check['symbol']} ({check['folder_name']})")
        print(f"   配置: {check['condition_triggers']}")
        if check["quote"] and "error" not in check["quote"]:
            q = check["quote"]
            print(f"   行情: 收盘={q.get('close', '-')}, 涨跌={q.get('change_pct', '-'):.2f}%, 量比={q.get('volume_ratio', '-')}")
        elif check["quote"] and "error" in check["quote"]:
            print(f"   行情: 获取失败 — {check['quote']['error']}")
        print(f"   判断: {check['message']}")
        print()

    # 保存到文件
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"watchlist_triggers_{timestamp}.json"
    json_path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")

    # latest.json 符号链接
    latest_path = output_dir / "watchlist_triggers_latest.json"
    latest_path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"报告已保存: {json_path}")
    print(f"最新报告: {latest_path}")


if __name__ == "__main__":
    main()
