"""数据证据结构统一契约测试。

覆盖：
- 裸值可 normalize 成 evidence field。
- 已是 evidence field 时 normalize 幂等。
- missing value 应有 available=false。
- warnings 必须始终是 list。
- confidence 若给出必须限制在 0-1。
- normalize_key_fields() 不应修改原始 result 的关键裸值。
- validate_evidence_fields() 结构化错误。
- summarize_evidence_coverage() 覆盖率统计。
- strict source 规则（行业分位、EVA partial、盈利质量）。
"""

from services.data.evidence_schema import (
    extract_display_value,
    is_evidence_field,
    is_strict_source,
    make_evidence_field,
    normalize_evidence_field,
    normalize_key_fields,
    summarize_evidence_coverage,
    validate_evidence_fields,
)


class TestMakeEvidenceField:

    def test_basic_field(self):
        ev = make_evidence_field(42, source="qmt", as_of="2026-05-01")
        assert ev["value"] == 42
        assert ev["source"] == "qmt"
        assert ev["as_of"] == "2026-05-01"
        assert ev["quality"]["available"] is True
        assert ev["quality"]["missing_reason"] is None
        assert ev["warnings"] == []

    def test_none_value_marks_unavailable(self):
        ev = make_evidence_field(None, source="unknown")
        assert ev["quality"]["available"] is False
        assert ev["quality"]["missing_reason"] is None  # not set when not provided

    def test_missing_reason_set(self):
        ev = make_evidence_field(
            None, source="unknown", missing_reason="loss_making_or_invalid_pe"
        )
        assert ev["quality"]["available"] is False
        assert ev["quality"]["missing_reason"] == "loss_making_or_invalid_pe"

    def test_confidence_clamped(self):
        ev = make_evidence_field(1.0, confidence=1.5)
        assert ev["quality"]["confidence"] == 1.0

        ev2 = make_evidence_field(1.0, confidence=-0.5)
        assert ev2["quality"]["confidence"] == 0.0

    def test_valid_source(self):
        ev = make_evidence_field(1, source="akshare")
        assert ev["source"] == "akshare"

    def test_invalid_source_normalized(self):
        ev = make_evidence_field(1, source="some_random_source")
        assert ev["source"] == "unknown"

    def test_warnings_always_list(self):
        ev = make_evidence_field(1, warnings=None)
        assert isinstance(ev["warnings"], list)

        ev2 = make_evidence_field(1, warnings=["w1", "w2"])
        assert ev2["warnings"] == ["w1", "w2"]

    def test_new_sources_accepted(self):
        for src in [
            "qmt_xtdata", "local_csmar_daily_derived",
            "local_csmar_financial_statements", "local_csmar_industry_history",
            "local_csmar_eva_structure_partial", "derived", "missing",
            "event_provider", "local_csmar_eva_structure",
            "local_csmar_industry_non_strict",
        ]:
            ev = make_evidence_field(1, source=src)
            assert ev["source"] == src, f"source={src} 应被接受"

    def test_new_freshness_accepted(self):
        for fresh in ["historical", "estimated", "missing"]:
            ev = make_evidence_field(1, freshness=fresh)
            assert ev["quality"]["freshness"] == fresh


class TestIsEvidenceField:

    def test_valid_evidence_field(self):
        ev = make_evidence_field(42, source="qmt")
        assert is_evidence_field(ev) is True

    def test_bare_value(self):
        assert is_evidence_field(42) is False
        assert is_evidence_field("hello") is False
        assert is_evidence_field(None) is False

    def test_partial_dict(self):
        assert is_evidence_field({"value": 1}) is False
        assert is_evidence_field({"value": 1, "source": "qmt"}) is False

    def test_dict_with_quality(self):
        d = {"value": 1, "source": "qmt", "quality": {"available": True}}
        assert is_evidence_field(d) is True


class TestIsStrictSource:

    def test_strict_sources(self):
        for src in ["qmt_xtdata", "local_csmar_daily_derived",
                     "local_csmar_financial_statements", "local_csmar_industry_history",
                     "akshare"]:
            assert is_strict_source(src) is True, f"{src} 应为 strict"

    def test_non_strict_sources(self):
        for src in [None, "", "missing", "non_strict", "mock", "unknown",
                     "local_csmar_industry_non_strict",
                     "local_csmar_eva_structure_partial"]:
            assert is_strict_source(src) is False, f"{src} 应为 non-strict"


