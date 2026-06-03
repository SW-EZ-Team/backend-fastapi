from __future__ import annotations

import os
import re
from functools import cache
from pathlib import Path

from dotenv import load_dotenv

_SCHEMA_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BACKEND_ROOT = Path(__file__).resolve().parents[4]


@cache
def _load_env() -> None:
    """환경 파일은 공통 설정 계층에서 한 번만 로드한다."""
    load_dotenv()


def _optional_value(key: str) -> str | None:
    """빈 문자열은 설정되지 않은 값으로 취급한다."""
    _load_env()
    value = os.environ.get(key)
    if value is None or value == "":
        return None
    return value


def _path_value(key: str, default: str) -> Path:
    """상대 경로 설정은 backend-fastapi 루트 기준으로 고정한다."""
    raw_value = _optional_value(key) or default
    path = Path(raw_value).expanduser()
    return path if path.is_absolute() else _BACKEND_ROOT / path


def _required_value(key: str) -> str:
    """필수 환경값이 없으면 시작 단계에서 즉시 실패하게 한다."""
    value = _optional_value(key)
    if value is None:
        raise RuntimeError(f"{key}가 설정되지 않았다.")
    return value


def _float_value(key: str, default: str, min_value: float, max_value: float) -> float:
    """실수 환경값을 공통 범위 검증으로 읽는다."""
    raw_value = _optional_value(key) or default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{key}는 숫자여야 한다.") from exc
    if value < min_value or value > max_value:
        raise RuntimeError(f"{key}는 {min_value:g}~{max_value:g} 범위여야 한다.")
    return value


def _int_value(key: str, default: str, min_value: int, max_value: int) -> int:
    """정수 환경값을 공통 범위 검증으로 읽는다."""
    raw_value = _optional_value(key) or default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{key}는 정수여야 한다.") from exc
    if value < min_value or value > max_value:
        raise RuntimeError(f"{key}는 {min_value}~{max_value} 범위여야 한다.")
    return value


def database_url() -> str:
    value = _required_value("DATABASE_URL")
    return value.replace("postgresql+asyncpg://", "postgresql://", 1)


def database_schema() -> str:
    """PostgreSQL search_path에 사용할 schema 이름을 검증한다."""
    value = _optional_value("DATABASE_SCHEMA") or "chapter_studio"
    if not _SCHEMA_PATTERN.fullmatch(value):
        raise RuntimeError("DATABASE_SCHEMA 형식이 안전하지 않다.")
    return value


def anthropic_api_key() -> str | None:
    return _optional_value("ANTHROPIC_API_KEY")


def claude_sonnet_api_key() -> str | None:
    return _optional_value("CLAUDE_SONNET_API_KEY") or anthropic_api_key()


def claude_sonnet_model() -> str:
    return _optional_value("CLAUDE_SONNET_MODEL") or "claude-sonnet-4-5-20250929"


def claude_sonnet_timeout_sec() -> float:
    return _float_value("CLAUDE_SONNET_TIMEOUT_SEC", "300", 30, 1200)


def claude_sonnet_max_concurrency() -> int:
    return _int_value("CLAUDE_SONNET_MAX_CONCURRENCY", "4", 1, 8)


def gemini_api_key() -> str | None:
    return _optional_value("GEMINI_API_KEY")


def google_api_key() -> str | None:
    """Google AI Studio API 키를 반환한다. GEMINI_API_KEY를 대체 키로 허용한다."""
    return _optional_value("GOOGLE_API_KEY") or gemini_api_key()


def gemini_text_model() -> str:
    """google-genai 텍스트 커넥터의 모델 ID를 반환한다."""
    return _optional_value("GEMINI_TEXT_MODEL") or "gemini-3.5-flash"


def modal_token_id() -> str | None:
    return _optional_value("MODAL_TOKEN_ID")


def modal_token_secret() -> str | None:
    return _optional_value("MODAL_TOKEN_SECRET")


def active_text_model() -> str:
    return _optional_value("ACTIVE_TEXT_MODEL") or _optional_value("AI_MODEL") or "qwen27b_modal"


def active_planner_model() -> str:
    return _optional_value("ACTIVE_PLANNER_MODEL") or "opus46"


