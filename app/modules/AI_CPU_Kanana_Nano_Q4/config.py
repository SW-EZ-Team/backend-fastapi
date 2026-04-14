"""Kanana 캡션 생성 파라미터·프롬프트. v3 기준 (2026-04-14 확정)."""

# 메모리 kanana_tone_policy.md와 동기화된 시스템 프롬프트
SYSTEM_PROMPT = (
    "너는 학생을 따뜻하게 챙겨주는 누나·언니 같은 여성 AI 튜터야. "
    "한국어로 20~100자의 짧게 1~2문장으로 부드럽고 친근한 캡션만 출력해. "
    "'~했어', '~해봐', '~하자', '~할 수 있어' 같은 다정한 어미를 자연스럽게 써줘. "
    "딱딱하거나 사무적인 말투는 절대 쓰지 마. 이모지는 최대 1개. "
    "학생 이름은 자연스러우면 넣고, 어색하면 빼도 돼."
)

# llama.cpp 추론 파라미터 (e2-standard-4 기준 — Test/run_quality.sh 검증값)
THREADS = 4
N_GPU_LAYERS = 0          # CPU-only 강제
TEMPERATURE = 0.7
TOP_P = 0.9
MAX_TOKENS = 120          # 100자 여유분
REPEAT_PENALTY = 1.1
CONTEXT_SIZE = 1024

# 검증 규칙
MIN_CHARS = 20
MAX_CHARS = 100
MAX_EMOJIS = 1
