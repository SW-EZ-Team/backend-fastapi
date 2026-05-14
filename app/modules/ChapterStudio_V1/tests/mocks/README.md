# tests/mocks

## 모듈 목적
Phase 4 이후 LangGraph 노드 테스트에서 실제 Modal, Anthropic, TTS 호출 없이 동일 Protocol을 검증함.

## IN·OUT
IN은 `ChapterAIRequest` 또는 TTS 텍스트이며, OUT은 정규화된 `ChapterAIResponse` 또는 `audio_url`/`duration_sec` mapping임.

## 환경변수
해당 없음. mock은 외부 서비스와 연결하지 않음.

## 의존성
`ai_connectors.base` Protocol과 `ai_connectors.schemas`만 사용함.

## 사용 예시
테스트에서 `registry._REGISTRY["qwen27b_mock"] = Qwen27BMockConnector`로 주입한 뒤 `clear_cache()`를 호출함.

## 에러 정책
실제 장애 재현은 unit test에서 별도 stub으로 만들고, 기본 mock은 정상 경로만 제공함.
