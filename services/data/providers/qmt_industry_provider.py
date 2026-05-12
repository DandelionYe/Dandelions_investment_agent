from datetime import date
from time import perf_counter

from services.data.provider_contracts import (
    ProviderDataQualityError,
    ProviderMetadata,
    ProviderResult,
    ProviderSchemaError,
    ProviderUnavailableError,
    get_provider_error_type,
)
from services.data.qmt_provider import _env_bool, _import_xtdata, connect_qmt


class QMTIndustryProvider:
    provider = "qmt"
    dataset = "industry_sector"

    def download_sector_data(self) -> None:
        xtdata = _import_xtdata()
        try:
            download = getattr(xtdata, "download_sector_data", None)
            if callable(download):
                download()
        except Exception as exc:
            raise ProviderUnavailableError(f"QMT sector data download failed: {exc}") from exc

    def list_sectors(self, level: str = "SW1") -> list[str]:
        xtdata = _import_xtdata()
        try:
            connect_qmt()
            if _env_bool("QMT_INDUSTRY_AUTO_DOWNLOAD", True):
                self.download_sector_data()
            sectors = xtdata.get_sector_list()
        except ProviderUnavailableError:
            raise
        except Exception as exc:
            raise ProviderUnavailableError(f"QMT sector list query failed: {exc}") from exc

        if not isinstance(sectors, (list, tuple, set)):
            raise ProviderSchemaError(
                f"QMT sector list must be list-like, got {type(sectors).__name__}"
            )

        sector_names = [str(item) for item in sectors if item]
        level = (level or "SW1").upper()
        level_matches = [
            name for name in sector_names
            if name.upper().startswith(level) or level in name.upper()
        ]
        return level_matches or sector_names

    def get_sector_members(
        self,
        sector_name: str,
        as_of: str | None = None,
    ) -> list[str]:
        xtdata = _import_xtdata()
        real_timetag = -1 if as_of is None else self._to_real_timetag(as_of)
        try:
            connect_qmt()
            members = xtdata.get_stock_list_in_sector(
                sector_name,
                real_timetag=real_timetag,
            )
        except TypeError:
            try:
                members = xtdata.get_stock_list_in_sector(sector_name)
            except Exception as exc:
                raise ProviderUnavailableError(
                    f"QMT sector member query failed for {sector_name}: {exc}"
                ) from exc
        except Exception as exc:
            raise ProviderUnavailableError(
                f"QMT sector member query failed for {sector_name}: {exc}"
            ) from exc

        if not isinstance(members, (list, tuple, set)):
            raise ProviderSchemaError(
                f"QMT sector members must be list-like, got {type(members).__name__}"
            )

        return [str(item) for item in members if item]

    def resolve_industry(
        self,
        symbol: str,
        level: str = "SW1",
        as_of: str | None = None,
    ) -> ProviderResult:
        started = perf_counter()
        resolved_as_of = as_of or str(date.today())

        try:
            sectors = self.list_sectors(level=level)
            for sector_name in sectors:
                members = self.get_sector_members(sector_name, as_of=as_of)
                if symbol in members:
                    if not members:
                        raise ProviderDataQualityError(
                            f"QMT industry sector has no members: {sector_name}"
                        )
                    payload = {
                        "industry_level": level,
                        "industry_name": sector_name,
                        "industry_members": members,
                        "peer_count": len(members),
                    }
                    return ProviderResult(
                        provider=self.provider,
                        dataset=self.dataset,
                        symbol=symbol,
                        as_of=resolved_as_of,
                        data=payload,
                        raw={},
                        metadata=ProviderMetadata(
                            success=True,
                            latency_ms=int((perf_counter() - started) * 1000),
                        ),
                    )
        except (ProviderUnavailableError, ProviderSchemaError, ProviderDataQualityError):
            raise
        except Exception as exc:
            raise ProviderSchemaError(
                f"QMT industry response cannot be normalized for {symbol}: {exc}"
            ) from exc

        error = ProviderDataQualityError(
            f"QMT industry could not resolve sector for {symbol} at level {level}"
        )
        return ProviderResult(
            provider=self.provider,
            dataset=self.dataset,
            symbol=symbol,
            as_of=resolved_as_of,
            data={},
            raw={},
            metadata=ProviderMetadata(
                success=False,
                error=str(error),
                error_type=get_provider_error_type(error),
                latency_ms=int((perf_counter() - started) * 1000),
            ),
        )

    @staticmethod
    def _to_real_timetag(as_of: str) -> int:
        compact = as_of.replace("-", "").strip()
        if len(compact) != 8 or not compact.isdigit():
            raise ProviderSchemaError(f"Invalid QMT industry as_of date: {as_of}")
        return int(compact)
