import pandas as pd
import pytest

from services.data.aggregator.evidence_builder import EvidenceBuilder
from services.data.provider_contracts import (
    ProviderDataQualityError,
    ProviderMetadata,
    ProviderResult,
)
from services.data.providers import qmt_peer_valuation_loader as peer_loader_module
from services.data.providers.qmt_peer_valuation_loader import QMTPeerValuationLoader
from services.research.industry_valuation_engine import (
    IndustryValuationService,
    PeerValuationInput,
    calculate_industry_valuation_percentiles,
    calculate_peer_multiples,
    percentile_midrank,
)
from services.research.valuation_engine import ValuationService


def _peer(
    symbol: str,
    *,
    close: float = 10,
    total_volume: float = 100,
    net_profit_ttm: float | None = 100,
    revenue_ttm: float | None = 500,
    bps: float | None = 5,
    asset_type: str = "stock",
    is_st: bool = False,
    is_suspended: bool = False,
) -> PeerValuationInput:
    return PeerValuationInput(
        symbol=symbol,
        name=symbol,
        asset_type=asset_type,
        close=close,
        total_volume=total_volume,
        float_volume=total_volume,
        net_profit_ttm=net_profit_ttm,
        revenue_ttm=revenue_ttm,
        bps=bps,
        is_st=is_st,
        is_suspended=is_suspended,
    )


def test_calculate_peer_multiples():
    result = calculate_peer_multiples(_peer("600000.SH", close=10, total_volume=100, net_profit_ttm=50, revenue_ttm=200, bps=5))
    assert result["pe_ttm"] == 20
    assert result["pb_mrq"] == 2
    assert result["ps_ttm"] == 5


def test_midrank_percentile_handles_duplicates():
    assert percentile_midrank(10, [5, 10, 10, 20]) == pytest.approx(0.5)


def test_industry_percentile_normal_case_is_deterministic():
    peers = [
        _peer(f"600{i:03d}.SH", net_profit_ttm=1000 / (i + 1), bps=10 / (i + 1))
        for i in range(30)
    ]
    result1 = calculate_industry_valuation_percentiles(
        target_symbol="600010.SH",
        industry_level="SW1",
        industry_name="SW1 Test",
        industry_members=[peer.symbol for peer in peers],
        peers=peers,
    )
    result2 = calculate_industry_valuation_percentiles(
        target_symbol="600010.SH",
        industry_level="SW1",
        industry_name="SW1 Test",
        industry_members=[peer.symbol for peer in reversed(peers)],
        peers=list(reversed(peers)),
    )

    assert result1.industry_valid_peer_count_pe == 30
    assert result1.industry_pe_percentile is not None
    assert result1.to_dict() == result2.to_dict()


def test_insufficient_peers_returns_none_and_warning():
    peers = [_peer(f"600{i:03d}.SH") for i in range(5)]
    result = calculate_industry_valuation_percentiles(
        target_symbol="600001.SH",
        industry_level="SW1",
        industry_name="SW1 Small",
        industry_members=[peer.symbol for peer in peers],
        peers=peers,
        min_valid_peers=20,
    )

    assert result.industry_pe_percentile is None
    assert result.industry_valuation_label == "industry_insufficient_peers"
    assert any("below 20" in warning for warning in result.warnings)


def test_loss_making_target_does_not_look_cheap_from_low_pb():
    peers = [_peer(f"600{i:03d}.SH", net_profit_ttm=100) for i in range(25)]
    peers[3] = _peer("600003.SH", net_profit_ttm=-10, bps=1000)

    result = calculate_industry_valuation_percentiles(
        target_symbol="600003.SH",
        industry_level="SW1",
        industry_name="SW1 Loss",
        industry_members=[peer.symbol for peer in peers],
        peers=peers,
    )

    assert result.industry_pe_percentile is None
    assert result.industry_valuation_label == "industry_loss_making_or_invalid_pe"


def test_filters_non_stock_st_suspended_and_outliers():
    peers = [_peer(f"600{i:03d}.SH", net_profit_ttm=100) for i in range(25)]
    peers += [
        _peer("510300.SH", asset_type="etf"),
        _peer("600900.SH", is_st=True),
        _peer("600901.SH", is_suspended=True),
        _peer("600902.SH", net_profit_ttm=1),
        _peer("600903.SH", bps=0.01),
        _peer("600904.SH", revenue_ttm=1),
    ]

    result = calculate_industry_valuation_percentiles(
        target_symbol="600001.SH",
        industry_level="SW1",
        industry_name="SW1 Filter",
        industry_members=[peer.symbol for peer in peers],
        peers=peers,
    )

    assert result.industry_valid_peer_count_pe == 27
    assert result.industry_valid_peer_count_pb == 27
    assert result.industry_valid_peer_count_ps == 27
    assert len(result.warnings) == 3


