# replay — 저장된 모의고사 문항 품질 재검증 (LLM 호출 0)

`app/modules/ExamForge_V1/quality/replay.py`

## 목적

품질 로직(챕터 쿼터·의미 dedup·과대표현·해설)을 바꿀 때마다 **새 시험을 생성하지 않고**,
이미 DB에 저장된 문항을 품질 게이트에 다시 통과시켜 "무엇이 플래그되는지"를 **LLM 호출 0**으로
확인한다. 비싼 풀 재생성 반복(오늘 비용의 대부분)을 정적 재검증으로 대체한다.

라이브 AI 생성·임베딩 API를 **절대 호출하지 않는다**. 모든 계산은 결정론적 정적 분석(DB SELECT만).

## 공개 API

`from app.modules.ExamForge_V1.quality import analyze_questions, load_attempt_questions, fetch_attempt_question_rows, format_report_text`

### `analyze_questions(questions: list[dict]) -> dict`  (순수 함수, 인프라 의존 0)

| 항목 | 내용 |
|---|---|
| IN | 문항 dict 리스트. 최소 `stem`. 선택: `correct_answer`, `explanation`, `template_id`, `options`, `topic`, `chapter`, `_concept_key`/`concept_key`, `question_id`/`draft_id` |
| OUT | 구조화 리포트 dict (아래 키) |

OUT dict 키:
- `question_count: int`
- `meta`: `{chapter_meta_stored: bool, chapter_basis: "stored"|"estimated", llm_calls: 0, notes: [str]}`
- `scenario_gate`: `{flagged_count, flagged: {id:[issue]}, clusters: [{kind, question_ids, count}]}`
  - `kind` ∈ `scenario_duplicate` | `semantic_duplicate` | `concept_overrepresentation`
  - `scenario_gate.check_scenario_quality`를 그대로 호출 — 게이트 동작 변경 없음
- `chapter_coverage`: `{estimated, total_questions, distinct_chapters, counts, unlabeled_questions, skewed_chapters}`
- `concept_diversity`: `{total_questions, distinct_concepts, diversity_ratio, unlabeled_questions, top_concepts}`
- `explanation_lengths`: `{missing, stub, short, ok, min_length, max_length, mean_length, flagged}`
- `type_distribution`: `{distinct_types, counts}` (template_id 기준, 빈값은 `UNKNOWN`)

### `load_attempt_questions(attempt_id: str) -> list[dict]`  (async, DB 어댑터)

`DATABASE_URL`(asyncpg DSN)로 연결해 `exam_attempt_question`을 **SELECT만** 수행하고
게이트가 먹는 dict로 변환한다. TTS_V2 `helpers_async` asyncpg 패턴과 동일.
`DATABASE_URL` 미설정 시 `RuntimeError`.

### `fetch_attempt_question_rows(conn, attempt_id) -> list[dict]`  (async, DI)

주입된 asyncpg 호환 커넥션으로 행을 읽어 변환한다(테스트에서 mock 커넥션 주입용).

### `format_report_text(attempt_id, report) -> str`  (순수 함수)

리포트를 사람이 읽는 텍스트(챕터 커버리지·중복 클러스터·해설 길이 요약)로 렌더한다.

## CLI

```bash
cd backend-fastapi
DATABASE_URL=postgresql://... uv run python -m app.modules.ExamForge_V1.quality.replay <attempt_id>
```

종료 코드: `0`=성공(플래그 유무 무관), `1`=로드/실행 실패. CI 게이트로 쓰려면 호출부가
리포트의 `scenario_gate.flagged_count`를 직접 판정한다.

## DB 컬럼 매핑 — 챕터/개념 메타 저장 한계 (중요)

`exam_attempt_question`(Spring 소유, V14 마이그레이션) 컬럼:
`id, attempt_id, question_id, template_id, display_order, stem, options_json(JSONB), points, correct_answer, explanation, source_reference, grading_metadata_json(JSONB)`

- **`chapter` / `concept_key` 컬럼은 존재하지 않는다.** 생성 시점의 `_concept_key`는
  `mock_generation_callback._to_spring_question` 경계에서 버려진다.
- 저장 시 살아남는 메타는 `grading_metadata_json` 안의 `topic` / `difficulty` / `bloom_level` 뿐.
- 따라서 **챕터 커버리지는 정확 집계 불가** → `topic`(있으면) 또는 `stem` 토큰으로 추정.
  리포트 `meta.chapter_basis = "estimated"`, `chapter_coverage.estimated = True`로 한계를 명시한다.
- 입력 dict에 `chapter`/`_concept_key`가 직접 들어오면(생성 직후 in-memory 검증) 그 값을
  우선 사용 → `estimated = False`. replay는 DB 경로·in-memory 경로 양쪽을 지원한다.

매핑(`_row_to_question`): `options_json` → `options`(label/text/is_correct, snake/camel 둘 다 복원),
`grading_metadata_json` → `topic`/`difficulty`/`bloom_level`/`code_snippet`를 최상위로 평탄화.

## 폴백 / 에러 정책

- 빈/단일 입력: 예외 없이 0/빈 매핑 리포트 반환.
- 깨진 `options_json`/`grading_metadata_json`: 빈 리스트/빈 dict로 안전 처리(분석은 stem만으로 가능).
- `DATABASE_URL` 미설정: `RuntimeError`. 연결/조회 실패: CLI는 exit 1 + 메시지(트레이스백 없음).

## 테스트

`app/modules/ExamForge_V1/tests/test_replay.py` — 의미 중복 클러스터, 챕터 편중, 해설 길이 통계,
빈/단일 안전, 유형 분포, 행 매핑(mock 커넥션), DSN 가드, CLI 경로. 전부 fixture/mock — 라이브 호출 0.
