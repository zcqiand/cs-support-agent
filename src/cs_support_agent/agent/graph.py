"""graph.py 客服流程图——树锚点 M01.F02（意图路由 / RAG 循环 / 护栏）、M02.F02（三分支兜底）。

v2 编排内核（书 ch12 框架对齐）：v1 手写 tool-use 循环换 LangGraph StateGraph，
换芯不换壳——事件协议/落库/校验语义逐锚点保持（tests/ 既有 97 项为零改动等价门）。

图拓扑（12 节点）：
  begin → classify → kb / ticket / chitchat / unknown / handoff_out
  kb → answer ⇄ feedback ⇄ execute → finish / handoff_out
  全部转人工（意图转人工/轮次触顶/校验不过/意图不明二次）收口 handoff_out 节点。
  不用 checkpointer：会话状态每轮从 SQLite store 重建（store 是 SSOT），图是无状态纯函数。
  事件通道走 config["configurable"]["events"]（queue.SimpleQueue），_emit 对 None 安全。
"""
from __future__ import annotations

import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from cs_support_agent.agent import prompts
# search 经 support 模块命名空间迟到绑定：既有测试把 search patch 在 support_mod 上
# （等价门不许改测试）；只绑模块对象不绑名字，同时避开循环导入（双模块互相只绑模块对象）。
from cs_support_agent.agent import support as support_mod
from cs_support_agent.agent.tools import ANSWER_TOOLS, INTENT_TOOLS, execute_tool
from cs_support_agent.llm import tool_msg
from cs_support_agent.verify import verify_answer

_MAX_TOOL_ROUNDS = 4


class SupportState(TypedDict, total=False):
    session_id: str
    text: str
    fatal: bool          # 会话不存在/已转人工 → 只发 error 事件
    intent: str
    direct_text: str     # 意图轮顺带回的寒暄文本
    args: dict
    branch: str          # kb | ticket（execute 之后回哪个轮节点）
    messages: list       # 当前分支的 LLM 消息列
    hits: list
    rounds: int
    verify_attempts: int
    final: dict | None
    calls: list
    content: str
    verdict_ok: bool
    verify_reason: str
    handoff_text: str
    handoff_reason: str
    handoff_delta: bool  # 意图转人工不发 delta（v1 _handoff 锚），系统级转人工发（v1 _system_handoff 锚）
    plain_system: str
    ended: bool          # 终态事件已发出 → 条件边走 END


def _emit(config, event: dict) -> None:
    events = (config or {}).get("configurable", {}).get("events")
    if events is not None:
        events.put(event)


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


def _history(store, session_id: str) -> list[dict]:
    """会话历史转 LLM 消息形状（只带 user/assistant，citations_json 等不带）。"""
    return [
        {"role": m["role"], "content": m["content"]}
        for m in store.get_messages(session_id)
        if m["role"] in ("user", "assistant")
    ]


def _last_user_text(store, session_id: str) -> str:
    for m in reversed(store.get_messages(session_id)):
        if m["role"] == "user":
            return m["content"]
    return ""


# ---- 节点工厂 ----

def _make_begin(store, max_turns: int):
    def begin(state, config):
        sid = state["session_id"]
        sess = store.get_session(sid)
        if sess is None:
            _emit(config, {"type": "error", "message": f"会话 {sid} 不存在"})
            return {"fatal": True}
        if sess["status"] == "handed_off":
            _emit(config, {"type": "error", "message": "会话已转人工，请等待人工客服跟进；如需继续咨询请新建会话。"})
            return {"fatal": True}
        store.append_message(sid, "user", state["text"])
        _emit(config, {"type": "session", "session_id": sid, "status": sess["status"]})
        prior_user = sum(1 for m in store.get_messages(sid) if m["role"] == "user") - 1  # 不含刚 append 的本条
        if prior_user >= max_turns:
            return {"handoff_text": prompts.FALLBACK_TURN_LIMIT, "handoff_reason": "会话轮次已达上限"}
        return {}
    return begin


