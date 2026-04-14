# backend-fastapi — Claude 작업 컨텍스트

## 이 레포의 역할 (절대 변경 금지)

**AI 사용 및 AI 에이전트 사용** 전담 서버. LLM·GPU 추론·OCR 추론·RAG·AI 에이전트를 모두 여기서 처리한다.

## 하지 말아야 할 것

- 메인 비즈니스 로직·결제·인증·세션 작성 금지 (Spring의 책임)
- 이미지 전처리 코드 작성 금지 (Rust의 책임)
- SSE 스트리밍 로직 추가 금지 (프로젝트 전체에서 SSE 미사용)

## 해야 할 것

- Claude API 호출 (검증/재작업 루프)
- Modal GPU 서버리스 추론 (Qwen/GLM/TTS/ASR 등)
- PaddleOCR ONNX 추론 (Rust에서 gRPC로 수신)
- Qdrant RAG 검색
- Celery로 비동기 AI 작업 큐잉
- AI 에이전트 워크플로 오케스트레이션

## 데이터 플로우

```
Spring Boot → FastAPI (AI·채점 요청)
Rust         → FastAPI (OCR gRPC)
FastAPI      → Modal GPU / Claude API / Qdrant
```

## 코드 주석 언어

모든 코드 주석은 한국어로 작성한다. 영어 주석 금지.

## 모듈 작업 규칙 (라이브러리형 모듈)

- 신규 AI 파이프라인 단계는 **반드시** `app/modules/<ModuleName>/` 아래에 라이브러리형 모듈로 만든다. 라우터·task에 로직을 직접 쓰는 것 금지.
- 공개 API는 `__init__.py`의 `__all__`과 re-export로만 드러낸다. 외부가 `app.modules.X.internal_file`을 직접 import하면 리뷰 거절.
- 모듈 간 직접 의존 금지. 공통 로직은 `app/core/`로 승격.
- 모델 파일(.gguf, .onnx 등)은 모듈 내 `models/` 하위 또는 환경변수 경로에 둔다. 모듈 루트에 흩뿌리지 않는다.
- 모듈 단위 테스트는 `app/modules/<ModuleName>/tests/`에서 pytest로 실행 가능해야 한다.
- 모듈은 자기 README에 IN/OUT·파라미터·폴백 정책을 명시한다.
