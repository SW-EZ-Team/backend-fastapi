# db

## 모듈 목적
DB 참조 모델을 보관한다. 스키마 SSOT는 `infra/schema/migrations/V2__chapter_studio.sql`이다.

## IN·OUT
IN은 schema 정의이며 OUT은 SQLAlchemy ORM 참조 모델이다.

## 환경변수
`DATABASE_URL`, `DATABASE_SCHEMA`를 사용한다.

## 의존성
`sqlalchemy`, `common.config`에 의존한다.

## 사용 예시
```python
from db.models import Base
```

## 에러 정책
실제 DB 작업 실패 처리는 Phase 5 asyncpg 클라이언트에서 담당한다.
