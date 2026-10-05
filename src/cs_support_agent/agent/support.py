"""support.py 客服 Agent 循环——树锚点 M01.F02（意图路由 / RAG 循环 / 护栏）、M02.F02（三分支兜底）。

一轮 reply 的事件流（SSE 协议：session/delta/reasoning/citations/ticket/handoff/done/error）：
  意图轮（llm.chat 不流式，classify_intent 强约束）→ 路由：
    kb       → 本地检索 → 空命中走固定文案（不转人工）；有命中注入片段 →
               作答轮（流式但 delta 缓冲）→ 逐句引用校验 → 过：一次性发出+citations 事件；
               不过：固定文案+自动转人工（答案绝不带病上线）
    ticket   → 工单轮（create_ticket / handoff_to_human，delta 直发）
    handoff  → 直接转人工收尾
    chitchat → 意图轮顺带的文本直出；没有文本再起寒暄轮
    unknown  → 澄清一次；再不明 → 转人工（sessions.clarified 标志）
  护栏：会话轮次上限（触顶不调 LLM 直接转人工收尾）、单轮工具循环 ≤4、
  一切异常转 error 事件不崩会话（查询异常捕获，M00.F02.I03）。
"""
from __future__ import annotations

import json
from collections.abc import Iterator

from cs_support_agent.agent import prompts
from cs_support_agent.agent.tools import ANSWER_TOOLS, INTENT_TOOLS, execute_tool
from cs_support_agent.kb import search
from cs_support_agent.llm import tool_msg
from cs_support_agent.verify import verify_answer

_MAX_TOOL_ROUNDS = 4


def _done(
    status: str = "live",
    *,
    citations: list | None = None,
    ticket: dict | None = None,
    handoff: dict | None = None,
    no_result: bool = False,
) -> dict:
    return {
        "type": "done",
        "status": status,
        "citations": citations or [],
        "ticket": ticket,
        "handoff": handoff,
        "no_result": no_result,
    }


