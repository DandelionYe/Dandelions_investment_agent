"""Tests for LLM input slimming (P2: LLM 输出瘦身验收)."""

from __future__ import annotations

import json

from services.agents.research_context import compact_research_result_for_llm

# ── Fixtures ─────────────────────────────────────────────────────────

def _full_research_result(**overrides):
    """A realistic research_result with large internal fields that must be trimmed."""
    data = {
        "symbol": "600519.SH",
        "name": "贵州茅台",
        "asset_type": "stock",
        "as_of": "2026-05-21",
        "data_source": "qmt",
        "data_source_chain": ["qmt"],
        "data_warnings": [],
        "score": 72,
        "rating": "B",
        "action": "观察",
        "max_position": "5%-8%",
        "score_breakdown": {
            "trend_momentum": 16,
            "liquidity": 13,
            "fundamental_quality": 16,
            "valuation": 10,
            "risk_control": 15,
            "event_policy": 2,
        },
        "price_data": {
            "close": 1688.0,
            "change_20d": 0.052,
            "change_60d": 0.083,
            "ma20_position": "above",
            "ma60_position": "above",
            "max_drawdown_60d": -0.092,
            "volatility_60d": 0.186,
            "avg_turnover_20d": 4_800_000_000,
            "data_vendor": "eastmoney",
            # Should be removed:
            "history_close": list(range(500)),
            "internal_debug": "should not leak",
        },
        "fundamental_data": {
            "roe": 0.33,
            "gross_margin": 0.91,
            "revenue_growth": 0.15,
            "net_profit_growth": 0.12,
            "debt_ratio": 0.22,
            "operating_cashflow_quality": 1.3,
            # Should be removed:
            "raw_financial_tables": {"Balance": list(range(100))},
        },
        "valuation_data": {
            "pe_ttm": 28.5,
            "pb_mrq": 9.2,
            "ps_ttm": 14.1,
            "market_cap": 2_100_000_000_000,
            "pe_percentile": 0.42,
            "pb_percentile": 0.51,
            "ps_percentile": 0.47,
            "dividend_yield": 0.018,
            "valuation_label": "reasonable",
            "industry_name": "食品饮料",
            "industry_level": "申万一级",
            "industry_peer_count": 120,
            "industry_valid_peer_count": 95,
            "industry_valid_peer_count_pe": 90,
            "industry_valid_peer_count_pb": 92,
            "industry_valid_peer_count_ps": 88,
            "industry_pe_percentile": 0.35,
            "industry_pb_percentile": 0.45,
            "industry_ps_percentile": 0.40,
            "industry_valuation_label": "industry_reasonable",
            "industry_valuation_source": "local_csmar+qmt_financial+qmt_price",
            "industry_valuation_warnings": [],
            # Should be removed — full peer lists:
            "industry_peer_inputs": [
                {"symbol": f"60000{i}.SH", "name": f"Peer{i}", "close": 10 + i}
                for i in range(120)
            ],
            "industry_members": [f"60000{i}.SH" for i in range(120)],
            "peer_inputs": [{"symbol": f"60000{i}.SH"} for i in range(120)],
            # Should be removed — raw data:
            "raw": {"some": "large payload"},
        },
        "event_data": {
            "recent_news_sentiment": "neutral",
            "policy_risk": "low",
            "major_event": "暂无重大事件",
            "events": [
                {
                    "title": f"事件{i}",
                    "summary": f"事件{i}摘要",
                    "severity": "low",
                    "sentiment": "neutral",
                    "source": "eastmoney",
                    "publish_time": "2026-05-20",
                    "url": f"https://example.com/{i}",
                    # Should be removed:
                    "full_text": "很长的原文" * 100,
                    "raw_html": "<html>...</html>" * 50,
                }
                for i in range(10)
            ],
        },
        "evidence_bundle": {
            "bundle_id": "evb_600519_SH_20260521",
            "symbol": "600519.SH",
            "as_of": "2026-05-21",
            "items": [
                {
                    "evidence_id": f"ev_{i}",
                    "category": "price",
                    "title": f"证据{i}",
                    "display_value": f"{100 + i}",
                    "source": "qmt",
                    "source_date": "2026-05-21",
                    "confidence": 0.9,
                    "url": f"https://example.com/ev/{i}",
                    # Should be removed:
                    "raw_value": list(range(50)),
                }
                for i in range(30)
            ],
        },
        "data_quality": {
            "overall_confidence": 0.85,
            "has_placeholder": False,
            "blocking_issues": [],
            "warnings": ["测试警告"],
            "field_quality": {"price_data": {"available": True}},
        },
        # Should be removed entirely:
        "provider_run_log": [
            {"provider": "qmt", "status": "success", "rows": 100},
            {"provider": "akshare", "status": "fallback", "rows": 50},
        ],
        "source_metadata": {"price_data": {"source": "qmt"}},
        "basic_info": {"total_volume": 1_000_000_000},
        "symbol_info": {"qmt_code": "600519.SH"},
        "fundamental_analysis": {"quality_label": "high"},
        "etf_data": {},
        "_internal_flag": True,
        "_debug_trace": ["step1", "step2"],
    }
    data.update(overrides)
    return data


