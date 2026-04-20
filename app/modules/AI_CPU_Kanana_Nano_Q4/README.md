# AI_CPU_Kanana_Nano_Q4

Kanana Nano 2.1B Q4_K_M (1.3GB) GGUF 모델 기반 텔레그램 과제 캡션 생성 모듈이다. CPU-only로 동작하며 GCP e2-standard-4 기준으로 설계됐다.

---

## 공개 API

```python
from app.modules.AI_CPU_Kanana_Nano_Q4 import generate_caption, CaptionResult
```

이 두 심볼만 외부에서 사용한다. 내부 파일(`caption.py`, `model_loader.py` 등)을 직접 import하면 안 된다.

### 사용 예

```python
from app.modules.AI_CPU_Kanana_Nano_Q4 import generate_caption, CaptionResult

result = generate_caption(
    student_name="김민준",
    assignment_name="파이썬 리스트 컴프리헨션",
    weakness=None,
    deadline="내일 23:59",
)
print(result.text)        # "민준아, 오늘 리스트 컴프리헨션 같이 해보자! 내일 23:59까지야, 할 수 있어!"
print(result.source)      # "kanana" 또는 "fallback"
print(result.char_count)  # 글자수 정수
```

---

## IN / OUT

### 입력 (`generate_caption` 인자)

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `student_name` | `str` | ✅ | 학생 이름 |
| `assignment_name` | `str` | ✅ | 과제 이름 |
| `weakness` | `str \| None` | - | 약점 키워드 (없으면 생략) |
| `difficulty` | `str \| None` | - | 난이도 표현 (없으면 생략) |
| `deadline` | `str \| None` | - | 마감 표현 (없으면 생략) |

### 출력 (`CaptionResult` 필드)

| 필드 | 타입 | 설명 |
|---|---|---|
| `text` | `str` | 20~100자 캡션 본문 |
| `source` | `"kanana" \| "fallback"` | 생성 경로 — Kanana 추론 성공 시 `"kanana"`, 폴백 시 `"fallback"` |
| `char_count` | `int` | `text` 글자수 |

---

## 출력 제약

길이 20~100자, 1~2문장, 이모지 최대 1개. 학생 이름은 자연스러우면 포함하고 어색하면 누락을 허용한다. 톤 세부 정책은 `config.py`의 `SYSTEM_PROMPT`로 내부 고정되어 있으며 외부에 공개하지 않는다. `MIN_CHARS` / `MAX_CHARS` / `MAX_EMOJIS` 상수가 제약을 코드 레벨에서 강제한다. 임의 변경 금지.

---

## 폴백 흐름

```
generate_caption() 호출
       |
       v
Kanana 추론 (_run_kanana)
       |
       v
validator.sanitize() 검증
  - 20자 미만 → None
  - 100자 초과 → None
  - 이모지 2개 이상 → None
       |
    통과?
   /     \
 YES      NO
  |        |
  v        v
source=   Jinja2 템플릿 렌더링 (fallback.py)
"kanana"  source="fallback"
```

Jinja2 폴백은 항상 100자 이내를 보장한다. 추론 자체가 예외를 던져도 폴백으로 안전하게 처리된다.

---

## 파라미터 (config.py 기준)

| 상수 | 값 | 설명 |
|---|---|---|
| `THREADS` | `4` | llama.cpp 스레드 수 (e2-standard-4의 vCPU 4개) |
| `N_GPU_LAYERS` | `0` | GPU 레이어 0 — CPU-only 강제 |
| `TEMPERATURE` | `0.7` | 샘플링 온도 |
| `TOP_P` | `0.9` | Top-p 샘플링 |
| `MAX_TOKENS` | `120` | 최대 생성 토큰 (100자 여유분) |
| `REPEAT_PENALTY` | `1.1` | 반복 억제 |
| `CONTEXT_SIZE` | `1024` | 컨텍스트 윈도우 크기 |

---

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `KANANA_MODEL_PATH` | `app/modules/AI_CPU_Kanana_Nano_Q4/models/kanana-nano-2.1b-instruct.Q4_K_M.gguf` | GGUF 모델 파일 절대 경로. 운영 환경에서는 볼륨 마운트 경로로 덮어쓴다. |

모델 파일은 git에 포함되지 않는다. `.gitignore`에 `models/*.gguf` 등록 상태.

---

## 모델 다운로드

`scripts/setup.sh`를 실행하면 llama.cpp 빌드와 모델 다운로드가 진행된다.

```bash
cd app/modules/AI_CPU_Kanana_Nano_Q4
bash scripts/setup.sh
```

스크립트가 완료되면 `models/kanana-nano-2.1b-instruct.Q4_K_M.gguf` 파일이 생성된다.

---

## 실측 품질 (v3, 2026-04-14)

GCP e2-standard-4 시뮬레이션 기준 `scripts/run_quality.sh` 실행 결과다.

| 항목 | 수치 |
|---|---|
| 생성 속도 | 22.3 tok/s |
| 100자 이내 비율 | 15샘플 중 13개 (86.7%) |
| 톤 일관성 | 내부 기준 유지 |
| 할루시네이션 | 0건 |

100자 초과 2건은 `validator.sanitize()`가 걸러내고 Jinja2 폴백으로 처리된다.

---

## 테스트 실행

```bash
pytest app/modules/AI_CPU_Kanana_Nano_Q4/tests/
```

| 테스트 파일 | 검증 내용 |
|---|---|
| `test_config.py` | `SYSTEM_PROMPT` 내용 일치, `MAX_CHARS == 100`, `THREADS == 4` 등 출력 제약 회귀 확인 |
| `test_validator.py` | 10자 미만·100자 초과·이모지 2개 → `None` 반환, 정상 캡션 통과 |
| `test_fallback.py` | 이름/약점/마감 조합별 Jinja2 출력이 100자 이내인지 확인 |

---

## ⚠️ 주의

**Celery prefork 메모리**: 워커당 1.3GB 소비. e2-standard-4 (16GB) 기준 워커 수를 2~3개로 제한해야 한다. Celery 설정에서 `--concurrency` 를 반드시 확인할 것.

---

## 명명 근거

폴더명 `AI_CPU_Kanana_Nano_Q4`는 대문자·숫자 포함으로 PEP 8을 위배한다. 단, Python identifier로는 유효하며 import도 정상 동작한다. 사용자 지정 식별자로 예외 허용 — 변경 금지.
