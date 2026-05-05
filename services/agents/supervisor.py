import json

from services.llm.deepseek_client import DeepSeekClient


class Supervisor:
    """
    辩论主持人：评估各方观点，识别分歧，生成质询，判断收敛。

    在多轮辩论的每一轮结束后运行，决定：
    1. 辩论是否已经充分（is_converged）
    2. 如果继续，下一轮由谁发言、回答什么问题
    """

    def __init__(self, model: str | None = None):
        self._client = DeepSeekClient()
        self._model = model or self._client.fast_model

    def evaluate(
        self,
        research_result: dict,
        bull_case: dict,
        bear_case: dict,
        risk_review: dict,
        debate_history: list[dict],
        current_round: int,
        max_rounds: int,
    ) -> dict:
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            research_result=research_result,
            bull_case=bull_case,
            bear_case=bear_case,
            risk_review=risk_review,
            debate_history=debate_history,
            current_round=current_round,
            max_rounds=max_rounds,
        )
        return self._client.chat_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self._model,
            max_tokens=1000,
        )

    def _build_system_prompt(self) -> str:
        return (
            "你是一个A股/ETF私募投委会的**辩论主持人**。\n"
            "你的职责是：听取多头分析师、空头分析师和风险官的独立意见后，"
            "判断辩论是否已经充分，如果未充分则指定下一发言人并提出具体质询。\n"
            "\n"
            "## 收敛判断标准\n"
            "\n"
            "下列任一条件满足时，你应该判定 is_converged = true：\n"
            "\n"
            "1. **立场一致（all_agree）**：三方在操作建议（action）或立场（stance）上不存在实质性分歧。\n"
            "   例如 Bull 和 Bear 都认为应该\"观察\"、Risk 不阻断，则已收敛。\n"
            "2. **无新论据（no_new_arguments）**：最近两轮的质询和回应没有产生任何新的实质性论据，\n"
            "   各方只是在重复已有观点。\n"
            "3. **max_rounds_reached**：已完成的评估轮次达到上限。\n"
            "\n"
            "## 未收敛时的调度原则\n"
            "\n"
            "- 优先选择存在明显分歧或数据薄弱的一方作为 next_speaker\n"
            "- 质询(challenge)必须：具体引用数据或前序论据、可回答、有针对性\n"
            "- 不要让同一方连续发言两次（除非另一方的质询直接指向他）\n"
            "- next_speaker 必须是 \"bull\"、\"bear\" 或 \"risk\" 之一\n"
            "\n"
            "## 输出格式\n"
            "严格规则：\n"
            "- 只输出合法 JSON，不要输出 Markdown、解释文字或任何其他内容。\n"
            "- 风格应简洁、专业。\n"
        )

    def _build_user_prompt(
        self,
        research_result: dict,
        bull_case: dict,
        bear_case: dict,
        risk_review: dict,
        debate_history: list[dict],
        current_round: int,
        max_rounds: int,
    ) -> str:
        summary = {
            "symbol": research_result.get("symbol"),
            "name": research_result.get("name"),
            "score": research_result.get("score"),
            "rating": research_result.get("rating"),
        }

        parts = [
            "请根据以下信息，判断辩论是否已收敛，若未收敛则指定下一发言人和质询。\n",
            "==========================",
            "研究摘要",
            "==========================",
            json.dumps(summary, ensure_ascii=False, indent=2),
            "",
            "==========================",
            "完整研究数据",
            "==========================",
            json.dumps(research_result, ensure_ascii=False, indent=2),
            "",
            "==========================",
            "多头分析师当前立场 (bull_case)",
            "==========================",
            json.dumps(bull_case, ensure_ascii=False, indent=2),
            "",
            "==========================",
            "空头分析师当前立场 (bear_case)",
            "==========================",
            json.dumps(bear_case, ensure_ascii=False, indent=2),
            "",
            "==========================",
            "风险官当前评估 (risk_review)",
            "==========================",
            json.dumps(risk_review, ensure_ascii=False, indent=2),
            "",
        ]

        if debate_history:
            parts.extend([
                "==========================",
                "辩论历史",
                "==========================",
                self._format_history(debate_history),
                "",
            ])

        parts.extend([
            "==========================",
            "当前状态",
            "==========================",
            f"已完成评估轮次：{current_round} / 最大轮次上限：{max_rounds}",
            "",
            '请严格按照下面 JSON 结构输出（不要附加其他字段说明）：',
            "",
            "{",
            '  "is_converged": false,',
            '  "convergence_reason": null,',
            '  "next_speaker": "bear",',
            '  "challenge": "针对某方前序论据的具体质询问题",',
            '  "round_summary": "本轮辩论要点的一句话总结"',
            "}",
            "",
            "注意：",
            "- is_converged 为 true 时，next_speaker 和 challenge 必须为 null",
            "- convergence_reason 在收敛时必须是 all_agree / no_new_arguments / max_rounds_reached 之一",
            "- next_speaker 必须是 bull / bear / risk 之一（小写英文）",
        ])

        return "\n".join(parts)

    def _format_history(self, history: list[dict]) -> str:
        lines = []
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
                if decision.get("is_converged"):
                    lines.append(f"  → 判定收敛：{decision.get('convergence_reason')}")
            elif entry_type == "challenge_response":
                speaker = entry.get("speaker", "?")
                challenge = entry.get("challenge", "")
                output = entry.get("output", {})
                thesis = output.get("thesis") or output.get("risk_summary", "(无)")
                lines.append(f"[第{rnd}轮] {speaker} 回应质询")
                if challenge:
                    lines.append(f"  质询：{challenge[:120]}")
                lines.append(f"  回应：{thesis[:150]}")
            else:
                lines.append(f"[第{rnd}轮] {entry_type}")

        return "\n".join(lines)
