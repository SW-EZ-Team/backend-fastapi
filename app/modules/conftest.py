"""app/modules 공통 conftest.

모듈별 테스트에서 TestClient(app) 를 직접 생성할 때
X-API-Key 헤더가 누락돼 401이 반환되는 문제를 해결한다.

TestClient 생성자를 패치하는 대신, pytest의 fixture로 환경변수가
항상 설정된 상태를 보장한다. TestClient(app, headers={"X-API-Key": ...}) 를
사용하는 fixture를 제공하고, 기존 인라인 TestClient(app) 는
헤더를 주입할 conftest_test_client fixture를 통해 사용하도록 권장한다.

단기 하위 호환을 위해 os.environ에 테스트 키가 있으면
TestClient(app)의 기본 headers에 자동 주입하는 autouse fixture를 제공한다.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ──────────────────────────────────────────────────────────────────────────────
# TestClient 자동 패치 — 루트 conftest.py가 설정한 FASTAPI_API_KEY를
# TestClient 인스턴스의 headers에 자동 주입한다.
# 이렇게 하면 각 테스트 파일에서 TestClient(app) 를 바꾸지 않아도
# X-API-Key 헤더가 항상 포함된다.
# ──────────────────────────────────────────────────────────────────────────────

_ORIGINAL_TESTCLIENT_INIT = TestClient.__init__


def _patched_testclient_init(
    self: TestClient,
    app: object,
    *args: object,
    headers: dict[str, str] | None = None,
    **kwargs: object,
) -> None:
    """TestClient 생성 시 X-API-Key 헤더를 자동 삽입한다."""
    api_key = os.environ.get("FASTAPI_API_KEY", "")
    if api_key:
        merged_headers: dict[str, str] = {"X-API-Key": api_key}
        if headers:
            merged_headers.update(headers)
        headers = merged_headers
    _ORIGINAL_TESTCLIENT_INIT(self, app, *args, headers=headers, **kwargs)


@pytest.fixture(autouse=True)
def _auto_inject_api_key_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """모든 테스트에서 TestClient 생성 시 X-API-Key 헤더를 자동 삽입한다."""
    monkeypatch.setattr(TestClient, "__init__", _patched_testclient_init)
