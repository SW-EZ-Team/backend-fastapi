"""프로젝트 루트 conftest. pytest 수집 전 외부 의존성 더미를 등록한다.

llama_cpp·jinja2가 설치되지 않은 환경(로컬 단위 테스트, CI)에서도
config·validator·fallback 테스트가 실행될 수 있도록 sys.modules에
더미 모듈을 미리 등록한다.
실제 운영 코드는 변경하지 않으며, 테스트 컬렉션 시점에만 적용된다.
"""
import sys
import types


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
if "jinja2" not in sys.modules:
    _jinja2 = _make_dummy("jinja2")

    class _DummyTemplate:
        """jinja2.Template 더미. test_fallback.py는 pytest.importorskip으로 건너뜀."""
        def __init__(self, source: str) -> None:
            self._source = source

        def render(self, **kwargs) -> str:
            return self._source

    _jinja2.Template = _DummyTemplate
    sys.modules["jinja2"] = _jinja2