def _make_classify(llm, store):
    def classify(state, config):
        sid = state["session_id"]
        messages = [{"role": "system", "content": prompts.INTENT_SYSTEM}, *_history(store, sid)]
        final = llm.chat(messages=messages, tools=INTENT_TOOLS)
        calls = final.get("tool_calls") or []
        if not calls:
            # 模型没调分类工具直接回了话 → 当寒暄文本直出
            return {"intent": "chitchat", "direct_text": (final.get("content") or "").strip(), "args": {}}
        args = calls[0].arguments or {}
        intent = str(args.get("intent", "unknown"))
        if intent not in ("kb", "ticket", "handoff", "chitchat"):
            intent = "unknown"
        update = {"intent": intent, "direct_text": "", "args": args}
        if intent == "handoff":  # 转人工不再起生成轮，文案在这里算好
            topic = str(args.get("topic") or "").strip()
            update["handoff_text"] = "好的，正在为您转接人工客服，请稍候。"
            update["handoff_reason"] = "用户要求转人工" + (f"：{topic}" if topic else "")
            update["handoff_delta"] = False  # v1 _handoff：落库不发 delta
        return update
    return classify


def _make_kb(store):
    def kb(state, config):
        sid = state["session_id"]
        question = _last_user_text(store, sid)
        hits = support_mod.search(question, store.list_kb_articles())
        if not hits:  # 检索空 → 如实说（不编、不自动转人工）
            store.append_message(sid, "assistant", prompts.FALLBACK_NO_RESULT)
            _emit(config, {"type": "delta", "text": prompts.FALLBACK_NO_RESULT})
            _emit(config, _done(no_result=True))
            return {"ended": True}
        return {
            "branch": "kb",
            "hits": hits,
            "rounds": 0,
            "verify_attempts": 0,
            "messages": [{"role": "system", "content": prompts.kb_system(hits)}, *_history(store, sid)],
        }
    return kb


def _make_answer(llm):
    def answer(state, config):
        final = None
        for ev in llm.chat_stream(messages=state["messages"], tools=ANSWER_TOOLS):
            # 答案未过校验前不直发 delta；思维链（reasoning）不是答案，可直发
            if ev["type"] == "reasoning":
                _emit(config, ev)
            elif ev["type"] == "final":
                final = ev["message"]
        calls = (final or {}).get("tool_calls") or []
        if calls and calls[0].name == "answer_with_citations":
            content = str(calls[0].arguments.get("answer", "")).strip()
        elif not calls:  # 模型忘调工具直接写了答案 → 照样过校验，不豁免
            content = ((final or {}).get("content") or "").strip()
        else:
            content = ""
        update = {"rounds": state["rounds"] + 1, "final": final, "calls": calls, "content": content}
        if content:
            verdict = verify_answer(content, state["hits"])
            update["verdict_ok"] = verdict.ok
            update["verify_reason"] = verdict.reason
            if not verdict.ok:
                update["verify_attempts"] = state["verify_attempts"] + 1
                retryable = bool(calls) and calls[0].name == "answer_with_citations" and update["verify_attempts"] < 2
                if not retryable:  # 二次仍败 / 无工具直答败 → 校验兜底文案在这里算好
                    update["handoff_text"] = prompts.FALLBACK_VERIFY_FAILED
                    update["handoff_reason"] = f"答案校验未通过（{verdict.reason}）"
        return update
    return answer


def _make_feedback():
    def feedback(state):
        call = state["calls"][0]
        payload = json.dumps(
            {
                "ok": False,
                "reason": state["verify_reason"],
                "hint": "答案未通过引用校验（" + state["verify_reason"] + "）："
                        "每个实质内容句末尾必须标注 [片段编号]；"
                        "措辞须贴近片段原文，大幅改写会因词重叠不足被拦截；"
                        "不得补充片段之外的内容。请基于片段重新提交答案。",
            },
            ensure_ascii=False,
        )
        return {"messages": [*state["messages"], state["final"], tool_msg(call.id, payload)]}
    return feedback


