"""应用装配（M04.F01）：create_app 工厂——LLM/Store 注入点。

settings 缺省走 load_settings()（fail-fast，LLM_MODE 缺失直接拒绝启动）；
测试与离线演示用参数注入 MockLLM / 临时库，不读 env。
"""
from __future__ import annotations

from fastapi import FastAPI

from cs_support_agent.api.routes import router
from cs_support_agent.config import Settings, load_settings
from cs_support_agent.kb_seed import seed_articles
from cs_support_agent.llm import LLMClient, LiveLLM
from cs_support_agent.mock_llm import MockLLM
from cs_support_agent.store import Store


def build_llm(settings: Settings) -> LLMClient:
    if settings.llm_mode == "live":
        return LiveLLM(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
    return MockLLM()


def create_app(
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    store: Store | None = None,
) -> FastAPI:
    settings = settings if settings is not None else load_settings()
    app = FastAPI(title="云杉科技智能客服", version="0.1.0")
    app.state.settings = settings
    app.state.llm = llm if llm is not None else build_llm(settings)
    app.state.store = store if store is not None else Store(settings.db_path)
    seed_articles(app.state.store)  # 演示种子幂等 upsert：KB 永有数据可演示
    app.include_router(router)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "mode": settings.llm_mode}

    return app
