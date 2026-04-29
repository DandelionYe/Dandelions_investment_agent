import json

from services.protocols.validation import validate_protocol


def generate_debate_result(research_result: dict) -> dict:
    """
    根据已有研究结果，生成多头/空头/风险官/投委会结论。
    第一版先用一个 Agent 一次性生成完整辩论结果。
    """

    from services.llm.deepseek_client import DeepSeekClient

    client = DeepSeekClient()

    system_prompt = """
你是一个A股/ETF私募投委会研究助手。

你必须只输出合法 JSON，不要输出 Markdown，不要输出解释文字。

你的任务是根据输入的量化评分和基础研究结果，生成：
1. 多头观点 bull_case
2. 空头观点 bear_case
3. 风险官意见 risk_review
4. 投委会收敛结论 committee_conclusion

严格规则：
- 只能基于用户提供的数据进行分析。
- 不允许编造具体财务数据。
- 不允许编造公告、政策、分红、回购、并购、监管、行业新闻等输入中没有出现的信息。
- 如果输入数据不足，必须明确写“当前输入证据不足，需要后续补充真实数据验证”。
- catalysts 只能写“可能需要观察的催化方向”，不能写成已经发生的事实。
- 买卖建议允许，但不能涉及自动下单。
- 风格应接近“私募投委会纪要 + 量化因子打分卡”。
- 如果 source_metadata 中出现 mock_placeholder，必须明确提示这些基本面/估值/事件证据仍需真实数据验证。
- 必须优先基于 evidence_bundle 和 data_quality 形成结论；如果证据不足，必须明确说明证据不足。
- 不允许引用 evidence_bundle 中不存在的公告、政策、财务或估值事实。
- 只要输入中包含 mock 或 mock_placeholder 数据，committee_conclusion.confidence 不得超过 0.80。
- 必须返回 json。
"""

    user_prompt = f"""
请根据以下研究结果生成结构化投委会辩论 JSON。

输入研究结果如下：

{json.dumps(research_result, ensure_ascii=False, indent=2)}

请严格按照下面 JSON 结构输出：

{{
  "bull_case": {{
    "thesis": "一句话多头核心观点",
    "key_arguments": ["多头理由1", "多头理由2", "多头理由3"],
    "catalysts": ["潜在催化1", "潜在催化2"],
    "invalidation_conditions": ["多头观点失效条件1", "多头观点失效条件2"]
  }},
  "bear_case": {{
    "thesis": "一句话空头核心观点",
    "key_arguments": ["空头理由1", "空头理由2", "空头理由3"],
    "main_concerns": ["主要担忧1", "主要担忧2"],
    "invalidation_conditions": ["空头观点失效条件1", "空头观点失效条件2"]
  }},
  "risk_review": {{
    "risk_level": "low/medium/high",
    "blocking": false,
    "risk_summary": "风险官总结",
    "max_position": "建议仓位上限，例如5%-8%",
    "risk_triggers": ["风险触发条件1", "风险触发条件2"]
  }},
  "committee_conclusion": {{
    "stance": "看多/谨慎看多/中性/谨慎/回避",
    "action": "买入/分批买入/持有/观察/回避",
    "confidence": 0.0,
    "final_opinion": "最终投委会意见"
  }}
}}
"""

    result = client.chat_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=client.fast_model,
        max_tokens=2500,
    )

    validate_protocol("debate_result", result)
    return result