class TestNormalizeEvidenceField:

    def test_bare_value_normalized(self):
        ev = normalize_evidence_field(42, default_source="qmt")
        assert is_evidence_field(ev)
        assert ev["value"] == 42
        assert ev["source"] == "qmt"

    def test_already_evidence_field_idempotent(self):
        original = make_evidence_field(42, source="akshare", as_of="2026-05-01")
        normalized = normalize_evidence_field(original)
        assert normalized["value"] == 42
        assert normalized["source"] == "akshare"
        assert normalized["as_of"] == "2026-05-01"

    def test_none_value(self):
        ev = normalize_evidence_field(None)
        assert ev["quality"]["available"] is False

    def test_partial_dict_becomes_evidence(self):
        d = {"value": 10, "source": "qmt", "quality": {"available": True}}
        ev = normalize_evidence_field(d)
        assert is_evidence_field(ev)
        assert ev["value"] == 10


class TestExtractDisplayValue:

    def test_evidence_field_returns_value(self):
        ev = make_evidence_field(42)
        assert extract_display_value(ev) == 42

    def test_bare_value_returns_itself(self):
        assert extract_display_value(42) == 42
        assert extract_display_value("hello") == "hello"
        assert extract_display_value(None) is None


class TestNormalizeKeyFields:

    def _make_result(self):
        return {
            "symbol": "600519.SH",
            "as_of": "2026-05-01",
            "price_data": {
                "close": 1688.0,
                "change_20d": 0.05,
                "change_60d": 0.08,
                "ma20_position": "above",
                "ma60_position": "above",
                "max_drawdown_60d": -0.08,
                "volatility_60d": 0.22,
                "avg_turnover_20d": 500000000,
            },
            "fundamental_data": {
                "roe": 0.25,
                "gross_margin": 0.60,
                "net_margin": 0.30,
                "revenue_ttm": 1000000000,
                "net_profit_ttm": 300000000,
                "revenue_growth": 0.10,
                "net_profit_growth": 0.15,
                "debt_ratio": 0.30,
                "operating_cashflow_quality": 0.90,
                "total_volume": 1000000000,
                "float_volume": 800000000,
                "bps": 50.0,
            },
            "valuation_data": {
                "pe_ttm": 21.5,
                "pb_mrq": 5.2,
                "ps_ttm": 10.1,
                "dividend_yield": 0.015,
                "market_cap": 100000000000,
                "pe_percentile": 0.42,
                "pb_percentile": 0.51,
                "ps_percentile": 0.47,
                "industry_pe_percentile": 0.30,
                "industry_pb_percentile": 0.40,
                "industry_ps_percentile": 0.50,
                "industry_percentile_source": "local_csmar_industry_history",
            },
            "industry": {
                "industry_code": "C1234",
                "industry_name": "白酒",
                "classification_system": "P0221",
                "peer_count": 20,
                "valid_peer_count_pe": 18,
                "valid_peer_count_pb": 17,
                "valid_peer_count_ps": 16,
            },
            "event_data": {
                "recent_news_sentiment": "neutral",
                "policy_risk": "low",
                "major_event": "无重大事件",
            },
            "source_metadata": {
                "price_data": {"source": "qmt_xtdata"},
                "fundamental_data": {"source": "local_csmar_financial_statements"},
                "capital_structure_source": "local_csmar_eva_structure_partial",
                "valuation_data": {"source": "local_csmar_daily_derived"},
                "industry_source": "local_csmar_industry_history",
                "event_data": {"source": "cninfo"},
            },
            "data_quality": {
                "field_quality": {
                    "price_data": {"confidence": 0.95, "freshness": "fresh"},
                    "fundamental_data": {"confidence": 0.85, "freshness": "historical"},
                    "valuation_data": {"confidence": 0.80, "freshness": "stale"},
                    "event_data": {"confidence": 0.70, "freshness": "fresh"},
                }
            },
        }

    def test_creates_evidence_fields(self):
        result = self._make_result()
        normalize_key_fields(result)
        assert "evidence_fields" in result
        ef = result["evidence_fields"]
        assert "price_data.close" in ef
        assert "valuation_data.pe_ttm" in ef
        assert "fundamental_data.roe" in ef
        assert "event_data.recent_news_sentiment" in ef

    def test_does_not_modify_original_values(self):
        result = self._make_result()
        orig_close = result["price_data"]["close"]
        orig_pe = result["valuation_data"]["pe_ttm"]
        normalize_key_fields(result)
        assert result["price_data"]["close"] == orig_close
        assert result["valuation_data"]["pe_ttm"] == orig_pe

    def test_source_propagated(self):
        result = self._make_result()
        normalize_key_fields(result)
        ef = result["evidence_fields"]
        assert ef["price_data.close"]["source"] == "qmt_xtdata"
        assert ef["valuation_data.pe_ttm"]["source"] == "local_csmar_daily_derived"

    def test_missing_field_has_unavailable(self):
        result = self._make_result()
        result["valuation_data"]["pe_ttm"] = None
        normalize_key_fields(result)
        ef = result["evidence_fields"]
        assert ef["valuation_data.pe_ttm"]["quality"]["available"] is False
        assert ef["valuation_data.pe_ttm"]["quality"]["missing_reason"] is not None

    def test_missing_field_uses_specific_reason(self):
        result = self._make_result()
        result["valuation_data"]["pe_ttm"] = None
        result["valuation_data"]["pe_ttm_missing_reason"] = "loss_making_or_invalid_pe"
        normalize_key_fields(result)
        ef = result["evidence_fields"]
        assert ef["valuation_data.pe_ttm"]["quality"]["missing_reason"] == "loss_making_or_invalid_pe"

    def test_confidence_from_field_quality(self):
        result = self._make_result()
        normalize_key_fields(result)
        ef = result["evidence_fields"]
        assert ef["price_data.close"]["quality"]["confidence"] == 0.95

    def test_evidence_fields_count(self):
        result = self._make_result()
        normalize_key_fields(result)
        # 8 price + 9 fundamental (incl. capital structure) + 5 valuation core + 3 historical percentile + 3 industry percentile + 7 industry + 2 event = 37
        count = len(result["evidence_fields"])
        assert count >= 37, f"Expected >= 37 evidence fields, got {count}"

    def test_industry_percentile_strict_source(self):
        result = self._make_result()
        normalize_key_fields(result)
        ef = result["evidence_fields"]
        assert ef["valuation_data.industry_pe_percentile"]["source"] == "local_csmar_industry_history"
        assert ef["valuation_data.industry_pe_percentile"]["quality"]["available"] is True
        assert len(ef["valuation_data.industry_pe_percentile"]["warnings"]) == 0

    def test_industry_percentile_non_strict_has_warning(self):
        result = self._make_result()
        result["valuation_data"]["industry_percentile_source"] = "local_csmar_industry_non_strict"
        normalize_key_fields(result)
        ef = result["evidence_fields"]
        assert ef["valuation_data.industry_pe_percentile"]["source"] == "local_csmar_industry_non_strict"
        assert len(ef["valuation_data.industry_pe_percentile"]["warnings"]) > 0

    def test_eva_partial_as_capital_structure_source(self):
        result = self._make_result()
        normalize_key_fields(result)
        ef = result["evidence_fields"]
        # total_volume comes from capital_structure (EVA partial)
        assert ef["fundamental_data.total_volume"]["source"] == "local_csmar_eva_structure_partial"
        # roe comes from fundamental_data (CSMAR financial statements)
        assert ef["fundamental_data.roe"]["source"] == "local_csmar_financial_statements"

    def test_industry_fields_from_industry_source(self):
        result = self._make_result()
        normalize_key_fields(result)
        ef = result["evidence_fields"]
        assert ef["industry.industry_name"]["source"] == "local_csmar_industry_history"
        assert ef["industry.peer_count"]["value"] == 20

    def test_industry_non_strict_sets_estimated_freshness(self):
        result = self._make_result()
        result["source_metadata"]["industry_source"] = "local_csmar_industry_non_strict"
        normalize_key_fields(result)
        ef = result["evidence_fields"]
        assert ef["industry.industry_name"]["quality"]["freshness"] == "estimated"