# ── compact_research_result_for_llm tests ────────────────────────────

class TestCompactRemovesInternalFields:
    def test_removes_provider_run_log(self):
        result = compact_research_result_for_llm(_full_research_result())
        assert "provider_run_log" not in result

    def test_removes_industry_peer_inputs(self):
        result = compact_research_result_for_llm(_full_research_result())
        val = result.get("valuation_data", {})
        assert "industry_peer_inputs" not in val
        assert "peer_inputs" not in val
        assert "industry_members" not in val

    def test_removes_raw_fields(self):
        result = compact_research_result_for_llm(_full_research_result())
        val = result.get("valuation_data", {})
        assert "raw" not in val

    def test_removes_internal_underscore_keys(self):
        result = compact_research_result_for_llm(_full_research_result())
        for key in result:
            assert not key.startswith("_"), f"Internal key {key} leaked"
        val = result.get("valuation_data", {})
        for key in val:
            assert not key.startswith("_"), f"Internal key {key} leaked in valuation_data"

    def test_removes_source_metadata(self):
        result = compact_research_result_for_llm(_full_research_result())
        assert "source_metadata" not in result

    def test_removes_basic_info(self):
        result = compact_research_result_for_llm(_full_research_result())
        assert "basic_info" not in result

    def test_removes_symbol_info(self):
        result = compact_research_result_for_llm(_full_research_result())
        assert "symbol_info" not in result

    def test_removes_fundamental_analysis(self):
        result = compact_research_result_for_llm(_full_research_result())
        assert "fundamental_analysis" not in result

    def test_removes_etf_data(self):
        result = compact_research_result_for_llm(_full_research_result())
        assert "etf_data" not in result

    def test_removes_price_debug_fields(self):
        result = compact_research_result_for_llm(_full_research_result())
        price = result.get("price_data", {})
        assert "history_close" not in price
        assert "internal_debug" not in price

    def test_removes_fundamental_raw_fields(self):
        result = compact_research_result_for_llm(_full_research_result())
        fund = result.get("fundamental_data", {})
        assert "raw_financial_tables" not in fund


