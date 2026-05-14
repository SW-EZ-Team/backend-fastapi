# docs

## 모듈 목적
ChapterStudio_V1 sandbox 내부 검증 기록과 spec drift를 보관한다.

## IN·OUT
IN은 검증 명령 결과이며 OUT은 Markdown 기록이다.

## 환경변수
해당 없음.

## 의존성
해당 없음.

## 사용 예시
```bash
find docs -type f -name "*.md"
```

## 주요 문서
- `demo-langgraph-agent.md`: 수동 테스트용 LangGraph 단일 agent 흐름과 timeout 정책을 기록한다.
- `demo-template-catalog.md`: 프론트 색상 토큰과 1강 5장 테스트 템플릿 구조를 기록한다.
- `phase3-production-readiness.md`: Phase 3 커넥터와 후처리 연결 검토를 기록한다.
- `spec-drift.md`: MainAI_docs와 sandbox 구현 차이를 기록한다.

## 에러 정책
문서와 구현이 다르면 `spec-drift.md`에 기록한다.