class TestValidateEvidenceFields:

    def _make_valid_result(self):
        result = {
            "as_of": "2026-05-01",
            "price_data": {"close": 100.0, "change_20d": 0.05},
            "valuation_data": {"pe_ttm": 15.0},
            "fundamental_data": {"roe": 0.15},
            "industry": {"industry_name": "测试行业"},
            "event_data": {"recent_news_sentiment": "neutral"},
            "source_metadata": {
                "price_data": {"source": "qmt_xtdata"},
                "valuation_data": {"source": "local_csmar_daily_derived"},
                "fundamental_data": {"source": "local_csmar_financial_statements"},
                "industry_source": "local_csmar_industry_history",
                "event_data": {"source": "cninfo"},
            },
            "data_quality": {},
        }
        normalize_key_fields(result)
        return result

    def test_valid_result_no_errors(self):
        result = self._make_valid_result()
        errors = validate_evidence_fields(result)
        # All required fields should be present with values
        # Filter out errors about missing fields that we didn't populate
        critical_errors = [e for e in errors if e["error"] not in ("missing_field",)]
        assert len(critical_errors) == 0

    def test_missing_evidence_fields_detected(self):
        result = {"as_of": "2026-05-01"}
        errors = validate_evidence_fields(result)
        assert any(e["error"] == "missing_evidence_fields" for e in errors)

    def test_missing_path_detected(self):
        result = self._make_valid_result()
        errors = validate_evidence_fields(
            result,
            required_paths=["price_data.close", "nonexistent.path"],
        )
        path_errors = [e for e in errors if e["path"] == "nonexistent.path"]
        assert len(path_errors) == 1
        assert path_errors[0]["error"] == "missing_field"

    def test_empty_source_detected(self):
        result = self._make_valid_result()
        result["evidence_fields"]["price_data.close"]["source"] = ""
        errors = validate_evidence_fields(
            result, required_paths=["price_data.close"]
        )
        assert any(e["error"] == "empty_source" for e in errors)

    def test_confidence_out_of_range_detected(self):
        result = self._make_valid_result()
        result["evidence_fields"]["price_data.close"]["quality"]["confidence"] = 1.5
        errors = validate_evidence_fields(
            result, required_paths=["price_data.close"]
        )
        assert any(e["error"] == "confidence_out_of_range" for e in errors)

    def test_inconsistent_available_missing_reason(self):
        result = self._make_valid_result()
        result["evidence_fields"]["price_data.close"]["quality"]["available"] = True
        result["evidence_fields"]["price_data.close"]["quality"]["missing_reason"] = "some_reason"
        errors = validate_evidence_fields(
            result, required_paths=["price_data.close"]
        )
        assert any(e["error"] == "inconsistent_available_missing_reason" for e in errors)

    def test_warnings_not_list_detected(self):
        result = self._make_valid_result()
        result["evidence_fields"]["price_data.close"]["warnings"] = "not a list"
        errors = validate_evidence_fields(
            result, required_paths=["price_data.close"]
        )
        assert any(e["error"] == "warnings_not_list" for e in errors)


