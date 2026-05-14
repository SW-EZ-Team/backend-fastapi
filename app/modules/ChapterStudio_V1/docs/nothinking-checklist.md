# NoThinking Checklist
Source: direct leader instruction

- [x] (D1) "requirements.txt 17번째 줄 `anthropic==0.85.0` 정정 + `uv pip compile` 충돌 0건"
- [x] (D2) "ai_connectors/__init__.py 생성"
- [x] (D3) "ai_connectors/base.py — AIConnector + TTSConnector Protocol (07_Connectors.md §2 그대로, generate / generate_batch / supports / synthesize 시그니처)"
- [x] (D4) "ai_connectors/schemas.py — AIRequest / AIResponse / TTSRequest / TTSResponse Pydantic V2 (07_Connectors.md §3 그대로, ConfigDict strict frozen)"
- [x] (D5) "ai_connectors/errors.py — ConnectorError (base) + RateLimitError + AuthError + ModelNotFoundError + TimeoutError + ContextLengthExceeded (07_Connectors.md §4 그대로, 5종 정규화)"
- [x] (D6) "ai_connectors/registry.py — Pydantic Registry + 싱글톤 캐시 + get_text_connector() / get_planner_connector() / get_tts_connector() (07_Connectors.md §5 그대로)"
- [x] (D7) "ai_connectors/qwen27b_modal_connector.py — Qwen27BModalConnector (vLLM Modal endpoint, n=N 배치, 07_Connectors.md §6 그대로)"
- [x] (D8) "ai_connectors/opus46_connector.py — Opus46Connector (모델 ID 상수 `_MODEL_ID = \"claude-opus-4-6\"` 고정, 07_Connectors.md §7 그대로)"
- [x] (D9) "ai_connectors/ttsv1_connector.py — TTSV1Connector (httpx 60s timeout, 07_Connectors.md §8 그대로)"
- [x] (D10) "ai_connectors/mock_connector.py — Mock 커넥터(단위 테스트용, 07_Connectors.md mocks 섹션 그대로)"
- [x] (D11) "postprocess/ + 7 모듈(__init__.py + shiki.py + mermaid.py + katex.py + matplotlib.py + sanitizer.py + iframe.py + pipeline.py). pipeline은 `postprocess_slide` / `postprocess_all` 시그니처. 처리 순서 정확히 Shiki → mermaid-cli → KaTeX → matplotlib → nh3 → iframe (05_Postprocess.md §2 그대로)"
- [x] (D12) "postprocess/sanitizer.py — nh3 BASE_ALLOWED_TAGS + INTERACTIVE_EXTRA_TAGS (05_Postprocess.md §3 그대로, 화이트리스트 그대로)"
- [x] (D13) "postprocess/iframe.py — IFRAME_TEMPLATE + sandbox=\"allow-scripts\"(allow-same-origin 부재) + CSP meta (05_Postprocess.md §4 그대로)"
- [x] (D14) "tests/unit/test_connectors_*.py + tests/unit/test_postprocess_*.py — 단위 테스트 50+ 항목 PASS, 0 FAIL (15_PhaseChecklist.md §3 완료 조건 그대로). 검증: `cd Test_FastAPI_Module/ChapterStudio_V1 && uv run pytest tests/unit -q`"

## 4차 라운드 (Fix Round 4) — SSOT 3차 정정 반영

- [x] (R4-1) "BASE_ALLOWED_TAGS 정의 — SSOT §3.5 본문 그대로 일치"
- [x] (R4-2) "INTERACTIVE_EXTRA_TAGS = {\"script\", \"button\", \"details\", \"summary\"}"
- [x] (R4-3) "BASE_ALLOWED_ATTRS dict 13개 키 (*, a, button, details, img, script, summary, svg, code, div, pre, th, td)"
- [x] (R4-4) "sanitize 함수 docstring + tags 동적 구성 + attributes 동적 필터링(한 줄) + nh3.clean 호출"
- [x] (R4-5) "attributes 필터링 표현은 SSOT와 문자 그대로 일치: `{k: v for k, v in BASE_ALLOWED_ATTRS.items() if k == \"*\" or k in tags}`"
- [x] (R4-6) "url_schemes=set() / strip_comments=True 유지"
- [x] (R4-7) "Korean comments only (영문 주석 금지)"
- [ ] (R4-8) "pytest 25/25 PASS" — BLOCKED (2 failed: test_interactive_category_allows_script_tag, test_interactive_category_allows_button — ammonia-4.0.0 PanicException)
