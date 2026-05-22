"""Phase 2B: QMT 真实历史回测集成测试。

仅在 RUN_HISTORICAL_QMT_BACKTEST=1 时运行。
需要 MiniQMT 在后台运行。

Usage:
    set RUN_HISTORICAL_QMT_BACKTEST=1
    pytest tests/test_historical_qmt_integration.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SKIP_REASON = os.getenv("RUN_HISTORICAL_QMT_BACKTEST") != "1"

pytestmark = pytest.mark.skipif(
    SKIP_REASON,
    reason="需要 RUN_HISTORICAL_QMT_BACKTEST=1 和 MiniQMT 运行",
)


# ── QMT 连通性 ──────────────────────────────────────────────────

class TestQMTConnectivity:

    def test_xtdata_importable(self):
        from xtquant import xtdata  # type: ignore[import-untyped]
        assert xtdata is not None

    def test_check_qmt_available(self):
        from services.research.historical_sample_builder import check_qmt_available
        available, msg = check_qmt_available()
        assert available, f"QMT 不可用: {msg}"

    def test_fetch_daily_kline(self):
        from services.research.historical_sample_builder import fetch_daily_kline
        df = fetch_daily_kline("600519.SH", "2024-01-01", "2024-03-01")
        assert not df.empty
        assert "close" in df.columns
        assert "volume" in df.columns


# ── 股票池 ──────────────────────────────────────────────────

class TestSymbolPool:

    def test_get_mainboard_symbols(self):
        from services.research.historical_sample_builder import (
            get_mainboard_a_symbols_from_qmt,
            is_mainboard_a,
        )
        symbols = get_mainboard_a_symbols_from_qmt()
        assert len(symbols) > 100, f"主板 A 股数量不足: {len(symbols)}"
        # 所有返回的 symbol 都应是主板
        for sym in symbols[:20]:
            assert is_mainboard_a(sym), f"{sym} 不是主板"


# ── 真实样本构建 ──────────────────────────────────────────────

class TestRealSampleBuild:

    @pytest.fixture(scope="class")
    def build_result(self):
        from services.research.historical_sample_builder import try_build_from_qmt
        result = try_build_from_qmt(
            symbols=["600519.SH", "000001.SZ", "601318.SH"],
            start_year=2023,
            end_year=2024,
            max_samples=10,
        )
        return result

    def test_build_returns_result(self, build_result):
        assert build_result is not None
        assert "samples" in build_result
        assert "source" in build_result

    def test_samples_have_qmt_source(self, build_result):
        source = build_result["source"]
        assert source["price"] == "qmt_xtdata"

    def test_samples_have_provenance(self, build_result):
        for sample in build_result["samples"]:
            sm = sample["input_result"]["source_metadata"]
            assert sm["price_source"] == "qmt_xtdata"

    def test_forward_metrics_not_all_none(self, build_result):
        has_non_none = False
        for sample in build_result["samples"]:
            fm = sample["forward_metrics"]
            if fm.get("return_20d") is not None:
                has_non_none = True
                break
        assert has_non_none, "所有 forward metrics 都为 None"

    def test_at_least_one_sample(self, build_result):
        assert len(build_result["samples"]) >= 1


# ── 端到端构建脚本 ──────────────────────────────────────────────

class TestEndToEndBuild:

    def test_build_script_runs(self):
        """运行构建脚本并验证输出。"""
        output_path = PROJECT_ROOT / "storage" / "test_artifacts" / "qmt_test_samples.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "build_historical_research_samples.py"),
                "--use-qmt",
                "--output", str(output_path.relative_to(PROJECT_ROOT)),
                "--max-samples", "5",
                "--start-year", "2023",
                "--end-year", "2024",
                "--overwrite",
            ],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            pytest.fail(
                f"构建脚本失败 (exit {result.returncode}):\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )

        assert output_path.exists(), "输出文件未生成"

        data = json.loads(output_path.read_text(encoding="utf-8"))
        assert "source" in data
        assert data["source"]["price"] == "qmt_xtdata"
        assert len(data["samples"]) >= 1

        # 清理
        output_path.unlink(missing_ok=True)


# ── 边界股票覆盖 ──────────────────────────────────────────────

class TestBoundaryStockCoverage:

    def test_boundary_stocks_either_included_or_skipped(self):
        """所有 13 个边界股票必须在结果中出现（included 或 skipped）。"""
        from services.research.historical_sample_builder import (
            BOUNDARY_SYMBOLS,
            try_build_from_qmt,
        )
        result = try_build_from_qmt(
            symbols=BOUNDARY_SYMBOLS,
            start_year=2023,
            end_year=2024,
            max_samples=50,
        )
        if result is None:
            pytest.skip("QMT 不可用")

        included = set(result.get("included", []))
        skipped = {s["symbol"] for s in result.get("skipped", [])}
        covered = included | skipped

        for sym in BOUNDARY_SYMBOLS:
            assert sym in covered, f"边界股票 {sym} 既不在 included 也不在 skipped 中"
