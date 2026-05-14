# schemas

## 모듈 목적
FastAPI 요청과 응답의 Pydantic V2 strict 스키마를 정의한다.

## IN·OUT
IN은 외부 JSON 요청이며 OUT은 불변 Pydantic 모델이다.

## 환경변수
해당 없음.

## 의존성
`pydantic`에 의존한다.

## 사용 예시
```python
from schemas.request import ChapterRequest
```

## 에러 정책
스키마 위반은 Pydantic `ValidationError`로 즉시 거부한다.
