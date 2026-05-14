# tests/unit

## 모듈 목적
작은 함수와 모델의 단위 동작을 검증한다.

## IN·OUT
IN은 함수 입력과 mock 객체이며 OUT은 pytest assertion 결과다.

## 환경변수
테스트가 직접 필요한 값만 `monkeypatch`로 주입한다.

## 의존성
`pytest`, `pytest-asyncio`에 의존한다.

## 사용 예시
```bash
uv --cache-dir .uv-cache run pytest -v tests/unit/
```

## 에러 정책
단위 테스트 실패는 해당 Phase 재작업으로 처리한다.
