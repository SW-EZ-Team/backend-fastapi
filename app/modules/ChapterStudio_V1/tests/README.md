# tests

## 모듈 목적
단위·통합·HTML 테스트를 보관한다.

## IN·OUT
IN은 테스트 대상 함수와 fixture이며 OUT은 pytest 결과다.

## 환경변수
테스트별로 `monkeypatch`를 통해 필요한 값만 주입한다.

## 의존성
`pytest`, `pytest-asyncio`, `fastapi.testclient`에 의존한다.

## 사용 예시
```bash
uv --cache-dir .uv-cache run pytest -v tests/unit/
```

## 에러 정책
실패 테스트는 Phase 완료 조건 미달로 처리한다.