def _make_finish(store):
    def finish(state, config):
        sid, content, hits = state["session_id"], state["content"], state["hits"]
        store.append_message(sid, "assistant", content, citations_json=json.dumps(hits, ensure_ascii=False))
        _emit(config, {"type": "delta", "text": content})
        _emit(config, {"type": "citations", "citations": hits})
        _emit(config, _done(citations=hits))
        return {"ended": True}
    return finish


def _make_execute(store):
    def execute(state, config):
        call = state["calls"][0]
        result, event = execute_tool(call.name, call.arguments, store=store, session_id=state["session_id"])
        update = {"messages": [*state["messages"], state["final"], tool_msg(call.id, result)]}
        if event is not None:
            _emit(config, event)
            if event["type"] == "handoff":
                _emit(config, _done("ended", handoff={"reason": event["reason"]}))
                update["ended"] = True
        return update
    return execute


def _make_ticket(llm, store):
    def ticket(state, config):
        messages = state.get("messages") or [
            {"role": "system", "content": prompts.TICKET_SYSTEM},
            *_history(store, state["session_id"]),
        ]
        final = None
        for ev in llm.chat_stream(messages=messages, tools=ANSWER_TOOLS):
            if ev["type"] in ("delta", "reasoning"):  # 工单轮 delta 直发（无校验语义）
                _emit(config, ev)
            elif ev["type"] == "final":
                final = ev["message"]
        calls = (final or {}).get("tool_calls") or []
        update = {
            "branch": "ticket",
            "messages": messages,  # 首入图时构建的工单轮消息必须回写，execute 追加 tool 消息要用
            "rounds": state.get("rounds", 0) + 1,
            "final": final,
            "calls": calls,
        }
        if not calls:
            content = ((final or {}).get("content") or "").strip()
            if content:
                store.append_message(state["session_id"], "assistant", content)
            _emit(config, _done())
            update["ended"] = True
        return update
    return ticket


def _make_chitchat(store):
    def chitchat(state, config):
        direct = state.get("direct_text") or ""
        if direct:  # 意图轮顺带回的文本，直接发
            store.append_message(state["session_id"], "assistant", direct)
            _emit(config, {"type": "delta", "text": direct})
            _emit(config, _done())
            return {"ended": True}
        return {"plain_system": prompts.CHITCHAT_SYSTEM}
    return chitchat


def _make_unknown(store):
    def unknown(state):
        sess = store.get_session(state["session_id"])
        if sess and sess.get("clarified"):
            return {"handoff_text": prompts.FALLBACK_UNKNOWN, "handoff_reason": "意图仍无法识别"}
        store.update_session(state["session_id"], {"clarified": 1})
        return {"plain_system": prompts.CLARIFY_SYSTEM}
    return unknown


def _make_plain(llm, store):
    def plain(state, config):
        """无工具生成轮（澄清/寒暄兜底）：流式直发，落库收尾。"""
        sid = state["session_id"]
        messages = [{"role": "system", "content": state["plain_system"]}, *_history(store, sid)]
        text = ""
        final = None
        for ev in llm.chat_stream(messages=messages):
            if ev["type"] == "delta":
                text += ev["text"]
                _emit(config, ev)
            elif ev["type"] == "reasoning":
                _emit(config, ev)
            elif ev["type"] == "final":
                final = ev["message"]
        content = ((final or {}).get("content") or text).strip()
        if content:
            store.append_message(sid, "assistant", content)
        _emit(config, _done())
        return {"ended": True}
    return plain


