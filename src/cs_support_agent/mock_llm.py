"""mock_llm.py 运行时离线演示件——树锚点 M04.F02（LLM_MODE=mock 时由 main.build_llm 装配）。

与 LiveLLM 同形状（chat / chat_stream），无网无 Key 可全链路演示：
- 意图轮（chat）：按用户文本里的分流标记词分类，优先级 handoff > ticket > kb > chitchat > unknown；
  chitchat 直接回文本（不走分类工具，同 LiveLLM 偶发的直答行为）。
- 生成轮（chat_stream）：按 system 提示词特征分流——
  含【检索片段】→ 摘抄第一条片段原文 + [1]（过 verify_answer 校验，守引用铁纪律）；
  工单轮第一遍 → create_ticket 工具调用；工具回执后 → 收尾话术；
  澄清轮 → 一句话澄清；其余 → 通用问候。
"""
from __future__ import annotations

import re

from cs_support_agent.llm import ToolCall, assistant_msg

_HANDOFF_RE = re.compile(r"转人工|人工客服|投诉")
_TICKET_RE = re.compile(r"报障|故障|坏了|登不上|登录不上|开单|登记|工单")
_KB_RE = re.compile(
    r"退货|退款|发票|换货|保修|报修|密码|注销|换绑|手机号|会员|优惠券|实名|认证"
    r"|报销|差旅|审批|备用金|年终奖|工资|薪资|客服电话"
)
_CHIT_RE = re.compile(r"你好|您好|谢谢|在吗|再见|早上好|下午好|晚上好")

_SNIP_RE = re.compile(r"^\[\d+\]（.+?）(.+)$", re.MULTILINE)


class MockLLM:
    """离线演示件：无状态，全靠输入文本与 system 特征分流。"""

    def chat(self, *, messages, tools=None, temperature: float = 0.8) -> dict:
        text = self._last_user(messages)
        if _CHIT_RE.search(text) and not (_HANDOFF_RE.search(text) or _TICKET_RE.search(text) or _KB_RE.search(text)):
            return assistant_msg("您好呀，我是云杉科技的智能客服杉杉，很高兴为您服务～")
        return assistant_msg(
            None,
            [ToolCall(id="mock-intent-1", name="classify_intent",
                      arguments={"intent": self._intent(text), "topic": text[:30]})],
        )

    def chat_stream(self, *, messages, tools=None, temperature: float = 0.8):
        system = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
        has_tool_result = any(m.get("role") == "tool" for m in messages)
        if "create_ticket" in system and not has_tool_result:
            user_text = self._last_user(messages)
            msg = assistant_msg(
                None,
                [ToolCall(id="mock-ticket-1", name="create_ticket",
                          arguments={"title": (user_text[:20] or "用户报告的问题"),
                                     "description": user_text or "（用户未描述）"})],
            )
            yield {"type": "final", "message": msg}
            return
        if "【检索片段】" in system:
            m = _SNIP_RE.search(system)
            snippet = m.group(1) if m else "抱歉，暂时没有相关资料。"
            text = snippet.rstrip("。！？!?；; \n") + " [1]。"
        elif has_tool_result:
            text = "已为您登记工单，人工同事会尽快跟进处理。"
        elif "澄清" in system:
            text = "方便说说您遇到的具体问题吗？退货、账号或报销方面都可以。"
        else:
            text = "您好，我是云杉科技智能客服杉杉，请问有什么可以帮您？"
        for i in range(0, len(text), 6):
            yield {"type": "delta", "text": text[i : i + 6]}
        yield {"type": "final", "message": assistant_msg(text)}

    # ---- 内部 ----

    @staticmethod
    def _intent(text: str) -> str:
        if _HANDOFF_RE.search(text):
            return "handoff"
        if _TICKET_RE.search(text):
            return "ticket"
        if _KB_RE.search(text):
            return "kb"
        if _CHIT_RE.search(text):
            return "chitchat"
        return "unknown"

    @staticmethod
    def _last_user(messages) -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                return m.get("content") or ""
        return ""
