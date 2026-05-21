"""Helpers for tracing LLM agent prompts and input snapshots."""

from __future__ import annotations

import hashlib
from typing import Any

from services.agents.research_context import compact_research_result_for_llm


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

    The snapshot compacts defensively even when the caller already passes
    compact data, so future callers cannot accidentally persist full peer lists
    or raw provider payloads in audit metadata.
    """
    compact = compact_research_result_for_llm(research_result)
    bundle = compact.get("evidence_bundle") or {}
    return {
        "symbol": compact.get("symbol"),
        "name": compact.get("name"),
        "asset_type": compact.get("asset_type"),
        "as_of": compact.get("as_of"),
        "data_source": compact.get("data_source"),
        "score": compact.get("score"),
        "rating": compact.get("rating"),
        "action": compact.get("action"),
        "price_data": compact.get("price_data", {}),
        "fundamental_data": compact.get("fundamental_data", {}),
        "valuation_data": compact.get("valuation_data", {}),
        "event_data": compact.get("event_data", {}),
        "evidence_bundle": _evidence_preview(bundle),
        "data_quality": compact.get("data_quality", {}),
    }


def summarize_agent_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep only small, useful identifiers from another agent's audit metadata."""
    if not isinstance(metadata, dict):
        return None
    summary = {
        "agent_role": metadata.get("agent_role"),
        "prompt_version": metadata.get("prompt_version"),
        "model": metadata.get("model"),
        "prompt_hashes": metadata.get("prompt_hashes"),
        "challenge_present": metadata.get("challenge_present"),
        "debate_history_turns": metadata.get("debate_history_turns"),
    }
    return {key: value for key, value in summary.items() if value is not None}


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
