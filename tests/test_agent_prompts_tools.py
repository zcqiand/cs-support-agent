"""prompts.py / tools.py——树锚点 M01.F01.I01、M01.F02.I01、M01.F03.I02。"""
from __future__ import annotations

from cs_support_agent.agent import prompts, tools
from cs_support_agent.store import Store


# ---- prompts ----

def test_intent_system_names_four_intents_and_tool():
    s = prompts.INTENT_SYSTEM
    for word in ("kb", "ticket", "handoff", "chitchat", "unknown", "classify_intent"):
        assert word in s


def test_kb_system_injects_hits_with_refs_and_rules():
    hits = [
        {"category": "售后", "title": "退货政策", "score": 0.31,
         "snippet": "商品签收后 7 天内可退货，运费买家承担。"},
    ]
    s = prompts.kb_system(hits)
    assert "[1]" in s and "商品签收后 7 天内可退货" in s
    assert "转人工" in s and "绝不编造" in s


def test_kb_system_accepts_generator():
    hits = iter([
        {"category": "账号", "title": "密码重置", "score": 0.2, "snippet": "手机验证码重置。"},
    ])
    s = prompts.kb_system(hits)
    assert "[1]" in s and "手机验证码" in s


def test_ticket_and_chitchat_and_clarify_personas():
    assert "create_ticket" in prompts.TICKET_SYSTEM
    assert "简短" in prompts.CHITCHAT_SYSTEM
    assert "澄清" in prompts.CLARIFY_SYSTEM


def test_fallback_copy_exists_and_fiction_safe():
    assert "转人工" in prompts.FALLBACK_NO_RESULT
    assert "转接人工" in prompts.FALLBACK_VERIFY_FAILED
    assert "上限" in prompts.FALLBACK_TURN_LIMIT


# ---- tools ----

def test_tools_schema_four_tools():
    names = [t["function"]["name"] for t in tools.TOOLS]
    assert names == ["classify_intent", "answer_with_citations", "create_ticket", "handoff_to_human"]
    enums = tools.TOOLS[0]["function"]["parameters"]["properties"]["intent"]["enum"]
    assert set(enums) == {"kb", "ticket", "handoff", "chitchat", "unknown"}


def test_execute_classify_and_answer_return_no_event():
    s = Store(":memory:")
    res, ev = tools.execute_tool("classify_intent", {"intent": "kb"}, store=s, session_id="x")
    assert '"kb"' in res and ev is None
    res2, ev2 = tools.execute_tool("answer_with_citations", {"answer": "文本 [1]"}, store=s, session_id="x")
    assert ev2 is None and "ok" in res2


def test_execute_create_ticket_persists_and_emits_event():
    s = Store(":memory:")
    sess = s.create_session()
    res, ev = tools.execute_tool(
        "create_ticket",
        {"title": "无法登录", "description": "重置后仍失败"},
        store=s,
        session_id=sess["id"],
    )
    assert ev is not None and ev["type"] == "ticket"
    assert ev["ticket"]["status"] == "open"
    assert "ticket_id" in res
    assert len(s.list_tickets()) == 1


def test_execute_handoff_updates_session_status():
    s = Store(":memory:")
    sess = s.create_session()
    _, ev = tools.execute_tool(
        "handoff_to_human", {"reason": "用户要求"}, store=s, session_id=sess["id"]
    )
    assert ev == {"type": "handoff", "reason": "用户要求"}
    assert s.get_session(sess["id"])["status"] == "handed_off"


def test_execute_unknown_tool():
    s = Store(":memory:")
    res, ev = tools.execute_tool("nope", {}, store=s, session_id="x")
    assert "未知工具" in res and ev is None
