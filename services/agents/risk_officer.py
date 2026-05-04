import json

from services.llm.deepseek_client import DeepSeekClient


class RiskOfficer:
    """
    风险官：评估资产风险等级，判断是否阻断买入，给出仓位上限。
    独立 Agent 节点，可单独调用，为 LangGraph 编排做好准备。
    """

    def __init__(self, model: str | None = None):
        self._client = DeepSeekClient()
        self._model = model or self._client.fast_model

    def review(self, research_result: dict) -> dict:
        system_prompt = (
            "你是一个A股/ETF私募投委会的**风险官**。\n"
            "你的职责是：保守评估该资产的风险等级，判断是否应阻断买入建议，并给出仓位上限。\n"
            "\n"
            "严格规则：\n"
            "- 只能基于输入数据中**实际存在**的信息进行评估，不允许编造任何风险事件。\n"
            "- 风险等级必须偏保守：有不确定性时应倾向于给出更高风险等级。\n"
            "- 如果 source_metadata 中出现 mock_placeholder，说明部分数据是占位符，"
            "应明确指出数据质量不足以支持低风险判断。\n"
            "- blocking 为 true 意味着应完全阻止任何买入操作，仅当存在 critical 级别事件或"
            "数据质量存在严重阻断项时才设置为 true。\n"
            "- max_position 格式如「3%-5%」、「5%-8%」或「不超过3%」。\n"
            "- risk_triggers 应列出具体的、可观察的风险触发条件。\n"
            "- 只输出合法 JSON，不要输出 Markdown、解释文字或任何其他内容。\n"
        )

        user_prompt = (
            "请根据以下研究结果，从**风险控制视角**生成结构化风险评估 JSON。\n"
            "\n"
            "重点关注：data_quality 中的 has_placeholder 和 blocking_issues、"
            "event_data 中的 critical/high 严重性事件、source_metadata 中的 mock_placeholder 标记、"
            "risk_control 得分及其扣分项、price_data 中的最大回撤和波动率、"
            "fundamental_data 中的负债率等。\n"
            "\n"
            "输入研究结果如下：\n"
            "\n"
            + json.dumps(research_result, ensure_ascii=False, indent=2)
            + "\n\n"
            '请严格按照下面 JSON 结构输出（不要附加其他字段说明）：\n'
            "\n"
            "{\n"
            '  "risk_level": "low",\n'
            '  "blocking": false,\n'
            '  "risk_summary": "基于数据的具体风险总结，需提及主要风险来源",\n'
            '  "max_position": "5%-8%",\n'
            '  "risk_triggers": ["具体的风险触发条件1", "具体的风险触发条件2"]\n'
            "}\n"
            "\n"
            "注意：risk_level 必须是「low」「medium」或「high」之一。\n"
        )

        return self._client.chat_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self._model,
            max_tokens=1000,
        )
