# ai_connectors — 커넥터 추가 가이드

샌드박스에서 새 AI 모델을 붙일 때 이 문서의 3단계만 따르면 된다.

## 설계 원칙

- 모든 커넥터는 `base.AIConnector` 프로토콜을 구현해야 한다.
- 호출부(`app/main.py` 등)는 구체 커넥터를 **직접 import하지 않는다**. 반드시 `registry.get_connector(model_name)` 경유.
- 벤더 예외는 `errors.py`의 공통 예외로 번역한다 — 그래야 FastAPI 핸들러가 HTTP 코드를 일관되게 매핑한다.

## 커넥터 추가 3단계

### Step 1 — 구현 파일 생성

`ai_connectors/<vendor>.py` 예시 (Kanana API):

```python
from __future__ import annotations
import os
import httpx
from .base import AIConnector
from .schemas import AIRequest, AIResponse
from .errors import AuthError, RateLimitError, AIConnectorError


class KananaConnector:
    """Kanana API 커넥터."""

    name = "kanana-v1"

    def __init__(self) -> None:
        key = os.getenv("KANANA_API_KEY")
        if not key:
            raise AuthError("KANANA_API_KEY not set")
        self._key = key

    async def generate(self, request: AIRequest) -> AIResponse:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # 실제 엔드포인트/페이로드로 치환
            resp = await client.post(
                "https://api.kakao-kanana.example/v1/generate",
                headers={"Authorization": f"Bearer {self._key}"},
                json={"prompt": request.prompt},
            )
        if resp.status_code == 429:
            raise RateLimitError("Kanana rate limit")
        if resp.status_code >= 400:
            raise AIConnectorError(f"Kanana error: {resp.status_code}")
        data = resp.json()
        return AIResponse(text=data["text"], model=self.name, raw=data)

    def supports(self, feature: str) -> bool:
        return feature in {"text_generation"}
```

### Step 2 — registry.py에 한 줄 등록

```python
# ai_connectors/registry.py
from .kanana import KananaConnector  # noqa: E402

CONNECTORS: dict[str, Callable[[], AIConnector]] = {
    "kanana-v1": lambda: KananaConnector(),
}
```

### Step 3 — .env.example 갱신

사용자가 필요한 API 키 이름을 알 수 있도록 `KANANA_API_KEY=` 형태 placeholder만 추가. **실제 키는 절대 커밋 금지**.

## Local ↔ Production 교체 패턴

동일한 모델을 로컬(Mac)과 프로덕션(Modal GPU)에서 다르게 실행할 때 이름을 분리한다.

```python
CONNECTORS = {
    "qwen3-tts-mlx": lambda: Qwen3TtsMacConnector(),       # 로컬 Mac MLX 추론
    "qwen3-tts-modal": lambda: Qwen3TtsModalConnector(),   # 프로덕션 Modal GPU
}
```

`.env`의 `AI_MODEL` 값만 바꾸면 호출부 코드 변경 없이 백엔드가 교체된다.

## backend-fastapi로 이동할 때

1. 샌드박스에서 커넥터가 `/api/generate`를 통과하는지 확인
2. `ai_connectors/` 폴더 전체를 `backend-fastapi/app/modules/ai_connectors/`로 이동
3. 버전 drift 없는지 재확인(pyproject.toml diff) — 본 샌드박스는 이미 backend-fastapi와 버전 매칭되어 있으므로 충돌 없어야 정상
