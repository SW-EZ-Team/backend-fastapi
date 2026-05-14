# Spec Drift

- `Test_FastAPI_Module/MainAI_docs/09_Database.md`는 PostgreSQL 16과 alembic 중심 설명을 포함하지만, 현재 실행 infra는 PostgreSQL 17 + Flyway다. 코드와 실행 검증은 infra 기준으로 맞추고 원본 MainAI 문서는 수정하지 않는다.
- `Test_FastAPI_Module/MainAI_docs/09_Database.md`의 테이블명은 schema 미지정이지만, 공용 `sw_ez` DB 충돌 방지를 위해 실제 마이그레이션은 `chapter_studio` schema-qualified 테이블로 둔다.
- 응답 스키마(`schemas/response.py`)의 dict 키와 V2 SQL(`infra/schema/migrations/V2__chapter_studio.sql`) 컬럼명 사이에 아래와 같은 naming drift가 존재한다. `db/asyncpg_client.py`가 INSERT 시 매핑 함수를 거치지 않으면 컬럼 미스매치로 실패함.

  | 도메인 | 응답 dict 키 | V2 SQL 컬럼 | 비고 |
  |---|---|---|---|
  | Slide | `slide_idx` | `index` | int 위치 인덱스, 의미는 동일 |
  | Slide | `html_content` | `html` | DB는 짧은 이름 채택 |
  | Slide | (없음) | `category`, `css` | DB 전용 — 응답에는 미노출 |
  | Quiz | `quiz_idx` | (없음) | 응답 전용 — DB 정렬은 `id` 기반 |
  | Quiz | `difficulty` | `depth` | 값 도메인은 동일 (상/중/하 + hard/medium/easy) |
  | Quiz | (없음) | `explanation` | DB 전용 — 응답 단계에서 미반환 |
  | Note | `content` | `html` | DB는 HTML 의도 명시 |
  | Assignment | `content` | `prompt` | DB는 LLM 프롬프트 의도 명시 |
  | Assignment | (없음) | `criteria`, `expected_minutes` | DB 전용 — 응답 단계에서 미반환 |
  | VoiceScript | `slide_idx` | `slide_index` | 짧은 별칭 vs 풀네임 |
  | VoiceScript | `script_text` | `text` | DB는 짧은 이름 채택 |

  처리 원칙은 다음과 같다. 응답 스키마는 사용자 노출용 단순 키를 유지하고, DB 컬럼은 무결성·인덱스·HTML/프롬프트 의도를 드러내는 풀네임을 유지한다. 응답 전용 필드(`quiz_idx`)는 INSERT 시 DROP하고, DB 전용 필드(`category`, `css`, `explanation`, `criteria`, `expected_minutes`, `duration_hint_sec`, `audio_url`)는 connector 레이어가 별도로 채워야 한다. ORM 모델(`db/models.py`)은 V2 SQL 컬럼명 그대로 유지한다(이미 일치). Phase 5 `db/asyncpg_client.py` INSERT 함수는 반드시 응답 dict → DB row 매핑을 명시적으로 한 곳에서 처리해야 한다.

## 4. nh3==0.2.18 / ammonia-4.0.0 — `"a"` attrs `"rel"` 비호환

- **발견 일시**: 2026-04-28 Phase 3 NoThinkingAgent 재스폰 1차
- **증상**: `nh3.clean()` 호출 시 Rust 레벨 PanicException 발생
  - 메시지: `assertion failed: self.tag_attributes.get("a").and_then(|a| a.get("rel")).is_none()`
  - 위치: `ammonia-4.0.0/src/lib.rs:1776`
- **원인**: ammonia는 `"a"` 태그의 `rel` 속성을 `attributes` 딕셔너리로 직접 받는 것을 거부함. 별도 `link_rel` 메서드로만 외부 링크 rel 강제 추가를 허용함. `attributes` 인자에 `"rel"`이 들어오면 assertion으로 차단함.
- **사용자 결정 (2026-04-28)**: 옵션 A — SSOT(`MainAI_docs/05_Postprocess.md §3.5`)의 `BASE_ALLOWED_ATTRS["a"]`에서 `"rel"` 항목 삭제. ChapterStudio_V1 `postprocess/sanitizer.py`도 정정 SSOT 그대로 따름.
- **처리 원칙**:
  - sanitize 화이트리스트는 ammonia 인자 한계에 맞춤
  - 외부 링크 보안(`rel="noopener noreferrer"`) 의도가 필요한 경우 향후 별도 라운드에서 `nh3.clean(... link_rel=...)` 옵션 도입 논의
  - 현재는 sanitize 화이트리스트만 우선 가동
- **다음 액션**: Phase 3 NoThinkingAgent 2차 재스폰 → sanitizer.py 정정 SSOT 그대로 재작성 → pytest 122 passed / 0 failed 복원

## 5. nh3==0.2.18 / ammonia-4.0.0 두 번째 비호환 — `tags` ⊆ `attributes` 키 제약

### 발견 일시
2026-04-28 (Phase 3 NoThinkingAgent 재스폰 2차 라운드)

### 증상
`tests/unit/test_postprocess_sanitizer.py`의 `test_interactive_category_allows_script_tag`, `test_interactive_category_allows_button` 두 케이스에서 `pyo3_runtime.PanicException: assertion failed: !self.tags.contains(tag_name)` Rust 레벨 panic 발생. 4번째 비호환 정정(rel 제거) 후에도 panic 지속.

