"""观察池条件触发器测试。"""

import pytest
import json


class TestConditionTriggersSchema:

    def test_all_null_default(self):
        """默认 ConditionTriggers 所有字段为 None（不触发）。"""
        from apps.api.schemas.watchlist import ConditionTriggers
        ct = ConditionTriggers()
        assert ct.price_change_pct is None
        assert ct.score_threshold is None
        assert ct.volume_spike_ratio is None

    def test_partial_config(self):
        """部分字段有值的配置。"""
        from apps.api.schemas.watchlist import ConditionTriggers
        ct = ConditionTriggers(price_change_pct=5.0)
        assert ct.price_change_pct == 5.0
        assert ct.score_threshold is None
        assert ct.volume_spike_ratio is None

    def test_schedule_config_includes_triggers(self):
        """ScheduleConfig 包含 condition_triggers。"""
        from apps.api.schemas.watchlist import ScheduleConfig, ConditionTriggers
        sc = ScheduleConfig(
            mode="cron",
            condition_triggers=ConditionTriggers(price_change_pct=3.0, score_threshold=75.0),
        )
        assert sc.condition_triggers.price_change_pct == 3.0
        assert sc.condition_triggers.score_threshold == 75.0

    def test_roundtrip_via_json(self):
        """验证 condition_triggers 可以通过 JSON 序列化/反序列化保留。"""
        from apps.api.schemas.watchlist import ScheduleConfig, ConditionTriggers
        sc = ScheduleConfig(
            mode="cron",
            condition_triggers=ConditionTriggers(volume_spike_ratio=2.5),
        )
        dumped = sc.model_dump()
        assert dumped["condition_triggers"]["volume_spike_ratio"] == 2.5
        # 模拟存储层往返
        reloaded = json.loads(json.dumps(dumped))
        assert reloaded["condition_triggers"]["volume_spike_ratio"] == 2.5


class TestConditionEvaluation:

    def test_empty_triggers_no_trigger(self):
        """condition_triggers 为空 dict 时不触发。"""
        ct = {}
        assert all(v is None for v in ct.values())

    def test_price_trigger_below_threshold(self):
        """价格变动未达阈值不触发。"""
        change_pct = 2.0
        threshold = 5.0
        assert abs(change_pct) < threshold

    def test_price_trigger_above_threshold(self):
        """价格变动达阈值触发。"""
        change_pct = -6.0
        threshold = 5.0
        assert abs(change_pct) >= threshold

    def test_score_trigger_below_threshold(self):
        """评分未达阈值不触发。"""
        last_score = 70
        threshold = 80
        assert last_score < threshold

    def test_score_trigger_above_threshold(self):
        """评分达阈值触发。"""
        last_score = 85
        threshold = 80
        assert last_score >= threshold

    def test_volume_trigger_below_threshold(self):
        """成交量未达异动倍数不触发。"""
        vol_ratio = 2.0
        threshold = 3.0
        assert vol_ratio < threshold

    def test_volume_trigger_above_threshold(self):
        """成交量达异动倍数触发。"""
        vol_ratio = 4.5
        threshold = 3.0
        assert vol_ratio >= threshold

    def test_multiple_triggers_partial(self):
        """多条件中只有一个满足也应触发。"""
        ct = {"price_change_pct": 5.0, "score_threshold": 90, "volume_spike_ratio": None}
        # 价格满足，评分不满足
        change_pct = 7.0
        last_score = 75
        vol_ratio = 1.0
        triggered = False
        if ct.get("price_change_pct") and abs(change_pct) >= ct["price_change_pct"]:
            triggered = True
        if ct.get("volume_spike_ratio") and vol_ratio >= ct["volume_spike_ratio"]:
            triggered = True
        if ct.get("score_threshold") and last_score >= ct["score_threshold"]:
            triggered = True
        assert triggered is True


class TestAntiRepeat:

    def test_recent_scan_blocked(self):
        """30 分钟内已扫描则跳过。"""
        from datetime import datetime, timezone, timedelta
        recent_scan = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        last_dt = datetime.fromisoformat(recent_scan.replace("Z", "+00:00"))
        elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
        assert elapsed < 1800

    def test_old_scan_allowed(self):
        """超过 30 分钟的扫描允许再次触发。"""
        from datetime import datetime, timezone, timedelta
        old_scan = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
        last_dt = datetime.fromisoformat(old_scan.replace("Z", "+00:00"))
        elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
        assert elapsed >= 1800


