"""support.py 客服 Agent 接线层——树锚点 M01.F02 / M02.F02（v2 编排内核）。

v2：循环本体在 graph.py（LangGraph StateGraph：五路由 + 校验重答条件边 + 转人工入图）；
本文件只剩对消费者暴露的 SupportAgent——与 v1 同签名同事件流：
reply() 把图跑在 daemon 线程，事件经 queue.SimpleQueue 旁路成 SSE 生成器；
worker 异常 → error 事件（v1 文案「处理出错：」），不发 done（v1 行为：异常后流直接结束）。
等价门：tests/ 既有 97 项零改动。search 保留在本模块命名空间（test_search_crash 的
monkeypatch 接缝，graph.py 经 support_mod.search 迟到绑定）。
"""
from __future__ import annotations

import queue
import threading
from collections.abc import Iterator

# 模块级导入（不能 from ...graph import build_graph：graph.py 也反向导入本模块，
# 双方都只绑模块对象、调用期才取属性，循环导入才安全）。
from cs_support_agent.agent import graph as graph_mod
from cs_support_agent.kb import search  # noqa: F401  # monkeypatch 接缝


class SupportAgent:
    def __init__(self, llm, store, max_turns: int = 20):
        self.llm = llm
        self.store = store
        self.max_turns = max_turns
        self._graph = graph_mod.build_graph(llm, store, max_turns)

    # ---- 对外入口 ----

    def reply(self, session_id: str, user_text: str) -> Iterator[dict]:
        events: queue.SimpleQueue = queue.SimpleQueue()
        state = {"session_id": session_id, "text": user_text}
        config = {"configurable": {"events": events}}
        worker = threading.Thread(target=self._run, args=(state, config, events), daemon=True)
        worker.start()
        try:
            for event in iter(events.get, None):
                yield event
        finally:
            worker.join()

    def _run(self, state, config, events) -> None:
        try:
            self._graph.invoke(state, config)
        except Exception as exc:  # 检索/LLM 等一切异常 → error 事件，会话不崩（M00.F02.I03）
            events.put({"type": "error", "message": f"处理出错：{exc}"})
        finally:
            events.put(None)  # 哨兵：只由接线层 put，图与直连 invoke 都没有
