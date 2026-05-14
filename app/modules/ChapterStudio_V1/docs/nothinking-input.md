== 작업 개요 ==
ChapterStudio_V1 Phase 3 — AI 커넥터 + 후처리 모듈 구현. Codex가 2회 연속 동일 BLOCKED(anthropic 버전 충돌). 백업 플랜으로 너에게 위임. **추론 절대 금지, 창의 절대 금지, SSOT 문서 그대로만 구현.**

== 0순위 — 이 항목부터 가장 먼저 처리해라 ==
`/Users/kimtaekyu/Documents/Develop_Fold/100_UnivVT/SW_project/Test_FastAPI_Module/ChapterStudio_V1/requirements.txt` 17번째 줄을 정확히 다음과 같이 정정한다:

기존: `anthropic==0.39.0`
정정: `anthropic==0.85.0`

정정 후 즉시 검증:
```
cd /Users/kimtaekyu/Documents/Develop_Fold/100_UnivVT/SW_project/Test_FastAPI_Module/ChapterStudio_V1 && uv pip compile requirements.txt -o /tmp/req-phase3.lock 2>&1
```
이 명령이 충돌 0건으로 끝나야 다음 항목 진행. 안 끝나면 즉시 STOP하고 docs/nothinking-execution-log.md에 BLOCKED 기록.

== 작업 디렉토리 ==
`/Users/kimtaekyu/Documents/Develop_Fold/100_UnivVT/SW_project/Test_FastAPI_Module/ChapterStudio_V1/`

== SSOT 문서 (이 3개만 따라라, 다른 추론 금지) ==
1. `/Users/kimtaekyu/Documents/Develop_Fold/100_UnivVT/SW_project/Test_FastAPI_Module/MainAI_docs/07_Connectors.md` — AIConnector + TTSConnector + 5종 예외 + registry + 3 connectors
2. `/Users/kimtaekyu/Documents/Develop_Fold/100_UnivVT/SW_project/Test_FastAPI_Module/MainAI_docs/05_Postprocess.md` — Shiki/mermaid/KaTeX/matplotlib/nh3/iframe 7 모듈
3. `/Users/kimtaekyu/Documents/Develop_Fold/100_UnivVT/SW_project/Test_FastAPI_Module/MainAI_docs/15_PhaseChecklist.md` (§3 Phase 3 부분만) — 완료 조건

이 3개 문서가 곧 명세다. 거기 있는 것만 만들고, 거기 있는 그대로만 만든다. 함수 시그니처·매개변수·반환 타입·예외 타입·필드명·상수명 모두 SSOT 그대로.

== 절대 변경 금지 핀 (17개) ==
```
langchain-anthropic==1.4.0
langgraph==1.1.6
asyncpg==0.31.0
nh3==0.2.18
pydantic==2.13.3
fastapi==0.136.0
uvicorn[standard]==0.43.0
loguru==0.7.3
pytest==9.0.3
pytest-asyncio==1.3.0
httpx==0.27.2
python-dotenv==1.2.2
modal==0.66.34
mypy==1.13.0
SQLAlchemy==2.0.49
vllm==0.6.4
anthropic==0.85.0   ← 0.39.0에서 정정 필요
```
이 17개 외 패키지가 SSOT에 명시되면 SSOT 명시값 그대로 추가. 임의 버전 선택 절대 금지.

== 산출물 (필수 3개) ==
1. `docs/nothinking-input.md` — **이 프롬프트 본문 전체를 그대로 저장**한다. 한 글자도 다르지 않게.
2. `docs/nothinking-checklist.md` — 아래 D1~D14 14항을 정확히 마크다운 체크박스(`- [ ]` / `- [x]`)로 만든다. 각 항목 처리 끝나면 `- [x]`로 바꾼다.
3. `docs/nothinking-execution-log.md` — 각 항목 실행 결과를 즉시 append한다. 형식:
   ```
   ### Dn: <한 줄 요약>
   - 변경/생성 파일: <path 목록>
   - 라인 수: <wc -l 결과>
   - 검증 명령: <bash 명령>
   - 검증 출력: <첫 30줄 또는 전체>
   - 판정: PASS | FAIL
   ```
   **마지막 항목 D14 PASS 후 마지막 줄에 정확히 `=== EXECUTION COMPLETE ===` 추가.** 이 마커가 monitor의 polling 시그널이다.

