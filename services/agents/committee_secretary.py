import json

from services.llm.deepseek_client import DeepSeekClient


class CommitteeSecretary:
    """
    投委会秘书：整合多头、空头、风险官三方意见，形成最终投委会结论。
    独立 Agent 节点，可单独调用，为 LangGraph 编排做好准备。
    """

    def __init__(self, model: str | None = None):
        self._client = DeepSeekClient()
        self._model = model or self._client.fast_model

    def converge(
        self,
        research_result: dict,
        bull_case: dict,
        bear_case: dict,
        risk_review: dict,
        debate_history: list | None = None,
    ) -> dict:
        system_prompt = (
            "你是一个A股/ETF私募投委会的**投委会秘书**。\n"
            "你的职责是：在听取多头分析师、空头分析师和风险官的独立意见后，"
            "基于原始研究数据，形成最终的投委会结论。\n"
            "\n"
            "你需要：\n"
            "1. 权衡三方的观点，谁的论据更有数据支撑就偏向谁\n"
            "2. 参考原始研究数据中的评分、评级、数据质量信息\n"
            "3. 给出明确的立场(stance)、操作建议(action)、置信度(confidence)和最终意见(final_opinion)\n"
            "\n"
            "严格规则：\n"
            "- 你只能基于输入的研究数据和三方意见做判断，不允许编造任何新的数据、公告或事实。\n"
            "- confidence 是 0.0-1.0 之间的数值，反映你对最终结论的确信程度。\n"
            "- 如果输入数据中包含 mock 或 mock_placeholder，confidence 不得超过 0.80。\n"
            "- 如果三方意见存在明显分歧，应在 final_opinion 中如实反映分歧。\n"
            "- 不要简单地选一边站——你需要在三方意见之间做真正的权衡。\n"
            "- 风格应接近「私募投委会纪要」——简洁、专业、有结论。\n"
            "- 买卖建议允许，但不能涉及自动下单。\n"
            "- 只输出合法 JSON，不要输出 Markdown、解释文字或任何其他内容。\n"
        )

        if debate_history:
            system_prompt += (
                "\n"
                "本轮包含多轮质询辩论，你应该参考完整辩论历程（debate_history）"
                "来理解各方的最终立场。特别注意最后几轮中各方是否改变了立场或提出了新论据。\n"
            )

        def _format_case(label: str, case: dict) -> str:
            return json.dumps(case, ensure_ascii=False, indent=2)

        user_prompt = (
            "请根据以下原始研究数据和三方独立意见，生成最终投委会结论 JSON。\n"
            "\n"
            "==========================\n"
            "原始研究数据\n"
            "==========================\n"
            + json.dumps(research_result, ensure_ascii=False, indent=2)
            + "\n\n"
            "==========================\n"
            "多头分析师意见 (bull_case)\n"
            "==========================\n"
            + _format_case("bull_case", bull_case)
            + "\n\n"
            "==========================\n"
            "空头分析师意见 (bear_case)\n"
            "==========================\n"
            + _format_case("bear_case", bear_case)
            + "\n\n"
            "==========================\n"
            "风险官意见 (risk_review)\n"
            "==========================\n"
            + _format_case("risk_review", risk_review)
            + "\n"
        )

        if debate_history:
            user_prompt += (
                "\n"
                + self._format_debate_history(debate_history)
                + "\n\n"
            )

        user_prompt += (
            '请严格按照下面 JSON 结构输出（不要附加其他字段说明）：\n'
            "\n"
            "{\n"
            '  "stance": "看多",\n'
            '  "action": "分批买入",\n'
            '  "confidence": 0.75,\n'
            '  "final_opinion": "综合多头分析师、空头分析师和风险官的意见后，'
            "投委会认为……（需结合具体数据和论据）\"\n"
            "}\n"
            "\n"
            "注意：\n"
            '- stance 可选：看多 / 谨慎看多 / 中性 / 谨慎 / 回避\n'
            '- action 可选：买入 / 分批买入 / 持有 / 观察 / 回避\n'
        )

        return self._client.chat_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self._model,
            max_tokens=1500,
        )

    @staticmethod
    def _format_debate_history(history: list) -> str:
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
