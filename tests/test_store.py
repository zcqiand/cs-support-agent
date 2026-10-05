"""store.py SQLite thin DAO——树锚点 M03.F01 / M00.F01.I02 / M01.F03.I02。

sessions / messages / kb_articles / tickets 四表；:memory: 可跑。
"""
from __future__ import annotations

from cs_support_agent.store import Store


def test_create_and_get_session():
    s = Store(":memory:")
    row = s.create_session(channel="web", user_name="演示用户")
    assert row["status"] == "live"
    got = s.get_session(row["id"])
    assert got is not None and got["channel"] == "web"


def test_update_session_status():
    s = Store(":memory:")
    row = s.create_session(channel="web", user_name="")
    s.update_session(row["id"], {"status": "handed_off"})
    assert s.get_session(row["id"])["status"] == "handed_off"


def test_get_session_missing():
    s = Store(":memory:")
    assert s.get_session("nope") is None


def test_append_and_list_messages():
    s = Store(":memory:")
    sess = s.create_session(channel="web", user_name="")
    s.append_message(sess["id"], "user", "怎么退货")
    s.append_message(sess["id"], "assistant", "签收后 7 天内可退货 [1]。", citations_json='[{"ref":1,"kb_id":"kb-01"}]')
    msgs = s.get_messages(sess["id"])
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["citations_json"].startswith("[")


def test_messages_isolated_by_session():
    s = Store(":memory:")
    a = s.create_session(channel="web", user_name="")
    b = s.create_session(channel="web", user_name="")
    s.append_message(a["id"], "user", "A 的问题")
    s.append_message(b["id"], "user", "B 的问题")
    assert [m["content"] for m in s.get_messages(a["id"])] == ["A 的问题"]


def test_kb_upsert_idempotent_and_list():
    s = Store(":memory:")
    s.upsert_kb_article("kb-01", "售后", "退货政策", "签收后 7 天内可退货。")
    s.upsert_kb_article("kb-01", "售后", "退货政策（修订）", "签收后 15 天内可退货。")
    arts = s.list_kb_articles()
    assert len(arts) == 1
    assert arts[0]["title"] == "退货政策（修订）"
    assert s.get_kb_article("kb-01")["content"].startswith("签收后 15")


def test_ticket_create_and_list():
    s = Store(":memory:")
    sess = s.create_session(channel="web", user_name="")
    t = s.create_ticket(sess["id"], title="无法登录", description="用户反馈密码重置后仍无法登录")
    assert t["status"] == "open"
    rows = s.list_tickets()
    assert len(rows) == 1 and rows[0]["session_id"] == sess["id"]
