"""P2 Phase 6: baseline 配置契约测试。

覆盖：
- baseline JSON 可加载
- 所有 component 有 metrics
- metric 有 severity
- enabled 字段存在
- default_enabled=false 的有 opt_in_reason
- artifact_path 指向的文件存在（对 enabled=true 且有 artifact_path 的）
"""

import json
from pathlib import Path

from services.research.quality_governance import validate_baseline_schema

BASELINE_PATH = Path(__file__).resolve().parent.parent / "configs" / "research_quality_baseline.json"


def _load_baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


class TestBaselineContract:

    def test_baseline_loads(self):
        data = _load_baseline()
        assert "version" in data
        assert "components" in data

    def test_schema_valid(self):
        data = _load_baseline()
        errors = validate_baseline_schema(data)
        assert errors == []

    def test_all_components_have_metrics(self):
        data = _load_baseline()
        for name, comp in data["components"].items():
            assert "metrics" in comp, f"{name} 缺少 metrics"
            assert len(comp["metrics"]) > 0, f"{name} metrics 为空"

    def test_all_metrics_have_severity(self):
        data = _load_baseline()
        for name, comp in data["components"].items():
            for metric_path, rule in comp["metrics"].items():
                assert "severity" in rule, f"{name}.{metric_path} 缺少 severity"
                assert rule["severity"] in ("blocker", "warning", "watch"), \
                    f"{name}.{metric_path} severity={rule['severity']}"

    def test_all_components_have_enabled(self):
        data = _load_baseline()
        for name, comp in data["components"].items():
            assert "enabled" in comp, f"{name} 缺少 enabled"

    def test_disabled_components_have_opt_in_reason(self):
        data = _load_baseline()
        for name, comp in data["components"].items():
            if comp.get("default_enabled") is False or comp.get("enabled") is False:
                assert "opt_in_reason" in comp, \
                    f"{name} default_enabled=false 但缺少 opt_in_reason"

    def test_enabled_artifacts_exist(self):
        """对 enabled=true 且有 artifact_path 的 component，验证文件存在。"""
        data = _load_baseline()
        project_root = BASELINE_PATH.parent.parent
        for name, comp in data["components"].items():
            if not comp.get("enabled", True):
                continue
            artifact_path = comp.get("artifact_path")
            if artifact_path is None:
                continue
            full_path = project_root / artifact_path
            assert full_path.exists(), \
                f"{name} artifact_path={artifact_path} 不存在"

    def test_metric_paths_are_strings(self):
        data = _load_baseline()
        for name, comp in data["components"].items():
            for metric_path in comp["metrics"]:
                assert isinstance(metric_path, str), \
                    f"{name} metric path 不是 string: {metric_path}"

    def test_expected_metrics_match_artifact_structure(self):
        """验证 baseline 中的 metric path 在对应 artifact 中能找到。

        可选指标（rule.optional=true）允许缺失。
        """
        from services.research.quality_governance import extract_metric
        data = _load_baseline()
        project_root = BASELINE_PATH.parent.parent
        for name, comp in data["components"].items():
            if not comp.get("enabled", True):
                continue
            artifact_path = comp.get("artifact_path")
            if artifact_path is None:
                continue
            full_path = project_root / artifact_path
            if not full_path.exists():
                continue
            artifact = json.loads(full_path.read_text(encoding="utf-8"))
            for metric_path, rule in comp["metrics"].items():
                value = extract_metric(artifact, metric_path)
                if value is None and not rule.get("optional", False):
                    raise AssertionError(
                        f"{name}.{metric_path} 在 artifact 中不存在且未标记 optional"
                    )
