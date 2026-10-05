"""kb.py 检索器——树锚点 M00.F02（分词向量化 / 余弦 TopK / 命中阈值）。

纯 stdlib、确定性、无网可跑：同一知识库同一问句，两次检索结果必须一致。
阈值语义：最高分低于 min_score → 返回空列表，即「检索无结果」分支。
"""
from __future__ import annotations

from cs_support_agent.kb import tokenize, vectorize, cosine, search

# ---- 分词与向量化（M00.F02.I01）----

def test_tokenize_cjk_bigram():
    assert tokenize("退货政策") == ["退货", "货政", "政策"]


def test_tokenize_ascii_words_lowercased():
    assert tokenize("FastAPI 50元") == ["fastapi", "50", "元"]  # 单个 CJK 字不成 bigram 也应计为 token


def test_tokenize_mixed():
    toks = tokenize("发票抬头 FastAPI")
    assert "发票" in toks and "票抬" in toks and "fastapi" in toks


def test_vectorize_counts():
    v = vectorize("退货、退货、退款")
    assert v["退货"] == 2 and v["退款"] == 1


def test_cosine_identical_is_one():
    v = vectorize("退货政策")
    assert cosine(v, v) == pytest.approx(1.0)


def test_cosine_disjoint_is_zero():
    assert cosine(vectorize("退货"), vectorize("发票")) == 0.0


# ---- 检索（M00.F02.I02）----

KB = [
    {"id": "kb-1", "title": "退货政策", "text": "商品签收后 7 天内可退货，运费买家承担。"},
    {"id": "kb-2", "title": "发票开具", "text": "支持电子发票，下单后 30 天内可开具。"},
    {"id": "kb-3", "title": "账号注销", "text": "账号注销后数据不可恢复，请谨慎操作。"},
]


def test_search_hits_relevant_article():
    hits = search("我想退货", KB)
    assert hits and hits[0]["id"] == "kb-1"
    assert hits[0]["score"] > 0


def test_search_no_result_below_threshold():
    # 与知识库完全无关的问句 → 检索无结果（阈值拦截）
    hits = search("今天外面天气怎么样", KB)
    assert hits == []


def test_search_topk_limit_and_order():
    hits = search("退货 发票", KB, top_k=2)
    assert len(hits) <= 2
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_search_deterministic():
    a = search("注销账号要几天", KB)
    b = search("注销账号要几天", KB)
    assert a == b


def test_search_returns_snippet_fields():
    hits = search("怎么开发票", KB)
    assert hits
    h = hits[0]
    assert h["id"] == "kb-2"
    assert "title" in h and "snippet" in h and "score" in h