def _make_handoff_out(store):
    def handoff_out(state, config):
        """系统级/意图级转人工统一收口：固定文案 → 置状态 → handoff 事件 → done(ended)。"""
        sid = state["session_id"]
        text = state.get("handoff_text") or prompts.FALLBACK_TURN_LIMIT
        reason = state.get("handoff_reason") or "工具轮次触顶"
        store.append_message(sid, "assistant", text)
        if state.get("handoff_delta", True):
            _emit(config, {"type": "delta", "text": text})
        store.update_session(sid, {"status": "handed_off"})
        _emit(config, {"type": "handoff", "reason": reason})
        _emit(config, _done("ended", handoff={"reason": reason}))
        return {"ended": True}
    return handoff_out


# ---- 条件边 ----

def _after_begin(state):
    if state.get("fatal"):
        return END
    if state.get("handoff_text"):
        return "handoff_out"
    return "classify"


def _after_classify(state):
    return {
        "kb": "kb",
        "ticket": "ticket",
        "handoff": "handoff_out",
        "chitchat": "chitchat",
        "unknown": "unknown",
    }[state["intent"]]


def _after_answer(state):
    if state.get("content"):
        if state.get("verdict_ok"):
            return "finish"
        retryable = (
            bool(state["calls"])
            and state["calls"][0].name == "answer_with_citations"
            and state["verify_attempts"] < 2
        )
        if retryable:
            # v1 锚：第 4 轮才失败的可重答，反馈追加后循环自然退出 → 轮次触顶收尾，不起第 5 轮
            return "feedback" if state["rounds"] < _MAX_TOOL_ROUNDS else "handoff_out"
        return "handoff_out"  # 校验失败文案/理由已在 answer 节点算好
    if state["calls"]:
        return "execute"
    if state["rounds"] >= _MAX_TOOL_ROUNDS:
        return "handoff_out"
    return "answer"


def _after_execute(state):
    if state.get("ended"):
        return END
    if state["rounds"] >= _MAX_TOOL_ROUNDS:  # v1 锚：第 4 轮工具先执行完才触顶收尾
        return "handoff_out"
    return "ticket" if state.get("branch") == "ticket" else "answer"


def _after_ticket(state):
    if state.get("ended"):
        return END
    return "execute"


def build_graph(llm, store, max_turns: int = 20):
    g = StateGraph(SupportState)
    g.add_node("begin", _make_begin(store, max_turns))
    g.add_node("classify", _make_classify(llm, store))
    g.add_node("kb", _make_kb(store))
    g.add_node("answer", _make_answer(llm))
    g.add_node("feedback", _make_feedback())
    g.add_node("finish", _make_finish(store))
    g.add_node("execute", _make_execute(store))
    g.add_node("ticket", _make_ticket(llm, store))
    g.add_node("chitchat", _make_chitchat(store))
    g.add_node("unknown", _make_unknown(store))
    g.add_node("plain", _make_plain(llm, store))
    g.add_node("handoff_out", _make_handoff_out(store))

    g.add_edge(START, "begin")
    g.add_conditional_edges("begin", _after_begin, ["classify", "handoff_out", END])
    g.add_conditional_edges("classify", _after_classify, ["kb", "ticket", "handoff_out", "chitchat", "unknown"])
    g.add_conditional_edges("kb", lambda s: END if s.get("ended") else "answer", ["answer", END])
    g.add_conditional_edges("answer", _after_answer, ["finish", "feedback", "execute", "handoff_out", "answer"])
    g.add_edge("feedback", "answer")
    g.add_edge("finish", END)
    g.add_conditional_edges("execute", _after_execute, ["answer", "ticket", "handoff_out", END])
    g.add_conditional_edges("ticket", _after_ticket, ["execute", END])
    g.add_conditional_edges("chitchat", lambda s: END if s.get("ended") else "plain", ["plain", END])
    g.add_conditional_edges("unknown", lambda s: "handoff_out" if s.get("handoff_text") else "plain", ["handoff_out", "plain"])
    g.add_edge("plain", END)
    g.add_edge("handoff_out", END)
    return g.compile()
