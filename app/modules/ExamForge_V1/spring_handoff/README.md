# ExamForge Spring Grading Handoff

이 폴더는 `backend-spring/`을 직접 수정하지 않고 준비한 Spring 이식용 코드다.
`backend-spring/` 병합 전까지 이 폴더를 기준 구현으로 삼고, 병합 시 같은 패키지 구조로 복사한다.

## 이식 위치

`src/main/java/com/swez/backend/examforge/grading/**` 아래 파일을 Spring repo의 동일 패키지로 복사한다.

## 역할 분리

- Spring: 응시 생성/제출 수명주기, 서버 DB 스냅샷 조회, 객관식/단답/빈칸/순서/연결형 확정 채점, 총점 병합, 공개 응답 반환.
- FastAPI: 시험 생성, 정답지 seal 검증, 서술형/논술형/실기형 AI 루브릭 채점.
- Frontend: 시험지 표시와 답안 입력만 담당. 정답, 해설, `answerKeySeal`은 절대 받거나 보내지 않는다.

## 운영 흐름

1. Spring이 FastAPI `/api/exam-forge/generate` 결과를 서버 DB에 저장한다.
2. 프론트에는 시험지 표시용 데이터와 `attemptId`만 내려준다.
3. `correctAnswer`, `explanation`, `sourceReference`, `answerKeySeal`, `answersHtml`은 프론트로 보내지 않는다.
4. 제출 시 프론트는 `attemptId`와 `submittedAnswers`만 Spring에 보낸다.
5. Spring은 서버 저장 스냅샷으로 객관식/단답/빈칸/순서/연결형을 자체 채점한다.
6. 서술형/논술형/실기형 루브릭 문항만 FastAPI `/api/exam-forge/grade-submission`으로 보낸다.
7. Spring은 전체 점수를 병합하고 누수 검사를 통과한 공개 응답만 프론트로 반환한다.

## Spring 공개 API

`POST /api/exam-forge/submissions/grade`

요청은 아래 두 값만 받는다.

```json
{
  "attemptId": "attempt_20260526_0001",
  "submittedAnswers": [
    {
      "questionId": "q_0001",
      "answer": "B"
    },
    {
      "questionId": "q_0002",
      "answer": {
        "text": "응시자 서술형 답안"
      }
    }
  ]
}
```

응답에는 점수, 상태, 공개 피드백만 포함한다. 정답/해설/seal/채점용 HTML은 포함하지 않는다.

## 필수 설정

```yaml
examforge:
  fastapi:
    base-url: http://localhost:8000
    api-key: ${FASTAPI_API_KEY}
    connect-timeout: 3s
    read-timeout: 120s
```

Spring에서 FastAPI를 호출할 때는 `X-API-Key: ${FASTAPI_API_KEY}`를 붙인다. 프론트엔드에는 이 키를 절대 내려주지 않는다.
`examforge.fastapi.base-url`과 `examforge.fastapi.api-key`가 없으면 FastAPI client bean은 생성하지 않는다. 따라서 병합 직후 설정이 비어 있어도 Spring Boot 부팅이 깨지지 않고, 실제 연동 시점에 환경변수만 주입하면 된다.

## 이식 후 반드시 구현할 포트

`ExamAttemptRepositoryPort` 구현체를 Spring DB 레이어에 붙인다.

- `findGradingSnapshot(attemptId)`는 서버 저장 시험 스냅샷을 반환해야 한다.
- 반환 스냅샷에는 `answerKeySeal`, 정답, 해설, 루브릭 기준이 있어야 한다.
- 이 값들은 절대 프론트 응답 DTO에 매핑하지 않는다.

## 권장 DB 스키마

Spring 팀 DB 규칙에 맞게 엔티티명/컬럼명은 조정해도 되지만, 아래 데이터는 반드시 서버에 남아야 한다.

- `exam_attempts`: `attempt_id`, `exam_id`, `user_id`, `status`, `pass_percentage`, `answer_key_seal`, `created_at`, `submitted_at`, `graded_at`
- `exam_attempt_questions`: `attempt_id`, `question_id`, `template_id`, `display_order`, `stem`, `options_json`, `points`, `correct_answer`, `explanation`, `source_reference`, `grading_metadata_json`
- `exam_submitted_answers`: `attempt_id`, `question_id`, `answer_json`, `submitted_at`
- `exam_question_grades`: `attempt_id`, `question_id`, `score`, `max_score`, `grading_mode`, `feedback`, `rubric_breakdown_json`, `confidence`, `needs_manual_review`
- `exam_grade_results`: `attempt_id`, `total_score`, `max_score`, `percentage`, `passed`, `grading_status`, `graded_at`

프론트 조회용 projection은 위 테이블에서 `correct_answer`, `explanation`, `source_reference`, `answer_key_seal`, `grading_metadata_json`을 제외해서 만든다.

## 누수 방지 체크

`GradingLeakGuard`가 공개 응답 직렬화 결과에서 아래 항목을 차단한다.

- 필드명 차단: `correctAnswer`, `correct_answer`, `explanation`, `sourceReference`, `source_reference`, `answerKeySeal`, `answer_key_seal`, `answersHtml`, `answers_html`
- 값 차단: 서버 스냅샷 안의 정답, 해설, 출처, 오답 근거, 정렬형 정답, 빈칸 정답, 연결형 우항, 정답 보기 값이 공개 피드백/루브릭 사유에 섞이면 차단
- 저장 순서: 공개 응답 누수 검사를 통과한 뒤에만 `saveGradingResult`를 호출한다.
- FastAPI 루브릭 응답 검증: 요청한 문항 외 결과, 누락 결과, 중복 결과, 음수 점수, 만점 초과 점수, 문항 만점 불일치를 실패 처리
- 빈 제출 허용: `submittedAnswers: []`는 전체 미응답으로 간주해 0점 채점한다. 시간초과 자동제출/백지 제출 케이스를 정상 처리하기 위함이다.

## 병합 전 체크리스트

- `ExamAttemptRepositoryPort` 실제 DB 어댑터 구현
- `examforge.fastapi.base-url`, `examforge.fastapi.api-key` 운영 환경 주입
- Spring 통합 테스트에서 FastAPI `/api/exam-forge/grade-submission` 실제 호출 확인
- 프론트 제출 API가 `attemptId + submittedAnswers` 외 값을 보내지 않는지 확인
- 공개 시험지 API에서 정답/해설/seal/채점용 HTML이 내려가지 않는지 JSON 스냅샷 테스트 추가

## 현재 독립 검증

```bash
/Users/kimtaekyu/Documents/Develop_Fold/100_UnivVT/SW_project/backend-spring/gradlew \
  -p /Users/kimtaekyu/Documents/Develop_Fold/100_UnivVT/SW_project/backend-fastapi/app/modules/ExamForge_V1/spring_handoff \
  test --no-daemon
```

통과 기준: handoff 모듈 컴파일, 결정형 채점, AI 루브릭 포트 라우팅, 중복/위조 제출 차단, 공개 응답 누수 차단 테스트 통과.