def active_verifier_model() -> str | None:
    """내용 정확성 검증 패스에 쓸 커넥터 이름을 반환한다(미설정이면 None).

    None이면 registry가 활성 텍스트 커넥터로 폴백한다. 검증을 더 강한/독립 모델로
    돌리고 싶을 때만 ACTIVE_VERIFIER_MODEL을 명시한다.
    """
    return _optional_value("ACTIVE_VERIFIER_MODEL")


def active_tts_model() -> str:
    return _optional_value("ACTIVE_TTS_MODEL") or "tts_v1"


def tts_endpoint() -> str | None:
    return _optional_value("TTS_ENDPOINT") or _optional_value("TTS_V1_ENDPOINT")


def tts_ref_audio_path() -> Path | None:
    value = _optional_value("TTS_REF_AUDIO_PATH")
    return Path(value).expanduser() if value is not None else None


def tts_ref_text() -> str | None:
    return _optional_value("TTS_REF_TEXT")


def tts_output_dir() -> Path:
    if _optional_value("TTS_OUTPUT_DIR") is not None:
        return _path_value("TTS_OUTPUT_DIR", "media/tts")
    return media_root_dir() / "tts"


def media_root_dir() -> Path:
    if _optional_value("MEDIA_ROOT_DIR") is not None:
        return _path_value("MEDIA_ROOT_DIR", "media")
    if _optional_value("TTS_OUTPUT_DIR") is not None:
        return _path_value("TTS_OUTPUT_DIR", "media/tts").parent
    return _path_value("MEDIA_ROOT_DIR", "media")


def tts_media_url(filename: str) -> str:
    """DB에는 브라우저가 바로 요청할 수 있는 media 상대 URL만 저장한다."""
    try:
        relative_dir = tts_output_dir().resolve().relative_to(media_root_dir().resolve())
    except ValueError as exc:
        raise RuntimeError("TTS_OUTPUT_DIR는 MEDIA_ROOT_DIR 내부 경로여야 한다.") from exc
    return f"/media/{relative_dir.as_posix()}/{filename}"


def tts_timeout_sec() -> float:
    return _float_value("TTS_TIMEOUT_SEC", "300", 30, 1200)


def qwen_app_name() -> str:
    return _optional_value("QWEN_APP_NAME") or "chapterstudio-qwen27b"


def kanana_app_name() -> str:
    return _optional_value("KANANA_MODAL_APP_NAME") or "kanana2-typofix"


def kanana_polish_enabled() -> bool:
    """Kanana2 교정 패스는 로컬·테스트 안전을 위해 명시 설정 때만 켠다."""
    return _bool_value("KANANA_POLISH_ENABLED", False)


def tts_autogen_enabled() -> bool:
    """튜터 음성 자동생성은 원격 TTS 비용 방지를 위해 명시 설정 때만 켠다."""
    return _bool_value("TTS_AUTOGEN_ENABLED", False)


def tts_selective_tilde_enabled() -> bool:
    """합성용 대본에만 선택적 물결표를 적용할지 반환한다."""
    return _bool_value("TTS_SELECTIVE_TILDE", True)


def tts_synth_concurrency() -> int:
    """슬라이드별 TTS 합성 동시 요청 수를 반환한다."""
    return _int_value("TTS_SYNTH_CONCURRENCY", "8", 1, 16)


def tts_warmup_enabled() -> bool:
    """대량 TTS 합성 전 콜드스타트 흡수용 워밍업 호출 여부를 반환한다."""
    return _bool_value("TTS_WARMUP_ENABLED", True)


def kanana_polish_max_concurrency() -> int:
    """교정은 Modal 원격 호출이므로 동시성을 제한해 비용과 큐 적체를 막는다."""
    return _int_value("KANANA_POLISH_MAX_CONCURRENCY", "8", 1, 16)


def modal_teardown_enabled() -> bool:
    """Modal 앱을 완전히 un-deploy(decommission)할지 여부를 반환한다(기본 false).

    [중요] 비용 통제 목적으로 이 값을 true로 설정하면 안 된다.
    Modal은 running 컨테이너 시간만 과금하므로, 배포된 앱이 0 컨테이너 상태(scale-to-zero)면
    idle 비용이 0이다. 비용 통제는 scaledown_window=30초(deploy/modal_app.py)가 이미 담당한다.

    이 스위치는 순전히 "서비스 전체를 영구 폐기할 때"(decommission) 쓰는 것이다.
    true로 설정하면 modal app stop 으로 배포 자체가 내려가 다음 요청이 App not found로 깨진다.
    라이브 서비스 환경에서 true로 설정하는 것은 절대 금지다.
    """
    return _bool_value("CHAPTERSTUDIO_MODAL_TEARDOWN", False)


