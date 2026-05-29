#!/bin/bash
# 스프링 통합 테스트 실행 — 실제 JSON 페이로드로 엔드포인트 검증
# mock, MagicMock, @patch, monkeypatch 절대 금지
# 사용법: bash tests/integration/run_integration_tests.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "=== 스프링 통합 테스트 시작 ==="
echo "프로젝트 루트: ${PROJECT_ROOT}"

cd "${PROJECT_ROOT}"

# anyio pytest 플러그인이 설치되어 있는지 확인한다
if ! python -c "import anyio" 2>/dev/null; then
  echo "[경고] anyio 가 설치되어 있지 않습니다. 'uv pip install anyio[trio]' 를 실행하세요."
fi

if ! python -c "import httpx" 2>/dev/null; then
  echo "[경고] httpx 가 설치되어 있지 않습니다. 'uv pip install httpx' 를 실행하세요."
fi

if ! python -c "import pytest_anyio" 2>/dev/null && ! python -c "import anyio" 2>/dev/null; then
  echo "[경고] pytest-anyio 가 없을 수 있습니다. 'uv pip install pytest-anyio' 를 실행하세요."
fi

python -m pytest tests/integration/ \
  -v \
  --tb=short \
  --no-header \
  -p anyio \
  "$@"

echo "=== 테스트 완료 ==="
