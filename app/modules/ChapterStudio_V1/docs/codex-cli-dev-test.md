# Codex CLI 로컬 검증 경로

## 목적
`codex_cli` 커넥터는 ChapterStudio_V1의 1강 5슬라이드 품질 검증을 위해 추가한 개인 로컬 개발 전용 경로임. 기존 Qwen Modal, Opus Planner, TTS V1 production 구조는 유지함.

## 인증 정책
이 경로는 `~/.codex/auth.json`을 읽지 않음. `codex exec`를 하위 프로세스로 실행하고, ChatGPT OAuth refresh와 인증 처리는 Codex CLI가 담당함.

## 실행 방식
HTML 테스트 페이지에서 `실제 Codex CLI OAuth` 모드를 고르면 `/demo/chapter-studio/stream`이 `codex_cli`를 호출함. 출력은 `app/codex_demo_result.schema.json`으로 제한하고, 이후 기존 `postprocess_all()`과 `app/frontend_payload.py`를 거쳐 프론트 iframe `srcDoc` 문서 HTML로 표시함.

테스트 속도를 위해 커넥터는 `model_reasoning_effort`를 기본 `low`로 override한다. 로컬 `~/.codex/config.toml`이 `xhigh`여도 1강 5슬라이드 확인은 빠른 생성 경로를 우선한다.

## 제한
이 경로는 production API가 아님. 장기 운영, 서버 배포, CI 공유, API Key 대체 목적으로 쓰지 않음. 실제 production 검증은 Qwen Modal 커넥터와 Phase 7 E2E에서 수행함.
