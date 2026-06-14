# Chat_V1 — ChapterStudio 학습 챗봇 모듈

## 목적

ChapterStudio가 생성한 강의 콘텐츠(슬라이드·음성대본·퀴즈)를 컨텍스트로 활용해 학생 질문에 답변하는 학습 챗봇이다. 텍스트 채팅과 음성 대화 두 가지 모드를 지원한다.

---

## 두 가지 모드

| 모드 | 엔드포인트 | 텍스트 모델 | 입력 | 출력 |
|---|---|---|---|---|
| 텍스트 채팅 | `POST /api/chat/v1/ask` | `ACTIVE_TEXT_MODEL` 활성 커넥터 (codex_cli·claude_sonnet 등) | 텍스트 질문 | 텍스트 답변 |
| 음성 대화 | `POST /api/chat/v1/voice` | Gemini 2.0 Flash Live | 음성(base64) | 음성(base64) |

텍스트 모드는 특정 벤더에 고정되지 않는다. `service.py`의 `call_text_model()`이 `ai_connectors.registry.get_text_connector()`로 `ACTIVE_TEXT_MODEL`이 가리키는 커넥터를 받아 쓴다. `.env`에서 `ACTIVE_TEXT_MODEL` 값 하나만 바꾸면 Claude·codex·Qwen 어느 것으로도 스왑된다.

두 모드 모두 강의 컨텍스트(슬라이드·음성대본·퀴즈)를 함께 받아 컨텍스트 기반 답변을 생성한다.

---

## IN/OUT 인터페이스

### 텍스트 채팅 (POST `/api/chat/v1/ask`)

```json
{
  "session_id": "sess_abc123",
  "user_message": "2번 슬라이드에서 이진 탐색 시간복잡도가 왜 O(log n)인가요?",
  "lecture_context": {
    "chapter_title": "자료구조 기초 — 탐색 알고리즘",
    "slides": [
      { "slide_idx": 0, "title": "선형 탐색", "content": "배열을 처음부터 끝까지 순회한다. 시간복잡도 O(n)." },
      { "slide_idx": 1, "title": "이진 탐색", "content": "정렬된 배열에서 중간 값과 비교해 탐색 범위를 절반으로 줄인다. 시간복잡도 O(log n)." }
    ],
    "voice_scripts": ["이번 시간에는 탐색 알고리즘을 배워볼게요."],
    "quiz_items": ["이진 탐색의 전제 조건은 무엇인가요?"]
  }
}
```

### 응답

```json
{
  "session_id": "sess_abc123",
  "answer": "이진 탐색은 [슬라이드 2]에서 설명하듯이 탐색할 때마다 범위가 절반으로 줄어들기 때문에 O(log n)이에요...",
  "referenced_slides": [1]
}
```

`referenced_slides`는 0-based 인덱스이며, 답변에서 `[슬라이드 N]` 패턴(1-based)을 자동 추출해 변환한다. 슬라이드 총 개수를 상한으로 검증하므로, 모델이 존재하지 않는 슬라이드를 인용하면 해당 참조는 버린다.

---

### 음성 대화 (POST `/api/chat/v1/voice`)

Gemini 2.0 Flash Live를 사용해 음성 입력을 받고 음성 응답을 반환한다.

#### 요청

