"""verify.py 引用校验器——树锚点 M02.F01（引用存在性 / 句级片段重叠）。

突出点件：答案必须句句有据——[n] 引用必须指向本次检索返回的片段，
每个实质内容句与其所引片段的词重叠率 ≥ 阈值；任一不过 → 整体拒绝。
口径从严（知之为知之）：同义改写可能被误杀——那是特性不是缺陷，
误杀走「校验不过→转人工」分支（M02.F02.I03）；提示词会要求模型摘抄片段原文表述。

规则（经测试校准）：
- 短句（内容 token < 4）跳过：太短，无实质内容可校验，也不算内容句。
- 客套句（命中客套模式且 token < 10）跳过：问候/收尾话术天然不来自知识库。
- 实质句：无 [n] → no_citations；[n] 越界 → bad_ref；重叠 < min_overlap → low_overlap。
- 整场没有任何实质句过校验 → no_content。
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from cs_support_agent.kb import tokenize

_REF_RE = re.compile(r"\[(\d+)\]")
_SENT_SPLIT = re.compile(r"[。！？!?\n]+")
_POLITE_RE = re.compile(r"您好|请问|还有什么|其他问题|帮您|祝您|感谢|欢迎|很高兴|为您服务")

MIN_CONTENT_TOKENS = 4
POLITE_MAX_TOKENS = 12  # 「请问还有其他可以帮您的吗」实测 11 token
MIN_OVERLAP = 0.3


@dataclass(frozen=True)
class VerifyVerdict:
    ok: bool
    reason: str  # ok | no_citations | bad_ref | low_overlap | no_content


def split_sentences(answer: str) -> list[str]:
    """按句末标点/换行切句，去空。"""
    return [s for s in _SENT_SPLIT.split(answer) if s.strip()]


def verify_answer(
    answer: str,
    hits: list[Mapping],
    min_overlap: float = MIN_OVERLAP,
) -> VerifyVerdict:
    """校验答案：句级引用存在性 + 片段重叠。任一实质句不过 → 整体拒绝。"""
    n = len(hits)
    content_passed = False
    for sent in split_sentences(answer):
        tokens = tokenize(_REF_RE.sub("", sent))
        if _POLITE_RE.search(sent) and len(tokens) < POLITE_MAX_TOKENS:
            continue  # 客套句
        if len(tokens) < MIN_CONTENT_TOKENS:
            continue  # 短句
        refs = [int(x) for x in _REF_RE.findall(sent)]
        if not refs:
            return VerifyVerdict(False, "no_citations")
        if any(r < 1 or r > n for r in refs):
            return VerifyVerdict(False, "bad_ref")
        cited: set[str] = set()
        for r in refs:
            cited.update(tokenize(hits[r - 1]["snippet"]))
        overlap = len(cited & set(tokens)) / len(tokens)
        if overlap < min_overlap:
            return VerifyVerdict(False, "low_overlap")
        content_passed = True
    if not content_passed:
        return VerifyVerdict(False, "no_content")
    return VerifyVerdict(True, "ok")
