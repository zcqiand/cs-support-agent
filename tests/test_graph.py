"""graph.py 客服流程图——五路由 / 校验重答条件边 / 转人工入图（直连 invoke，不经 SSE 接线）。

直连 invoke 的排空必须用 get_nowait 循环：None 哨兵由接线层（support.SupportAgent._run）
put，图本身从不 put——用 iter(events.get, None) 会永久阻塞（kids-english T2 同款教训）。
"""
from __future__ import annotations

import json
import queue

from cs_support_agent.agent.graph import build_graph
from cs_support_agent.llm import ToolCall, assistant_msg
from cs_support_agent.store import Store

GOOD_ANSWER = "商品签收后 7 天内可退货 [1]，运费由买家承担 [1]。"
BAD_ANSWER = "上门取件完全免费 [1]。"
HITS_SNIPPET = "商品签收后 7 天内可退货，运费需保持原包装；非质量问题运费由买家承担。"


def make_store():
    store = Store(":memory:")
    store.upsert_kb_article("kb-01", "售后", "退货政策", HITS_SNIPPET)
    return store


def intents(name, topic=None):
    args = {"intent": name}
    if topic:
        args["topic"] = topic
    return assistant_msg(None, [ToolCall(id="c1", name="classify_intent", arguments=args)])


def answer_call(answer, cid="c2"):
    return assistant_msg(None, [ToolCall(id=cid, name="answer_with_citations", arguments={"answer": answer})])


def ticket_call(cid="c2"):
    return assistant_msg(None, [ToolCall(id=cid, name="create_ticket",
                                         arguments={"title": "无法登录", "description": "重置后仍失败"})])


class _Fake:
    """薄壳：把 turns 顺序弹给 chat / chat_stream（接口同 llm.FakeLLM）。"""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    def chat(self, *, messages, tools=None, temperature=0.8):
        self.calls.append({"messages": messages, "tools": tools})
        msg = self.turns.pop(0)
        if isinstance(msg, BaseException):
            raise msg
        return msg

    def chat_stream(self, *, messages, tools=None, temperature=0.8):
        self.calls.append({"messages": messages, "tools": tools})
        msg = self.turns.pop(0)
        if isinstance(msg, BaseException):
            raise msg
        if isinstance(msg, dict) and "reasoning" in msg:  # reasoning 事件 + final
            yield {"type": "reasoning", "text": msg["reasoning"]}
            msg = msg["message"]
        if msg.get("content"):
            yield {"type": "delta", "text": msg["content"]}
        yield {"type": "final", "message": msg}


def _run(llm, text="怎么退货？", *, store=None, session_id=None, max_turns=20):
    store = store or make_store()
    if session_id is None:
        session_id = store.create_session()["id"]
    events = queue.SimpleQueue()
    state = {"session_id": session_id, "text": text}
    build_graph(llm, store, max_turns).invoke(state, {"configurable": {"events": events}})
    out = []
    while True:
        try:
            out.append(events.get_nowait())
        except queue.Empty:
            return out


def by_types(events):
    return [e["type"] for e in events]


def _sid(events):
    return events[0]["session_id"]


# ---- kb 分支 ----

def test_graph_kb_happy_path():
    store = make_store()
    llm = _Fake([intents("kb"), answer_call(GOOD_ANSWER)])
    events = _run(llm, store=store)
    types = by_types(events)
    assert types[0] == "session"
    assert "citations" in types
    done = events[-1]
    assert done["type"] == "done" and done["status"] == "live"
    assert done["citations"][0]["id"] == "kb-01"
    # answer 轮的 system 含检索片段
    assert "商品签收后 7 天内可退货" in llm.calls[1]["messages"][0]["content"]
    # 落库带 citations_json
    last_msg = store.get_messages(_sid(events))[-1]
    assert last_msg["role"] == "assistant" and GOOD_ANSWER in last_msg["content"]


def test_graph_kb_no_result_says_so_without_llm():
    llm = _Fake([intents("kb")])
    events = _run(llm, text="年终奖什么时候发？")
    assert by_types(events) == ["session", "delta", "done"]
    assert events[-1]["no_result"] is True and events[-1]["status"] == "live"
    assert len(llm.calls) == 1  # 检索空不进生成轮


def test_graph_verify_feedback_reanswer_cycle():
    """校验反馈环（C038）+ reasoning 直发/delta 缓冲锚。"""
    llm = _Fake([
        intents("kb"),
        {"reasoning": "让我想想……", "message": answer_call(BAD_ANSWER)},
        answer_call(GOOD_ANSWER, cid="c3"),
    ])
    events = _run(llm)
    types = by_types(events)
    assert types == ["session", "reasoning", "delta", "citations", "done"]
    assert events[-1]["status"] == "live" and events[-1]["citations"]
    # 重答轮的 messages 里有校验失败反馈（tool 消息，配对 tool_call）
    retry_messages = llm.calls[2]["messages"]
    assert any(m["role"] == "tool" and "未通过引用校验" in m["content"] for m in retry_messages)


def test_graph_verify_fail_twice_hands_off():
    llm = _Fake([intents("kb"), answer_call(BAD_ANSWER), answer_call(BAD_ANSWER, cid="c3")])
    store = make_store()
    events = _run(llm, store=store)
    types = by_types(events)
    assert "handoff" in types
    done = events[-1]
    assert done["status"] == "ended"
    assert store.get_session(_sid(events))["status"] == "handed_off"
    assert BAD_ANSWER not in [m["content"] for m in store.get_messages(_sid(events))]
    assert len(llm.calls) == 3  # 意图 + 两次作答，二次败即收尾


