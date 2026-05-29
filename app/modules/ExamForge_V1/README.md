# MockExam_V1 - AI 모의고사 생성 모듈

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
| `ANTHROPIC_API_KEY` | O | - | Claude API 키 |
| `ACTIVE_TEXT_MODEL` | X | `opus46` | 텍스트 생성 커넥터 |
| `ACTIVE_PLANNER_MODEL` | X | `opus46` | 계획 수립 커넥터 |
| `ACTIVE_VERIFIER_MODEL` | X | `claude_sonnet` | 정답 검증 커넥터 |
| `MAX_RETRIES` | X | `3` | 파이프라인 최대 재시도 |
| `GENERATION_CONCURRENCY` | X | `4` | 문제 생성 병렬 수 |
| `VERIFICATION_CONCURRENCY` | X | `2` | 검증 병렬 수 |
| `MOCK_EXAM_PORT` | X | `8900` | 샌드박스 서버 포트 |

## 사용 예시

### 라이브러리 호출

```python
from MockExam_V1 import generate_mock_exam, MockExamRequest

request = MockExamRequest(
    source_text="학습 자료 전문...",
    subject="소프트웨어공학",
)
response = await generate_mock_exam(request)
print(f"생성 문항: {len(response.questions)}개")
print(f"정답 정확률: {response.quality_metrics.answer_accuracy_rate:.0%}")
```

### 샌드박스 서버 실행

```bash
cd Test_FastAPI_Module/MockExam_V1
uv venv && uv pip install -r requirements.txt
cp .env.example .env  # API 키 설정
uv run uvicorn app.main:app --port 8900
# 브라우저에서 http://localhost:8900 접속
```

## 파이프라인 구조

```
parse_source -> plan_exam -> generate_questions -> generate_distractors
    -> generate_answers -> verify_answers -> validate -> retry_router
    -> [passed] calibrate_difficulty -> format_output -> END
    -> [retry] generate_questions (최대 3회)
    -> [exhausted] calibrate_difficulty -> format_output -> END
```

## 지원 문제 유형

### 한국어 (9종)
- 4지선다, 5지선다, 단답형, 서술형, 논술형, OX형, 빈칸채우기, 순서배열, 연결형

### English (8종)
- Multiple Choice (4/5), True/False, Short Answer, Essay, Fill Blank, Matching, Ordering

### 전문자격 (3종)
- 정보처리기사 필기, 정보처리기사 실기, 자격시험 기본형

## 의존성

- `common/ai_bridge.py`: 자체 포함 AI 커넥터 브리지 (외부 모듈 참조 없음)
- LangGraph: 파이프라인 오케스트레이션
- Pydantic: 스키마 검증
- FastAPI: 샌드박스 API 서버

## 폴백/에러 정책

- AI 응답 파싱 실패 시: 해당 문제를 빈 정답으로 마킹하고 검증 단계에서 재생성 대상으로 분류
- 검증 실패율 10% 이상 시: 자동 재시도 (최대 3회, `common/ai_bridge.py` 내부 지수 백오프)
- 최대 재시도 소진 시: 현재까지 통과한 문제로 출력 (품질 메트릭에 반영)
