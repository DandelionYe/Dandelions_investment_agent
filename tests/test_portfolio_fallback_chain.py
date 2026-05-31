"""Tests for portfolio research result fallback chain.

Verifies the priority-based loading logic in _load_research_results:
  Priority 1: result JSON file
  Priority 2: task summary + watchlist snapshot enrichment
  Priority 3: watchlist snapshot only
  Priority 4: missing (empty dict)

Also verifies that Priority 2 adds a data_quality warning when merging
task + snapshot data from different sources.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_task(symbol, score=None, rating=None, action=None,
               completed_at="2026-05-31T10:00:00", json_path=None):
    """Create a minimal task dict."""
    task = {
        "id": f"task_{symbol}",
        "symbol": symbol,
        "status": "completed",
        "completed_at": completed_at,
    }
    if score is not None:
        task["score"] = score
    if rating:
        task["rating"] = rating
    if action:
        task["action"] = action
    if json_path:
        task["report_paths"] = {"json": str(json_path)}
    else:
        task["report_paths"] = {}
    return task


def _make_snapshot_entry(score=None, valuation_data=None, risk_review=None,
                         event_data=None, updated_at="2026-05-28T08:00:00"):
    """Create a minimal watchlist snapshot map entry."""
    entry = {}
    if score is not None:
        entry["score"] = score
    if valuation_data:
        entry["valuation_data"] = valuation_data
    if risk_review:
        entry["risk_review"] = risk_review
    if event_data:
        entry["event_data"] = event_data
    entry["_snapshot_updated_at"] = updated_at
    return entry


class TestFallbackChain:
    """Test the Priority 1-4 fallback chain in _load_research_results."""

    def _call_under_test(self, positions, owner, wl_snapshot_map, tasks_by_symbol):
        """Call _load_research_results with mocked task store."""
        from apps.api.routers.portfolio import _load_research_results

        mock_task_store = MagicMock()

        def mock_list_tasks(symbol, status, username, page, page_size):
            tasks = tasks_by_symbol.get(symbol, [])
            return tasks, len(tasks)

        mock_task_store.list_tasks.side_effect = mock_list_tasks

        with patch("apps.api.routers.portfolio.get_task_store", return_value=mock_task_store):
            return _load_research_results(positions, owner, wl_snapshot_map)

    def test_priority1_result_json_file(self, tmp_path):
        """When a JSON result file exists, it should be used (Priority 1)."""
        json_file = tmp_path / "result.json"
        json_file.write_text('{"score": 85, "rating": "B+"}', encoding="utf-8")

        positions = [{"symbol": "A.SH"}]
        task = _make_task("A.SH", score=70, json_path=json_file)
        tasks_by_symbol = {"A.SH": [task]}
        wl_snapshot_map = {}

        results = self._call_under_test(positions, None, wl_snapshot_map, tasks_by_symbol)
        assert results["A.SH"]["score"] == 85  # From JSON file, not task

    def test_priority1_invalid_json_falls_back_to_priority2(self, tmp_path):
        """When a JSON file is malformed, fall through to Priority 2."""
        json_file = tmp_path / "corrupt.json"
        json_file.write_text("not valid json {{{", encoding="utf-8")

        positions = [{"symbol": "A.SH"}]
        task = _make_task("A.SH", score=75, rating="B", json_path=json_file)
        tasks_by_symbol = {"A.SH": [task]}
        wl_snapshot_map = {
            "A.SH": _make_snapshot_entry(
                valuation_data={"pe_percentile": 0.3},
                risk_review="低风险",
            )
        }

        results = self._call_under_test(positions, None, wl_snapshot_map, tasks_by_symbol)
        r = results["A.SH"]

        # Fallback confirmed: task score used, not corrupt file
        assert r["score"] == 75
        # Priority 2 merge semantics are covered by existing tests

    def test_priority1_unreadable_json_falls_back_to_priority2(self, tmp_path):
        """When a JSON file path doesn't exist, fall through to Priority 2."""
        json_file = tmp_path / "nonexistent.json"

        positions = [{"symbol": "A.SH"}]
        task = _make_task("A.SH", score=75, json_path=json_file)
        tasks_by_symbol = {"A.SH": [task]}
        wl_snapshot_map = {
            "A.SH": _make_snapshot_entry(score=60)
        }

        results = self._call_under_test(positions, None, wl_snapshot_map, tasks_by_symbol)
        r = results["A.SH"]

        # Fallback confirmed: task score overrides snapshot score
        assert r["score"] == 75  # From task, not snapshot's score=60

    def test_priority2_task_summary_enriched_by_snapshot(self):
        """When no JSON file, task summary is enriched with snapshot data (Priority 2)."""
        positions = [{"symbol": "A.SH"}]
        task = _make_task("A.SH", score=75, rating="B", action="观察")
        tasks_by_symbol = {"A.SH": [task]}
        wl_snapshot_map = {
            "A.SH": _make_snapshot_entry(
                score=60,  # Will be overwritten by task's score
                valuation_data={"pe_percentile": 0.3},
                risk_review="低风险",
                event_data={"events": []},
            )
        }

        results = self._call_under_test(positions, None, wl_snapshot_map, tasks_by_symbol)
        r = results["A.SH"]

        # Task's score/rating/action should take priority
        assert r["score"] == 75
        assert r["rating"] == "B"
        assert r["action"] == "观察"
        # Snapshot's enrichment data should be present
        assert r["valuation_data"] == {"pe_percentile": 0.3}
        assert r["risk_review"] == "低风险"
        assert r["event_data"] == {"events": []}

    def test_priority2_warns_on_mixed_sources(self):
        """Priority 2 should add a data_quality warning when merging task + snapshot."""
        positions = [{"symbol": "A.SH"}]
        task = _make_task("A.SH", score=75, completed_at="2026-05-31T10:00:00")
        tasks_by_symbol = {"A.SH": [task]}
        wl_snapshot_map = {
            "A.SH": _make_snapshot_entry(
                valuation_data={"pe_percentile": 0.3},
                updated_at="2026-05-28T08:00:00",
            )
        }

        results = self._call_under_test(positions, None, wl_snapshot_map, tasks_by_symbol)
        r = results["A.SH"]

        # Should have data_quality warning about mixed sources
        dq = r.get("data_quality", {})
        warnings = dq.get("warnings", [])
        assert len(warnings) > 0
        assert "混合来源" in warnings[0]
        assert "2026-05-31" in warnings[0]  # task timestamp
        assert "2026-05-28" in warnings[0]  # snapshot timestamp

    def test_priority2_no_warning_when_no_snapshot_enrichment(self):
        """When snapshot has no enrichment data, no warning should be added."""
        positions = [{"symbol": "A.SH"}]
        task = _make_task("A.SH", score=75)
        tasks_by_symbol = {"A.SH": [task]}
        # Snapshot only has score (same as what task provides), no enrichment
        wl_snapshot_map = {
            "A.SH": _make_snapshot_entry(score=60)
        }

        results = self._call_under_test(positions, None, wl_snapshot_map, tasks_by_symbol)
        r = results["A.SH"]

        # No data_quality warning because no enrichment data was merged
        assert "data_quality" not in r or "warnings" not in r.get("data_quality", {})

    def test_priority2_cleans_internal_metadata(self):
        """_snapshot_updated_at should be removed from the result."""
        positions = [{"symbol": "A.SH"}]
        task = _make_task("A.SH", score=75)
        tasks_by_symbol = {"A.SH": [task]}
        wl_snapshot_map = {
            "A.SH": _make_snapshot_entry(
                valuation_data={"pe_percentile": 0.3},
            )
        }

        results = self._call_under_test(positions, None, wl_snapshot_map, tasks_by_symbol)
        assert "_snapshot_updated_at" not in results["A.SH"]

    def test_priority3_watchlist_snapshot_only(self):
        """When no task exists, watchlist snapshot is used (Priority 3)."""
        positions = [{"symbol": "A.SH"}]
        tasks_by_symbol = {"A.SH": []}  # No tasks
        wl_snapshot_map = {
            "A.SH": _make_snapshot_entry(
                score=65, valuation_data={"pe_percentile": 0.5}
            )
        }

        results = self._call_under_test(positions, None, wl_snapshot_map, tasks_by_symbol)
        r = results["A.SH"]
        assert r["score"] == 65
        assert r["valuation_data"] == {"pe_percentile": 0.5}
        assert "_snapshot_updated_at" not in r

    def test_priority4_missing(self):
        """When no task and no snapshot, symbol is absent from results (Priority 4)."""
        positions = [{"symbol": "A.SH"}]
        tasks_by_symbol = {"A.SH": []}
        wl_snapshot_map = {}

        results = self._call_under_test(positions, None, wl_snapshot_map, tasks_by_symbol)
        assert "A.SH" not in results
