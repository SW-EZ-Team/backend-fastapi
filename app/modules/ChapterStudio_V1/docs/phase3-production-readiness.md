# Phase 3 프로덕션 연결성 보강 기록

## 목적
단위 테스트 통과를 넘어 실제 후처리 결과가 DB에 저장 가능한 완성 HTML인지 검증함.

## 보강 항목
- `nh3_sanitizer.py`: chart PNG data URI를 `img[src]`에서만 보존하고 외부 URL은 제거함.
- `nh3_sanitizer.py`: Mermaid SVG 렌더링에 필요한 geometry 속성(`path.d`, 좌표, stroke/fill)을 보존함.
- `qwen27b_modal_connector.py`: Modal 호출을 60초 timeout으로 감싸 무기한 대기를 차단함.
- `matplotlib_chart.py`: 앱 import 시점 부작용을 줄이기 위해 matplotlib을 chart 렌더 시점에 lazy import함.
- `registry.py`: `close_all()`을 추가해 TTS HTTP client 수명주기를 lifespan에서 닫을 수 있게 함.

## 검증 기준
- `postprocess_slide(..., category="chart")` 결과 HTML에 `data:image/png;base64`가 남아야 함.
- sanitizer 통과 후 Mermaid SVG의 `path.d`, `stroke`, `text.x/y`가 남아야 함.
- `uv run mypy --config-file pyproject.toml`은 0 errors여야 함.
- `uv run pytest -q tests/unit/`은 전체 PASS여야 함.
