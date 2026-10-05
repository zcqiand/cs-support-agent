"""API e2e（TestClient，LLM_MODE=mock 全链路离线）——树锚点 M03。

流程：建会话 → kb 咨询（引用）/ 无结果 / 报障开单 / 澄清-转人工 → 会话详情 → 工单列表。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from cs_support_agent.config import load_settings
from cs_support_agent.main import create_app
from cs_support_agent.mock_llm import MockLLM
from cs_support_agent.store import Store


@pytest.fixture()
def client(tmp_path):
    settings = load_settings(environ={"LLM_MODE": "mock"}, env_file=tmp_path / "no.env")
    app = create_app(settings, llm=MockLLM(), store=Store(str(tmp_path / "api.db")))
    with TestClient(app) as c:
        yield c


def _sse_events(text: str) -> list[dict]:
    return [
        json.loads(line[len("data: "):])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


def _new_session(client) -> str:
    r = client.post("/api/sessions", json={"user_name": "测试用户"})
    assert r.status_code == 201
    return r.json()["id"]


def _say(client, sid: str, text: str) -> list[dict]:
    r = client.post(f"/api/sessions/{sid}/messages", json={"text": text})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    return _sse_events(r.text)


# ---- 知识库 ----


def test_kb_list_seeded_and_detail(client):
    r = client.get("/api/kb")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 16  # 种子全量入库（create_app 注入）
    first = items[0]
    for key in ("id", "category", "title", "content"):
        assert key in first
    r = client.get("/api/kb/kb-01")
    assert r.status_code == 200
    assert r.json()["title"] == "退货政策"
    assert client.get("/api/kb/nope").status_code == 404


# ---- 会话与消息 ----


def test_create_session_201(client):
    r = client.post("/api/sessions", json={"user_name": "张三"})
    body = r.json()
    assert r.status_code == 201
    assert body["status"] == "live" and body["id"]


def test_message_kb_flow_emits_citations(client):
    sid = _new_session(client)
    events = _say(client, sid, "商品怎么退货？")
    types = [e["type"] for e in events]
    assert types[0] == "session" and "delta" in types
    assert "citations" in types
    done = events[-1]
    assert done["type"] == "done" and done["status"] == "live"
    assert done["citations"][0]["id"] == "kb-01"


def test_message_no_result_branch(client):
    sid = _new_session(client)
    events = _say(client, sid, "年终奖什么时候发？")
    done = events[-1]
    assert done["no_result"] is True and done["status"] == "live"


def test_message_ticket_flow_and_listing(client):
    sid = _new_session(client)
    events = _say(client, sid, "系统登不上了，帮我报障")
    assert "ticket" in [e["type"] for e in events]
    assert events[-1]["status"] == "live"
    tickets = client.get("/api/tickets").json()
    assert len(tickets) == 1
    assert tickets[0]["status"] == "open" and tickets[0]["session_id"] == sid


def test_message_unknown_clarifies_then_hands_off(client):
    sid = _new_session(client)
    e1 = _say(client, sid, "嗯嗯就那个事儿")
    assert e1[-1]["status"] == "live"  # 第一次：澄清
    e2 = _say(client, sid, "就那样")
    assert "handoff" in [e["type"] for e in e2]
    assert e2[-1]["status"] == "ended"
    # 已转人工后再发消息 → SSE error 事件（不是 HTTP 错误）
    e3 = _say(client, sid, "还有个问题")
    assert e3[0]["type"] == "error" and "人工" in e3[0]["message"]


def test_message_unknown_session_404(client):
    r = client.post("/api/sessions/nope/messages", json={"text": "在吗"})
    assert r.status_code == 404


def test_session_detail_with_messages(client):
    sid = _new_session(client)
    _say(client, sid, "商品怎么退货？")
    r = client.get(f"/api/sessions/{sid}")
    assert r.status_code == 200
    body = r.json()
    assert body["session"]["status"] == "live"
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant"]
    assert body["messages"][1]["citations"]  # citations_json 已解析成列表
    assert client.get("/api/sessions/nope").status_code == 404