class SupportAgent:
    def __init__(self, llm, store, max_turns: int = 20):
        self.llm = llm
        self.store = store
        self.max_turns = max_turns

    # ---- 对外入口 ----

    def reply(self, session_id: str, user_text: str) -> Iterator[dict]:
        sess = self.store.get_session(session_id)
        if sess is None:
            yield {"type": "error", "message": f"会话 {session_id} 不存在"}
            return
        if sess["status"] == "handed_off":
            yield {"type": "error", "message": "会话已转人工，请等待人工客服跟进；如需继续咨询请新建会话。"}
            return
        self.store.append_message(session_id, "user", user_text)
        yield {"type": "session", "session_id": session_id, "status": sess["status"]}
        try:
            yield from self._route(session_id)
        except Exception as exc:  # 检索/LLM 等一切异常 → error 事件，会话不崩
            yield {"type": "error", "message": f"处理出错：{exc}"}

    # ---- 路由 ----

    def _route(self, session_id: str) -> Iterator[dict]:
        history = self.store.get_messages(session_id)
        prior_user = sum(1 for m in history if m["role"] == "user") - 1  # 不含刚 append 的本条
        if prior_user >= self.max_turns:
            yield from self._system_handoff(session_id, prompts.FALLBACK_TURN_LIMIT, "会话轮次已达上限")
            return
        intent, direct_text, args = self._classify(session_id)
        if intent == "kb":
            yield from self._kb(session_id)
        elif intent == "ticket":
            yield from self._tool_round(session_id, prompts.TICKET_SYSTEM)
        elif intent == "handoff":
            yield from self._handoff(session_id, args)
        elif intent == "chitchat":
            yield from self._chitchat(session_id, direct_text)
        else:
            yield from self._unknown(session_id)

    def _classify(self, session_id: str) -> tuple[str, str, dict]:
        """意图轮：不流式 chat + classify_intent 强约束。返回 (意图, 顺带文本, 工具参数)。"""
        messages = [{"role": "system", "content": prompts.INTENT_SYSTEM}, *self._history(session_id)]
        final = self.llm.chat(messages=messages, tools=INTENT_TOOLS)
        calls = final.get("tool_calls") or []
        if not calls:
            # 模型没调分类工具直接回了话 → 当寒暄文本直出
            return "chitchat", (final.get("content") or "").strip(), {}
        args = calls[0].arguments or {}
        intent = str(args.get("intent", "unknown"))
        if intent not in ("kb", "ticket", "handoff", "chitchat"):
            intent = "unknown"
        return intent, "", args

    # ---- 分支 ----

    def _kb(self, session_id: str) -> Iterator[dict]:
        """知识库分支：本地检索 → 片段注入 → 作答轮 → 逐句引用校验（答案缓冲到过检才发出）。"""
        question = self._last_user_text(session_id)
        hits = search(question, self.store.list_kb_articles())
        if not hits:
            self.store.append_message(session_id, "assistant", prompts.FALLBACK_NO_RESULT)
            yield {"type": "delta", "text": prompts.FALLBACK_NO_RESULT}
            yield _done(no_result=True)
            return
        messages = [{"role": "system", "content": prompts.kb_system(hits)}, *self._history(session_id)]
        for _ in range(_MAX_TOOL_ROUNDS):
            final = None
            for ev in self.llm.chat_stream(messages=messages, tools=ANSWER_TOOLS):
                # 答案未过校验前不直发 delta；思维链（reasoning）不是答案，可直发
                if ev["type"] == "reasoning":
                    yield ev
                elif ev["type"] == "final":
                    final = ev["message"]
            calls = (final or {}).get("tool_calls") or []
            if calls and calls[0].name == "answer_with_citations":
                content = str(calls[0].arguments.get("answer", "")).strip()
            elif not calls:  # 模型忘调工具直接写了答案 → 照样过校验，不豁免
                content = ((final or {}).get("content") or "").strip()
            else:
                content = ""
            if content:
                verdict = verify_answer(content, hits)
                if verdict.ok:
                    self.store.append_message(
                        session_id, "assistant", content,
                        citations_json=json.dumps(hits, ensure_ascii=False),
                    )
                    yield {"type": "delta", "text": content}
                    yield {"type": "citations", "citations": hits}
                    yield _done(citations=hits)
                else:
                    yield from self._system_handoff(
                        session_id, prompts.FALLBACK_VERIFY_FAILED, f"答案校验未通过（{verdict.reason}）"
                    )
                return
            if calls:  # create_ticket / handoff_to_human 等工具 → 执行后继续循环
                call = calls[0]
                result, event = execute_tool(call.name, call.arguments, store=self.store, session_id=session_id)
                if event is not None:
                    if event["type"] == "handoff":
                        yield event
                        yield _done("ended", handoff={"reason": event["reason"]})
                        return
                    yield event
                messages = [*messages, final, tool_msg(call.id, result)]
        yield from self._system_handoff(session_id, prompts.FALLBACK_TURN_LIMIT, "工具轮次触顶")

    def _tool_round(self, session_id: str, system: str) -> Iterator[dict]:
        """工单轮：delta 直发（无校验语义），create_ticket 落库并回传结果继续，直到无工具调用。"""
        messages = [{"role": "system", "content": system}, *self._history(session_id)]
        for _ in range(_MAX_TOOL_ROUNDS):
            final = None
            for ev in self.llm.chat_stream(messages=messages, tools=ANSWER_TOOLS):
                if ev["type"] in ("delta", "reasoning"):
                    yield ev
                elif ev["type"] == "final":
                    final = ev["message"]
            calls = (final or {}).get("tool_calls") or []
            if not calls:
                content = ((final or {}).get("content") or "").strip()
                if content:
                    self.store.append_message(session_id, "assistant", content)
                yield _done()
                return
            call = calls[0]
            result, event = execute_tool(call.name, call.arguments, store=self.store, session_id=session_id)
            if event is not None:
                if event["type"] == "handoff":
                    yield event
                    yield _done("ended", handoff={"reason": event["reason"]})
                    return
                yield event
            messages = [*messages, final, tool_msg(call.id, result)]
        yield from self._system_handoff(session_id, prompts.FALLBACK_TURN_LIMIT, "工具轮次触顶")

    def _handoff(self, session_id: str, args: dict) -> Iterator[dict]:
        """意图=转人工：不再起生成轮，直接收尾（意图轮已经听懂来意）。"""
        topic = str(args.get("topic") or "").strip()
        reason = "用户要求转人工" + (f"：{topic}" if topic else "")
        self.store.append_message(session_id, "assistant", "好的，正在为您转接人工客服，请稍候。")
        self.store.update_session(session_id, {"status": "handed_off"})
        yield {"type": "handoff", "reason": reason}
        yield _done("ended", handoff={"reason": reason})

    def _chitchat(self, session_id: str, direct_text: str) -> Iterator[dict]:
        if direct_text:  # 意图轮顺带回的文本，直接发
            self.store.append_message(session_id, "assistant", direct_text)
            yield {"type": "delta", "text": direct_text}
            yield _done()
            return
        yield from self._plain_round(session_id, prompts.CHITCHAT_SYSTEM)

    def _unknown(self, session_id: str) -> Iterator[dict]:
        sess = self.store.get_session(session_id)
        if sess and sess.get("clarified"):
            yield from self._system_handoff(session_id, prompts.FALLBACK_UNKNOWN, "意图仍无法识别")
            return
        yield from self._plain_round(session_id, prompts.CLARIFY_SYSTEM)
        self.store.update_session(session_id, {"clarified": 1})

    # ---- 公共件 ----

    def _plain_round(self, session_id: str, system: str) -> Iterator[dict]:
        """无工具生成轮（澄清/寒暄兜底）：流式直发，落库收尾。"""
        messages = [{"role": "system", "content": system}, *self._history(session_id)]
        text = ""
        final = None
        for ev in self.llm.chat_stream(messages=messages):
            if ev["type"] == "delta":
                text += ev["text"]
                yield ev
            elif ev["type"] == "reasoning":
                yield ev
            elif ev["type"] == "final":
                final = ev["message"]
        content = ((final or {}).get("content") or text).strip()
        if content:
            self.store.append_message(session_id, "assistant", content)
        yield _done()

    def _system_handoff(self, session_id: str, text: str, reason: str) -> Iterator[dict]:
        """系统级转人工收尾：固定文案 → 置状态 → handoff 事件 → done(ended)。"""
        self.store.append_message(session_id, "assistant", text)
        yield {"type": "delta", "text": text}
        self.store.update_session(session_id, {"status": "handed_off"})
        yield {"type": "handoff", "reason": reason}
        yield _done("ended", handoff={"reason": reason})

    def _history(self, session_id: str) -> list[dict]:
        """会话历史转 LLM 消息形状（只带 user/assistant，citations_json 等不带）。"""
        return [
            {"role": m["role"], "content": m["content"]}
            for m in self.store.get_messages(session_id)
            if m["role"] in ("user", "assistant")
        ]

    def _last_user_text(self, session_id: str) -> str:
        for m in reversed(self.store.get_messages(session_id)):
            if m["role"] == "user":
                return m["content"]
        return ""