class _FakeXtData:
    def __init__(self) -> None:
        self.price_calls = []
        self.financial_calls = []

    def get_market_data_ex(
        self,
        field_list,
        stock_list,
        period,
        start_time,
        end_time,
        count,
        dividend_type,
        fill_data,
    ):
        self.price_calls.append(tuple(stock_list))
        return {
            symbol: pd.DataFrame([{"time": end_time, "close": 10 + index}])
            for index, symbol in enumerate(stock_list)
        }

    def get_instrument_detail(self, symbol: str):
        return {
            "InstrumentName": f"Name {symbol}",
            "TotalVolume": 100,
            "FloatVolume": 80,
        }

    def get_financial_data(self, symbols, tables, start, end, report_type):
        self.financial_calls.append((tuple(symbols), start, end, report_type))
        return {
            symbol: {
                "Income": pd.DataFrame(
                    [{"m_timetag": "20251231", "revenue": 500, "net_profit": 100}]
                ),
                "PershareIndex": pd.DataFrame(
                    [{"m_timetag": "20251231", "bps": 5}]
                ),
            }
            for symbol in symbols
        }


def test_qmt_peer_valuation_loader_batches_and_normalizes(monkeypatch):
    fake_xtdata = _FakeXtData()
    monkeypatch.setattr(peer_loader_module, "_import_xtdata", lambda: fake_xtdata)
    monkeypatch.setattr(peer_loader_module, "connect_qmt", lambda: None)

    loader = QMTPeerValuationLoader(chunk_size=1)
    peers = loader.load_peer_inputs(
        ["600001.SH", "600002.SH", "600001.SH"],
        as_of="2026-05-12",
    )

    assert len(peers) == 2
    assert fake_xtdata.price_calls == [("600001.SH",), ("600002.SH",)]
    assert fake_xtdata.financial_calls[0][2] == "20260512"
    assert peers[0]["symbol"] == "600001.SH"
    assert peers[0]["asset_type"] == "stock"
    assert peers[0]["close"] == 10
    assert peers[0]["total_volume"] == 100
    assert peers[0]["float_volume"] == 80
    assert peers[0]["net_profit_ttm"] == 100
    assert peers[0]["revenue_ttm"] == 500
    assert peers[0]["bps"] == 5
    assert peers[0]["is_suspended"] is False


class _IndustryProviderWithMembers:
    def __init__(self, members: list[str]) -> None:
        self.members = members

    def resolve_industry(self, symbol: str, level: str = "SW1", as_of: str | None = None):
        return ProviderResult(
            provider="qmt",
            dataset="industry_sector",
            symbol=symbol,
            as_of=as_of or "2026-05-12",
            data={
                "industry_level": level,
                "industry_name": "SW1 Test",
                "industry_members": self.members,
                "peer_count": len(self.members),
            },
            raw={},
            metadata=ProviderMetadata(success=True),
        )


class _PeerValuationLoaderWithMembers:
    def __init__(self) -> None:
        self.calls = []

    def load_peer_inputs(self, symbols, as_of: str | None = None):
        self.calls.append((list(symbols), as_of))
        peers = []
        for index, symbol in enumerate(symbols):
            peers.append(
                {
                    "symbol": symbol,
                    "name": symbol,
                    "asset_type": "stock",
                    "close": 10,
                    "total_volume": 100,
                    "float_volume": 80,
                    "net_profit_ttm": 1000 / (index + 1),
                    "revenue_ttm": 500,
                    "bps": 10 / (index + 1),
                }
            )
        return peers


def test_industry_valuation_service_loads_qmt_peer_inputs_by_default():
    members = [f"600{i:03d}.SH" for i in range(25)]
    peer_loader = _PeerValuationLoaderWithMembers()
    service = IndustryValuationService(
        industry_provider=_IndustryProviderWithMembers(members),
        peer_valuation_loader=peer_loader,
    )

    result = service.build(
        asset_data={"symbol": "600010.SH", "asset_type": "stock", "as_of": "2026-05-12"},
        valuation_data={},
    )

    fields = result["fields"]
    assert peer_loader.calls == [(members, "2026-05-12")]
    assert fields["industry_valid_peer_count_pe"] == 25
    assert fields["industry_valid_peer_count_pb"] == 25
    assert fields["industry_pe_percentile"] is not None
    assert fields["industry_valuation_warnings"] == []
    assert result["provider_run_log"][0]["status"] == "success"


