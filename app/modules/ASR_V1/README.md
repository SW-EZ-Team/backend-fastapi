# ASR V1 — 실시간 대화형 ASR 파이프라인

## 목적

기존 배치 ASR(`/api/asr` on port 8001)을 확장해 WebSocket 기반 실시간 스트리밍 전사를 지원한다.
Silero VAD로 음성 구간을 감지하고, 침묵 감지 시 기존 `ASRConnector.generate()`를 배치 호출한다(pseudo-streaming).
LLM→TTS 파이프라인에서 완결 문장을 실시간으로 공급하는 것이 최종 목표다.

## 포트

**8011** (TTS_V2: 8010, 허브 서브앱: 8001–8004)

## 실행 방법

```bash
# backend-fastapi/ 디렉토리에서 실행
cd /path/to/backend-fastapi
uv run uvicorn app.modules.ASR_V1.app.main:app --port 8011
```

브라우저 테스트 UI: `http://localhost:8011/static/asr_v1_test.html`

## 의존성

추가 패키지 설치 불필요 — 기존 venv에 모두 포함됨:

| 패키지 | 용도 |
|---|---|
| `torch` | Silero VAD (clearvoice 의존성으로 설치됨) |
| `fastapi[websockets]` | WebSocket 서버 |
| `numpy` | PCM 배열 처리 |
| `librosa`, `scipy` | 오디오 포맷 변환 (common.audio_io) |

Silero VAD 모델(~2MB)은 `torch.hub.load` 최초 실행 시 `~/.cache/torch/hub/`에 자동 캐시된다.

## WebSocket 프로토콜

엔드포인트: `ws://localhost:8011/ws/asr-v1`

### 업스트림 (브라우저 → 서버)

| 타입 | 내용 |
|---|---|
| **바이너리** | PCM Int16LE 16kHz mono 샘플 청크 |
| **텍스트 JSON** | `{ "action": "stop" }` — 세션 종료 |

### 다운스트림 (서버 → 브라우저)

| type | 설명 | 예시 |
|---|---|---|
| `session_ack` | 세션 시작/종료 응답 | `{"type":"session_ack","session_id":"...","action":"started"}` |
| `vad_state` | VAD 상태 전환 | `{"type":"vad_state","speaking":true}` |
| `partial` | 부분 전사 (UI 전용) | `{"type":"partial","text":"안녕..."}` |
| `final` | 확정 전사 | `{"type":"final","text":"안녕하세요.","turn_id":"...","duration_sec":1.2,"latency_ms":350}` |
| `flush` | LLM→TTS 전달 세그먼트 | `{"type":"flush","segments":["안녕하세요."]}` |
| `error` | 오류 알림 | `{"type":"error","detail":"추론 실패"}` |

## REST 엔드포인트

### POST /api/asr-v1/offline

배치 전사 — 파일 업로드 방식.

**요청**: `multipart/form-data` — `audio` 파일 + `language` 쿼리 파라미터(기본 `ko`)

**응답** (`ASRResponse`):
```json
{
  "text": "전사된 텍스트",
  "language": "ko",
  "duration_sec": 2.3,
  "latency_ms": 420.0,
  "model": "mlx-qwen3-asr"
}
```

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `ASR_V1_VAD_MIN_SILENCE_MS` | `800` | 침묵 판정 최소 시간(ms) |
| `ASR_V1_VAD_THRESHOLD` | `0.5` | VAD 음성 감지 임계값 |
| `ASR_V1_VAD_SPEECH_PAD_MS` | `200` | 음성 경계 패딩(ms) |
| `ASR_V1_VAD_MIN_SPEECH_MS` | `250` | 최소 음성 길이(ms) |
| `ASR_V1_TURN_MIN_CHARS` | `2` | 커밋 최소 글자수 |
| `ASR_V1_TURN_GRACE_MS` | `300` | 마지막 음성 후 추가 대기(ms) |
| `ASR_V1_PARTIAL_INTERVAL_MS` | `500` | 부분 전사 주기(ms) |
| `ASR_V1_BUFFER_MAX_SEC` | `20.0` | 버퍼 최대 누적 시간(초) |
| `ASR_V1_MODEL` | `mlx-qwen3-asr` | ASR 커넥터 레지스트리 키 |
| `ASR_V1_PORT` | `8011` | 서버 포트 |

## 기존 ASR(port 8001)과의 관계

| | 기존 ASR | ASR V1 |
|---|---|---|
| 포트 | 8001 | 8011 |
| 방식 | HTTP REST 파일 업로드 | WebSocket 스트리밍 |
| VAD | 없음 | Silero VAD |
| 용도 | 단일 파일 전사 | 실시간 대화형 전사 |
| 커넥터 | ASRConnector 직접 사용 | 동일 커넥터 재사용 (배치 호출) |

## 단위 테스트

```bash
cd backend-fastapi
uv run pytest app/modules/ASR_V1/tests/ -v
```

## 모듈 구조

```
app/modules/ASR_V1/
├── pipeline/
│   ├── config.py         # 전체 파라미터 (환경변수 override)
│   ├── vad.py            # Silero VAD 싱글톤 래퍼
│   ├── audio_buffer.py   # 스트리밍 오디오 링 버퍼
│   ├── turn_manager.py   # 턴 커밋 정책
│   ├── flush_policy.py   # LLM→TTS 플러시 정책 (순수 함수)
│   └── session.py        # WS 세션 상태 머신
├── connectors/
│   └── asr_engine.py     # numpy→ASRRequest 변환 엔진
├── schemas/
│   ├── ws_messages.py    # WebSocket 메시지 Pydantic 모델
│   └── config.py         # 세션 설정 스키마
├── app/
│   ├── main.py           # FastAPI 앱 (port 8011, lifespan VAD 사전 로드)
│   └── routers/asr_v1.py # WS + REST 라우터
├── tests/                # 단위 테스트 (5개 파일)
├── static/               # 브라우저 테스트 HTML (한국어 UI)
└── README.md
```

## 프로덕션 라우터 연동

`backend-fastapi/main.py`에서 이 모듈의 라우터를 include할 때:

```python
from app.modules.ASR_V1.app.routers.asr_v1 import router as asr_v1_router
app.include_router(asr_v1_router)
```
