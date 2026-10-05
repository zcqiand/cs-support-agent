"""知识库与本地检索——树锚点 M00.F02（分词向量化 / 余弦 TopK / 命中阈值）。

纯 stdlib、确定性、无网可跑：同一知识库同一问句，两次检索结果必须一致。
阈值语义：最高分低于 min_score → 返回空列表，即「检索无结果」分支（M02.F02.I01）。
书 C033 向量检索的「词频向量」口径：向量化=可数、相似度=可算，教学直觉优先于检索质量。
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping

_TOKEN = re.compile(r"[一-鿿]+|[a-z0-9]+")

DEFAULT_MIN_SCORE = 0.12
DEFAULT_TOP_K = 3


def tokenize(text: str) -> list[str]:
    """CJK 段切 bigram（单字成 token），ASCII 段整词小写。确定性。"""
    tokens: list[str] = []
    for m in _TOKEN.finditer(text.lower()):
        seg = m.group()
        if seg[0] >= "一":
            if len(seg) == 1:
                tokens.append(seg)
            else:
                tokens.extend(seg[i : i + 2] for i in range(len(seg) - 1))
        else:
            tokens.append(seg)
    return tokens


def vectorize(text: str) -> Counter:
    """词频向量。"""
    return Counter(tokenize(text))


def cosine(a: Mapping[str, int], b: Mapping[str, int]) -> float:
    """余弦相似度；零向量返回 0.0。"""
    dot = sum(cnt * b.get(k, 0) for k, cnt in a.items())
    if dot == 0:
        return 0.0
    na = sum(c * c for c in a.values()) ** 0.5
    nb = sum(c * c for c in b.values()) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def search(
    query: str,
    articles: Iterable[Mapping],
    top_k: int = DEFAULT_TOP_K,
    min_score: float = DEFAULT_MIN_SCORE,
) -> list[dict]:
    """检索 TopK 命中。文档向量 = title 词频 ×3 + content 词频；低于 min_score 全丢弃。

    文章字段沿用 store 行形状 {"id","title","content",...}；
    命中项 {"id","title","snippet","score"}，按分数降序（同分按 id，确定性）。
    """
    qv = vectorize(query)
    if not qv:
        return []
    hits: list[dict] = []
    for art in articles:
        dv: Counter = Counter()
        for k, cnt in vectorize(art["title"]).items():
            dv[k] += cnt * 3
        for k, cnt in vectorize(art["content"]).items():
            dv[k] += cnt
        score = cosine(qv, dv)
        if score >= min_score:
            hits.append(
                {
                    "id": art["id"],
                    "category": art.get("category", ""),
                    "title": art["title"],
                    "snippet": art["content"],
                    "score": round(score, 4),
                }
            )
    hits.sort(key=lambda h: (-h["score"], h["id"]))
    return hits[:top_k]
