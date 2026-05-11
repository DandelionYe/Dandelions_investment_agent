import pytest

from services.agents.audit_metadata import build_agent_metadata
from services.agents.json_call import chat_json_checked
from services.llm.deepseek_client import DeepSeekClient
from services.llm.json_guard import (
    LLMJsonParseError,
    LLMJsonValidationError,
    extract_json_object,
    validate_json_payload,
)
from services.orchestrator.single_asset_research import run_single_asset_research


def test_extract_json_object_from_fenced_text():
    payload = extract_json_object('```json\n{"ok": true}\n```')

    assert payload == {"ok": True}


def test_extract_json_object_from_wrapped_text():
    payload = extract_json_object('说明文字 {"ok": true, "value": 1} trailing')

    assert payload["ok"] is True
    assert payload["value"] == 1


def test_validate_json_payload_rejects_missing_required_field():
    with pytest.raises(LLMJsonValidationError):
        validate_json_payload({"ok": True}, required_fields=["missing"])


def test_deepseek_client_repairs_invalid_json_once():
    client = DeepSeekClient.__new__(DeepSeekClient)
    client.fast_model = "fake-fast"
    outputs = iter(["not json", '{"ok": true}'])
    calls = []

    def fake_complete_json_text(**kwargs):
        calls.append(kwargs)
        return next(outputs)

    client._complete_json_text = fake_complete_json_text

    payload = client.chat_json(
        system_prompt="system",
        user_prompt="user",
        required_fields=["ok"],
        field_types={"ok": bool},
        max_retries=1,
    )

    assert payload == {"ok": True}
    assert len(calls) == 2
    assert "JSON" in calls[1]["system_prompt"]


def test_deepseek_client_raises_after_repair_exhausted():
    client = DeepSeekClient.__new__(DeepSeekClient)
    client.fast_model = "fake-fast"

    def fake_complete_json_text(**kwargs):
        return "not json"

    client._complete_json_text = fake_complete_json_text

    with pytest.raises(LLMJsonParseError):
        client.chat_json(
            system_prompt="system",
            user_prompt="user",
            required_fields=["ok"],
            max_retries=0,
        )


def test_chat_json_checked_attaches_audit_metadata():
    class FakeClient:
        def chat_json(self, **kwargs):
            return {"ok": True}

    metadata = {"agent_role": "bull", "prompt_version": "bull_analyst_v1"}

    payload = chat_json_checked(
        FakeClient(),
        system_prompt="system",
        user_prompt="user",
        model="fake",
        max_tokens=100,
        metadata=metadata,
        required_fields=["ok"],
    )

    assert payload["ok"] is True
    assert payload["metadata"] == metadata


def test_build_agent_metadata_includes_prompt_hash_and_input_snapshot():
    metadata = build_agent_metadata(
        agent_role="risk",
        prompt_version="risk_officer_v1",
        model="fake-model",
        system_prompt="system prompt",
        user_prompt="user prompt",
        research_result={
            "symbol": "600519.SH",
            "name": "贵州茅台",
            "asset_type": "stock",
            "as_of": "2026-05-12",
            "data_source": "mock",
            "source_metadata": {"price_data": {"source": "mock"}},
            "evidence_bundle": {
                "bundle_id": "bundle-1",
                "items": [
                    {
                        "evidence_id": "ev-1",
                        "category": "price",
                        "title": "收盘价",
                        "source": "mock",
                        "confidence": 0.5,
                    }
                ],
            },
        },
    )

    assert metadata["agent_role"] == "risk"
    assert metadata["prompt_version"] == "risk_officer_v1"
    assert len(metadata["prompt_hashes"]["system_sha256"]) == 64
    assert metadata["input_snapshot"]["symbol"] == "600519.SH"
    assert metadata["input_snapshot"]["evidence_bundle"]["item_count"] == 1


def test_single_asset_research_falls_back_when_llm_json_fails(monkeypatch):
    def raise_json_error(result):
        raise LLMJsonValidationError("missing field")

    monkeypatch.setattr(
        "services.orchestrator.single_asset_research.generate_debate_result",
        raise_json_error,
    )

    result = run_single_asset_research(
        "600519.SH",
        use_llm=True,
        data_source="mock",
    )

    assert result["analysis_mode"] == "llm_json_fallback_template"
    assert result["llm_enabled"] is False
    assert any("LLM JSON" in item for item in result["analysis_warnings"])
