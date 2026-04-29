from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SymbolInfo:
    input_symbol: str
    normalized_symbol: str
    plain_code: str
    exchange: str
    market: str
    asset_type: str
    qmt_code: str
    tushare_code: str
    akshare_code: str
    eastmoney_code: str
    tx_code: str
    cninfo_code: str

    def to_dict(self) -> dict:
        return asdict(self)


class SymbolResolver:
    def resolve(self, symbol: str) -> dict:
        cleaned = symbol.strip().upper()
        plain_code, exchange = self._split_or_infer(cleaned)
        normalized = f"{plain_code}.{exchange}"
        asset_type = self._guess_asset_type(plain_code, exchange)
        exchange_lower = exchange.lower()

        return SymbolInfo(
            input_symbol=symbol,
            normalized_symbol=normalized,
            plain_code=plain_code,
            exchange=exchange,
            market="CN_A",
            asset_type=asset_type,
            qmt_code=normalized,
            tushare_code=normalized,
            akshare_code=plain_code,
            eastmoney_code=f"{exchange}{plain_code}",
            tx_code=f"{exchange_lower}{plain_code}",
            cninfo_code=plain_code,
        ).to_dict()

    def _split_or_infer(self, symbol: str) -> tuple[str, str]:
        if "." in symbol:
            plain_code, exchange = symbol.split(".", 1)
            if exchange not in {"SH", "SZ", "BJ"}:
                raise ValueError(f"不支持的交易所后缀：{exchange}")
            return plain_code, exchange

        plain_code = symbol

        if plain_code.startswith("6") or plain_code.startswith(("51", "56", "58")):
            return plain_code, "SH"
        if plain_code.startswith(("0", "3", "15", "16", "159")):
            return plain_code, "SZ"
        if plain_code.startswith(("8", "4")):
            return plain_code, "BJ"

        raise ValueError(f"无法推断交易所后缀，请使用 600519.SH 格式：{symbol}")

    def _guess_asset_type(self, plain_code: str, exchange: str) -> str:
        if exchange == "SH" and plain_code.startswith("5"):
            return "etf"
        if exchange == "SZ" and plain_code.startswith(("159", "16", "15")):
            return "etf"
        return "stock"
