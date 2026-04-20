"""backend-fastapi 진입점.
/health 엔드포인트만 제공하며 외부 의존 없이 부팅된다.
"""

from fastapi import FastAPI

from app.modules.Telegram_control_module import router as telegram_control_router

app = FastAPI(title="backend-fastapi", version="0.1.0")
app.include_router(telegram_control_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "fastapi"}
