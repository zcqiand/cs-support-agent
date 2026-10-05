"""mock_llm.py 运行时离线演示件——树锚点 M04.F02。

分流标记词驱动：意图轮按用户文本标记词分类（handoff>ticket>kb>chitchat>unknown）；
生成轮按 system 提示词特征应答。kb 答案摘抄片段原文+[1]——mock 也守引用铁纪律，
必须能过 verify_answer 校验（否则离线演示会走出「校验失败转人工」假分支）。
"""
from __future__ import annotations

from cs_support_agent.agent import prompts
from cs_support_agent.agent.support import SupportAgent
from cs_support_agent.kb import search
from cs_support_agent.kb_seed import seed_articles
from cs_support_agent.mock_llm import MockLLM
from cs_support_agent.store import Store
from cs_support_agent.verify import verify_answer


def make_store():
    s = Store(":memory:")
    seed_articles(s)
    return s


def intent_of(text):
    llm = MockLLM()
    final = llm.chat(messages=[{"role": "user", "content": text}], tools=[])
    calls = final.get("tool_calls") or []
    if not calls:
        return None  # chitchat 直接回文本，不走分类工具
    return calls[0].arguments["intent"]


def collect(llm, messages, tools=None):
    text = ""
    final = None
    for ev in llm.chat_stream(messages=messages, tools=tools):
        if ev["type"] == "delta":
            text += ev["text"]
        elif ev["type"] == "final":
            final = ev["message"]
    return text, final


# ---- 意图分流（标记词）----

def test_intent_kb_by_marker():
    assert intent_of("商品怎么退货？") == "kb"


def test_intent_kb_salary_is_deliberate_no_result_slot():
    assert intent_of("年终奖什么时候发？") == "kb"  # 种子刻意不覆盖薪酬 → 检索无结果演示


def test_intent_ticket_by_marker():
    assert intent_of("系统登不上了，帮我报障") == "ticket"


def test_intent_handoff_beats_kb():
    assert intent_of("我要投诉，退货太慢了") == "handoff"


def test_intent_chitchat_replies_text_without_tool():
    final = MockLLM().chat(messages=[{"role": "user", "content": "你好"}], tools=[])
    assert final["tool_calls"] is None
    assert "杉杉" in final["content"]


def test_intent_unknown_fallback():
    assert intent_of("嗯嗯就那个事儿") == "unknown"


# ---- 生成轮 ----

def test_kb_answer_copies_snippet_and_passes_verify():
    store = make_store()
    hits = search("商品怎么退货？", store.list_kb_articles())
    assert hits
    llm = MockLLM()
    messages = [{"role": "system", "content": prompts.kb_system(hits)},
                {"role": "user", "content": "商品怎么退货？"}]
    text, final = collect(llm, messages, tools=[])
    assert text and final["content"] == text
    answer = final["content"]
    assert "[1]" in answer
    verdict = verify_answer(answer, hits)
    assert verdict.ok, verdict.reason  # mock 答案必须过校验，否则演示走出假分支


def test_ticket_round_calls_create_ticket_then_wraps_up():
    llm = MockLLM()
    messages = [{"role": "system", "content": prompts.TICKET_SYSTEM},
                {"role": "user", "content": "系统登不上了"}]
    _, final = collect(llm, messages, tools=[])
    assert final["tool_calls"] and final["tool_calls"][0].name == "create_ticket"
    messages2 = [
        *messages, final,
        {"role": "tool", "tool_call_id": final["tool_calls"][0].id, "content": '{"ok": true}'},
    ]
    _, final2 = collect(llm, messages2, tools=[])
    assert final2["tool_calls"] is None
    assert "登记" in final2["content"]


def test_clarify_round_asks_once():
    llm = MockLLM()
    messages = [{"role": "system", "content": prompts.CLARIFY_SYSTEM},
                {"role": "user", "content": "嗯嗯"}]
    _, final = collect(llm, messages)
    assert "说说" in final["content"]


# ---- mini 集成：SupportAgent + MockLLM + 种子库全分支 ----

def _agent(store):
    return SupportAgent(MockLLM(), store)


def test_integration_kb_round_emits_citations():
    store = make_store()
    sess = store.create_session()
    events = list(_agent(store).reply(sess["id"], "商品怎么退货？"))
    types = [e["type"] for e in events]
    assert "citations" in types
    done = events[-1]
    assert done["status"] == "live" and done["citations"]


def test_integration_no_result_branch():
    store = make_store()
    sess = store.create_session()
    events = list(_agent(store).reply(sess["id"], "年终奖什么时候发？"))
    done = events[-1]
    assert done["no_result"] is True and done["status"] == "live"


def test_integration_ticket_round():
    store = make_store()
    sess = store.create_session()
    events = list(_agent(store).reply(sess["id"], "系统登不上了，帮我报障"))
    assert "ticket" in [e["type"] for e in events]
    assert len(store.list_tickets()) == 1


def test_integration_unknown_clarify_then_handoff():
    store = make_store()
    sess = store.create_session()
    e1 = list(_agent(store).reply(sess["id"], "嗯嗯就那个事儿"))
    assert e1[-1]["status"] == "live"
    e2 = list(_agent(store).reply(sess["id"], "就那样"))
    assert e2[-1]["status"] == "ended"


def test_integration_handoff_and_chitchat():
    store = make_store()
    sess = store.create_session()
    events = list(_agent(store).reply(sess["id"], "给我转人工"))
    assert events[-1]["status"] == "ended"
    sess2 = store.create_session()
    events2 = list(_agent(store).reply(sess2["id"], "你好"))
    assert events2[-1]["status"] == "live"
    assert any(e["type"] == "delta" for e in events2)
