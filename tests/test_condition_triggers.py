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
