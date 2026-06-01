# ExamForge_V1 — AI 모의고사 생성 모듈

AI 기반 고품질 모의고사를 자동 생성하는 라이브러리 스타일 모듈.

## 목적

학습 자료를 입력하면 다단계 파이프라인을 거쳐 검증된 모의고사를 생성한다.
20종 문제 유형(한국어 9, 영어 8, 전문자격 3)을 지원하며, 교차 모델 정답 검증과
블룸 분류 기반 난이도 보정을 통해 시험 품질을 보장한다.

## IN/OUT 인터페이스

### IN (입력)

```python
MockExamRequest(
    source_text: str,       # 학습 자료 원문 (최소 100자)
    subject: str,           # 과목명
    exam_config: ExamConfig(
        total_questions: int,           # 5~200
        time_limit_minutes: int,        # 10~300
        locale: str,                    # "ko" | "en"
        category: str,                  # "korean" | "us" | "professional"
        question_types: list[str],      # 템플릿 ID 목록
        difficulty_distribution: dict,  # {1: 0.2, 2: 0.3, ...}
        passing_score: float,           # 합격 기준 (0~100)
        include_explanations: bool,     # 해설 포함 여부
    )
)
```

### OUT (출력)

```python
MockExamResponse(
    exam_id: str,
    exam_plan: ExamPlan,
    questions: list[Question],
    quality_metrics: QualityMetrics(
        answer_accuracy_rate: float,        # 교차 검증 통과율
        dedup_score: float,                 # 중복 점수 (1.0 = 중복 없음)
        coverage_score: float,              # 주제 커버리지
        distractor_plausibility_score: float, # 오답 그럴듯함
        length_variance_ratio: float,         # 보기 길이 분산 비율
        bloom_distribution_actual: dict,    # 실제 블룸 분포
        retry_count: int,                   # 재시도 횟수
        generation_time_sec: float,         # 총 생성 시간
    ),
    exam_html: str | None,      # 시험지 HTML
    answers_html: str | None,   # 답안지 HTML
)
```

## 환경 변수

| 변수명 | 필수 | 기본값 | 설명 |
|--------|------|--------|------|
| `ANTHROPIC_API_KEY` | 선택 | — | Claude 커넥터 사용 시 필요 |
| `ACTIVE_TEXT_MODEL` | 선택 | `opus46` | 문제 생성 커넥터 이름 |
| `ACTIVE_PLANNER_MODEL` | 선택 | `opus46` | 계획 수립 커넥터 이름 |
| `ACTIVE_VERIFIER_MODEL` | 선택 | `claude_sonnet` | 정답 교차 검증 및 표적 교정 커넥터. 미설정 시 `claude_sonnet` 사용 |
| `EXAMFORGE_ANSWER_KEY_SECRET` | **필수** | — | 정답 키 위변조 방지용 HMAC secret. **32자 이상 무작위 문자열** 필수. 짧으면 서버 시작 시 즉시 실패 |
| `EXAMFORGE_TARGETED_REPAIR` | 선택 | `true` | 검증 실패 문항의 표적 교정(fix_instructions 소비) 활성화. `false`로 끄면 blind 재생성으로 폴백 |
| `EXAMFORGE_DISTRACTOR_REWRITE` | 선택 | `true` | 오답 선택지 재작성 노드 활성화. 코드 헤비 보기로 JSON이 깨질 위험이 있는 환경에서 `false`로 끈다 |
| `MAX_RETRIES` | 선택 | `3` | 파이프라인 최대 재시도 횟수 |
| `GENERATION_CONCURRENCY` | 선택 | `4` | 문제 생성 병렬 수 |
| `VERIFICATION_CONCURRENCY` | 선택 | `2` | 검증 병렬 수 |
| `MOCK_EXAM_PORT` | 선택 | `8900` | 샌드박스 서버 포트 |

## 사용 예시

### 라이브러리 호출

