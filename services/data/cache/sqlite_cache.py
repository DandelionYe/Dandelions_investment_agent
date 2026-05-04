import hashlib
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


DEFAULT_CACHE_PATH = Path("storage/cache/research_data.sqlite")


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


class ResearchDataCache:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path or os.getenv("RESEARCH_CACHE_DB", DEFAULT_CACHE_PATH))

    def enabled(self) -> bool:
        return os.getenv("RESEARCH_CACHE_ENABLED", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
            "on",
        }

    def store_run(self, asset_data: dict) -> None:
        if not self.enabled():
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            self._init_schema(conn)
            run_id = self._run_id(asset_data)
            self._upsert_symbol(conn, asset_data)
            self._insert_provider_logs(conn, run_id, asset_data)
            self._insert_raw_response_snapshot(conn, run_id, asset_data)
            if asset_data.get("asset_type") == "stock":
                self._upsert_fundamental(conn, asset_data)
                self._upsert_valuation(conn, asset_data)
            self._upsert_events(conn, asset_data)

    def _run_id(self, asset_data: dict) -> str:
        seed = f"{asset_data.get('symbol')}|{asset_data.get('as_of')}|{_now()}"
        return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            create table if not exists symbol_map (
                symbol text primary key,
                plain_code text,
                exchange text,
                asset_type text,
                name text,
                updated_at text
            );

            create table if not exists raw_provider_response (
                id integer primary key autoincrement,
                provider text,
                dataset text,
                symbol text,
                request_params_hash text,
                raw_json text,
                success integer,
                error text,
                created_at text
            );

            create table if not exists fundamental_snapshot (
                symbol text,
                report_period text,
                ann_date text,
                roe real,
                gross_margin real,
                net_margin real,
                revenue_growth real,
                net_profit_growth real,
                debt_ratio real,
                operating_cashflow_quality real,
                source text,
                confidence real,
                updated_at text,
                primary key (symbol, report_period, source)
            );

            create table if not exists valuation_snapshot (
                symbol text,
                trade_date text,
                pe_ttm real,
                pb_mrq real,
                ps_ttm real,
                dividend_yield real,
                market_cap real,
                pe_percentile real,
                pb_percentile real,
                source text,
                confidence real,
                updated_at text,
                primary key (symbol, trade_date, source)
            );

            create table if not exists event_item (
                event_id text primary key,
                symbol text,
                event_type text,
                title text,
                publish_time text,
                source text,
                url text,
                severity text,
                sentiment text,
                summary text,
                dedupe_key text,
                confidence real,
                updated_at text
            );

            create table if not exists provider_run_log (
                id integer primary key autoincrement,
                run_id text,
                symbol text,
                provider text,
                dataset text,
                start_time text,
                end_time text,
                status text,
                error text,
                rows integer
            );
            """
        )

    def _upsert_symbol(self, conn: sqlite3.Connection, asset_data: dict) -> None:
        info = asset_data.get("symbol_info", {})
        conn.execute(
            """
            insert into symbol_map(symbol, plain_code, exchange, asset_type, name, updated_at)
            values (?, ?, ?, ?, ?, ?)
            on conflict(symbol) do update set
                plain_code=excluded.plain_code,
                exchange=excluded.exchange,
                asset_type=excluded.asset_type,
                name=excluded.name,
                updated_at=excluded.updated_at
            """,
            (
                asset_data.get("symbol"),
                info.get("plain_code"),
                info.get("exchange"),
                asset_data.get("asset_type"),
                asset_data.get("name"),
                _now(),
            ),
        )

    def _insert_provider_logs(self, conn: sqlite3.Connection, run_id: str, asset_data: dict) -> None:
        for row in asset_data.get("provider_run_log", []):
            conn.execute(
                """
                insert into provider_run_log(
                    run_id, symbol, provider, dataset, start_time, end_time, status, error, rows
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    row.get("symbol", asset_data.get("symbol")),
                    row.get("provider"),
                    row.get("dataset"),
                    row.get("start_time", row.get("as_of")),
                    row.get("end_time", row.get("as_of")),
                    row.get("status"),
                    row.get("error"),
                    row.get("rows"),
                ),
            )

    def _insert_raw_response_snapshot(self, conn: sqlite3.Connection, run_id: str, asset_data: dict) -> None:
        payload = {
            "source_metadata": asset_data.get("source_metadata", {}),
            "data_quality": asset_data.get("data_quality", {}),
            "evidence_bundle": asset_data.get("evidence_bundle", {}),
        }
        conn.execute(
            """
            insert into raw_provider_response(
                provider, dataset, symbol, request_params_hash, raw_json, success, error, created_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "aggregator",
                "research_data",
                asset_data.get("symbol"),
                run_id,
                _json(payload),
                1,
                None,
                _now(),
            ),
        )

    def _upsert_fundamental(self, conn: sqlite3.Connection, asset_data: dict) -> None:
        data = asset_data.get("fundamental_data", {})
        if not data:
            return
        metadata = asset_data.get("source_metadata", {}).get("fundamental_data", {})
        conn.execute(
            """
            insert into fundamental_snapshot(
                symbol, report_period, ann_date, roe, gross_margin, net_margin,
                revenue_growth, net_profit_growth, debt_ratio, operating_cashflow_quality,
                source, confidence, updated_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(symbol, report_period, source) do update set
                ann_date=excluded.ann_date,
                roe=excluded.roe,
                gross_margin=excluded.gross_margin,
                net_margin=excluded.net_margin,
                revenue_growth=excluded.revenue_growth,
                net_profit_growth=excluded.net_profit_growth,
                debt_ratio=excluded.debt_ratio,
                operating_cashflow_quality=excluded.operating_cashflow_quality,
                confidence=excluded.confidence,
                updated_at=excluded.updated_at
            """,
            (
                asset_data.get("symbol"),
                data.get("report_period", asset_data.get("as_of")),
                data.get("ann_date"),
                data.get("roe"),
                data.get("gross_margin"),
                data.get("net_margin"),
                data.get("revenue_growth"),
                data.get("net_profit_growth"),
                data.get("debt_ratio"),
                data.get("operating_cashflow_quality")
                if isinstance(data.get("operating_cashflow_quality"), (int, float))
                else None,
                metadata.get("source"),
                metadata.get("confidence"),
                _now(),
            ),
        )

    def _upsert_valuation(self, conn: sqlite3.Connection, asset_data: dict) -> None:
        data = asset_data.get("valuation_data", {})
        if not data:
            return
        metadata = asset_data.get("source_metadata", {}).get("valuation_data", {})
        conn.execute(
            """
            insert into valuation_snapshot(
                symbol, trade_date, pe_ttm, pb_mrq, ps_ttm, dividend_yield, market_cap,
                pe_percentile, pb_percentile, source, confidence, updated_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(symbol, trade_date, source) do update set
                pe_ttm=excluded.pe_ttm,
                pb_mrq=excluded.pb_mrq,
                ps_ttm=excluded.ps_ttm,
                dividend_yield=excluded.dividend_yield,
                market_cap=excluded.market_cap,
                pe_percentile=excluded.pe_percentile,
                pb_percentile=excluded.pb_percentile,
                confidence=excluded.confidence,
                updated_at=excluded.updated_at
            """,
            (
                asset_data.get("symbol"),
                data.get("trade_date", str(asset_data.get("as_of", "")).replace("-", "")),
                data.get("pe_ttm"),
                data.get("pb_mrq"),
                data.get("ps_ttm"),
                data.get("dividend_yield"),
                data.get("market_cap"),
                data.get("pe_percentile"),
                data.get("pb_percentile"),
                metadata.get("source"),
                metadata.get("confidence"),
                _now(),
            ),
        )

    def _upsert_events(self, conn: sqlite3.Connection, asset_data: dict) -> None:
        metadata = asset_data.get("source_metadata", {}).get("event_data", {})
        confidence = metadata.get("confidence")
        for event in asset_data.get("event_data", {}).get("events", []):
            conn.execute(
                """
                insert into event_item(
                    event_id, symbol, event_type, title, publish_time, source, url, severity,
                    sentiment, summary, dedupe_key, confidence, updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(event_id) do update set
                    title=excluded.title,
                    publish_time=excluded.publish_time,
                    severity=excluded.severity,
                    sentiment=excluded.sentiment,
                    summary=excluded.summary,
                    confidence=excluded.confidence,
                    updated_at=excluded.updated_at
                """,
                (
                    event.get("event_id"),
                    event.get("symbol", asset_data.get("symbol")),
                    event.get("event_type"),
                    event.get("title"),
                    event.get("publish_time"),
                    event.get("source"),
                    event.get("url"),
                    event.get("severity"),
                    event.get("sentiment"),
                    event.get("summary"),
                    event.get("dedupe_key"),
                    confidence,
                    _now(),
                ),
            )

    # ── read-back ──────────────────────────────────────────

    def get_latest_fundamental(self, symbol: str) -> dict | None:
        """Return the most recent fundamental snapshot from cache, or None."""
        if not self.enabled():
            return None
        if not self.db_path.exists():
            return None
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    """
                    select * from fundamental_snapshot
                    where symbol = ?
                    order by report_period desc, updated_at desc
                    limit 1
                    """,
                    (symbol,),
                ).fetchone()
            if row is None:
                return None
            cols = [
                "symbol", "report_period", "ann_date", "roe", "gross_margin",
                "net_margin", "revenue_growth", "net_profit_growth", "debt_ratio",
                "operating_cashflow_quality", "source", "confidence", "updated_at",
            ]
            return dict(zip(cols, row))
        except Exception:
            return None

    def get_latest_valuation(self, symbol: str) -> dict | None:
        """Return the most recent valuation snapshot from cache, or None."""
        if not self.enabled():
            return None
        if not self.db_path.exists():
            return None
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    """
                    select * from valuation_snapshot
                    where symbol = ?
                    order by trade_date desc, updated_at desc
                    limit 1
                    """,
                    (symbol,),
                ).fetchone()
            if row is None:
                return None
            cols = [
                "symbol", "trade_date", "pe_ttm", "pb_mrq", "ps_ttm",
                "dividend_yield", "market_cap", "pe_percentile", "pb_percentile",
                "source", "confidence", "updated_at",
            ]
            return dict(zip(cols, row))
        except Exception:
            return None

    def get_recent_events(self, symbol: str, since_days: int = 90) -> list[dict]:
        """Return recent cached events for a symbol."""
        if not self.enabled():
            return []
        if not self.db_path.exists():
            return []
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    """
                    select * from event_item
                    where symbol = ?
                    order by publish_time desc
                    limit 200
                    """,
                    (symbol,),
                ).fetchall()
            cols = [
                "event_id", "symbol", "event_type", "title", "publish_time",
                "source", "url", "severity", "sentiment", "summary",
                "dedupe_key", "confidence", "updated_at",
            ]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            return []
