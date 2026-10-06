"""support.py 客服 Agent 循环——树锚点 M01.F02.I01/I02/I03、M02.F02 全部。

FakeLLM 脚本化：意图轮走 llm.chat（不流式），面向用户的文本轮走 chat_stream。
事件协议：session/delta/reasoning/citations/ticket/handoff/done/error。
"""
from __future__ import annotations

import json

from cs_support_agent.agent.support import SupportAgent
from cs_support_agent.llm import ToolCall, assistant_msg
from cs_support_agent.store import Store

GOOD_ANSWER = "商品签收后 7 天内可退货 [1]，运费由买家承担 [1]。"
HITS_SNIPPET = "商品签收后 7 天内可退货，运费需保持原包装；非质量问题运费由买家承担。"


def make_agent(turns, max_turns=20):
    store = Store(":memory:")
    store.upsert_kb_article("kb-01", "售后", "退货政策", HITS_SNIPPET)
    agent = SupportAgent(llm=_Fake(turns), store=store, max_turns=max_turns)
    return agent, store


class _Fake:
    """薄壳：把 turns 顺序弹给 chat / chat_stream（接口同 llm.FakeLLM）。"""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    def chat(self, *, messages, tools=None, temperature=0.8):
        self.calls.append({"messages": messages, "tools": tools})
        return self.turns.pop(0)

    def chat_stream(self, *, messages, tools=None, temperature=0.8):
        self.calls.append({"messages": messages, "tools": tools})
        msg = self.turns.pop(0)
        if msg.get("content"):
            yield {"type": "delta", "text": msg["content"]}
        yield {"type": "final", "message": msg}


def intents(name):
    return assistant_msg(None, [ToolCall(id="c1", name="classify_intent", arguments={"intent": name})])


def by_types(events):
    return [e["type"] for e in events]


def last(events):
    return events[-1]


# ---- kb 分支 ----

def test_kb_branch_happy_path():
    agent, store = make_agent([
        intents("kb"),
        assistant_msg(None, [ToolCall(id="c2", name="answer_with_citations", arguments={"answer": GOOD_ANSWER})]),
    ])
    sess = store.create_session()
    events = list(agent.reply(sess["id"], "怎么退货？"))
    assert by_types(events)[:1] == ["session"]
    assert "citations" in by_types(events)
    done = last(events)
    assert done["type"] == "done" and done["status"] == "live"
    assert done["citations"][0]["id"] == "kb-01"
    msgs = store.get_messages(sess["id"])
    assert msgs[-1]["role"] == "assistant" and GOOD_ANSWER in msgs[-1]["content"]
    # 第二轮 LLM 调用的 system 含检索片段
    kb_call = agent.llm.calls[1]
    assert "商品签收后 7 天内可退货" in kb_call["messages"][0]["content"]


def test_kb_branch_rejects_uncited_answer_and_hands_off():
    agent, store = make_agent([
        intents("kb"),
        assistant_msg(None, [ToolCall(id="c2", name="answer_with_citations",
                                      arguments={"answer": "上门取件完全免费 [1]。"})]),
        assistant_msg(None, [ToolCall(id="c3", name="answer_with_citations",
                                      arguments={"answer": "上门取件完全免费，一分钱不花 [1]。"})]),
    ])
    sess = store.create_session()
    events = list(agent.reply(sess["id"], "怎么退货？"))
    types = by_types(events)
    assert "handoff" in types
    done = last(events)
    assert done["status"] == "ended"
    assert store.get_session(sess["id"])["status"] == "handed_off"
    msgs = store.get_messages(sess["id"])
    assert "转接人工" in msgs[-1]["content"]  # 固定兜底文案，编造答案未落库


def test_kb_verify_feedback_retry_then_success():
    """自我校验反馈环（C038）：一次校验失败先喂回原因重答，二次通过才发给用户。"""
    agent, store = make_agent([
        intents("kb"),
        assistant_msg(None, [ToolCall(id="c2", name="answer_with_citations",
                                      arguments={"answer": "上门取件完全免费 [1]。"})]),
        assistant_msg(None, [ToolCall(id="c3", name="answer_with_citations",
                                      arguments={"answer": GOOD_ANSWER})]),
    ])
    sess = store.create_session()
    events = list(agent.reply(sess["id"], "怎么退货？"))
    done = last(events)
    assert done["status"] == "live" and done["citations"]
    assert "citations" in by_types(events)
    # 第三轮 LLM 调用的 messages 里带校验失败反馈（tool 消息）
    retry_messages = agent.llm.calls[2]["messages"]
    assert any(m["role"] == "tool" and "未通过引用校验" in m["content"] for m in retry_messages)