```python
from app.modules.ExamForge_V1 import generate_exam_forge, ExamForgeRequest

request = ExamForgeRequest(
    source_text="학습 자료 전문...",
    subject="소프트웨어공학",
)
response = await generate_exam_forge(request)
print(f"생성 문항: {len(response.questions)}개")
print(f"정답 정확률: {response.quality_metrics.answer_accuracy_rate:.0%}")
```

### 샌드박스 서버 실행

```bash
cd Test_FastAPI_Module/ExamForge_V1
uv venv && uv pip install -r requirements.txt
cp .env.example .env  # API 키·EXAMFORGE_ANSWER_KEY_SECRET 설정
uv run uvicorn app.main:app --port 8900
# 브라우저에서 http://localhost:8900 접속
```

## 파이프라인 구조

```
parse_source → plan_exam → generate_questions → generate_distractors
    → generate_answers → verify_answers
         │
         ├─ [통과] calibrate_difficulty → format_output → END
         │
         └─ [실패] repair_questions
                    │
                    ├─ [교정 성공] verify_answers (재검증)
                    │
                    └─ [교정 실패 / EXAMFORGE_TARGETED_REPAIR=false]
                          generate_questions (blind 재생성, 최대 MAX_RETRIES회)
                               └─ [소진] calibrate_difficulty → format_output → END
```

### 품질 견고성 장치

- **`<think>` 제거**: 모든 LLM 응답에 `common.llm_output.strip_thinking`을 적용한다. Qwen·reasoning 모델 스왑 시에도 reasoning 블록이 문항 본문에 흘러들어가는 것을 막는다
- **few-shot 앵커**: 문제 생성 프롬프트에 고차원 인지수준 문항 예시를 포함한다. 단순 암기 수준의 단조로운 문항 생성을 줄인다
- **표적 교정 (`repair_questions_node`)**: 검증자(`ACTIVE_VERIFIER_MODEL`)가 생성한 `fix_instructions`를 소비해 실패 문항의 지적된 부분만 교정한다. 교정 실패 또는 `EXAMFORGE_TARGETED_REPAIR=false`이면 기존 blind 재생성으로 폴백해 기존 동작을 보존한다
- **오답 재작성 (`generate_distractors_node`)**: 같은 과목·오개념 기반 오답지를 생성한다. `EXAMFORGE_DISTRACTOR_REWRITE` 플래그로 켜고 끈다. 코드 헤비 선택지(줄바꿈·언어 키워드 포함)는 JSON 파싱 위험이 있어 원본 보존
- **정답 계약 불변**: 교정·재작성 과정에서 `question_id`, `template_id`, `draft_id` 등 식별자·메타데이터는 절대 변경하지 않는다. content 필드(`stem`, `options`, `correct_answer`, `explanation` 등)만 허용 화이트리스트로 관리
- **해설 오개념 라벨**: 퀴즈 해설에 오답별 오개념을 명시적으로 기술하도록 프롬프트가 요구한다

## 지원 문제 유형

### 한국어 (9종)
- 4지선다, 5지선다, 단답형, 서술형, 논술형, OX형, 빈칸채우기, 순서배열, 연결형

### English (8종)
- Multiple Choice (4/5), True/False, Short Answer, Essay, Fill Blank, Matching, Ordering

### 전문자격 (3종)
- 정보처리기사 필기, 정보처리기사 실기, 자격시험 기본형

## 의존성

- `common/llm_output.py`: `strip_thinking`·`extract_json_block`·`loads_lenient` — 모델 스왑(codex↔Qwen↔Claude) 시 출력 정규화 공통 유틸. ExamForge 내부 파서 전단에서 반드시 거친다
- `common/ai_bridge.py`: 자체 포함 AI 커넥터 브리지 (외부 레지스트리 참조 없음)
- LangGraph: 파이프라인 오케스트레이션
- Pydantic: 스키마 검증
- FastAPI: 샌드박스 API 서버

## 폴백/에러 정책

