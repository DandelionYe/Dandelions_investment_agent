"""QMT_INDUSTRY_AUTO_DOWNLOAD 默认行为测试。

验证行业数据自动下载默认关闭，不会在研究流程中阻塞。
"""

import pytest

from services.data.provider_contracts import (
    ProviderDataQualityError,
    ProviderMetadata,
    ProviderResult,
)
from services.data.providers import qmt_industry_provider as industry_module
from services.data.providers.qmt_industry_provider import QMTIndustryProvider
from services.research.industry_valuation_engine import IndustryValuationService


class _FakeXtDataSector:
    """模拟 xtdata，记录 download_sector_data 是否被调用。"""

    def __init__(self) -> None:
        self.download_called = False
        self._sectors = ["SW1_食品饮料", "SW1_银行", "SW1_医药生物"]

    def download_sector_data(self) -> None:
        self.download_called = True

    def get_sector_list(self) -> list[str]:
        return self._sectors

    def get_stock_list_in_sector(self, sector_name, real_timetag=-1):
        if sector_name == "SW1_食品饮料":
            return ["600519.SH", "000858.SZ", "000568.SZ"]
        return []


def test_download_sector_data_not_called_by_default(monkeypatch):
    """默认 QMT_INDUSTRY_AUTO_DOWNLOAD 未设置时，不应调用 download_sector_data。"""
    fake = _FakeXtDataSector()
    monkeypatch.setattr(industry_module, "_import_xtdata", lambda: fake)
    monkeypatch.setattr(industry_module, "connect_qmt", lambda: None)
    monkeypatch.delenv("QMT_INDUSTRY_AUTO_DOWNLOAD", raising=False)

    provider = QMTIndustryProvider()
    result = provider.resolve_industry(symbol="600519.SH", level="SW1")

    assert fake.download_called is False
    assert result.metadata.success is True
    assert "600519.SH" in result.data["industry_members"]


def test_download_sector_data_not_called_when_explicitly_false(monkeypatch):
    """QMT_INDUSTRY_AUTO_DOWNLOAD=false 时，不应调用 download_sector_data。"""
    fake = _FakeXtDataSector()
    monkeypatch.setattr(industry_module, "_import_xtdata", lambda: fake)
    monkeypatch.setattr(industry_module, "connect_qmt", lambda: None)
    monkeypatch.setenv("QMT_INDUSTRY_AUTO_DOWNLOAD", "false")

    provider = QMTIndustryProvider()
    result = provider.resolve_industry(symbol="600519.SH", level="SW1")

    assert fake.download_called is False
    assert result.metadata.success is True


def test_download_sector_data_called_when_explicitly_true(monkeypatch, capsys):
    """QMT_INDUSTRY_AUTO_DOWNLOAD=true 时，应调用 download_sector_data 并打印警告。"""
    fake = _FakeXtDataSector()
    monkeypatch.setattr(industry_module, "_import_xtdata", lambda: fake)
    monkeypatch.setattr(industry_module, "connect_qmt", lambda: None)
    monkeypatch.setenv("QMT_INDUSTRY_AUTO_DOWNLOAD", "true")

    provider = QMTIndustryProvider()
    result = provider.resolve_industry(symbol="600519.SH", level="SW1")

    assert fake.download_called is True
    assert result.metadata.success is True
    captured = capsys.readouterr()
    assert "WARNING" in captured.out
    assert "download_sector_data" in captured.out


def test_industry_valuation_service_graceful_on_provider_failure(monkeypatch):
    """行业估值 provider 失败时，不应阻塞主流程。"""

    class _FailingIndustryProvider:
        def resolve_industry(self, symbol, level="SW1", as_of=None):
            raise ProviderDataQualityError("QMT industry sector data unavailable")

    service = IndustryValuationService(
        industry_provider=_FailingIndustryProvider(),
    )

    with pytest.raises(ProviderDataQualityError):
        service.build(
            asset_data={"symbol": "600519.SH", "asset_type": "stock", "as_of": "2026-05-19"},
            valuation_data={"pe_ttm": 30, "market_cap": 20000},
        )