class TestCompactPreservesSummaryFields:
    def test_preserves_top_level_fields(self):
        result = compact_research_result_for_llm(_full_research_result())
        for key in ("symbol", "name", "asset_type", "as_of", "data_source",
                     "score", "rating", "action", "max_position", "score_breakdown"):
            assert key in result, f"Missing top-level key: {key}"

    def test_preserves_price_summary(self):
        result = compact_research_result_for_llm(_full_research_result())
        price = result.get("price_data", {})
        for key in ("close", "change_20d", "change_60d", "ma20_position",
                     "ma60_position", "max_drawdown_60d", "volatility_60d",
                     "avg_turnover_20d", "data_vendor"):
            assert key in price, f"Missing price key: {key}"

    def test_preserves_fundamental_summary(self):
        result = compact_research_result_for_llm(_full_research_result())
        fund = result.get("fundamental_data", {})
        for key in ("roe", "gross_margin", "revenue_growth", "net_profit_growth",
                     "debt_ratio", "operating_cashflow_quality"):
            assert key in fund, f"Missing fundamental key: {key}"

    def test_preserves_valuation_summary(self):
        result = compact_research_result_for_llm(_full_research_result())
        val = result.get("valuation_data", {})
        for key in ("pe_ttm", "pb_mrq", "ps_ttm", "market_cap",
                     "pe_percentile", "pb_percentile", "ps_percentile",
                     "dividend_yield", "valuation_label"):
            assert key in val, f"Missing valuation key: {key}"

    def test_preserves_industry_summary(self):
        result = compact_research_result_for_llm(_full_research_result())
        val = result.get("valuation_data", {})
        for key in ("industry_name", "industry_peer_count",
                     "industry_valid_peer_count", "industry_pe_percentile",
                     "industry_valuation_label", "industry_valuation_source"):
            assert key in val, f"Missing industry key: {key}"

    def test_preserves_missing_reasons(self):
        # Verify the allowlist doesn't strip missing_reason fields
        data = _full_research_result()
        data["valuation_data"]["pe_ttm_missing_reason"] = "loss_making_or_invalid_pe"
        data["valuation_data"]["industry_percentile_missing_reason"] = "insufficient_peer_samples"
        result = compact_research_result_for_llm(data)
        assert result["valuation_data"]["pe_ttm_missing_reason"] == "loss_making_or_invalid_pe"
        assert result["valuation_data"]["industry_percentile_missing_reason"] == "insufficient_peer_samples"

    def test_preserves_event_summary_fields(self):
        result = compact_research_result_for_llm(_full_research_result())
        event = result.get("event_data", {})
        assert event.get("recent_news_sentiment") == "neutral"
        assert event.get("policy_risk") == "low"
        assert event.get("major_event") == "暂无重大事件"


class TestEvidenceBundleLimited:
    def test_evidence_items_limited_to_20(self):
        data = _full_research_result()
        assert len(data["evidence_bundle"]["items"]) == 30  # precondition
        result = compact_research_result_for_llm(data)
        items = result["evidence_bundle"]["items"]
        assert len(items) <= 20

    def test_evidence_items_keep_allowed_keys(self):
        result = compact_research_result_for_llm(_full_research_result())
        items = result["evidence_bundle"]["items"]
        assert len(items) > 0
        item = items[0]
        for key in ("evidence_id", "category", "title", "display_value",
                     "source", "source_date", "confidence", "url"):
            assert key in item, f"Missing evidence key: {key}"
        # raw_value should be stripped
        assert "raw_value" not in item

    def test_evidence_bundle_preserves_metadata(self):
        result = compact_research_result_for_llm(_full_research_result())
        bundle = result["evidence_bundle"]
        assert bundle.get("bundle_id") is not None
        assert bundle.get("symbol") == "600519.SH"


class TestEventsLimited:
    def test_events_limited_to_3(self):
        data = _full_research_result()
        assert len(data["event_data"]["events"]) == 10  # precondition
        result = compact_research_result_for_llm(data)
        events = result["event_data"]["events"]
        assert len(events) <= 3

    def test_events_keep_allowed_keys(self):
        result = compact_research_result_for_llm(_full_research_result())
        events = result["event_data"]["events"]
        assert len(events) > 0
        event = events[0]
        for key in ("title", "summary", "severity", "sentiment",
                     "source", "publish_time", "url"):
            assert key in event, f"Missing event key: {key}"
        # full_text and raw_html should be stripped
        assert "full_text" not in event
        assert "raw_html" not in event


