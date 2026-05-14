# pipeline

## 모듈 목적
ChapterStudioState와 계층 간 변환을 관리한다.

## IN·OUT
IN은 `ChapterRequest`와 노드별 State 조각이며 OUT은 `ChapterStudioState`, `ChapterResponse`, DB 행 묶음이다.

## 환경변수
해당 없음. 환경값은 `common.config`가 관리한다.

## 의존성
`schemas`, `common.errors`에 의존한다.

## 사용 예시
```python
from pipeline.converters import request_to_initial_state
```

## 에러 정책
변환 실패는 `ConversionError`로 올린다.