### 원인
ammonia-4.0.0의 신규 제약 — `Builder.tags()`로 등록한 태그는 `Builder.tag_attributes()`(=`BASE_ALLOWED_ATTRS`) dict에도 반드시 키로 등록되어야 함. SSOT(`05_Postprocess.md` §3.5)의 `INTERACTIVE_EXTRA_TAGS = {"script", "button", "details", "summary"}` 중 `script`와 `button`이 `BASE_ALLOWED_ATTRS`에 키 없음 → ammonia 내부 assertion 위반 → panic.

### 사용자 결정
2026-04-28 옵션 1 선택 — SSOT(`05_Postprocess.md` §3.5)의 `BASE_ALLOWED_ATTRS`에 4종 항목 추가:
- `"script": set()`
- `"button": {"type"}`
- `"details": set()`
- `"summary": set()`

직전 4번 항목(rel 제거)과 동일한 처리 원칙 — SSOT를 라이브러리 동작에 맞춰 정정함.

### 처리 원칙
- SSOT를 ammonia-4.0.0 동작 사양에 맞게 정정함 (옵션 A 일관성)
- `INTERACTIVE_EXTRA_TAGS`에 등록된 태그는 항상 `BASE_ALLOWED_ATTRS`에도 키로 등록되어야 한다는 불변식을 SSOT에 반영함
- `script`/`details`/`summary`는 추가 attrs 없음(빈 set), `button`은 `type` 속성만 허용
- 향후 nh3 라이브러리 패치로 제약이 완화되더라도 SSOT 명시 항목은 그대로 유지함

### 다음 액션
- NoThinkingAgent 3차 재스폰으로 정정 SSOT 그대로 `postprocess/sanitizer.py` 재작성
- 부수 작업: `nothinking-execution-log.md` L113의 허위 `=== EXECUTION COMPLETE ===` 마커 삭제 + Fix Round 3 블록 append
- pytest 122+ passed / 0 failed 복원이 PASS 조건

## 6. ammonia 4.x 양방향 일치 제약 (`attributes` 키 ⊆ `tags`)

**SSOT 위치**: `MainAI_docs/05_Postprocess.md` §3.5 sanitize 함수 정의

**드리프트 내용**: SSOT는 `BASE_ALLOWED_ATTRS`를 카테고리 무관 정적 dict로 두고 `tags`만 카테고리별로 동적 변경하는 설계임. 그러나 ammonia-4.0.0(nh3 0.2.18 백엔드)은 `tags` 집합과 `attributes` 키 집합의 부분집합 관계를 양방향으로 강제함:

- 1차 발견: `attributes`에 등재된 태그 속성 화이트리스트 외 거부 (해소: `<a rel>` 제거)
- 2차 발견: `tags` ⊆ `attributes` 키 집합 — attributes에 키가 없으면 panic (해소: `BASE_ALLOWED_ATTRS`에 script/button/details/summary 4종 추가)
- 3차 발견: `attributes` 키 ⊆ `tags` — tags에 없는 태그가 attributes에 있으면 panic. general/text/code 카테고리에서는 script 등 4종이 tags에 없는데 attributes에는 있어 `assertion failed: !self.tag_attributes.contains_key(tag_name)` panic 발생함. unit test 25건 모두 실패로 확인함.

**런타임 영향**: `nh3.clean(html, tags=tags, attributes=BASE_ALLOWED_ATTRS, ...)` 호출 시 panic. 모든 후처리 카테고리 산출이 차단됨.

**해결**: SSOT sanitize 함수 본문에서 `attributes`를 `tags` 기준 동적 필터링하도록 한 줄 추가함. 정적 dict는 그대로 두고 함수 본문에서 양방향 제약을 런타임 충족시키는 방식임.

**상태**: SSOT 정정 적용됨 (2026-04-28 3차 변경 노트 참고).

**4차 보강 (2026-04-28)**: 동적 필터링 적용 후 unit test 25건 중 17건 PASS, interactive 카테고리 2건(`test_interactive_category_allows_script_tag`, `test_interactive_category_allows_button`)에서 새 panic 발생함. WebSearch로 ammonia 공식 문서·소스 확인 결과 ammonia가 `<script>`/`<style>`을 기본 `clean_content_tags`에 포함시키며, `add_tags`(=nh3 `tags=` 인자)로 화이트리스트에 추가하는 행위 자체를 의도적 panic으로 거부함이 ammonia 핵심 보안 설계임이 확정됨. SSOT의 `INTERACTIVE_EXTRA_TAGS`가 `script`를 포함하는 것은 ammonia 정책상 영구 충돌이며 nh3 유지 하에서는 어떤 우회도 불가능함.

**4차 결정**: SSOT를 다음과 같이 정정함.
- `INTERACTIVE_EXTRA_TAGS = {"button", "details", "summary"}` (script 제거)
- `BASE_ALLOWED_ATTRS`에서 `"script": set()` 키 제거
- 카테고리 정책 표에서 interactive 행의 script 칸을 "절대 제거"로 변경
- §3.5 마지막에 "AI 출력 script 처리 방침" 절 추가 — sanitizer 단계 영구 차단, 미래의 client-side JS 필요 시 iframe sandboxer가 system 화이트리스트 script를 직접 inject

**큰 흐름 보존 검증**: server-side 렌더링 흐름(mermaid/KaTeX/matplotlib), iframe sandbox wrap, 카테고리 4종, button/details/summary disclosure UI — 모두 영향 없음 확인. AI 출력 script use case는 SSOT 본래 정의가 없었으며(IFRAME_TEMPLATE에 system script 없음) 사용자 가이드라인의 "큰 흐름·기본 기능·아키텍처 보존" 조건을 충족함.

**상태**: SSOT 4차 정정 적용됨 (2026-04-28 4차 변경 노트 참고).