class TestSummarizeEvidenceCoverage:

    def _make_result_with_evidence(self):
        result = {
            "as_of": "2026-05-01",
            "price_data": {"close": 100.0, "change_20d": 0.05, "change_60d": 0.08,
                           "ma20_position": "above", "ma60_position": "above",
                           "max_drawdown_60d": -0.08, "volatility_60d": 0.22,
                           "avg_turnover_20d": 500000000},
            "valuation_data": {"pe_ttm": 15.0, "pb_mrq": 2.0, "ps_ttm": 5.0,
                               "dividend_yield": 0.02, "market_cap": 1e10,
                               "pe_percentile": 0.4, "pb_percentile": 0.5, "ps_percentile": 0.6},
            "fundamental_data": {"roe": 0.15, "gross_margin": 0.4, "net_margin": 0.2,
                                 "revenue_ttm": 1e9, "net_profit_ttm": 2e8,
                                 "revenue_growth": 0.1, "net_profit_growth": 0.15,
                                 "debt_ratio": 0.3, "operating_cashflow_quality": 0.9,
                                 "total_volume": 1e9, "float_volume": 8e8, "bps": 10.0},
            "industry": {"industry_code": "C1234", "industry_name": "测试",
                         "classification_system": "P0221", "peer_count": 20,
                         "valid_peer_count_pe": 18, "valid_peer_count_pb": 17,
                         "valid_peer_count_ps": 16},
            "event_data": {"recent_news_sentiment": "neutral", "policy_risk": "low"},
            "source_metadata": {
                "price_data": {"source": "qmt_xtdata"},
                "valuation_data": {"source": "local_csmar_daily_derived"},
                "fundamental_data": {"source": "local_csmar_financial_statements"},
                "capital_structure_source": "local_csmar_eva_structure_partial",
                "industry_source": "local_csmar_industry_history",
                "event_data": {"source": "cninfo"},
            },
            "data_quality": {},
        }
        normalize_key_fields(result)
        return result

    def test_all_covered(self):
        result = self._make_result_with_evidence()
        summary = summarize_evidence_coverage(result)
        assert summary["total_required"] > 0
        assert summary["coverage_rate"] > 0.5
        assert summary["covered"] + summary["missing"] == summary["total_required"]

    def test_by_source_populated(self):
        result = self._make_result_with_evidence()
        summary = summarize_evidence_coverage(result)
        assert "qmt_xtdata" in summary["by_source"]
        assert "local_csmar_daily_derived" in summary["by_source"]

    def test_by_quality_populated(self):
        result = self._make_result_with_evidence()
        summary = summarize_evidence_coverage(result)
        assert len(summary["by_quality"]) > 0

    def test_custom_required_paths(self):
        result = self._make_result_with_evidence()
        summary = summarize_evidence_coverage(
            result, required_paths=["price_data.close", "valuation_data.pe_ttm"]
        )
        assert summary["total_required"] == 2
        assert summary["covered"] == 2

    def test_missing_field_counted(self):
        result = self._make_result_with_evidence()
        result["valuation_data"]["pe_ttm"] = None
        normalize_key_fields(result)
        summary = summarize_evidence_coverage(result)
        assert summary["missing"] > 0
        assert len(summary["missing_reasons"]) > 0


