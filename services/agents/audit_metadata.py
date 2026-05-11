"""Helpers for tracing LLM agent prompts and input snapshots."""

from __future__ import annotations

import hashlib
from typing import Any


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pick(mapping: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: mapping[key] for key in keys if key in mapping}


def _evidence_preview(evidence_bundle: dict[str, Any], limit: int = 8) -> dict[str, Any]:
    items = evidence_bundle.get("items") or []
    preview = []
    for item in items[:limit]:
        preview.append(
            _pick(
                item,
                (
                    "evidence_id",
                    "category",
                    "title",
                    "source",
                    "source_date",
                    "confidence",
                    "display_value",
                ),
            )
        )
    return {
        "bundle_id": evidence_bundle.get("bundle_id"),
        "item_count": len(items),
        "items_preview": preview,
    }


def _event_preview(event_data: dict[str, Any], limit: int = 8) -> dict[str, Any]:
    items = event_data.get("items") or event_data.get("events") or []
    preview = []
    for item in items[:limit]:
        if isinstance(item, dict):
            preview.append(
                _pick(
                    item,
                    (
                        "title",
                        "event_type",
                        "severity",
                        "published_at",
                        "source",
                        "summary",
                    ),
                )
            )
    return {
        "item_count": len(items),
        "items_preview": preview,
        **_pick(event_data, ("positive_count", "negative_count", "critical_count")),
    }


def build_research_input_snapshot(research_result: dict[str, Any]) -> dict[str, Any]:
    """Build a compact, auditable snapshot of the data shown to an LLM agent."""
    price_data = research_result.get("price_data") or {}
    fundamental_data = research_result.get("fundamental_data") or {}
    valuation_data = research_result.get("valuation_data") or {}
    event_data = research_result.get("event_data") or {}

    return {
        "symbol": research_result.get("symbol"),
        "name": research_result.get("name"),
        "asset_type": research_result.get("asset_type"),
        "as_of": research_result.get("as_of"),
        "data_source": research_result.get("data_source"),
        "data_source_chain": research_result.get("data_source_chain", []),
        "score": research_result.get("score"),
        "rating": research_result.get("rating"),
        "action": research_result.get("action"),
        "source_metadata": research_result.get("source_metadata", {}),
        "data_quality": research_result.get("data_quality", {}),
        "price_data": _pick(
            price_data,
            (
                "close",
                "change_pct",
                "ma20",
                "ma60",
                "volume",
                "turnover",
                "data_vendor",
            ),
        ),
        "fundamental_data": _pick(
            fundamental_data,
            (
                "revenue_growth",
                "profit_growth",
                "roe",
                "gross_margin",
                "net_margin",
                "debt_to_asset",
            ),
        ),
        "valuation_data": _pick(
            valuation_data,
            ("pe_ttm", "pb", "pe_percentile", "pb_percentile", "valuation_score"),
        ),
        "event_data": _event_preview(event_data),
        "evidence_bundle": _evidence_preview(research_result.get("evidence_bundle") or {}),
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
