"""validator.py 단위 테스트.

패키지 __init__.py를 우회해 validator.py와 config.py만 직접 로드한다.
model_loader·jinja2·llama_cpp 없이 실행 가능하다.
"""
import importlib.util
import pathlib
import sys

_BASE = pathlib.Path(__file__).parent.parent

# config.py 먼저 로드 (validator가 의존)
_config_spec = importlib.util.spec_from_file_location("_kanana_config", _BASE / "config.py")
_config_mod = importlib.util.module_from_spec(_config_spec)
sys.modules["_kanana_config"] = _config_mod
_config_spec.loader.exec_module(_config_mod)

# validator.py 로드 — .config 상대 import를 우회해 직접 로드
import types
_pkg = types.ModuleType("app.modules.AI_CPU_Kanana_Nano_Q4")
_pkg.config = _config_mod
sys.modules["app"] = types.ModuleType("app")
sys.modules["app.modules"] = types.ModuleType("app.modules")
sys.modules["app.modules.AI_CPU_Kanana_Nano_Q4"] = _pkg

# config 상수를 직접 패치해 상대 import 없이 사용
_config_mod.MAX_CHARS = _config_mod.MAX_CHARS
_config_mod.MIN_CHARS = _config_mod.MIN_CHARS
_config_mod.MAX_EMOJIS = _config_mod.MAX_EMOJIS

_validator_spec = importlib.util.spec_from_file_location(
    "app.modules.AI_CPU_Kanana_Nano_Q4.validator", _BASE / "validator.py"
)
_validator_mod = importlib.util.module_from_spec(_validator_spec)
sys.modules["app.modules.AI_CPU_Kanana_Nano_Q4.validator"] = _validator_mod
_validator_spec.loader.exec_module(_validator_mod)

sanitize = _validator_mod.sanitize


def test_none_input_returns_none():
    """None 입력 시 None을 반환하는지 확인한다."""
    assert sanitize(None) is None


def test_empty_string_returns_none():
    """빈 문자열 입력 시 None을 반환하는지 확인한다."""
    assert sanitize("") is None


def test_whitespace_only_returns_none():
    """공백만 있는 문자열 입력 시 None을 반환하는지 확인한다."""
    assert sanitize("   ") is None


def test_too_short_returns_none():
    """19자 문자열 입력 시 None을 반환하는지 확인한다 (최소 20자 미만)."""
    short_text = "a" * 19
    assert sanitize(short_text) is None


def test_too_long_returns_none():
    """101자 문자열 입력 시 None을 반환하는지 확인한다 (최대 100자 초과)."""
    long_text = "가" * 101
    assert sanitize(long_text) is None


def test_exactly_100_chars_passes():
    """정확히 100자 문자열은 통과하는지 확인한다."""
    text = "가" * 100
    assert sanitize(text) == text


def test_exactly_20_chars_passes():
    """정확히 20자 문자열은 통과하는지 확인한다."""
    text = "가" * 20
    assert sanitize(text) == text


def test_two_emojis_returns_none():
    """이모지 2개 포함 시 None을 반환하는지 확인한다 (최대 1개 허용)."""
    text = "오늘 과제 같이 해보자! 😊😎 파이팅하자"
    assert sanitize(text) is None


def test_one_emoji_passes():
    """이모지 1개 포함 시 정상 통과하는지 확인한다."""
    text = "오늘 과제 같이 해보자! 😊 파이팅이야 할 수 있어"
    result = sanitize(text)
    assert result is not None


def test_normal_caption_passes():
    """일반적인 정상 캡션이 원본 그대로 통과하는지 확인한다."""
    caption = "민준아, 오늘 파이썬 리스트 컴프리헨션 같이 해보자! 할 수 있어."
    result = sanitize(caption)
    assert result == caption


def test_multiline_takes_first_line():
    """멀티라인 입력 시 첫 줄만 추출하는지 확인한다 (첫 줄은 20자 이상)."""
    first_line = "민준아, 오늘 파이썬 과제 같이 해보자!"    # 22자 — MIN_CHARS 충족
    text = first_line + "\n두 번째 줄은 무시됩니다."
    result = sanitize(text)
    assert result == first_line


def test_leading_trailing_whitespace_stripped():
    """앞뒤 공백이 제거된 결과를 반환하는지 확인한다."""
    text = "  민준아, 오늘 과제 같이 해보자! 할 수 있어.  "
    result = sanitize(text)
    assert result == "민준아, 오늘 과제 같이 해보자! 할 수 있어."
