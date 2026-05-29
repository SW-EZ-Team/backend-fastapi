# TTS_V2 — 텍스트 음성 합성 모듈

텍스트를 입력받아 MLX Qwen3-TTS 기반의 고품질 한국어 음성으로 합성한다. 내부적으로 LangGraph StateGraph 파이프라인을 사용하며, 청크 분할 → LLM 낭독 계획 → 합성 → QC → 후처리 → 병합 순서로 실행된다.

---

## 모듈 목적

- 텍스트(최대 50,000자)를 의미 단위로 분할하고 각 청크를 합성해 하나의 WAV 오디오로 병합한다.
- WhisperX 또는 ASR V1을 이용해 합성 품질을 검증하고, CER/WER 임계값을 초과한 청크는 자동 재합성한다.
- 고정 튜터 음성 프로필(tutor_1, tutor_2 등) 또는 호출자가 직접 업로드한 레퍼런스 음성으로 클로닝한다.

---

## 파이프라인 구조

```
load_input → clean_text → chunk_text → plan_reading
                                             ↓
                                        synthesize → postfx → qc → retry_router
                                                                          ↓
                                                                  passed/exhausted → merge → END
                                                                  retry → synthesize (루프백)
```

| 노드 | 역할 |
|---|---|
| `load_input` | 입력 텍스트를 파이프라인 상태에 적재 |
| `clean_text` | 특수문자·마크다운·숫자 정규화 |
| `chunk_text` | 의미 단위 분할 (40~120자) |
| `plan_reading` | LLM(Qwen3-4B Instruct)이 낭독 스타일 계획 생성. `skip_planner=True`이면 건너뜀 |
| `synthesize` | Qwen3-TTS로 청크별 오디오 합성 |
| `postfx` | loudness 정규화, 크로스페이드, 묵음 트림 |
| `qc` | WhisperX / ASR V1으로 CER·WER 검증 |
| `retry_router` | QC 결과에 따라 재합성 또는 병합으로 분기 |
| `merge` | 모든 청크 오디오를 하나의 WAV로 병합 |

---

## IN/OUT 인터페이스

### POST `/api/tts-v2` — 텍스트 직접 입력

**Request** (`application/json`)

```json
{
  "text": "합성할 텍스트 (1~50000자, 필수)",
  "voice_profile_id": "tutor_1",
  "ref_audio_base64": null,
  "ref_text": null,
  "language": "ko",
  "speed": 1.0,
  "skip_planner": false,
  "skip_postfx": false,
  "qc_engine": "whisperx"
}
```

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `text` | str | 필수 | — | 합성 대상 텍스트 (최대 50,000자) |
| `voice_profile_id` | str \| null | 선택 | null | 서버 등록 튜터 프로필 ID. null이면 기본값 사용 |
| `ref_audio_base64` | str \| null | 선택 | null | base64 인코딩 레퍼런스 오디오. 지정 시 `ref_text`도 필요 |
| `ref_text` | str \| null | 선택 | null | 레퍼런스 오디오의 전사 텍스트 (최대 500자) |
| `language` | str | 선택 | `"ko"` | 합성 언어 코드 |
| `speed` | float | 선택 | `1.0` | 재생 속도 배율 (0.5~2.0) |
| `skip_planner` | bool | 선택 | `false` | true이면 LLM 낭독 계획 단계를 건너뜀 |
| `skip_postfx` | bool | 선택 | `false` | true이면 loudness·크로스페이드 후처리를 건너뜀 |
| `qc_engine` | str | 선택 | `"whisperx"` | `"whisperx"` / `"v1_asr"` / `"both"` |

**Response** (`200 OK`)

