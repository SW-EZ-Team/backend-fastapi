# postprocess

## 모듈 목적
Qwen이 생성한 슬라이드 HTML+CSS를 DB 저장 직전 안전한 렌더 산출물로 변환함.

## IN·OUT
IN은 `index`, `category`, `html`, `css`를 가진 슬라이드 dict임. OUT은 `index`, `category`, `html`, `css`, `iframe_html`, `warnings` 6키를 가진 후처리 결과임. `iframe_html`은 내부 검증용 sandbox iframe 태그이며, 프론트·DB payload로 나가기 전 `app/frontend_payload.py`에서 `srcDoc` 문서 HTML로 정규화함.

## 환경변수
해당 없음.

## 의존성
`nh3`, `matplotlib`, Node 기반 `npx shiki`, `@mermaid-js/mermaid-cli`, `katex` CLI 실행 경로에 의존함. 단위 테스트에서는 `_run_external`을 stub하여 실제 외부 명령을 호출하지 않음.

## 사용 예시
```python
from postprocess.pipeline import postprocess_slide

result = await postprocess_slide(0, "code", raw_html, raw_css)
```

## 에러 정책
외부 렌더러 실패는 원본 보존 fallback과 warning으로 남김. 보안 처리는 `nh3_sanitizer.py`, `iframe_sandboxer.py`, `app/frontend_payload.py`에서 강제하며 iframe sandbox token은 `allow-scripts` 하나만 허용함.

## 처리 순서
`shiki.py` → `mermaid_cli.py` → `katex.py` → `matplotlib_chart.py` → `nh3_sanitizer.py` → `iframe_sandboxer.py` 순서로 처리함. category가 맞지 않는 단계는 입력 HTML을 그대로 통과시킴.

## 실제 연결 보존 정책
`matplotlib_chart.py`가 만든 `data:image/png;base64,...`는 `img[src]`에서만 보존함. `a[href]`와 외부 `http/https` URL은 제거함. `mermaid_cli.py`가 만든 SVG는 `path.d`, `stroke`, `fill`, 좌표 속성 등 렌더링에 필요한 geometry 속성만 보존하고 이벤트 속성·외부 참조는 허용하지 않음.

## matplotlib 런타임 정책
`matplotlib`은 앱 import 시점에 로드하지 않고 차트 렌더링 함수 내부에서 lazy import함. import 전에 `common.config.prepare_matplotlib_runtime()`이 `MPLCONFIGDIR`와 `XDG_CACHE_HOME`을 쓰기 가능한 `/tmp` 하위 경로로 고정해 startup 로그 오염과 cold-start 지연을 줄임.
