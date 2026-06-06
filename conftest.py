"""프로젝트 루트 conftest. pytest 수집 전 외부 의존성 더미를 등록한다.

llama_cpp·jinja2가 설치되지 않은 환경(로컬 단위 테스트, CI)에서도
config·validator·fallback 테스트가 실행될 수 있도록 sys.modules에
더미 모듈을 미리 등록한다.
실제 운영 코드는 변경하지 않으며, 테스트 컬렉션 시점에만 적용된다.
"""
import importlib
import importlib.machinery
import os
import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if not sys.path or sys.path[0] != str(_ROOT):
    # ChapterStudio_V1/ai_connectors가 루트 ai_connectors를 가리는 수집 순서 방지.
    sys.path.insert(0, str(_ROOT))
importlib.import_module("ai_connectors")

# ──────────────────────────────────────────────────────────────────────────────
# 테스트 API 키 설정 — ApiKeyMiddleware가 요청을 거부하지 않도록 한다.
# 통합 테스트는 실제 인증 경로를 테스트 키로 통과시킨다 (보안 끄기 방식 금지).
# ──────────────────────────────────────────────────────────────────────────────
_TEST_API_KEY = "test-api-key-for-pytest"
os.environ.setdefault("FASTAPI_API_KEY", _TEST_API_KEY)


def _make_dummy(name: str) -> types.ModuleType:
    """지정된 이름의 빈 더미 모듈을 생성한다."""
    return types.ModuleType(name)


# llama_cpp 더미 등록 — model_loader.py 최상위 import 차단
if "llama_cpp" not in sys.modules:
    _llama_cpp = _make_dummy("llama_cpp")
    # Llama 클래스 더미 (model_loader에서 타입 힌트 및 인스턴스로 사용)
    _llama_cpp.Llama = type("Llama", (), {})
    sys.modules["llama_cpp"] = _llama_cpp

# jinja2 더미 등록 — fallback.py 최상위 import 차단
# ──────────────────────────────────────────────────────────────────────────────
# 실제 jinja2는 설치돼 있으므로(pyproject.toml 의존성) 실 패키지를 그대로 쓴다.
# 더미로 교체하면 jinja2.__spec__ 이 None이 돼 mlx_lm·transformers 등
# jinja2에 의존하는 패키지가 초기화에 실패한다.
# 따라서 jinja2는 실 패키지를 유지하고 더미 등록을 건너뛴다.
# ──────────────────────────────────────────────────────────────────────────────
if "jinja2" not in sys.modules:
    try:
        import jinja2  # noqa: F401 — 실 패키지 import 확인 및 캐시 등록
    except ImportError:
        # jinja2가 실제로 없는 환경(CI 최소 설치)에서만 더미를 등록한다
        _jinja2 = _make_dummy("jinja2")

        class _DummyTemplate:
            """jinja2.Template 더미. test_fallback.py는 pytest.importorskip으로 건너뜀."""
            def __init__(self, source: str) -> None:
                self._source = source

            def render(self, **kwargs: object) -> str:
                return self._source

        _jinja2.Template = _DummyTemplate
        # __spec__을 None이 아닌 올바른 ModuleSpec으로 설정해야
        # mlx_lm 등 jinja2.__spec__ 을 검사하는 라이브러리가 정상 작동한다.
        _jinja2.__spec__ = importlib.machinery.ModuleSpec(
            name="jinja2",
            loader=None,
            origin="<dummy>",
        )
        sys.modules["jinja2"] = _jinja2
