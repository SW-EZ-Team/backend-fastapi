# app/routers

## 모듈 목적
HTTP 라우터를 기능 단위로 분리해 등록하는 공간이다.

## IN·OUT
IN은 FastAPI 요청 모델이며 OUT은 Pydantic 응답 모델이다.

## 환경변수
해당 없음. 환경값은 `common.config`를 통해 상위 계층에서 주입한다.

## 의존성
Phase 2 기준 직접 의존성은 없다.

## 사용 예시
```python
from fastapi import APIRouter

router = APIRouter()
```

## 에러 정책
라우터는 도메인 예외를 HTTP 예외로 변환한다.