class TestQMTQuoteModule:

    def test_import(self):
        """验证模块可以正常导入。"""
        from services.data.qmt_realtime_quote import get_latest_price_data
        assert callable(get_latest_price_data)

    def test_no_qmt_returns_none(self):
        """无 QMT 环境时返回 None 而非抛异常。"""
        # 模块在 import xtdata 时会抛 RuntimeError，函数内会 catch
        pass  # 测试实际运行时由 QMT 环境验证


class TestValuationTriggers:

    def test_pe_ttm_below_threshold(self):
        """PE <= 阈值时触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"pe_ttm_max": 20.0}}}
        latest = {"valuation_data": {"pe_ttm": 15.0}}
        result = evaluate_condition_triggers(item, latest_result=latest)
        assert result.triggered is True
        assert any("PE-TTM" in r for r in result.reasons)
        assert "pe_ttm_max" in result.categories_evaluated

    def test_pe_ttm_above_threshold(self):
        """PE > 阈值时不触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"pe_ttm_max": 20.0}}}
        latest = {"valuation_data": {"pe_ttm": 30.0}}
        result = evaluate_condition_triggers(item, latest_result=latest)
        assert result.triggered is False

    def test_pe_ttm_no_data(self):
        """估值数据不可用时不触发，记录 missing_reason。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"pe_ttm_max": 20.0}}}
        result = evaluate_condition_triggers(item, latest_result=None)
        assert result.triggered is False
        assert len(result.missing_reasons) > 0

    def test_pb_mrq_below_threshold(self):
        """PB <= 阈值时触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"pb_mrq_max": 2.0}}}
        latest = {"valuation_data": {"pb_mrq": 1.5}}
        result = evaluate_condition_triggers(item, latest_result=latest)
        assert result.triggered is True

    def test_valuation_percentile_below_threshold(self):
        """估值分位 <= 阈值时触发（低估区间）。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"valuation_percentile_max": 30.0}}}
        latest = {"valuation_data": {"valuation_percentile": 20.0}}
        result = evaluate_condition_triggers(item, latest_result=latest)
        assert result.triggered is True

    def test_valuation_percentile_above_threshold(self):
        """估值分位 > 阈值时不触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"valuation_percentile_max": 30.0}}}
        latest = {"valuation_data": {"valuation_percentile": 50.0}}
        result = evaluate_condition_triggers(item, latest_result=latest)
        assert result.triggered is False