class _StubResolver:
    def resolve(self, symbol):
        return {
            "normalized_symbol": symbol,
            "asset_type": "stock",
            "plain_code": symbol.split(".")[0],
            "exchange": "SH",
        }


class _StubService:
    def __init__(self, data):
        self.data = data

    def build(self, merged):
        return {
            "data": self.data,
            "source_metadata": {},
            "provider_run_log": [],
        }


class _StubQuality:
    def build_report(self, merged):
        return {
            "field_quality": {
                "price_data": {"confidence": 0.9, "freshness": "fresh"},
                "fundamental_data": {"confidence": 0.8, "freshness": "fresh"},
                "valuation_data": {"confidence": 0.8, "freshness": "fresh"},
                "event_data": {"confidence": 0.7, "freshness": "fresh"},
            }
        }


class _StubEvidence:
    def build(self, merged):
        return {"bundle_id": "test", "items": []}


class _StubCache:
    def store_run(self, merged):
        self.stored = merged


class TestPipelineEvidenceFields:

    def test_aggregator_writes_evidence_fields(self, monkeypatch):
        import services.data.aggregator.research_data_aggregator as aggregator_module
        from services.data.aggregator.research_data_aggregator import ResearchDataAggregator

        monkeypatch.setattr(aggregator_module, "validate_protocol", lambda *args: None)

        aggregator = ResearchDataAggregator()
        aggregator.symbol_resolver = _StubResolver()
        aggregator.fundamental_service = _StubService({
            "fundamental_data": {
                "roe": 0.2,
                "gross_margin": 0.5,
                "net_profit_growth": 0.1,
            }
        })
        aggregator.valuation_service = _StubService({
            "valuation_data": {
                "pe_ttm": 20,
                "pb_mrq": 3,
                "ps_ttm": 5,
                "pe_percentile": 0.4,
                "pb_percentile": 0.5,
                "ps_percentile": 0.6,
                "industry_pe_percentile": 0.3,
                "industry_pb_percentile": 0.4,
                "industry_ps_percentile": 0.5,
            }
        })
        aggregator.event_service = _StubService({
            "event_data": {"major_event": "无重大事件"}
        })
        aggregator.quality_service = _StubQuality()
        aggregator.evidence_builder = _StubEvidence()
        aggregator.cache = _StubCache()

        result = aggregator.enrich({
            "symbol": "600519.SH",
            "name": "测试标的",
            "asset_type": "stock",
            "as_of": "2026-05-01",
            "price_data": {
                "close": 1688,
                "change_20d": 0.05,
                "change_60d": 0.08,
                "avg_turnover_20d": 1000000,
            },
        })

        assert "evidence_fields" in result
        assert result["evidence_fields"]["price_data.close"]["value"] == 1688

    def test_partial_result_preserves_evidence_fields(self):
        from services.orchestrator.single_asset_research import _build_partial_result

        asset_data = {
            "symbol": "600519.SH",
            "name": "测试标的",
            "asset_type": "stock",
            "as_of": "2026-05-01",
            "price_data": {},
            "evidence_fields": {"price_data.close": make_evidence_field(1688)},
        }
        score_result = {
            "total_score": 70,
            "rating": "B",
            "action": "观察",
            "score_breakdown": {},
        }
        result = _build_partial_result(asset_data, "mock", score_result)
        assert result["evidence_fields"]["price_data.close"]["value"] == 1688