- AI 응답 파싱 실패 시: 해당 문제를 빈 정답으로 마킹하고 검증 단계에서 재생성 대상으로 분류
- 표적 교정 실패 시: blind 재생성으로 폴백 (기존 동작 유지, 최대 `MAX_RETRIES`회)
- 최대 재시도 소진 시: 현재까지 통과한 문제로 출력 (품질 메트릭에 반영)
- `EXAMFORGE_ANSWER_KEY_SECRET` 미설정 또는 32자 미만 시: 서버 시작 시 즉시 `RuntimeError`로 종료

---

## Spring 연결 엔드포인트

### POST /api/mock-exams/generate — 모의고사 생성 트리거

Spring `MockExamService.generateExam()`이 호출하는 fire-and-forget 진입점이다.
Spring은 `mock_exam`을 `status=GENERATING`으로 저장한 뒤 이 경로를 비동기 호출하고,
이후 `getExamDetail`로 폴링한다(READY 상태에서만 문항 조회).

#### 흐름

```
Spring POST /api/mock-exams/generate (Void)
   → 어댑터 202 즉시 반환
   → BackgroundTasks: public.mock_exam+course 조회 → source_text 조립(chapter/slide)
      → ExamForge generate_exam_forge() 실행
      → public.mock_exam_question INSERT + mock_exam.status='READY', total_points 갱신
```

#### 요청 바디 (Spring 발신)

| 키 | 타입 | 설명 |
|----|------|------|
| `examId` | str | `public.mock_exam.id` (연결 키, `mex_` ULID) |
| `courseId` | str | `public.course.id` (출제 자료 출처) |
| `examType` | str | 시험 유형 (midterm/final/practice 등) |
| `questionCount` | int | 문항 수 (1~50, 5 미만이면 5로 보정) |
| `difficulty` | str | easy/medium/hard → 난이도 분포로 매핑 |
| `focusTopics` | list[str] | 집중 주제 (자료 부족 시 보강에 사용) |
| `timeLimit` | int | 제한 시간(분) |

#### Spring이 읽는 결과 위치

- `public.mock_exam` — `status` GENERATING→READY 전이, `total_points` 합산 저장
- `public.mock_exam_question` — `id(mq_ ULID)`, `question_idx`, `question_text`,
  `question_type='multiple_choice'`, `options`(보기 텍스트 JSON 배열),
  `correct_option`(0-based 인덱스 문자열), `explanation`, `points`(정수)

#### 제약/정책

- ExamForge 객관식(options 보유)만 저장한다. 서술형 등 보기 없는 유형은 Spring 단일 정답 채점 스키마와 비호환이라 제외한다(전부 제외되면 READY 미전이)
- 실패 시 상태를 GENERATING으로 유지해 Spring이 미완료로 인지하게 한다(에러 삼킴 금지)
- 같은 `examId` 재요청은 멱등(기존 문항 삭제 후 재삽입)

---

### POST /api/mock-exams/analyze — 채점 결과 AI 총평 생성

Spring `submitExam`이 채점 끝난 결과를 보내 동기 호출하면, 활성 텍스트 커넥터(기본 codex)로 개인 맞춤 약점 진단 총평을 생성해 반환한다.

#### 요청 바디 (Spring 발신)

| 키 | 타입 | 설명 |
|----|------|------|
| `examId` | str | `public.mock_exam.id` |
| `subject` | str | 과목명 |
| `score` | int | 취득 점수 |
| `totalPoints` | int | 만점 |
| `grade` | str | 등급 문자열 (예: "A", "합격") |
| `results` | list | 문항별 채점 결과 (questionIdx, questionText, correct, options, selectedOption, correctOption, explanation) |

#### 응답

```json
{ "analysis": "<한국어 총평 문자열>" }
```

총평은 틀린 보기 텍스트를 복원해 인용하고, 오개념과 다음 학습 연습을 구조화해 제시한다.

#### 폴백 정책

커넥터 호출 실패·빈 응답 시 200으로 폴백 안내문을 반환한다. Spring 흐름을 끊지 않는 것이 우선이다. 실패 사유는 로깅한다.