def test_graph_no_tool_direct_answer_fail_hands_off_immediately():
    llm = _Fake([intents("kb"), assistant_msg("上门取件完全免费，一分钱不花。")])
    events = _run(llm)
    assert by_types(events) == ["session", "delta", "handoff", "done"]
    assert events[-1]["status"] == "ended"
    assert len(llm.calls) == 2  # 直答败不重答


def test_graph_fourth_round_tool_executes_then_handoff():
    llm = _Fake([intents("kb"), ticket_call("t1"), ticket_call("t2"), ticket_call("t3"), ticket_call("t4")])
    store = make_store()
    events = _run(llm, store=store)
    types = by_types(events)
    assert types == ["session", "ticket", "ticket", "ticket", "ticket", "delta", "handoff", "done"]
    assert events[-2]["reason"] == "工具轮次触顶"
    assert events[-1]["status"] == "ended"
    assert len(llm.calls) == 5  # 第 4 轮工具先执行，绝不起第 5 轮
    assert len(store.list_tickets()) == 4


# ---- Review Focus 1：第 4 轮才失败的可重答 → 轮次触顶，不起第 5 轮 ----

def test_graph_round4_retryable_fail_takes_turn_limit_not_fifth_call():
    llm = _Fake([intents("kb"), ticket_call("t1"), ticket_call("t2"), ticket_call("t3"), answer_call(BAD_ANSWER, "t4")])
    events = _run(llm)
    types = by_types(events)
    assert types == ["session", "ticket", "ticket", "ticket", "delta", "handoff", "done"]
    assert events[-2]["reason"] == "工具轮次触顶"  # 不是「答案校验未通过」
    assert len(llm.calls) == 5


# ---- ticket / handoff / chitchat / 澄清 ----

def test_graph_ticket_branch_round():
    store = make_store()
    llm = _Fake([
        intents("ticket"),
        ticket_call(),
        assistant_msg("已为您登记工单，人工会尽快跟进。"),
    ])
    events = _run(llm, text="系统登不上了，帮我报障", store=store)
    types = by_types(events)
    assert "ticket" in types
    assert events[-1]["status"] == "live"
    assert len(store.list_tickets()) == 1
    assert "已为您登记工单" in store.get_messages(_sid(events))[-1]["content"]


def test_graph_handoff_intent_no_generation_round():
    store = make_store()
    llm = _Fake([intents("handoff", topic="投诉物流")])
    events = _run(llm, text="给我转人工", store=store)
    assert by_types(events) == ["session", "handoff", "done"]
    assert events[1]["reason"] == "用户要求转人工：投诉物流"
    assert events[-1]["status"] == "ended"
    assert len(llm.calls) == 1  # 不起生成轮
    assert store.get_session(_sid(events))["status"] == "handed_off"


def test_graph_chitchat_direct_text():
    llm = _Fake([assistant_msg("您好呀，很高兴见到您～")])  # 意图轮直回文本=寒暄
    events = _run(llm, text="你好")
    assert by_types(events) == ["session", "delta", "done"]
    assert events[1]["text"] == "您好呀，很高兴见到您～"


def test_graph_unknown_clarify_then_second_handoff():
    store = make_store()
    sid = store.create_session()["id"]
    llm1 = _Fake([intents("unknown"), assistant_msg("方便说说您遇到的具体问题吗？")])
    e1 = _run(llm1, text="嗯……就那个事儿", store=store, session_id=sid)
    assert e1[-1]["status"] == "live"
    assert store.get_session(sid)["clarified"] == 1
    llm2 = _Fake([intents("unknown")])
    e2 = _run(llm2, text="对，就是那个", store=store, session_id=sid)
    assert "handoff" in by_types(e2)
    assert e2[-1]["status"] == "ended"


# ---- 审查 Important 2 锚：clarified 落库先于澄清轮成败（接受的 v1→v2 分歧） ----

def test_graph_clarified_persists_before_clarification_round_succeeds():
    """v2 在 unknown 分诊时即落库 clarified；v1 是澄清轮成功后才置位。
    分歧面：澄清轮崩掉 → v2 下一条含糊消息直接转人工（安全兜底），v1 会再澄清一次。
    裁定接受 v2 排序（转人工即安全路径），本测试钉住之。"""
    store = make_store()
    sid = store.create_session()["id"]
    llm1 = _Fake([intents("unknown"), RuntimeError("澄清轮 LLM 崩了")])
    try:
        _run(llm1, text="嗯……就那个事儿", store=store, session_id=sid)
    except RuntimeError:
        pass  # 直连 invoke 异常上抛；接线层才会把它转成 error 事件
    assert store.get_session(sid)["clarified"] == 1  # 崩了也已落库
    llm2 = _Fake([intents("unknown")])
    e2 = _run(llm2, text="对，就是那个", store=store, session_id=sid)
    assert "handoff" in by_types(e2)  # 不再二次澄清，直接人工兜底
    assert e2[-1]["status"] == "ended"
    assert len(llm2.calls) == 1


# ---- 护栏 ----

def test_graph_turn_limit_guard_skips_llm():
    store = make_store()
    sid = store.create_session()["id"]
    for i in ("一", "二"):
        store.append_message(sid, "user", i)
        store.append_message(sid, "assistant", f"答{i}")
    llm = _Fake([])
    events = _run(llm, text="三", store=store, session_id=sid, max_turns=2)
    assert by_types(events) == ["session", "delta", "handoff", "done"]
    assert events[-1]["status"] == "ended"
    assert llm.calls == []  # 上限收尾不调 LLM
