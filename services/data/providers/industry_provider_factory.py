from __future__ import annotations

import os

from services.data.providers.local_csmar_industry_provider import LocalCSMARIndustryProvider


class DisabledIndustryProvider:
    provider = "disabled"
    dataset = "industry_sector"

    def resolve_industry(self, symbol: str, level: str = "disabled", as_of: str | None = None):
        from services.data.provider_contracts import (
            ProviderMetadata,
            ProviderResult,
        )

        return ProviderResult(
            provider=self.provider,
            dataset=self.dataset,
            symbol=symbol,
            as_of=as_of or "",
            data={},
            raw={},
            metadata=ProviderMetadata(
                success=False,
                error="Industry classification is disabled.",
                error_type="provider_unavailable",
            ),
        )


def create_industry_provider():
    provider = os.getenv("INDUSTRY_CLASSIFICATION_PROVIDER", "local_csmar").strip().lower()
    if provider == "local_csmar":
        return LocalCSMARIndustryProvider()
    if provider == "qmt":
        if not os.getenv("QMT_INDUSTRY_PROVIDER_EXPERIMENTAL", "").strip().lower() == "true":
            raise ValueError(
                "QMT sector fallback is disabled by default. "
                "Set INDUSTRY_CLASSIFICATION_PROVIDER=local_csmar (recommended) or "
                "INDUSTRY_CLASSIFICATION_PROVIDER=disabled. "
                "If you explicitly need the legacy QMT sector provider, set "
                "QMT_INDUSTRY_PROVIDER_EXPERIMENTAL=true alongside "
                "INDUSTRY_CLASSIFICATION_PROVIDER=qmt."
            )
        from services.data.providers.qmt_industry_provider import QMTIndustryProvider

        return QMTIndustryProvider()
    if provider == "disabled":
        return DisabledIndustryProvider()
    raise ValueError(f"Unsupported INDUSTRY_CLASSIFICATION_PROVIDER={provider!r}")
