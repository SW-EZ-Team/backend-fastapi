# pipeline/nodes

## 모듈 목적
LangGraph 노드를 한 파일 한 책임으로 배치하는 공간이다.

## IN·OUT
IN은 `ChapterStudioState` 일부 필드이며 OUT은 갱신할 State 조각이다.

## 환경변수
해당 없음. 커넥터 설정은 `common.config`와 `ai_connectors`가 담당한다.

## 의존성
Phase 2 기준 직접 의존성은 없다.

## 사용 예시
```python
from pipeline.state import ChapterStudioState
```

## 에러 정책
노드 실패는 Phase 4에서 `error_log` 누적으로 통일한다.
