def format_debate_history(history: list) -> str:
    """将辩论历史格式化为可读文本，供所有 Agent 共享使用。"""
    if not history:
        return "（无历史——这是第一轮辩论）"
    lines = ["==========================", "辩论历史", "=========================="]
    for entry in history:
        entry_type = entry.get("type", "")
        rnd = entry.get("round", "?")
        if entry_type == "initial":
            lines.append(f"[第{rnd}轮] 三方发表初始观点")
            outputs = entry.get("outputs", {})
            bull = outputs.get("bull_case", {})
            bear = outputs.get("bear_case", {})
            risk = outputs.get("risk_review", {})
            lines.append(f"  多头：{bull.get('thesis', '(无)')}")
            lines.append(f"  空头：{bear.get('thesis', '(无)')}")
            lines.append(f"  风险官：{risk.get('risk_summary', '(无)')}")
        elif entry_type == "supervisor_judgment":
            decision = entry.get("decision", {})
            lines.append(
                f"[第{rnd}轮] 主持人评估：{decision.get('round_summary', '(无)')}"
            )
        elif entry_type == "challenge_response":
            speaker = entry.get("speaker", "?")
            challenge = entry.get("challenge", "")
            output = entry.get("output", {})
            thesis = output.get("thesis") or output.get("risk_summary", "(无)")
            lines.append(f"[第{rnd}轮] {speaker} 回应质询")
            if challenge:
                lines.append(f"  质询：{challenge[:150]}")
            lines.append(f"  回应：{thesis[:200]}")
    return "\n".join(lines)
