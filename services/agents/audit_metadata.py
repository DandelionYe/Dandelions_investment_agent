"""Helpers for tracing LLM agent prompts and input snapshots."""

from __future__ import annotations

import hashlib
from typing import Any


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _evidence_preview(evidence_bundle: dict[str, Any]) -> dict[str, Any]:
    items = evidence_bundle.get("items") or []
    return {
        "bundle_id": evidence_bundle.get("bundle_id"),
        "item_count": len(items),
        "items_preview": items[:8],
    }


def build_research_input_snapshot(research_result: dict[str, Any]) -> dict[str, Any]:
    """Build a compact, auditable snapshot of the data shown to an LLM agent.

    Agents are expected to pass already-compacted data (via
    ``compact_research_result_for_llm``), so this function simply records the
    fields that matter for audit without re-filtering.
    """
    bundle = research_result.get("evidence_bundle") or {}
    return {
        "symbol": research_result.get("symbol"),
        "name": research_result.get("name"),
        "asset_type": research_result.get("asset_type"),
        "as_of": research_result.get("as_of"),
        "data_source": research_result.get("data_source"),
        "score": research_result.get("score"),
        "rating": research_result.get("rating"),
        "action": research_result.get("action"),
        "price_data": research_result.get("price_data", {}),
        "fundamental_data": research_result.get("fundamental_data", {}),
        "valuation_data": research_result.get("valuation_data", {}),
        "event_data": research_result.get("event_data", {}),
        "evidence_bundle": _evidence_preview(bundle),
        "data_quality": research_result.get("data_quality", {}),
    }


def build_agent_metadata(
    *,
    agent_role: str,
    prompt_version: str,
    model: str | None,
    system_prompt: str,
    user_prompt: str,
    research_result: dict[str, Any] | None = None,
    challenge: str | None = None,
    debate_history: list[dict[str, Any]] | None = None,
    extra_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "agent_role": agent_role,
        "prompt_version": prompt_version,
        "model": model,
        "prompt_hashes": {
            "system_sha256": _sha256_text(system_prompt),
            "user_sha256": _sha256_text(user_prompt),
        },
        "challenge_present": bool(challenge),
        "debate_history_turns": len(debate_history or []),
    }
    if research_result is not None:
        metadata["input_snapshot"] = build_research_input_snapshot(research_result)
    if extra_inputs:
        metadata["extra_inputs"] = extra_inputs
    return metadata