class TestPromptDoesNotContainPeerList:
    """Verify that agent prompts don't contain full peer symbol lists."""

    def test_bull_prompt_excludes_peer_list(self, monkeypatch):
        from services.agents.bull_analyst import BullAnalyst

        prompts = []

        def mock_chat_json(self_client, system_prompt, user_prompt, model, max_tokens):
            prompts.append(user_prompt)
            return {"thesis": "test", "key_arguments": ["a"], "catalysts": [], "invalidation_conditions": []}

        monkeypatch.setattr(
            "services.llm.deepseek_client.DeepSeekClient.chat_json",
            mock_chat_json,
        )

        data = _full_research_result()
        # Add some distinctive peer symbols
        data["valuation_data"]["industry_peer_inputs"] = [
            {"symbol": f"PEER{i:04d}.SH"} for i in range(50)
        ]

        analyst = BullAnalyst()
        analyst.analyze(data)

        assert len(prompts) == 1
        prompt = prompts[0]
        # The prompt should NOT contain the full peer list
        assert "PEER0001.SH" not in prompt
        assert "PEER0049.SH" not in prompt
        # But SHOULD contain industry summary
        assert "食品饮料" in prompt
        assert "120" in prompt  # industry_peer_count

    def test_bear_prompt_excludes_provider_run_log(self, monkeypatch):
        from services.agents.bear_analyst import BearAnalyst

        prompts = []

        def mock_chat_json(self_client, system_prompt, user_prompt, model, max_tokens):
            prompts.append(user_prompt)
            return {"thesis": "test", "key_arguments": ["a"], "main_concerns": [], "invalidation_conditions": []}

        monkeypatch.setattr(
            "services.llm.deepseek_client.DeepSeekClient.chat_json",
            mock_chat_json,
        )

        data = _full_research_result()
        analyst = BearAnalyst()
        analyst.analyze(data)

        prompt = prompts[0]
        assert "provider_run_log" not in prompt
        assert "akshare" not in prompt  # from run log

    def test_risk_prompt_excludes_raw_data(self, monkeypatch):
        from services.agents.risk_officer import RiskOfficer

        prompts = []

        def mock_chat_json(self_client, system_prompt, user_prompt, model, max_tokens):
            prompts.append(user_prompt)
            return {"risk_level": "medium", "blocking": False, "risk_summary": "test", "max_position": "5%", "risk_triggers": []}

        monkeypatch.setattr(
            "services.llm.deepseek_client.DeepSeekClient.chat_json",
            mock_chat_json,
        )

        data = _full_research_result()
        officer = RiskOfficer()
        officer.review(data)

        prompt = prompts[0]
        assert "raw_financial_tables" not in prompt
        assert "history_close" not in prompt

    def test_supervisor_prompt_excludes_peer_list(self, monkeypatch):
        from services.agents.supervisor import Supervisor

        prompts = []

        def mock_chat_json(self_client, system_prompt, user_prompt, model, max_tokens):
            prompts.append(user_prompt)
            return {"is_converged": True, "convergence_reason": "all_agree", "next_speaker": None, "challenge": None, "round_summary": "test"}

        monkeypatch.setattr(
            "services.llm.deepseek_client.DeepSeekClient.chat_json",
            mock_chat_json,
        )

        data = _full_research_result()
        data["valuation_data"]["industry_peer_inputs"] = [
            {"symbol": f"PEER{i:04d}.SH"} for i in range(50)
        ]

        supervisor = Supervisor()
        supervisor.evaluate(
            research_result=data,
            bull_case={"thesis": "test"},
            bear_case={"thesis": "test"},
            risk_review={"risk_summary": "test"},
            debate_history=[],
            current_round=1,
            max_rounds=3,
        )

        prompt = prompts[0]
        assert "PEER0001.SH" not in prompt
        assert "食品饮料" in prompt

    def test_committee_prompt_excludes_run_log(self, monkeypatch):
        from services.agents.committee_secretary import CommitteeSecretary

        prompts = []

        def mock_chat_json(self_client, system_prompt, user_prompt, model, max_tokens):
            prompts.append(user_prompt)
            return {"stance": "谨慎看多", "action": "观察", "confidence": 0.7, "final_opinion": "test"}

        monkeypatch.setattr(
            "services.llm.deepseek_client.DeepSeekClient.chat_json",
            mock_chat_json,
        )

        data = _full_research_result()
        secretary = CommitteeSecretary()
        secretary.converge(
            research_result=data,
            bull_case={"thesis": "test"},
            bear_case={"thesis": "test"},
            risk_review={"risk_summary": "test"},
        )

        prompt = prompts[0]
        assert "provider_run_log" not in prompt
        assert "industry_peer_inputs" not in prompt


