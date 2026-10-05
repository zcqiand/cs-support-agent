"""`python -m cs_support_agent` 启动服务（LLM_MODE=mock 时离线可演示，8803）。"""
from __future__ import annotations

import uvicorn

from cs_support_agent.config import load_settings
from cs_support_agent.main import create_app


def main() -> None:
    settings = load_settings()
    app = create_app(settings)
    uvicorn.run(app, host="127.0.0.1", port=settings.app_port)


if __name__ == "__main__":
    main()
