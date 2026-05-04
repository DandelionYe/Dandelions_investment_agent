import json

from services.llm.deepseek_client import DeepSeekClient


class BullAnalyst:
    """
    多头分析师：从研究数据中识别看多信号和催化因素。
    独立 Agent 节点，可单独调用，为 LangGraph 编排做好准备。
    """

    def __init__(self, model: str | None = None):
        self._client = DeepSeekClient()
        self._model = model or self._client.fast_model

    def analyze(self, research_result: dict) -> dict:
        system_prompt = (
            "你是一个A股/ETF私募投委会的**多头分析师**。\n"
            "你的职责是：基于输入数据，识别和阐述该资产的看多逻辑。\n"
            "\n"
            "严格规则：\n"
            "- 只能基于输入数据中**实际存在**的信息进行分析，不允许编造任何财务数据、公告、新闻、政策、行业动态或公司事件。\n"
            "- 如果输入数据不足以支撑强看多观点，必须诚实说明「当前输入证据不足，需要补充真实数据验证」。\n"
            "- catalysts 只能写「可能需要观察的催化方向」，不能写成已经发生的事实或确定性事件。\n"
            "- 必须引用 evidence_bundle 或具体数据字段来支撑观点。\n"
            "- 风格应接近「私募投委会纪要」——简洁、专业、基于数据。\n"
            "- 只输出合法 JSON，不要输出 Markdown、解释文字或任何其他内容。\n"
        )

        user_prompt = (
            "请根据以下研究结果，从**多头视角**生成结构化分析 JSON。\n"
            "\n"
            "重点关注：评分明细中的趋势动量/基本面质量得分、"
            "价格数据中的涨跌幅和均线位置、基本面数据中的盈利能力和成长性、"
            "估值数据中的分位水平、事件数据中的积极催化因素。\n"
            "\n"
            "输入研究结果如下：\n"
            "\n"
            + json.dumps(research_result, ensure_ascii=False, indent=2)
            + "\n\n"
            '请严格按照下面 JSON 结构输出（不要附加其他字段说明）：\n'
            "\n"
            "{\n"
            '  "thesis": "一句话多头核心观点",\n'
            '  "key_arguments": ["基于数据的具体多头理由1", "基于数据的具体多头理由2", "基于数据的具体多头理由3"],\n'
            '  "catalysts": ["可能需要观察的催化方向1", "可能需要观察的催化方向2"],\n'
            '  "invalidation_conditions": ["多头观点失效条件1", "多头观点失效条件2"]\n'
            "}\n"
        )

        return self._client.chat_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self._model,
            max_tokens=1500,
        )
