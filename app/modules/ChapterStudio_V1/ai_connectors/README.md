# ai_connectors

## 모듈 목적
ChapterStudio_V1의 Planner, 텍스트 생성, TTS 합성 호출을 벤더 교체 가능한 커넥터로 격리함. 활성 텍스트 경로는 `gemini_flash`, 레슨 TTS는 `gemini_tts` 어댑터를 기본으로 씀. `qwen27b_modal`·`opus46`은 배포·폴백용으로 보존함.

## IN·OUT
IN은 `ChapterAIRequest` 또는 TTS 텍스트이며, OUT은 `ChapterAIResponse` 또는 `audio_url`/`duration_sec` mapping임. 외부 SDK 응답 타입은 이 폴더 밖으로 노출하지 않음.

## 환경변수
환경변수는 직접 읽지 않고 `common.config`만 통함. 사용 키는 `ACTIVE_TEXT_MODEL`, `ACTIVE_PLANNER_MODEL`, `ACTIVE_TTS_MODEL`, `AI_MODEL`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`/`GOOGLE_API_KEY`, `GEMINI_TEXT_MODEL`, `QWEN_APP_NAME`, `TTS_ENDPOINT`임.

## 의존성
`base.py`는 `AIConnector`, `TTSConnector` Protocol을 제공함. `registry.py`는 텍스트 커넥터(`gemini_flash`, `claude_sonnet`, `qwen27b_modal`, `opus46`, `qwen27b_sonnet_fallback`)와 TTS 커넥터(`gemini_tts`, `tts_v1`)를 싱글톤 캐시로 반환함. `gemini_tts`는 시스템 A(`ai_connectors/tts/gemini_tts_connector.py`)의 Gemini TTS를 ChapterStudio `TTSConnector` 인터페이스로 감싸는 얇은 어댑터(`gemini_tts_connector.py`)임.

## 사용 예시
```python
from app.modules.ChapterStudio_V1.ai_connectors.registry import get_text_connector

connector = get_text_connector()
response = await connector.generate(req)
```

레슨 TTS는 registry 의 `get_tts_connector()` 로 활성 `gemini_tts` 어댑터를 받아 `synthesize(text, voice)` 를 호출함.

## 에러 정책
Qwen Modal 연결 오류는 `TimeoutError`, 인증 오류는 `AuthError`, 등록되지 않은 이름은 `ModelNotFoundError`로 정규화함. Qwen 호출은 `asyncio.wait_for(..., 60초)`로 감싸 LangGraph 노드가 무기한 대기하지 않게 함. Opus 4.6은 `_MODEL_ID = "claude-opus-4-6"` 상수만 사용하며 인증, rate limit, context 초과를 별도 예외로 매핑함. TTS V1은 HTTP timeout과 status 오류를 커넥터 예외로 변환함. `gemini_tts`/`gemini_flash`는 google-genai SDK 오류를 공통 커넥터 예외로 정규화함.

## Phase 4 호출 방식
LangGraph 노드는 registry 함수만 호출함. Planner는 `get_planner_connector()`, SlideGenerator와 리뷰·퀴즈·노트·과제·대본 노드는 `get_text_connector()`, TTS 큐 워커는 `get_tts_connector()`를 사용함.

## 리소스 수명주기
FastAPI lifespan 종료 시 `await ai_connectors.registry.close_all()`을 호출하면 캐시된 커넥터의 `aclose()`가 실행되고 `_CACHE`가 비워짐. 특히 `TTSV1Connector`의 `httpx.AsyncClient` connection pool은 이 경로로 닫아야 함.
