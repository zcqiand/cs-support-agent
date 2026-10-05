"""verify.py 引用校验器——树锚点 M02.F01（引用存在性 / 句级片段重叠）。

突出点件：答案必须句句有据——[n] 引用必须指向本次检索返回的片段，
每个实质内容句与其所引片段的词重叠率 ≥ 阈值；任一不过 → 整体拒绝。
口径从严（知之为知之）：同义改写可能被误杀——那是特性不是缺陷，
误杀走「校验不过→转人工」分支；提示词会要求模型摘抄片段原文表述。
"""
from __future__ import annotations

import pytest

from cs_support_agent.verify import split_sentences, verify_answer

HITS = [
    {"id": "kb-1", "title": "退货政策", "snippet": "商品签收后 7 天内可退货，运费买家承担。", "score": 0.31},
    {"id": "kb-2", "title": "发票开具", "snippet": "支持电子发票，下单后 30 天内可开具。", "score": 0.26},
]


def test_split_sentences_basic():
    assert split_sentences("第一句。第二句！") == ["第一句", "第二句"]


def test_verify_ok_when_answer_quotes_snippet():
    ans = "您好。商品签收后 7 天内可退货 [1]，运费由买家承担 [1]。"
    v = verify_answer(ans, HITS)
    assert v.ok, v.reason


def test_verify_ok_multi_snippets():
    ans = "商品签收后 7 天内可退货 [1]。支持电子发票 [2]，下单后 30 天内可开具 [2]。"
    v = verify_answer(ans, HITS)
    assert v.ok, v.reason


def test_verify_fail_without_citations():
    v = verify_answer("商品签收后 7 天内可退货，运费由买家承担。", HITS)
    assert not v.ok
    assert v.reason == "no_citations"


def test_verify_fail_bad_ref():
    v = verify_answer("商品签收后 7 天内可退货 [5]。", HITS)
    assert not v.ok
    assert v.reason == "bad_ref"


def test_verify_fail_low_overlap_fabricated_sentence():
    # 引用真实片段，但句子内容是编的——借引用编内容，必须拦
    v = verify_answer("上门取件完全免费 [1]。", HITS)
    assert not v.ok
    assert v.reason == "low_overlap"


def test_verify_short_polite_sentence_skipped():
    # 客套短句不参与重叠校验，但实质句仍在
    ans = "您好，关于退货 [1]：商品签收后 7 天内可退货 [1]。"
    v = verify_answer(ans, HITS)
    assert v.ok, v.reason


def test_verify_no_content_sentence_fails():
    # 只有客套没有实质内容 → 拒（no_content）
    v = verify_answer("您好 [1]，很高兴为您服务 [1]。", HITS)
    assert not v.ok
    assert v.reason == "no_content"


def test_verify_real_world_mixed_answer():
    # 模拟真模型：客套 + 摘抄 + 自然收尾
    ans = (
        "您好，关于您的退货问题 [1]："
        "根据售后政策，商品签收后 7 天内可退货 [1]，运费买家承担 [1]。"
        "请问还有其他可以帮您的吗 [1]？"
    )
    v = verify_answer(ans, HITS)
    assert v.ok, v.reason


def test_verify_overlap_threshold_is_sentence_level():
    # 一句过一句编 → 整体拒
    ans = "商品签收后 7 天内可退货 [1]。会员享有双倍积分 [1]。"
    v = verify_answer(ans, HITS)
    assert not v.ok
    assert v.reason == "low_overlap"