class TestPromptContainsIndustrySummary:
    """Verify that essential industry summary IS present in prompts."""

    def test_bull_prompt_has_industry_pe_percentile(self, monkeypatch):
        from services.agents.bull_analyst import BullAnalyst

        prompts = []

        def mock_chat_json(self_client, system_prompt, user_prompt, model, max_tokens):
            prompts.append(user_prompt)
            return {"thesis": "test", "key_arguments": ["a"], "catalysts": [], "invalidation_conditions": []}

        monkeypatch.setattr(
            "services.llm.deepseek_client.DeepSeekClient.chat_json",
            mock_chat_json,
        )

        data = _full_research_result()
        analyst = BullAnalyst()
        analyst.analyze(data)

        prompt = prompts[0]
        prompt_dict = json.loads(prompt.split("输入研究结果如下：\n\n")[1].split("\n\n请严格按照")[0])
        val = prompt_dict.get("valuation_data", {})
        assert val.get("industry_pe_percentile") == 0.35
        assert val.get("industry_name") == "食品饮料"
        assert val.get("industry_valid_peer_count") == 95


class TestCompactPreservesDataQuality:
    def test_data_quality_keeps_summary_fields(self):
        result = compact_research_result_for_llm(_full_research_result())
        dq = result.get("data_quality", {})
        assert dq.get("overall_confidence") == 0.85
        assert dq.get("has_placeholder") is False
        assert "测试警告" in dq.get("warnings", [])

    def test_data_quality_strips_field_quality(self):
        result = compact_research_result_for_llm(_full_research_result())
        dq = result.get("data_quality", {})
        # field_quality is not in the compact data_quality
        assert "field_quality" not in dq


class TestEdgeCases:
    def test_empty_research_result(self):
        result = compact_research_result_for_llm({})
        assert isinstance(result, dict)
        assert "price_data" not in result
        assert "valuation_data" not in result

    def test_none_nested_fields(self):
        data = _full_research_result()
        data["price_data"] = None
        data["event_data"] = None
        result = compact_research_result_for_llm(data)
        assert "price_data" not in result
        assert "event_data" not in result

    def test_missing_evidence_bundle(self):
        data = _full_research_result()
        del data["evidence_bundle"]
        result = compact_research_result_for_llm(data)
        assert "evidence_bundle" not in result


# ── No-LLM mode and report pipeline not broken ──────────────────────

class TestNoLLMModeUnbroken:
    def test_no_llm_research_still_works(self):
        from services.orchestrator.single_asset_research import run_single_asset_research

        result = run_single_asset_research(
            "600519.SH",
            use_llm=False,
            data_source="mock",
        )

        assert result["symbol"] == "600519.SH"
        assert result["score"] >= 0
        assert result["decision_guard"]["enabled"] is True


class TestAuditMetadataWithCompactData:
    def test_build_agent_metadata_with_compact_data(self):
        from services.agents.audit_metadata import build_agent_metadata

        compact = compact_research_result_for_llm(_full_research_result())
        metadata = build_agent_metadata(
            agent_role="bull",
            prompt_version="test_v1",
            model="test-model",
            system_prompt="test system",
            user_prompt="test user",
            research_result=compact,
        )

        snapshot = metadata.get("input_snapshot", {})
        assert snapshot.get("symbol") == "600519.SH"
        # The snapshot should not contain peer lists
        val = snapshot.get("valuation_data", {})
        assert "industry_peer_inputs" not in val
