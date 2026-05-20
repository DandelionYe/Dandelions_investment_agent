import pandas as pd

from scripts.build_csmar_industry_reference import load_and_clean, write_sqlite
from services.data.providers.local_csmar_industry_provider import LocalCSMARIndustryProvider
from services.research.industry_valuation_engine import IndustryValuationService

REQUIRED_ROW_DEFAULTS = {
    "Listdt": "2020/1/1",
    "Cuntrycd": "10",
    "Conme": "Company",
    "Conme_en": "Company",
    "Indcd": "1",
    "Indnme": "Old",
    "Nindcd": "C",
    "Nindnme": "Manufacturing",
    "Nnindcd": "C15",
    "Nnindnme": "Beverage",
    "IndcdZX": "C15",
    "IndnmeZX": "Beverage",
    "Estbdt": "2020/1/1",
    "PROVINCE": "Test",
    "PROVINCECODE": "000000",
    "CITY": "Test City",
    "CITYCODE": "000000",
    "OWNERSHIPTYPE": "Private",
    "OWNERSHIPTYPECODE": "P",
    "Favaldt": "2020/1/1",
    "Curtrd": "CNY",
    "Ipoprm": "0",
    "Ipoprc": "1",
    "Ipocur": "CNY",
    "Nshripo": "1",
    "Parvcur": "CNY",
    "Ipodt": "2020/1/1",
    "Parval": "1",
    "Crcd": "",
    "Statdt": "2026/1/1",
    "Commnt": "",
    "FormerCode": "",
}


def _row(**overrides):
    row = dict(REQUIRED_ROW_DEFAULTS)
    row.update(overrides)
    return row


def _build_reference(tmp_path):
    csv_path = tmp_path / "TRD_Co.csv"
    db_path = tmp_path / "csmar_industry.sqlite"
    rows = [
        _row(Stkcd="600519", Stknme="Moutai", Sctcd="1", Statco="A", Markettype="1"),
        _row(Stkcd="858", Stknme="Wuliangye", Sctcd="2", Statco="A", Markettype="4"),
        _row(
            Stkcd="4",
            Stknme="Special",
            Sctcd="2",
            Statco="N",
            Markettype="4",
            IndcdZX="I65",
            IndnmeZX="Software",
            Nnindcd="I65",
            Nnindnme="Software",
        ),
        _row(Stkcd="3", Stknme="Delisted", Sctcd="2", Statco="D", Markettype="4"),
        _row(Stkcd="900001", Stknme="B Share", Sctcd="1", Statco="A", Markettype="2"),
    ]
    pd.DataFrame(rows).to_csv(csv_path, index=False, encoding="utf-8-sig")
    securities, members, stats = load_and_clean(
        input_path=csv_path,
        universe="sh_sz_bj",
        include_status={"A", "N"},
    )
    write_sqlite(db_path, securities, members, stats["metadata"])
    return db_path, securities


def test_build_csmar_reference_filters_and_normalizes_symbols(tmp_path):
    _, securities = _build_reference(tmp_path)

    assert set(securities["symbol"]) == {"600519.SH", "000858.SZ", "000004.SZ"}
    assert securities.loc[securities["symbol"] == "000004.SZ", "status_code"].item() == "N"
    assert "000003.SZ" not in set(securities["symbol"])
    assert "900001.SH" not in set(securities["symbol"])


def test_local_csmar_provider_resolves_members(tmp_path):
    db_path, _ = _build_reference(tmp_path)
    provider = LocalCSMARIndustryProvider(db_path=db_path, min_peers=1)

    result = provider.resolve_industry("600519.SH")

    assert result.metadata.success is True
    assert result.data["industry_level"] == "CSMAR_ZX"
    assert result.data["industry_code"] == "C15"
    assert result.data["industry_name"] == "Beverage"
    assert result.data["industry_members"] == ["000858.SZ", "600519.SH"]
    assert result.data["source"] == "local_csmar_trd_co"


class _PeerLoader:
    def load_peer_inputs(self, symbols, as_of=None):
        return [
            {
                "symbol": symbol,
                "name": symbol,
                "asset_type": "stock",
                "close": 10,
                "total_volume": 100,
                "float_volume": 80,
                "net_profit_ttm": 100,
                "revenue_ttm": 500,
                "bps": 5,
            }
            for symbol in symbols
        ]


def test_industry_service_uses_local_provider_factory(tmp_path, monkeypatch):
    db_path, _ = _build_reference(tmp_path)
    monkeypatch.setenv("INDUSTRY_CLASSIFICATION_PROVIDER", "local_csmar")
    monkeypatch.setenv("LOCAL_CSMAR_INDUSTRY_DB", str(db_path))
    monkeypatch.setenv("LOCAL_CSMAR_INDUSTRY_MIN_PEERS", "1")
    monkeypatch.setenv("INDUSTRY_MIN_VALID_PEERS", "1")
    monkeypatch.setenv("QMT_PEER_CACHE_PREFLIGHT", "false")

    service = IndustryValuationService(peer_valuation_loader=_PeerLoader())
    result = service.build(
        asset_data={"symbol": "600519.SH", "asset_type": "stock", "as_of": "2026-05-20"},
        valuation_data={},
    )

    fields = result["fields"]
    assert fields["industry_name"] == "Beverage"
    assert fields["industry_peer_count"] == 2
    assert fields["industry_valuation_source"] == "local_csmar_trd_co+qmt_financial+qmt_price"
    assert fields["industry_pe_percentile"] is not None