```json
{
  "session_id": "sess-abc-123",
  "audio_data": "<base64 인코딩된 음성>",
  "audio_format": "webm",
  "sample_rate": 16000,
  "lecture_context": {
    "chapter_title": "Python 데코레이터",
    "slides": [
      { "slide_idx": 0, "title": "개요", "content": "데코레이터는 함수를 감싸는 도구이다" }
    ]
  }
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `session_id` | str | 필수 | 채팅 세션 식별자 |
| `audio_data` | str | 필수 | base64 인코딩된 입력 음성 바이너리 |
| `audio_format` | str | 필수 | 입력 오디오 포맷 (예: `"webm"`, `"wav"`, `"ogg"`) |
| `sample_rate` | int | 필수 | 입력 오디오 샘플링 레이트 (Hz) |
| `lecture_context` | object | 필수 | 강의 콘텐츠 컨텍스트 (텍스트 모드와 동일 구조) |

#### 응답

```json
{
  "session_id": "sess-abc-123",
  "audio_data": "<base64 인코딩된 음성 응답>",
  "audio_format": "wav",
  "transcript_input": "데코레이터가 뭐예요?",
  "transcript_output": "데코레이터는 함수를 받아 새 함수를 돌려주는 구조예요...",
  "referenced_slides": [0]
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `session_id` | str | 요청의 `session_id`를 그대로 반환 |
| `audio_data` | str | base64 인코딩된 응답 음성 (WAV) |
| `audio_format` | str | 응답 오디오 포맷 (`"wav"` 고정) |
| `transcript_input` | str | 입력 음성의 전사 텍스트 |
| `transcript_output` | str | 챗봇 응답의 전사 텍스트 |
| `referenced_slides` | list[int] | 응답 생성에 참조한 슬라이드 `slide_idx` 목록 |

---

## 환경변수

| 변수명 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `ACTIVE_TEXT_MODEL` | 선택 | `claude_sonnet` | 텍스트 채팅에 쓸 커넥터 이름. `ai_connectors.registry`에 등록된 이름을 지정한다 |
| `GEMINI_API_KEY` | 조건부 | — | Google Gemini API 인증 키 (음성 모드 필수). `GOOGLE_API_KEY`로도 인식 |
| `GOOGLE_API_KEY` | 조건부 | — | `GEMINI_API_KEY`의 대체 환경변수명. 둘 중 하나만 있으면 됨 |
| `GEMINI_FLASH_LIVE_MODEL` | 선택 | `gemini-2.0-flash-live-001` | 음성 대화에 사용할 Gemini 모델 식별자 |
| `GEMINI_FLASH_LIVE_TIMEOUT_SEC` | 선택 | `60` | 음성 대화 API 호출 제한 시간(초) |

텍스트 커넥터별 추가 환경변수(API 키, 타임아웃 등)는 해당 커넥터 문서를 참조한다. 예: `claude_sonnet` 커넥터는 `ANTHROPIC_API_KEY`를 사용하고, `codex_cli` 커넥터는 별도 설정이 없어도 동작한다.

---

## 의존성

- `ai_connectors.registry` — `get_text_connector()` 로 벤더 중립 텍스트 커넥터 주입
- `ai_connectors.text_schemas` — `ChapterAIRequest` / `ChapterAIResponse`
- `common.llm_output` — `strip_thinking`: Qwen·codex 등 모델 스왑 시 `<think>` 블록 제거 공통 유틸. 자세한 내용은 `common/llm_output.py` 참조
- `google-genai>=1.10.0` — Gemini Flash Live API 클라이언트 (음성 모드)
- `langgraph` — 챗봇 파이프라인 상태 머신
- `pydantic` v2 — 요청/응답 스키마 검증
- `fastapi` — HTTP 라우터

---

## 파이프라인 구조

```
validate_input
      │
      ▼
generate_answer  ← ACTIVE_TEXT_MODEL 활성 커넥터 호출 (벤더 중립)
      │
      ▼
format_response  ← strip_thinking → 환각 가드 → 슬라이드 참조 추출
      │
      ▼
     END
```

### 각 노드 설명

- `validate_input`: 입력 유효성 검증, 시스템 프롬프트 확인
- `generate_answer`: `get_text_connector()`로 받은 커넥터를 통해 텍스트 모델 호출. 오류 발생 시 `error_message`에 기록
- `format_response`: 다음 세 단계를 순서대로 수행한다
  1. `common.llm_output.strip_thinking` — `<think>...</think>` reasoning 블록 제거. Qwen3.6·codex 등 모델 스왑 시에도 채팅 답변에 추론 과정이 노출되지 않도록 막는다
  2. `app.scope_guard.apply_hallucination_guard` — 강의 키워드와 겹치지 않는 답변은 그대로 유지하되 끝에 범위 밖 안내문(`SCOPE_NOTICE`) 한 줄을 덧붙인다. 답변 자체를 거절문으로 교체하지 않는다(거절 금지 정책 — 슬라이드는 참고 자료)
  3. `app.scope_guard.extract_referenced_slides` — `[슬라이드 N]` 패턴을 0-based 인덱스로 변환. 슬라이드 총 개수(`slide_count`)를 상한으로 검증해 없는 슬라이드 인용을 제거한다

### 견고성 장치

- **시스템 프롬프트 강화**: 비교·혼동 질문에 짧은 대조 예시 1개를 들도록 지시하고, 답변 문장 끝에 `[슬라이드 N]` 출처 인용을 항상 붙이도록 강제한다. few-shot 앵커 3개(단순 개념/비교/범위 밖)를 프롬프트에 포함한다
- **범위 가드 (`app/scope_guard.py`)**: 강의 키워드 어간 집합과 답변 어간 집합의 교집합이 비면 답변 끝에 `SCOPE_NOTICE`("이 내용은 이번 강의 범위 밖이에요.")를 덧붙인다. 슬라이드 인용이 있거나 이미 안내문이 포함된 답변이면 면제해 중복을 막는다. 진짜 질문에 대한 거절은 하지 않는다
- **슬라이드 상한 검증**: `slide_count`를 기준으로 존재하지 않는 슬라이드 참조를 제거한다. 환각 참조가 Spring/프론트로 흘러가 엉뚱한 자료를 띄우는 것을 막는다

오류 발생 시 `error_message`가 상태에 기록되고 `format_response`가 안내 문구로 대체한다.

---

## 사용 예시 (Python)

```python
from app.modules.Chat_V1 import ChatRequest, answer_question
from app.modules.Chat_V1.app.schemas import LectureContext, SlideContext

ctx = LectureContext(
    chapter_title="자료구조 기초",
    slides=[
        SlideContext(slide_idx=0, title="이진 탐색", content="O(log n) 탐색...")
    ],
)
req = ChatRequest(
    session_id="test_session",
    user_message="이진 탐색 시간복잡도를 설명해 주세요.",
    lecture_context=ctx,
)
response = await answer_question(req)
print(response.answer)
print(response.referenced_slides)
```

---

## 에러 핸들링 정책

| 상황 | HTTP 상태 | 동작 |
|---|---|---|
| 빈 질문 / 컨텍스트 없음 | 422 | `validate_input` 노드가 오류 상태 설정, 라우터가 422 반환 |
| 커넥터 오류 (인증 실패·레이트 리밋 등) | 500 | `AIConnectorError` → `format_response`가 사용자 친화 안내문으로 대체 |
| 파이프라인 타임아웃 | 500 | 상위 서킷 브레이커 또는 커넥터 타임아웃 설정으로 제한 |
| 강의 범위 밖 답변 | 200 | 답변 유지 + 끝에 범위 밖 안내문(`SCOPE_NOTICE`) 추가, `referenced_slides: []` |
| 슬라이드 참조 없음 | 200 | `referenced_slides: []`로 정상 반환 |

모든 오류는 사용자에게 "죄송해요, 답변을 생성하는 중에 오류가 발생했어요. 잠시 후 다시 시도해 주세요." 형태의 한국어 안내로 대체된다.