== Done Conditions (D1~D14) ==
- D1: requirements.txt 17번째 줄 `anthropic==0.85.0` 정정 + `uv pip compile` 충돌 0건
- D2: ai_connectors/__init__.py 생성
- D3: ai_connectors/base.py — AIConnector + TTSConnector Protocol (07_Connectors.md §2 그대로, generate / generate_batch / supports / synthesize 시그니처)
- D4: ai_connectors/schemas.py — AIRequest / AIResponse / TTSRequest / TTSResponse Pydantic V2 (07_Connectors.md §3 그대로, ConfigDict strict frozen)
- D5: ai_connectors/errors.py — ConnectorError (base) + RateLimitError + AuthError + ModelNotFoundError + TimeoutError + ContextLengthExceeded (07_Connectors.md §4 그대로, 5종 정규화)
- D6: ai_connectors/registry.py — Pydantic Registry + 싱글톤 캐시 + get_text_connector() / get_planner_connector() / get_tts_connector() (07_Connectors.md §5 그대로)
- D7: ai_connectors/qwen27b_modal_connector.py — Qwen27BModalConnector (vLLM Modal endpoint, n=N 배치, 07_Connectors.md §6 그대로)
- D8: ai_connectors/opus46_connector.py — Opus46Connector (모델 ID 상수 `_MODEL_ID = "claude-opus-4-6"` 고정, 07_Connectors.md §7 그대로)
- D9: ai_connectors/ttsv1_connector.py — TTSV1Connector (httpx 60s timeout, 07_Connectors.md §8 그대로)
- D10: ai_connectors/mock_connector.py — Mock 커넥터(단위 테스트용, 07_Connectors.md mocks 섹션 그대로)
- D11: postprocess/ + 7 모듈(__init__.py + shiki.py + mermaid.py + katex.py + matplotlib.py + sanitizer.py + iframe.py + pipeline.py). pipeline은 `postprocess_slide` / `postprocess_all` 시그니처. 처리 순서 정확히 Shiki → mermaid-cli → KaTeX → matplotlib → nh3 → iframe (05_Postprocess.md §2 그대로)
- D12: postprocess/sanitizer.py — nh3 BASE_ALLOWED_TAGS + INTERACTIVE_EXTRA_TAGS (05_Postprocess.md §3 그대로, 화이트리스트 그대로)
- D13: postprocess/iframe.py — IFRAME_TEMPLATE + sandbox="allow-scripts"(allow-same-origin 부재) + CSP meta (05_Postprocess.md §4 그대로)
- D14: tests/unit/test_connectors_*.py + tests/unit/test_postprocess_*.py — 단위 테스트 50+ 항목 PASS, 0 FAIL (15_PhaseChecklist.md §3 완료 조건 그대로). 검증: `cd Test_FastAPI_Module/ChapterStudio_V1 && uv run pytest tests/unit -q`

== 추론·창의 절대 금지 (위반 시 monitor가 FAIL 처리) ==
- SSOT에 명시되지 않은 함수·필드·예외·시그니처 추가 금지
- "이렇게 하면 더 좋을 것 같다" / "TODO" / "FIXME" / "권장" / "improvement" 류 주석·로그 추가 금지
- 명세에 있는 항목 누락 금지
- 파일 헤더 주석은 한국어 + WHY만(전역 CLAUDE.md 규칙), SSOT에 없는 자의적 설명 추가 금지
- README는 D11~D13 모듈에만, SSOT에 명시된 인터페이스 그대로 기록

== Workflow ==
1. 이 프롬프트 본문을 docs/nothinking-input.md에 그대로 저장
2. D1~D14 체크리스트를 docs/nothinking-checklist.md에 작성(모두 `- [ ]`)
3. D1부터 순서대로 실행. 각 항목 끝마다 execution-log에 append + checklist의 해당 항목을 `- [x]`로 변경
4. D14까지 모두 PASS면 마지막 줄에 `=== EXECUTION COMPLETE ===` 추가
5. 어느 단계에서 BLOCKED가 발생하면 즉시 STOP, execution-log에 BLOCKED 사유 기록 + 마커 추가하지 말 것(monitor가 FAIL로 인식)

시작.

---

## 4차 라운드 추가 입력 (2026-04-28 — SSOT 3차 정정)

### SSOT §3.5 본문 (05_Postprocess.md L436~L496)

