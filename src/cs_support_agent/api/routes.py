"""REST + SSE 路由（M03——M05 前端唯一消费面）。

SSE 事件直通：SupportAgent.reply 产出的事件逐条 data: 转发，不在路由层加工；
会话不存在走 HTTP 404，已转人工等业务状态走 SSE error 事件（资源在，状态受限）。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from cs_support_agent.agent.support import SupportAgent

router = APIRouter(prefix="/api")


class SessionIn(BaseModel):
    channel: str = "web"
    user_name: str = ""


class MessageIn(BaseModel):
    text: str


# ---- 会话 ----


@router.post("/sessions", status_code=201)
def create_session(body: SessionIn, request: Request):
    return request.app.state.store.create_session(body.channel, body.user_name)


@router.get("/sessions/{sid}")
def get_session_detail(sid: str, request: Request):
    store = request.app.state.store
    sess = store.get_session(sid)
    if sess is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = []
    for m in store.get_messages(sid):
        try:
            citations = json.loads(m["citations_json"])
        except json.JSONDecodeError:
            citations = []
        messages.append(
            {
                "id": m["id"],
                "role": m["role"],
                "content": m["content"],
                "citations": citations,
                "created_at": m["created_at"],
            }
        )
    return {"session": sess, "messages": messages}


@router.post("/sessions/{sid}/messages")
def post_message(sid: str, body: MessageIn, request: Request):
    store = request.app.state.store
    if store.get_session(sid) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    agent = SupportAgent(request.app.state.llm, store)

    def gen():
        for event in agent.reply(sid, body.text):
            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---- 知识库 ----


@router.get("/kb")
def list_kb(request: Request):
    return request.app.state.store.list_kb_articles()


@router.get("/kb/{kb_id}")
def get_kb(kb_id: str, request: Request):
    row = request.app.state.store.get_kb_article(kb_id)
    if row is None:
        raise HTTPException(status_code=404, detail="知识库条目不存在")
    return row


# ---- 工单 ----


@router.get("/tickets")
def list_tickets(request: Request):
    return request.app.state.store.list_tickets()
