"""客服 Agent 工具——树锚点 M01.F01.I01（classify_intent）、M01.F03.I02（create_ticket）。

execute_tool 返回 (工具结果 JSON 串, 事件|None)：事件由循环转交 SSE 流。
classify_intent / answer_with_citations 只回执不落库——路由与校验由循环负责。
"""
from __future__ import annotations

import json
from typing import Protocol


class _TicketStore(Protocol):
    def create_ticket(self, session_id: str, title: str, description: str) -> dict: ...
    def update_session(self, session_id: str, fields: dict) -> None: ...


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "classify_intent",
            "description": "对用户来意分类",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "enum": ["kb", "ticket", "handoff", "chitchat", "unknown"],
                        "description": "用户意图",
                    },
                    "topic": {"type": "string", "description": "一句话概括用户的问题"},
                },
                "required": ["intent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "answer_with_citations",
            "description": "提交带引用标注的答案，系统将逐句校验后才发给用户",
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {
                        "type": "string",
                        "description": "答案文本；实质内容句末尾带 [片段编号]",
                    }
                },
                "required": ["answer"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_ticket",
            "description": "创建工单，登记用户报告的问题",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "一句话标题"},
                    "description": {"type": "string", "description": "问题现象与背景"},
                },
                "required": ["title", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "handoff_to_human",
            "description": "转接人工客服",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string", "description": "转人工原因"}},
                "required": ["reason"],
            },
        },
    },
]

INTENT_TOOLS = [TOOLS[0]]
ANSWER_TOOLS = TOOLS[1:]  # answer_with_citations / create_ticket / handoff_to_human

_MAX_TOOL_ROUNDS = 4  # 单次 reply 的工具循环上限（轮次护栏 M01.F02.I03）


def execute_tool(name: str, args: dict, *, store: _TicketStore, session_id: str) -> tuple[str, dict | None]:
    """执行工具：返回 (结果 JSON 字符串, SSE 事件|None)。未知工具返回错误文本。"""
    if name == "classify_intent":
        return json.dumps({"ok": True, "intent": args.get("intent", "unknown")}, ensure_ascii=False), None
    if name == "answer_with_citations":
        return json.dumps({"ok": True, "note": "已提交校验"}, ensure_ascii=False), None
    if name == "create_ticket":
        ticket = store.create_ticket(
            session_id,
            title=str(args.get("title", ""))[:80],
            description=str(args.get("description", ""))[:500],
        )
        return json.dumps({"ok": True, "ticket_id": ticket["id"]}, ensure_ascii=False), {
            "type": "ticket",
            "ticket": ticket,
        }
    if name == "handoff_to_human":
        reason = str(args.get("reason", ""))[:200]
        store.update_session(session_id, {"status": "handed_off"})
        return json.dumps({"ok": True}, ensure_ascii=False), {"type": "handoff", "reason": reason}
    return json.dumps({"error": f"未知工具 {name}"}, ensure_ascii=False), None
