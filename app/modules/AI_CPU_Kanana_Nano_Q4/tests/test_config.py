"""config.py v3 정책 회귀 테스트.

model_loader 및 패키지 __init__을 거치지 않고 config.py만 직접 import한다.
실제 모델 파일·jinja2·llama_cpp 없이 실행 가능하다.
"""
import importlib.util
import pathlib

# 패키지 __init__.py를 우회해 config.py 단독 로드
_CONFIG_PATH = pathlib.Path(__file__).parent.parent / "config.py"
_spec = importlib.util.spec_from_file_location("_kanana_config", _CONFIG_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

SYSTEM_PROMPT = _mod.SYSTEM_PROMPT
MAX_CHARS = _mod.MAX_CHARS
MIN_CHARS = _mod.MIN_CHARS
MAX_EMOJIS = _mod.MAX_EMOJIS
THREADS = _mod.THREADS
N_GPU_LAYERS = _mod.N_GPU_LAYERS


def test_system_prompt_contains_persona():
    """시스템 프롬프트가 v3 핵심 페르소나 문구를 포함하는지 확인한다."""
    assert "누나·언니" in SYSTEM_PROMPT, "시스템 프롬프트에 '누나·언니' 페르소나 문구가 없음"


def test_max_chars_is_100():
    """캡션 최대 길이가 100자로 고정되어 있는지 확인한다."""
    assert MAX_CHARS == 100, f"MAX_CHARS가 100이 아님: {MAX_CHARS}"


def test_min_chars_is_20():
    """캡션 최소 길이가 20자로 고정되어 있는지 확인한다."""
    assert MIN_CHARS == 20, f"MIN_CHARS가 20이 아님: {MIN_CHARS}"


def test_threads_is_4():
    """e2-standard-4 기준 스레드 수가 4로 고정되어 있는지 확인한다."""
    assert THREADS == 4, f"THREADS가 4가 아님: {THREADS}"


def test_n_gpu_layers_is_0():
    """CPU-only 강제 설정(N_GPU_LAYERS=0)이 유지되는지 확인한다."""
    assert N_GPU_LAYERS == 0, f"N_GPU_LAYERS가 0이 아님: {N_GPU_LAYERS}"


def test_max_emojis_is_1():
    """이모지 최대 허용 개수가 1개로 고정되어 있는지 확인한다."""
    assert MAX_EMOJIS == 1, f"MAX_EMOJIS가 1이 아님: {MAX_EMOJIS}"