def gemini_cli_model() -> str:
    return _optional_value("GEMINI_CLI_MODEL") or "gemini-2.5-pro"


def gemini_cli_timeout_sec() -> int:
    return _int_value("GEMINI_CLI_TIMEOUT_SEC", "240", 30, 600)


def gemini_cli_max_concurrency() -> int:
    return _int_value("GEMINI_CLI_MAX_CONCURRENCY", "1", 1, 4)


def gemini_text_max_concurrency() -> int:
    """Gemini genai API 텍스트 생성 동시 호출 상한.

    API rate limit(Gemini Flash 기준 분당 수백 RPM)을 고려해 기본값 3~4.
    voice_cohesion rewrite_openings 병렬화 + ExamForge gemini_flash 경로에서 공유한다.
    env GEMINI_TEXT_MAX_CONCURRENCY로 오버라이드 가능.
    """
    return _int_value("GEMINI_TEXT_MAX_CONCURRENCY", "4", 1, 16)


def text_fallback_connector() -> str:
    return _optional_value("TEXT_FALLBACK_CONNECTOR") or "claude_sonnet"


def text_fallback_after_failures() -> int:
    return _int_value("TEXT_FALLBACK_AFTER_FAILURES", "3", 1, 10)


def text_primary_attempt_timeout_sec() -> float:
    return _float_value("TEXT_PRIMARY_ATTEMPT_TIMEOUT_SEC", "180", 30, 1200)


def codex_cli_model() -> str:
    return _optional_value("CODEX_CLI_MODEL") or "gpt-5.4"


def codex_cli_reasoning_effort() -> str:
    """로컬 검증용 Codex CLI 추론 강도를 반환한다."""
    value = _optional_value("CODEX_CLI_REASONING_EFFORT") or "low"
    if value not in {"low", "medium", "high", "xhigh"}:
        raise RuntimeError("CODEX_CLI_REASONING_EFFORT 값이 올바르지 않다.")
    return value


def codex_cli_timeout_sec() -> int:
    return _int_value("CODEX_CLI_TIMEOUT_SEC", "180", 30, 600)


def _bool_value(key: str, default: bool) -> bool:
    """불리언 환경값을 읽는다(미설정이면 기본값)."""
    raw_value = _optional_value(key)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def lesson_self_repair_enabled() -> bool:
    """강의 생성 self-check + targeted-repair 활성 여부를 반환한다(기본 ON).

    회귀 격리·비용 절감이 필요할 때 CHAPTERSTUDIO_LESSON_SELF_REPAIR=false로 끈다.
    """
    return _bool_value("CHAPTERSTUDIO_LESSON_SELF_REPAIR", True)


def lesson_content_verify_enabled() -> bool:
    """강의 내용 정확성(사실·논리) 검증 패스 활성 여부를 반환한다(기본 ON).

    형식/분량 self-repair와 별개의, LLM 1회(+교정 시 1회) 검증 장치다. 비용·지연
    절감이나 회귀 격리가 필요할 때 CHAPTERSTUDIO_CONTENT_VERIFY=false로 끈다.
    """
    return _bool_value("CHAPTERSTUDIO_CONTENT_VERIFY", True)


def lesson_parallel_verify_enabled() -> bool:
    """2차 내용 검증·교정을 병렬로 수행할지 여부를 반환한다(기본 ON).

    슬라이드·퀴즈·음성을 동시에 검증하고 이슈가 있는 컴포넌트만 동시에 교정한다. 직렬
    검증으로 회귀 격리하려면 CHAPTERSTUDIO_PARALLEL_VERIFY=false로 끈다(직렬 경로 폴백).
    """
    return _bool_value("CHAPTERSTUDIO_PARALLEL_VERIFY", True)


def verify_max_rounds() -> int:
    """병렬 검증·교정 최대 라운드 수를 반환한다(기본 2).

    1라운드 후 잔존 오류가 있으면 최대 이 값까지 추가 교정을 반복한다. 비용·속도 절감이
    필요하면 CHAPTERSTUDIO_VERIFY_MAX_ROUNDS=1 로 줄인다(기존 1라운드 동작 복원).
    """
    return _int_value("CHAPTERSTUDIO_VERIFY_MAX_ROUNDS", "2", 1, 4)