def test_evidence_builder_adds_industry_valuation_items():
    asset_data = {
        "symbol": "600010.SH",
        "as_of": "2026-05-12",
        "asset_type": "stock",
        "price_data": {"close": 10},
        "fundamental_data": {},
        "valuation_data": {
            "pe_ttm": 12,
            "industry_name": "SW1 Test",
            "industry_peer_count": 25,
            "industry_valid_peer_count": 24,
            "industry_valid_peer_count_pe": 24,
            "industry_valid_peer_count_pb": 23,
            "industry_valid_peer_count_ps": 22,
            "industry_pe_percentile": 0.30,
            "industry_pb_percentile": 0.40,
            "industry_ps_percentile": None,
            "industry_valuation_label": "industry_reasonable",
            "industry_valuation_source": "qmt_sector+qmt_financial+qmt_price",
        },
        "event_data": {},
        "source_metadata": {
            "valuation_data": {
                "source": "qmt_derived",
                "as_of": "2026-05-12",
                "confidence": 0.78,
            }
        },
    }

    bundle = EvidenceBuilder().build(asset_data)
    by_id = {item["evidence_id"]: item for item in bundle["items"]}

    pe_item = by_id["ev_val_industry_pe_percentile"]
    assert pe_item["display_value"] == "30.0%"
    assert pe_item["source"] == "qmt_sector+qmt_financial+qmt_price"
    assert by_id["ev_val_industry_peer_count"]["display_value"] == "25"
    assert by_id["ev_val_industry_valuation_label"]["display_value"] == "industry_reasonable"
    assert "ev_val_industry_ps_percentile" not in by_id


class _StubNormalizer:
    def derive_from_qmt(self, asset_data: dict) -> dict:
        return {
            "pe_ttm": 10,
            "pb_mrq": 2,
            "ps_ttm": 3,
            "market_cap": 1000,
            "valuation_label": "derived_no_percentile",
        }


class _SuccessfulIndustryService:
    def build(self, asset_data: dict, valuation_data: dict) -> dict:
        return {
            "fields": {
                "industry_level": "SW1",
                "industry_name": "SW1 Test",
                "industry_peer_count": 30,
                "industry_valid_peer_count": 25,
                "industry_valid_peer_count_pe": 25,
                "industry_valid_peer_count_pb": 26,
                "industry_valid_peer_count_ps": 27,
                "industry_pe_percentile": 0.3,
                "industry_pb_percentile": 0.4,
                "industry_ps_percentile": 0.5,
                "industry_valuation_label": "industry_reasonable",
                "industry_valuation_source": "qmt_sector+qmt_financial+qmt_price",
                "industry_valuation_warnings": [],
            },
            "provider_run_log": [
                {
                    "provider": "qmt",
                    "dataset": "industry_valuation",
                    "symbol": asset_data["symbol"],
                    "status": "success",
                    "rows": 30,
                    "error": None,
                    "error_type": None,
                    "as_of": asset_data.get("as_of"),
                }
            ],
        }


class _FailingIndustryService:
    def build(self, asset_data: dict, valuation_data: dict) -> dict:
        raise ProviderDataQualityError("industry peer inputs unavailable")


def _asset_for_valuation_service(asset_type: str = "stock") -> dict:
    return {
        "symbol": "600001.SH",
        "name": "Test Stock",
        "asset_type": asset_type,
        "data_source": "qmt",
        "as_of": "2026-05-12",
        "symbol_info": {"qmt_code": "600001.SH"},
        "price_data": {"close": 10},
        "basic_info": {"total_volume": 100},
        "fundamental_data": {
            "net_profit_ttm": 100,
            "revenue_ttm": 300,
            "bps": 5,
        },
    }


def test_valuation_service_merges_industry_fields():
    service = ValuationService(
        normalizer=_StubNormalizer(),
        industry_service=_SuccessfulIndustryService(),
    )

    result = service.build(_asset_for_valuation_service())
    valuation = result["data"]["valuation_data"]

    assert valuation["pe_ttm"] == 10
    assert valuation["industry_name"] == "SW1 Test"
    assert valuation["industry_valid_peer_count_pe"] == 25
    assert valuation["industry_valuation_label"] == "industry_reasonable"
    assert any(
        item["dataset"] == "industry_valuation" and item["status"] == "success"
        for item in result["provider_run_log"]
    )


def test_valuation_service_records_industry_failure_without_blocking_base_valuation():
    service = ValuationService(
        normalizer=_StubNormalizer(),
        industry_service=_FailingIndustryService(),
    )

    result = service.build(_asset_for_valuation_service())
    valuation = result["data"]["valuation_data"]

    assert valuation["pe_ttm"] == 10
    assert valuation["market_cap"] == 1000
    assert "industry peer inputs unavailable" in valuation["industry_valuation_warnings"]
    assert any(
        item["dataset"] == "industry_valuation"
        and item["status"] == "failed"
        and item["error_type"] == "provider_data_quality"
        for item in result["provider_run_log"]
    )
