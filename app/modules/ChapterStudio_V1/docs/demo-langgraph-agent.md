# Demo LangGraph Agent

## 목적
수동 테스트 데모는 Phase 4 본 LangGraph pipeline 이전 단계에서 하나의 얇은 LangGraph agent로 입력 분석, 템플릿 선택, 생성 도구 실행, 후처리, 결과 분리를 검증한다.

## 흐름
1. `agent_select`: `DemoGenerationInput`을 읽고 `select_template()`으로 주제별 학습 템플릿을 고른다.
2. `agent_generate`: `mock` 또는 `CodexCLIConnector(Sign in with ChatGPT)` 경로를 선택해 1강 5장 결과를 생성한다.
3. `agent_finish`: 슬라이드, 퀴즈, 핵심노트, 과제, 음성대본, DB 저장 preview를 분리하고 `agent_plan`을 결과에 붙인다.

## 과외 블루프린트
`tutor_blueprints.py`는 템플릿을 과외 전략으로 바꾼다. 기술 주제는 입력·상태·출력·검증, 과학 주제는 현상·원리·증거·한계, 통계 주제는 변수·분포·추론·한계, 인물 주제는 시대 문제의식·선택·업적·영향으로 설명한다. 이 값은 슬라이드 첫 설명, 핵심노트, 과제, 음성대본, Codex 프롬프트에 함께 들어간다.

## 출력 정책
- 화면은 어떤 단계에서 어떤 도구를 왜 썼는지 `agent_plan`으로 표시한다.
- 설명의 첫 블록은 형식적 목차가 아니라 주제가 왜 필요한지, 기본 철학, 생각 방식, 관점을 다룬다.
- 짧은 실습은 슬라이드 내부 활동이고, 퀴즈 5문항은 별도 산출물로 유지한다.
- 음성대본은 튜터 성향, 속도, 깊이, 질문우선 값을 반영해 슬라이드별 과외 멘트로 생성한다.

## Timeout 정책
- `mock`: 20초 제한으로 빠른 화면 검증을 보장한다.
- `codex_cli`: `CODEX_CLI_TIMEOUT_SEC`를 사용한다. 초과하면 서버 장애가 아니라 생성 도구 지연으로 명확히 분리해 오류를 반환한다.

## 프로덕션 연결성
이 agent는 본 pipeline을 대체하지 않는다. Phase 4에서 11개 노드 LangGraph가 들어오면 동일한 `agent_plan` 개념을 노드 trace와 연결할 수 있도록 데모 계약을 먼저 고정한 것이다.