```json
{
  "audio_base64": "<WAV base64 문자열>",
  "total_duration_sec": 42.3,
  "sample_rate": 24000,
  "chunk_count": 12,
  "failed_chunk_count": 0,
  "failed_chunk_ids": [],
  "avg_cer": 0.04,
  "avg_wer": 0.05,
  "qc_reason_counts": {},
  "chunk_qc_reasons": [],
  "timings": {
    "loading": 12,
    "cleaning": 30,
    "chunking": 45,
    "planning": 1200,
    "synthesize": 8400,
    "postfx": 310,
    "qc": 4200,
    "merge": 80
  },
  "model": "qwen3-tts-1.7b-base",
  "qc_engine_used": "whisperx"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `audio_base64` | str | base64 인코딩 WAV 바이너리. 클라이언트에서 직접 재생 가능 |
| `total_duration_sec` | float | 합성 오디오 전체 길이(초) |
| `sample_rate` | int | 샘플링 레이트 (기본 24,000 Hz) |
| `chunk_count` | int | 처리된 총 청크 수 |
| `failed_chunk_count` | int | QC 재시도 소진 후 실패한 청크 수 |
| `failed_chunk_ids` | list[str] | 실패 청크 ID 목록 |
| `avg_cer` | float \| null | 평균 문자 오류율 (QC 건너뛰면 null) |
| `avg_wer` | float \| null | 평균 단어 오류율 (QC 건너뛰면 null) |
| `qc_reason_counts` | dict | QC 실패 사유별 청크 수 |
| `chunk_qc_reasons` | list[dict] | 청크별 QC 실패 사유 |
| `timings` | dict[str, float] | 단계별 소요 시간 (ms) |
| `model` | str | 사용된 TTS 모델명 |
| `qc_engine_used` | str | 실제 사용된 QC 엔진 |

---

### POST `/api/tts-v2/file` — 파일 업로드 TTS

**Request** (`multipart/form-data`)

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `text_file` | file | 필수 | .txt 또는 .md 파일 |
| `ref_audio` | file | 선택 | 레퍼런스 오디오 파일. 없으면 기본 튜터 프로필 사용 |
| `ref_text` | str | 조건부 | `ref_audio` 지정 시 필수 |
| `voice_profile_id` | str | 선택 | 튜터 프로필 ID |
| `language` | str | 선택 | 기본 `"ko"` |
| `speed` | float | 선택 | 기본 `1.0` |
| `skip_planner` | bool | 선택 | 기본 `false` |
| `skip_postfx` | bool | 선택 | 기본 `false` |
| `qc_engine` | str | 선택 | 기본 `"whisperx"` |

**Response**: 텍스트 직접 입력과 동일한 `TTSV2Response`

---

### GET `/api/tts-v2/voices` — 음성 프로필 목록

**Response**

```json
{
  "profiles": [
    {
      "profile_id": "tutor_1",
      "display_name": "튜터 1",
      "tone": "차분하고 명료한 설명 톤",
      "language": "ko",
      "duration_sec": 8.5,
      "sample_rate": 22050
    }
  ]
}
```

---

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `TTS_V2_CHUNK_MIN_CHARS` | `40` | 청크 최소 글자 수 |
| `TTS_V2_CHUNK_MAX_CHARS` | `120` | 청크 최대 글자 수 |
| `TTS_V2_MAX_RETRIES` | `3` | QC 실패 시 재합성 최대 횟수 |
| `TTS_V2_CER_THRESHOLD` | `0.20` | CER 허용 상한 |
| `TTS_V2_WER_THRESHOLD` | `0.25` | WER 허용 상한 |
| `TTS_V2_SILENCE_MAX_RATIO` | `0.30` | 묵음 비율 상한 |
| `TTS_V2_CROSSFADE_MS` | `50` | 청크 간 크로스페이드 (ms) |
| `TTS_V2_TARGET_LUFS` | `-16.0` | 목표 loudness (LUFS) |
| `TTS_V2_PEAK_DBFS` | `-2.0` | 피크 제한 (dBFS) |
| `TTS_V2_QC_ENGINE` | `"whisperx"` | 기본 QC 엔진 |
| `TTS_V2_WHISPERX_MODEL` | `"large-v3"` | WhisperX 모델 크기 |
| `TTS_V2_LLM_PLANNER_MODEL_PATH` | `mlx-community/Qwen3-4B-Instruct-2507-4bit` | 낭독 계획 LLM 모델 경로 |
| `TTS_V2_PORT` | `8010` | 단독 서버 실행 시 포트 |
| `TTS_V2_AGGRESSIVE_UNLOAD` | `false` | 노드 실행 후 모델 즉시 언로드 여부 |
| `TTS_V2_DEFAULT_VOICE_PROFILE` | — | 기본 튜터 음성 프로필 ID |

---

## 의존성

```
mlx-audio          # MLX 기반 Qwen3-TTS 추론 (Mac MPS)
langgraph          # StateGraph 파이프라인
pydub              # 오디오 후처리 (loudness, crossfade, trim)
whisperx           # QC용 ASR 엔진 (기본)
pydantic >= 2      # 요청/응답 스키마
```

상세 버전은 `requirements.txt` 참조.

---

## 사용 예시

```python
import httpx, base64, json

payload = {
    "text": "오늘의 강의 주제는 뉴턴의 운동 법칙입니다.",
    "voice_profile_id": "tutor_1",
    "speed": 1.0,
    "qc_engine": "whisperx"
}

response = httpx.post("http://localhost:8010/api/tts-v2", json=payload)
data = response.json()

audio_bytes = base64.b64decode(data["audio_base64"])
with open("output.wav", "wb") as f:
    f.write(audio_bytes)
```

---

## 에러 처리 정책

| 상황 | HTTP 상태 | 설명 |
|---|---|---|
| 알 수 없는 `voice_profile_id` | 400 | 등록된 프로필 ID 목록을 에러 메시지에 포함 |
| `ref_audio_base64`만 있고 `ref_text` 누락 | 400 | 두 필드는 반드시 함께 제공해야 함 |
| `ref_audio_base64` base64 디코딩 실패 | 400 | 디코딩 오류 상세를 포함 |
| 파이프라인 오디오 생성 실패 | 500 | `error_message` 필드에 상세 원인 포함 |
| QC 재시도 소진 청크 | 200 | 실패 청크를 포함한 채로 병합 후 반환. `failed_chunk_ids`에 목록 기재 |

QC 재시도 소진 청크는 에러로 처리하지 않는다. 실패 청크가 있어도 나머지 청크로 오디오를 완성하고 `failed_chunk_ids`에 기록해 반환한다. 운영에서 `failed_chunk_count > 0`인 경우 수동 검토가 필요하다.
