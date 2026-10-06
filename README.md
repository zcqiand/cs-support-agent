# cs-support-agent — 云杉科技智能客服（知之为知之）

《图解AI Agent》第 12 章收官项目的实现仓：**Agentic RAG 客服**。
突出点只有一个——**回答自我校验**：查得到就引原文答，查不到绝不编，转人工兜底。

```
用户提问 → 意图识别（classify_intent 工具，前台分诊）
  ├─ kb       → 本地检索 TopK 片段 → 片段注入 → 带引用作答（[n]）
  │             → 逐句自我校验（引用存在性 + 片段重叠）
  │             ├─ 过  → citations 事件 + 依据面板
  │             ├─ 败  → 反馈原因重答一次（C038 闭环）→ 再败 → 转人工
  │             └─ 检索空 → 如实说「知识库没有」（不编、不自动转）
  ├─ ticket   → create_ticket 开单留痕 → 人工跟进
  ├─ handoff  → 直接转人工（会话结束，不再自动回）
  ├─ chitchat → 简短寒暄（不查库）
  └─ unknown  → 澄清一次 → 再不明 → 转人工
```

书中 ChromaDB 叙事改为**本地词频向量检索**（纯 stdlib，CJK bigram + 余弦，无网可跑，同等能力教学口径）；
编排自 v2 起用 **LangGraph StateGraph**（书 ch12 框架对齐：五路由、校验重答条件边、转人工收口全部入图）。

## 快速开始

```bash
# 后端（无 Key、无网全绿）
pip install -e ".[dev]"
pytest -q                                    # 110 项测试

# 离线演示（LLM_MODE=mock，分流标记词驱动，无需任何 Key）
python -m cs_support_agent                   # 127.0.0.1:8803

# 前端
cd frontend
npm install --registry=https://registry.npmmirror.com
npm run dev                                  # 127.0.0.1:5803（/api 代理 → 8803）

# live 模式：复制 .env.example 为 .env，填 OpenAI 兼容三件套（LLM_MODE=live）
```

mock 模式演示话术：`商品怎么退货？`（引用作答）· `年终奖什么时候发？`（检索无结果）
· `我们部门的打印机坏了，帮我登记报修工单`（开单）· `嗯嗯就那个事儿`×2（澄清→转人工）· `转人工`。

## 三分支兜底（书第 12 章护栏，全部真实实现 + live 冒烟实测）

| 分支 | 触发 | 行为 | live 实测（MiniMax-M3） |
|---|---|---|---|
| 检索无结果 | 检索最高分 < 0.12 | 固定文案如实说 + 询问转人工，不调 LLM 不编造 | 「年终奖」→ 如实告知无资料 ✓ |
| 意图不明 | unknown 澄清一次仍不明 | 固定文案 + 自动转人工 | 澄清→再问→ended ✓ |
| 校验不过 | 句无引用 / 越界引用 / 片段重叠 < 0.3 | 反馈原因重答一次 → 再败转人工；答案绝不带病上线 | 真模型同义改写被拦 → 喂回重答 ✓ |
| 意图=转人工 | classify_intent = handoff | 不再起生成轮，直接收尾 | 转人工后消息被拦截 ✓ |

**引用铁纪律**：答案的 [n] 必须指向本次检索返回的片段；每个实质句与所引片段的
bigram 词重叠 ≥ 0.3。宁可答「不知道，转人工」，不许编。live 实测答案样例：

> 商品签收后 7 天内可申请退货 [1]，且商品需保持原包装且配件齐全 [1]。
> 关于运费，非质量问题退货的运费由买家承担 [1]。

## 结构

```text
src/cs_support_agent/
├── config.py        # env 装配，fail-fast（LLM_MODE 必填，live 三件套缺一拒启）
├── llm.py           # LLMClient 协议 + LiveLLM（<think> 剥离 / wire 回传）+ FakeLLM 测试件
├── mock_llm.py      # MockLLM 离线演示件（分流标记词）
├── store.py         # SQLite thin DAO（sessions/messages/kb_articles/tickets）
├── kb.py            # ★ 检索器：CJK bigram 词频向量 + 余弦 TopK + 命中阈值
├── kb_seed.py       # 16 条虚构 FAQ（售后/账号/报销/通用；刻意不覆盖薪酬=无结果演示位）
├── verify.py        # ★ 引用校验器：句级引用存在性 + 片段重叠；失败拒绝
├── agent/
│   ├── prompts.py   # 人设「杉杉」+ 引用纪律 + 片段注入 + 固定兜底文案
│   ├── tools.py     # classify_intent / answer_with_citations / create_ticket / handoff_to_human
│   ├── graph.py     # ★ 客服流程图：五路由+校验重答条件边+转人工入图（12 节点 StateGraph）
│   └── support.py   # 客服 Agent 接线层（SSE 队列旁路，图跑 daemon 线程）
└── api/routes.py    # REST + SSE（M05 前端唯一消费面）
frontend/            # React 18 + TS：对话页（引用面板）/ 知识库页 / 工单页
```

## 护栏清单

- 转人工后会话 `handed_off`，后续消息走 error 事件拦截，不再自动回复；
- 会话轮次上限 20（触顶不调 LLM 直接转人工收尾）；单轮工具循环 ≤4；
- 检索/LLM 异常一律转 `error` 事件，会话不崩；
- KB 轮答案流式缓冲，校验通过才发出（思维链 reasoning 可直发，答案不行）；
- 知识库 16 条全部虚构（云杉科技/政策数字/400 号码），文件头注明示意。

## 验收

```bash
pytest -q                        # 110 passed，无 Key 无网
python -m cs_support_agent       # mock 离线可演示（8803）
cd frontend && npm run build     # tsc + vite 构建通过
```

功能全景见 [docs/functions/function-tree.md](docs/functions/function-tree.md)（6 模块全部已上线）。