def voice_length_gate_enabled() -> bool:
    """voice_script 결정적 길이 게이트(len() 기준 900자 미달 → 교정 강제) 활성 여부(기본 ON).

    LLM 판단 없이 len()으로 미달 항목을 찾아 확장 교정에 포함한다. 비용 절감·회귀 격리
    시 CHAPTERSTUDIO_VOICE_LENGTH_GATE=false로 끈다(미달 허용, 검증기 판단에만 의존).
    """
    return _bool_value("CHAPTERSTUDIO_VOICE_LENGTH_GATE", True)


def voice_cohesion_enabled() -> bool:
    """슬라이드 간 음성대본 도입부 응집성 재작성 활성 여부를 반환한다(기본 ON)."""
    return _bool_value("VOICE_COHESION_ENABLED", True)


def quiz_balance_enabled() -> bool:
    """퀴즈 보기 셔플 기반 정답 위치 균등화 활성 여부를 반환한다(기본 ON)."""
    return _bool_value("QUIZ_BALANCE_ENABLED", True)


def voice_min_chars() -> int:
    """voice_script 최소 문자 수를 반환한다(기본 900).

    이 값 미만인 voice_script는 길이 게이트 교정 대상에 강제 포함된다. 환경 변수
    CHAPTERSTUDIO_VOICE_MIN_CHARS로 조절(허용 범위 400~1600).
    """
    return _int_value("CHAPTERSTUDIO_VOICE_MIN_CHARS", "900", 400, 1600)


# ── plan-first 섹션 블루프린트 상수 ────────────────────────────────────
# 섹션 role → (min_chars, max_chars) 결정적 테이블(AI 미관여).
# 슬롯 min 합 = 110+420+250+120 = 900 → 글로벌 floor(voice_min_chars 기본 900)와 정확히 일치.
# 슬롯 max 합 = 200+700+450+250 = 1600 → 글로벌 ceiling(기존 1600)과 정확히 일치.
# 이렇게 슬롯합과 글로벌 게이트를 정합화해 plan-first가 레거시보다 짧은 대본을 허용하지 않게 한다.
VOICE_SECTION_RANGES: dict[str, tuple[int, int]] = {
    "intro":   (110, 200),
    "core":    (420, 700),
    "example": (250, 450),
    "closing": (120, 250),
}


def voice_section_min_total() -> int:
    """섹션 슬롯 min 합을 반환한다(글로벌 floor와 정합 검증용)."""
    return sum(min_c for min_c, _ in VOICE_SECTION_RANGES.values())


def voice_section_max_total() -> int:
    """섹션 슬롯 max 합을 반환한다(글로벌 ceiling과 정합 검증용)."""
    return sum(max_c for _, max_c in VOICE_SECTION_RANGES.values())


# 섹션 role별 내용 지시 — 코드 상수로 보유해 AI에 결정적으로 전달한다.
VOICE_SECTION_INSTRUCTIONS: dict[str, str] = {
    "intro":   "이 개념이 왜 중요한지 배경 2~3문장. slide_idx==0이면 짧은 인사 후 핵심 상황 진입(greeting 모드). slide_idx>0이면 직전 화면 주제에서 자연스럽게 이어지는 한 문장으로 시작(bridge 모드, 인사말 금지).",
    "core":    "핵심 개념·원리를 3~4문장으로 설명. 학습자가 처음 듣는다고 가정하고 단계별로 풀어 설명한다.",
    "example": "한 번에 이해되는 구체적 사례 2~3문장. 실제 숫자·상황을 들어 직관적으로 보여준다.",
    "closing": "다음 화면으로 연결하는 한 문장 + 자가점검 한 문장(총 1~2문장).",
}


def log_level() -> str:
    return (_optional_value("LOG_LEVEL") or "INFO").upper()


@cache
def prepare_matplotlib_runtime() -> None:
    """matplotlib 캐시 경로를 쓰기 가능한 임시 경로로 고정한다."""
    mpl_dir = Path(_optional_value("MPLCONFIGDIR") or "/tmp/chapterstudio-matplotlib")
    xdg_dir = Path(_optional_value("XDG_CACHE_HOME") or "/tmp/chapterstudio-cache")
    mpl_dir.mkdir(parents=True, exist_ok=True)
    xdg_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(mpl_dir))
    os.environ.setdefault("XDG_CACHE_HOME", str(xdg_dir))
