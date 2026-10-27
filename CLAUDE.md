# cs-support-agent — 仓库工作约定（供 Claude Code）

智能客服 Agent：**知之为知之**的客服——先查知识库、引用原文作答、查不到就老实转人工。
用户提问 → 意图识别（查知识库/报障开单/转人工/寒暄）→ 路由分发 → 检索 TopK 片段
→ 带引用作答（[n] 标注）→ 自我校验（每条主张回指片段）→ 校验不过或查不到 → 如实承认 + 转人工。
突出点只有一个：**回答自我校验**——查得到就引原文答，查不到绝不编，转人工兜底。

## 铁律

- **TDD**：核心逻辑（检索器/意图路由/引用校验/Agent 循环）先写失败测试 → 实现 → 绿 → commit。
- **mock-friendly**：`pip install -e ".[dev]" && pytest -q` 必须在无 Key、无网下全绿（FakeLLM 注入，禁止测试里真调 API）。
- **版本钉死**：依赖与 `version-lock.json` 一致，不引 lock 外的库（编排=LangGraph 单框架，书 ch12 对齐；禁 CrewAI/langchain 顶层/langchain-openai；检索手写，无外部 embedding/向量库）。
- **禁止 env 默认值兜底**：`LLM_MODE` 必填（mock|live）；live 模式下 base_url/api_key/model 缺一即启动报错。
- **密钥不入库**：key 只在 `.env`（已 gitignore），`.env.example` 放占位符。
- **只增不改**：扩功能不动现有模块签名/行为。

## 技术栈（钉死于 version-lock.json）

- 后端：Python 3.10+ / FastAPI / openai SDK（OpenAI 兼容直调：MiniMax-M3，base_url 可配）；编排：LangGraph StateGraph（graph.py 图内核，v2）
- 前端：React 18 + TypeScript + Vite 5（npm 走 registry.npmmirror.com）
- 存储：SQLite（`data/app.db`，thin DAO，不引 ORM）
- 检索：**本地词频向量 + 余弦相似度**（纯 stdlib，CJK bigram + ASCII 词；知识库不出本机、检索不依赖网络）

## 验收

```bash
pip install -e ".[dev]"
pytest -q                        # 全绿，无 Key/无网
python -m cs_support_agent       # LLM_MODE=mock 时离线可演示（8803）
cd frontend && npm install && npm run build  # 前端构建通过
```

## 结构

```text
src/cs_support_agent/
├── config.py        # env 装配，fail-fast
├── llm.py           # LLMClient 协议 + LiveLLM(OpenAI兼容) + FakeLLM 测试件（`<think>` 剥离 / wire 序列化）
├── mock_llm.py      # 运行时离线演示件（分流标记词驱动）
├── store.py         # SQLite DAO（sessions/messages/kb_articles/tickets）
├── kb.py            # ★ 知识库：种子 FAQ（虚构）+ 检索器（词频向量+余弦+TopK+命中阈值）
├── verify.py        # ★ 引用校验器：引用存在性+片段重叠校验；不过→拒绝转人工
├── agent/
│   ├── prompts.py   # 客服人设 + 意图/路由规则 + 引用纪律 + 检索片段组装
│   ├── tools.py     # search_kb / answer_with_citations / create_ticket / handoff_to_human
│   ├── graph.py     # ★ 客服流程图：五路由+校验重答条件边+转人工入图（12 节点 StateGraph）
│   └── support.py   # 客服 Agent 接线层（SSE 队列旁路，图跑 daemon 线程）
└── api/             # 路由：kb / sessions / messages(SSE) / tickets
frontend/            # React 18 + TS + Vite（工作台：对话+引用面板+KB+工单）
```

## 领域规则（书第 12 章护栏，全部真实实现可演示）

- **三分支兜底缺一不可**：检索无结果 → 如实说+可转人工；意图无法分类 → 澄清一次，仍不明转人工；自我校验不通过 → 承认不知道+转人工。
- **引用铁纪律**：答案里的 [n] 必须对应本次检索返回的片段编号；答案关键内容与被引片段词重叠过低 → 校验拒绝。宁可答「我不知道，为您转人工」，不许编。
- **查询异常捕获并提示**：检索/LLM 异常都不崩会话，转 error 事件。
- **意图路由 = 前台分诊**：先听懂来意再分发；chitchat 简短寒暄不查库；ticket 开单留痕。
- **知识库全虚构**：随仓种子 FAQ 的公司名/政策数字/电话一律虚构并在文件头注明示意。
- MiniMax-M3 对接坑（`<think>` 内联思维链、工具轮回传 wire 形状）已在 llm.py 处理，见记忆 `minimax-m3-integration-pitfalls`。

## 正式区 / 临时区（2026-10-24 人定，全产品线通用）

- 过程件不与正式件混放：任务卡/批次卡、片段（frags-*）、批次文件、合并/对账/自检脚本、门控回执（receipts-*）、调试日志、QC 抽帧——项目级进 `_work/`，章级/集级进所属正式目录下 `_work/` 子目录
- 正式区同名正式件有且仅有一个（不堆 v2/final 副本）
- 章节正文、章级门控记录（chapter-NNN.*）、各类台账 json 是正式件，不进 `_work`
- `_work/` 整目录 .gitignore，过程件可追溯由本地盘承担；`scratch/` 已废弃并入 `_work/`，临时区只认 `_work/` 一个入口（2026-10-27 人裁，同 xr-code-suite）
- 可再生件不入库（见 .gitignore）：node_modules、build、out、bin/obj、`**/_work/render`、hook 审计日志