def test_kb_branch_no_result_says_so_without_llm():
    agent, store = make_agent([intents("kb")])  # 生成轮不应被调用
    sess = store.create_session()
    events = list(agent.reply(sess["id"], "年终奖什么时候发？"))
    types = by_types(events)
    assert types == ["session", "delta", "done"]
    assert last(events)["no_result"] is True
    assert last(events)["status"] == "live"


# ---- ticket / handoff / chitchat / 澄清 ----

def test_ticket_branch_creates_ticket():
    agent, store = make_agent([
        intents("ticket"),
        assistant_msg(None, [ToolCall(id="c2", name="create_ticket",
                                      arguments={"title": "无法登录", "description": "重置后仍失败"})]),
        assistant_msg("已为您登记工单，人工会尽快跟进。"),
    ])
    sess = store.create_session()
    events = list(agent.reply(sess["id"], "我登录不上去了"))
    types = by_types(events)
    assert "ticket" in types
    assert last(events)["status"] == "live"
    assert len(store.list_tickets()) == 1
    assert "已为您登记工单" in store.get_messages(sess["id"])[-1]["content"]


def test_handoff_branch_ends_session():
    agent, store = make_agent([
        intents("handoff"),
        assistant_msg(None, [ToolCall(id="c2", name="handoff_to_human", arguments={"reason": "用户要求"})]),
    ])
    sess = store.create_session()
    events = list(agent.reply(sess["id"], "给我转人工"))
    assert by_types(events) == ["session", "handoff", "done"]
    assert last(events)["status"] == "ended"
    assert store.get_session(sess["id"])["status"] == "handed_off"


def test_chitchat_streams_without_tools():
    agent, store = make_agent([assistant_msg("您好呀，很高兴见到您～")])  # 意图轮直接回文本=寒暄
    sess = store.create_session()
    events = list(agent.reply(sess["id"], "你好"))
    types = by_types(events)
    assert "delta" in types
    assert last(events)["status"] == "live"
    assert last(events)["ticket"] is None


def test_unknown_first_time_clarifies_then_second_time_hands_off():
    agent, store = make_agent([
        intents("unknown"),
        assistant_msg("方便说说您遇到的具体问题吗？"),
        intents("unknown"),  # 第二次仍 unknown → 不再澄清
    ])
    sess = store.create_session()
    events1 = list(agent.reply(sess["id"], "嗯……就那个事儿"))
    assert last(events1)["status"] == "live"
    assert store.get_session(sess["id"])["clarified"] == 1
    events2 = list(agent.reply(sess["id"], "对，就是那个"))
    assert "handoff" in by_types(events2)
    assert last(events2)["status"] == "ended"


# ---- 护栏与错误 ----

def test_reply_404_yields_error():
    agent, store = make_agent([])
    events = list(agent.reply("no-such-session", "hi"))
    assert events[0]["type"] == "error" and "不存在" in events[0]["message"]


def test_reply_after_handoff_yields_error():
    agent, store = make_agent([])
    sess = store.create_session()
    store.update_session(sess["id"], {"status": "handed_off"})
    events = list(agent.reply(sess["id"], "还有个问题"))
    assert events[0]["type"] == "error" and "人工" in events[0]["message"]


def test_turn_limit_forces_handoff_without_llm():
    agent, store = make_agent([], max_turns=2)
    sess = store.create_session()
    store.append_message(sess["id"], "user", "一")
    store.append_message(sess["id"], "assistant", "答一")
    store.append_message(sess["id"], "user", "二")
    store.append_message(sess["id"], "assistant", "答二")
    events = list(agent.reply(sess["id"], "三"))
    assert "handoff" in by_types(events)
    assert last(events)["status"] == "ended"
    assert agent.llm.calls == []  # 上限收尾不调 LLM


def test_search_crash_becomes_error_event_not_crash(monkeypatch):
    agent, store = make_agent([intents("kb")])
    import cs_support_agent.agent.support as support_mod

    def boom(*a, **k):
        raise RuntimeError("检索器炸了")

    monkeypatch.setattr(support_mod, "search", boom)
    sess = store.create_session()
    events = list(agent.reply(sess["id"], "怎么退货？"))
    assert events[0]["type"] == "session"
    assert events[-1]["type"] == "error"
    assert "检索器炸了" in events[-1]["message"]
    assert store.get_session(sess["id"])["status"] == "live"  # 会话未崩


def test_reply_wraps_pre_route_crash_as_error_event(monkeypatch):
    """v1 的 try/except 只护 _route 之后的段落；v2 图内一切异常都转 error 事件（含 session 事件之前的落库段）。"""
    agent, store = make_agent([intents("kb")])

    def boom(*a, **k):
        raise RuntimeError("append 炸了")

    monkeypatch.setattr(store, "append_message", boom)
    sess = store.create_session()
    events = list(agent.reply(sess["id"], "怎么退货？"))
    assert events[0]["type"] == "error"
    assert "append 炸了" in events[0]["message"]