```python
# postprocess/sanitizer.py
import nh3

BASE_ALLOWED_TAGS = {
    "div", "span", "p", "section", "article", "header", "footer",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "dl", "dt", "dd",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td",
    "pre", "code", "blockquote",
    "strong", "em", "b", "i", "u", "s", "small", "sub", "sup",
    "a", "img",
    "br", "hr",
    "svg", "path", "circle", "rect", "line", "polyline", "polygon",
    "text", "g", "defs", "use", "symbol",
}

INTERACTIVE_EXTRA_TAGS = {"script", "button", "details", "summary"}

BASE_ALLOWED_ATTRS = {
    "*": {"class", "id", "aria-label", "aria-hidden", "role"},
    "a": {"href", "target"},
    "button": {"type"},
    "details": set(),
    "img": {"src", "alt", "width", "height"},
    "script": set(),
    "summary": set(),
    "svg": {"xmlns", "viewBox", "width", "height"},
    "code": {"data-lang"},
    "div": {"data-chart-type", "data-chart-spec"},
    "pre": {"class"},
    "th": {"colspan", "rowspan"},
    "td": {"colspan", "rowspan"},
}


def sanitize(html: str, category: str) -> str:
    """
    카테고리에 따라 허용 태그/속성을 결정하고 nh3로 sanitize한다.

    interactive 카테고리는 script/button/details/summary를 추가 허용한다.
    모든 카테고리에서 외부 URL(http/https href)은 제거한다.
    """
    tags = BASE_ALLOWED_TAGS.copy()
    if category == "interactive":
        tags |= INTERACTIVE_EXTRA_TAGS

    # ammonia 4.x는 attributes dict 키 집합이 tags 집합의 부분집합이어야 함을 강제한다.
    # 정적 BASE_ALLOWED_ATTRS를 그대로 넘기면 general/text/code 카테고리에서
    # script/button/details/summary 키가 tags에 없어 panic이 발생하므로,
    # tags 기준으로 attributes를 동적 필터링해 양방향 일치를 보장한다.
    attributes = {k: v for k, v in BASE_ALLOWED_ATTRS.items() if k == "*" or k in tags}

    return nh3.clean(
        html,
        tags=tags,
        attributes=attributes,
        url_schemes=set(),  # 외부 URL 전부 차단
        strip_comments=True,
    )
```

### 변경 노트 3차 (05_Postprocess.md L421)

> ※ 2026-04-28 3차 정정: ammonia 4.x가 `tags` 집합과 `attributes` 키 집합의 부분집합 관계를 양방향으로 강제하는 사실을 unit test 25건 panic으로 확인함. 정적 dict를 그대로 넘기면 general/text/code 카테고리에서 script 등 키가 tags에 없어 panic이 발생하므로, sanitize 본문에서 tags 기준 동적 필터링으로 보정하기로 결정함. BASE_ALLOWED_ATTRS 자체는 변경하지 않고 함수 본문 한 줄 추가로 양방향 제약을 런타임 충족함.

### spec-drift.md 6번

## 6. ammonia 4.x 양방향 일치 제약 (`attributes` 키 ⊆ `tags`)

**SSOT 위치**: `MainAI_docs/05_Postprocess.md` §3.5 sanitize 함수 정의

**드리프트 내용**: SSOT는 `BASE_ALLOWED_ATTRS`를 카테고리 무관 정적 dict로 두고 `tags`만 카테고리별로 동적 변경하는 설계임. 그러나 ammonia-4.0.0(nh3 0.2.18 백엔드)은 `tags` 집합과 `attributes` 키 집합의 부분집합 관계를 양방향으로 강제함:

- 1차 발견: `attributes`에 등재된 태그 속성 화이트리스트 외 거부 (해소: `<a rel>` 제거)
- 2차 발견: `tags` ⊆ `attributes` 키 집합 — attributes에 키가 없으면 panic (해소: `BASE_ALLOWED_ATTRS`에 script/button/details/summary 4종 추가)
- 3차 발견: `attributes` 키 ⊆ `tags` — tags에 없는 태그가 attributes에 있으면 panic. general/text/code 카테고리에서는 script 등 4종이 tags에 없는데 attributes에는 있어 `assertion failed: !self.tag_attributes.contains_key(tag_name)` panic 발생함. unit test 25건 모두 실패로 확인함.

**런타임 영향**: `nh3.clean(html, tags=tags, attributes=BASE_ALLOWED_ATTRS, ...)` 호출 시 panic. 모든 후처리 카테고리 산출이 차단됨.

**해결**: SSOT sanitize 함수 본문에서 `attributes`를 `tags` 기준 동적 필터링하도록 한 줄 추가함. 정적 dict는 그대로 두고 함수 본문에서 양방향 제약을 런타임 충족시키는 방식임.

**상태**: SSOT 정정 적용됨 (2026-04-28 3차 변경 노트 참고).
