# Postgres 17 호환성 검증

`Test_FastAPI_Module/MainAI_docs/09_Database.md`의 7개 테이블 SQL을 infra의 PostgreSQL 17에서 검증한 기록이다.

## 환경

| 항목 | 값 |
|---|---|
| 컨테이너 | `sw-ez-postgres` |
| 이미지 | `postgres:17-bookworm` |
| DB | `sw_ez` |
| 사용자 | `sw_ez` |
| schema | `chapter_studio` |
| 마이그레이션 | `infra/schema/migrations/V2__chapter_studio.sql` |

## 검증 결과

| 항목 | 검증 명령 | 결과 |
|---|---|---|
| CREATE SCHEMA `chapter_studio` | `docker exec sw-ez-postgres psql -U sw_ez -d sw_ez -c "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'chapter_studio';"` | 통과, 1행 반환 |
| 7개 CREATE TABLE | `docker exec sw-ez-postgres psql -U sw_ez -d sw_ez -c "SELECT table_name FROM information_schema.tables WHERE table_schema = 'chapter_studio' ORDER BY table_name;"` | 통과, 7행 반환 |
| JSONB 컬럼 INSERT/SELECT | `docker exec sw-ez-postgres psql -U sw_ez -d sw_ez -c "BEGIN; INSERT INTO chapter_studio.quiz ...; SELECT choices->>0 ...; ROLLBACK;"` | 통과, `A` 반환 |
| TIMESTAMPTZ DEFAULT NOW() | `docker exec sw-ez-postgres psql -U sw_ez -d sw_ez -c "BEGIN; INSERT INTO chapter_studio.slide ...; SELECT created_at IS NOT NULL ...; ROLLBACK;"` | 통과, `t` 반환 |
| REFERENCES 외래키 | `docker exec sw-ez-postgres psql -U sw_ez -d sw_ez -c "BEGIN; INSERT INTO chapter_studio.voice_script ...; INSERT INTO chapter_studio.voice_script_queue ...; ROLLBACK;"` | 통과, 참조 행 삽입 성공 |
| 인덱스 생성 + EXPLAIN | `docker exec sw-ez-postgres psql -U sw_ez -d sw_ez -c "EXPLAIN SELECT * FROM chapter_studio.slide WHERE chapter_id = 'compat-chapter' ORDER BY index; EXPLAIN SELECT * FROM chapter_studio.voice_script_queue WHERE status = 'pending' ORDER BY enqueued_at;"` | 통과, `idx_chapter_studio_slide_chapter`, `idx_chapter_studio_queue_status` 사용 확인 |

## 결론

17 호환 검증 통과. 사용한 구문은 `CREATE SCHEMA`, schema-qualified `CREATE TABLE`, `JSONB`, `TIMESTAMPTZ DEFAULT NOW()`, schema-qualified `REFERENCES`, B-tree 인덱스이며 PostgreSQL 16/17 공통 호환 범위 안에 있다.