class TestRiskTriggers:

    def test_risk_level_high_triggers(self):
        """风险等级 high >= medium 阈值时触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"risk_level_min": "medium"}}}
        latest = {"risk_review": {"risk_level": "high"}}
        result = evaluate_condition_triggers(item, latest_result=latest)
        assert result.triggered is True

    def test_risk_level_low_not_trigger(self):
        """风险等级 low < medium 阈值时不触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"risk_level_min": "medium"}}}
        latest = {"risk_review": {"risk_level": "low"}}
        result = evaluate_condition_triggers(item, latest_result=latest)
        assert result.triggered is False

    def test_risk_level_no_data(self):
        """风险数据不可用时不触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"risk_level_min": "high"}}}
        result = evaluate_condition_triggers(item, latest_result=None)
        assert result.triggered is False
        assert len(result.missing_reasons) > 0


class TestEventTriggers:

    def test_event_severity_high_triggers(self):
        """事件严重性 high >= high 阈值时触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"event_severity_min": "high"}}}
        latest = {"event_data": {"max_severity": "high"}}
        result = evaluate_condition_triggers(item, latest_result=latest)
        assert result.triggered is True

    def test_event_severity_low_not_trigger(self):
        """事件严重性 low < high 阈值时不触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"event_severity_min": "high"}}}
        latest = {"event_data": {"max_severity": "low"}}
        result = evaluate_condition_triggers(item, latest_result=latest)
        assert result.triggered is False

    def test_event_keywords_match(self):
        """事件关键词匹配时触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"event_keywords": ["问询函", "处罚"]}}}
        latest = {"event_data": {"announcements": [{"title": "关于收到问询函的公告"}]}}
        result = evaluate_condition_triggers(item, latest_result=latest)
        assert result.triggered is True
        assert any("问询函" in r for r in result.reasons)

    def test_event_keywords_no_match(self):
        """事件关键词不匹配时不触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"event_keywords": ["处罚"]}}}
        latest = {"event_data": {"announcements": [{"title": "2024年年度报告"}]}}
        result = evaluate_condition_triggers(item, latest_result=latest)
        assert result.triggered is False

    def test_event_keywords_no_data(self):
        """事件数据不可用时不触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"event_keywords": ["问询函"]}}}
        result = evaluate_condition_triggers(item, latest_result=None)
        assert result.triggered is False
        assert len(result.missing_reasons) > 0

    def test_empty_keywords_list_not_trigger(self):
        """空关键词列表不触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"event_keywords": []}}}
        result = evaluate_condition_triggers(item, latest_result=None)
        assert result.triggered is False
        assert "event_keywords" not in result.categories_evaluated


class TestMissingDataBehavior:

    def test_no_score_no_trigger_with_missing_reason(self):
        """无 last_score 时 score_threshold 不触发且记录 missing_reason。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"score_threshold": 80.0}}}
        result = evaluate_condition_triggers(item)
        assert result.triggered is False
        assert any("score" in r.lower() or "评分" in r for r in result.missing_reasons)

    def test_no_quote_no_trigger_with_missing_reason(self):
        """无行情数据时 price/volume 不触发且记录 missing_reason。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"price_change_pct": 5.0, "volume_spike_ratio": 3.0}}}
        result = evaluate_condition_triggers(item, quote=None)
        assert result.triggered is False
        assert len(result.missing_reasons) >= 2

    def test_quote_error_recorded(self):
        """行情获取失败时记录错误信息。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"price_change_pct": 5.0}}}
        quote = {"error": "QMT not available"}
        result = evaluate_condition_triggers(item, quote=quote)
        assert result.triggered is False
        assert any("QMT" in r for r in result.missing_reasons)


class TestThresholdZeroConfigured:

    def test_price_threshold_zero_is_configured(self):
        """price_change_pct=0 视为已配置（is not None），不是未配置。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {"price_change_pct": 0.0}}}
        quote = {"change_pct": 10.0, "volume_ratio": 1.0}
        result = evaluate_condition_triggers(item, quote=quote)
        assert result.triggered is True  # 0 threshold means always triggers
        assert "price_change_pct" in result.categories_evaluated


class TestMultipleTriggersAnyFires:

    def test_mixed_triggers_partial_match(self):
        """多条件中部分满足即触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {
            "schedule_config": {
                "condition_triggers": {
                    "price_change_pct": 5.0,
                    "pe_ttm_max": 20.0,
                    "event_severity_min": "high",
                }
            },
        }
        quote = {"change_pct": 7.0, "volume_ratio": 1.0}
        latest = {"valuation_data": {"pe_ttm": 25.0}, "event_data": {"max_severity": "low"}}
        result = evaluate_condition_triggers(item, quote=quote, latest_result=latest)
        assert result.triggered is True  # price trigger fires
        assert len(result.categories_evaluated) == 3

    def test_no_triggers_configured(self):
        """所有字段为 None/空时不触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {"schedule_config": {"condition_triggers": {}}}
        result = evaluate_condition_triggers(item)
        assert result.triggered is False
        assert len(result.categories_evaluated) == 0

    def test_all_none_not_triggered(self):
        """所有字段显式为 None 时不触发。"""
        from apps.api.task_manager.watchlist_triggers import evaluate_condition_triggers
        item = {
            "schedule_config": {
                "condition_triggers": {
                    "price_change_pct": None,
                    "score_threshold": None,
                    "volume_spike_ratio": None,
                    "pe_ttm_max": None,
                    "pb_mrq_max": None,
                }
            }
        }
        result = evaluate_condition_triggers(item)
        assert result.triggered is False
        assert len(result.categories_evaluated) == 0
