"""JSON 守卫 — 预留模块。

计划功能：对 LLM 输出的 JSON 进行结构性校验和自动修复，
确保输出符合预期 schema 后再进入决策流程。
当前 JSON 校验通过 services/protocols/validation.py 实现。
"""