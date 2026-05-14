# ai_connectors

## 모듈 목적
ChapterStudio_V1의 Planner, Qwen 텍스트 생성, TTS 합성 호출을 벤더 교체 가능한 커넥터로 격리함. `codex_cli`는 개인 로컬 검증 전용이며 production 경로에 넣지 않음.

## IN·OUT
IN은 `ChapterAIRequest` 또는 TTS 텍스트이며, OUT은 `ChapterAIResponse` 또는 `audio_url`/`duration_sec` mapping임. 외부 SDK 응답 타입은 이 폴더 밖으로 노출하지 않음.

## 환경변수
환경변수는 직접 읽지 않고 `common.config`만 통함. 사용 키는 `ACTIVE_TEXT_MODEL`, `ACTIVE_PLANNER_MODEL`, `ACTIVE_TTS_MODEL`, `AI_MODEL`, `ANTHROPIC_API_KEY`, `QWEN_APP_NAME`, `TTS_ENDPOINT`, `CODEX_CLI_MODEL`, `CODEX_CLI_TIMEOUT_SEC`임.

## 의존성
`base.py`는 `AIConnector`, `TTSConnector` Protocol을 제공함. `registry.py`는 production 커넥터 3종(`qwen27b_modal`, `opus46`, `tts_v1`)과 로컬 검증 전용 `codex_cli`를 싱글톤 캐시로 반환함.

## 사용 예시
```python
from ai_connectors.registry import get_text_connector

connector = get_text_connector()
response = await connector.generate(req)
```

로컬 검증에서만 ChatGPT OAuth로 로그인된 Codex CLI를 직접 호출할 수 있음.

```python
from ai_connectors.codex_cli_connector import CodexCLIConnector

response = await CodexCLIConnector().generate(req)
```

## 에러 정책
Qwen Modal 연결 오류는 `TimeoutError`, 인증 오류는 `AuthError`, 등록되지 않은 이름은 `ModelNotFoundError`로 정규화함. Qwen 호출은 `asyncio.wait_for(..., 60초)`로 감싸 LangGraph 노드가 무기한 대기하지 않게 함. Opus 4.6은 `_MODEL_ID = "claude-opus-4-6"` 상수만 사용하며 인증, rate limit, context 초과를 별도 예외로 매핑함. TTS V1은 HTTP timeout과 status 오류를 커넥터 예외로 변환함. `codex_cli`는 OAuth 토큰 파일을 읽지 않고 `codex exec` 프로세스에 인증 처리를 맡기며, 비정상 종료와 제한 시간 초과를 커넥터 예외로 변환함.

## Phase 4 호출 방식
LangGraph 노드는 registry 함수만 호출함. Planner는 `get_planner_connector()`, SlideGenerator와 리뷰·퀴즈·노트·과제·대본 노드는 `get_text_connector()`, TTS 큐 워커는 `get_tts_connector()`를 사용함.

## 리소스 수명주기
FastAPI lifespan 종료 시 `await ai_connectors.registry.close_all()`을 호출하면 캐시된 커넥터의 `aclose()`가 실행되고 `_CACHE`가 비워짐. 특히 `TTSV1Connector`의 `httpx.AsyncClient` connection pool은 이 경로로 닫아야 함.
