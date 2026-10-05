"""kb_seed.py 种子 FAQ——树锚点 M00.F01.I01。

种子内容必须：全虚构、三类覆盖、可支撑检索冒烟，
并刻意留出「知识库没有的领域」供检索无结果分支演示。
"""
from __future__ import annotations

from cs_support_agent import kb_seed
from cs_support_agent.kb import search
from cs_support_agent.store import Store


def test_seed_has_enough_articles():
    assert len(kb_seed.SEED_ARTICLES) >= 12


def test_seed_covers_three_categories():
    cats = {a["category"] for a in kb_seed.SEED_ARTICLES}
    assert {"售后", "账号", "报销"} <= cats


def test_seed_fields_wellformed():
    for a in kb_seed.SEED_ARTICLES:
        assert a["id"].startswith("kb-")
        assert a["title"].strip() and a["content"].strip()
        assert "snippet" not in a  # snippet 是检索产物，不入种子


def test_module_declares_fiction():
    assert kb_seed.__doc__ is not None and "虚构" in kb_seed.__doc__


def test_seed_articles_idempotent():
    s = Store(":memory:")
    n1 = kb_seed.seed_articles(s)
    n2 = kb_seed.seed_articles(s)
    assert n1 == n2 == len(kb_seed.SEED_ARTICLES)
    assert len(s.list_kb_articles()) == len(kb_seed.SEED_ARTICLES)


def test_seed_search_hit_after_sale():
    s = Store(":memory:")
    kb_seed.seed_articles(s)
    hits = search("怎么申请退货", s.list_kb_articles())
    assert hits and hits[0]["id"] == "kb-01"


def test_seed_search_hit_expense():
    s = Store(":memory:")
    kb_seed.seed_articles(s)
    hits = search("差旅住宿报销标准", s.list_kb_articles())
    assert hits and hits[0]["category"] == "报销"


def test_seed_search_miss_leaves_room_for_no_result_branch():
    # 刻意不入库的领域 → 检索无结果（M02.F02.I01 演示用）
    s = Store(":memory:")
    kb_seed.seed_articles(s)
    assert search("年终奖什么时候发", s.list_kb_articles()) == []
