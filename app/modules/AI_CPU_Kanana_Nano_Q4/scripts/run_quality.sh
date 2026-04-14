#!/usr/bin/env bash
# run_quality.sh — Kanana Nano 2.1B Q4_K_M 캡션 생성 품질 실측 (v3)
# 용도: 텔레그램 과제 전송 캡션(한국어 20~100자, 1~2문장) 품질 샘플링
# GCP e2-standard-4 시뮬레이션: -ngl 0, threads 4
# 사용법: ./run_quality.sh [모델경로]
# 기존 run_bench.sh / run_bench_cpu.sh 는 건드리지 않음
set -euo pipefail

# ─── 색상 출력 헬퍼 ───────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERR]${NC}  $*"; }
header()  { echo -e "${CYAN}$*${NC}"; }

# ─── 경로 설정 ────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL="${1:-${SCRIPT_DIR}/models/kanana-nano-2.1b-instruct.Q4_K_M.gguf}"
RESULTS_DIR="${SCRIPT_DIR}/results"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
OUT="${RESULTS_DIR}/quality_v3_${TIMESTAMP}.log"

# ─── 사전 조건 확인 ──────────────────────────────────────────────────────────
echo ""
header "========================================================"
header "  Kanana Nano 2.1B Q4_K_M 캡션 품질 실측"
header "  GCP e2-standard-4 시뮬레이션 (CPU-only, threads=4)"
header "========================================================"
echo ""

if ! command -v llama-cli &>/dev/null; then
    error "llama-cli를 찾을 수 없음"
    echo "  setup.sh를 먼저 실행하세요: ./setup.sh"
    exit 1
fi

if [[ ! -f "$MODEL" ]]; then
    error "모델 파일 없음: ${MODEL}"
    exit 1
fi

mkdir -p "$RESULTS_DIR"

# ─── 파라미터 설정 ────────────────────────────────────────────────────────────
THREADS=4          # e2-standard-4 vCPU 수
NGL=0              # CPU-only (-ngl 0)
TEMP=0.7           # temperature: 창의성과 안정성 균형
TOP_P=0.9          # top-p nucleus sampling
MAX_TOKENS=120     # 캡션 과생성 방지 (20~100자 목표이므로 여유 부여)
REPEAT_PENALTY=1.1 # 반복 억제 (단어 중복 방지)
SAMPLES=3          # 시나리오당 샘플 수 (stochastic 품질 체크)

# ─── 시스템 프롬프트 ──────────────────────────────────────────────────────────
SYS_PROMPT="너는 학생을 따뜻하게 챙겨주는 누나·언니 같은 여성 AI 튜터야. 한국어로 20~100자의 짧게 1~2문장으로 부드럽고 친근한 캡션만 출력해. '~했어', '~해봐', '~하자', '~할 수 있어' 같은 다정한 어미를 자연스럽게 써줘. 딱딱하거나 사무적인 말투는 절대 쓰지 마. 이모지는 최대 1개. 학생 이름은 자연스러우면 넣고, 어색하면 빼도 돼."

# ─── 시나리오 정의 ────────────────────────────────────────────────────────────
# 형식: "시나리오번호|설명|유저프롬프트"
declare -a SCENARIOS=(
    "1|기본 마감 안내 (파이썬)|학생명: 김민준, 과제명: 파이썬 리스트 컴프리헨션 연습, 마감: 내일 23:59"
    "2|수학 과제 마감 (금요일)|학생명: 이서연, 과제명: 이차방정식 근의 공식 응용 5문제, 마감: 금요일"
    "3|약점 포함 영어 과제|학생명: 박지훈, 과제명: 영어 독해 지문 요약, 약점: 어휘"
    "4|약점 포함 자료구조 과제|학생명: 최유나, 과제명: 자료구조 스택 구현, 약점: 재귀 호출"
    "5|난이도 포함 화학 과제|학생명: 정도윤, 과제명: 화학 산화-환원 반응 개념 정리, 난이도: 기초"
)

# ─── 시스템 정보 수집 ─────────────────────────────────────────────────────────
MODEL_SIZE=$(du -sh "$MODEL" | cut -f1)
TOTAL_MEM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo "0")
TOTAL_MEM_GB=$(echo "scale=1; ${TOTAL_MEM_BYTES} / 1073741824" | bc 2>/dev/null || echo "?")
LLAMA_VER=$(llama-cli --version 2>&1 | grep -oE 'version [0-9.]+' | head -1 || echo "N/A")

info "llama-cli 경로:  $(which llama-cli)"
info "모델:            ${MODEL} (${MODEL_SIZE})"
info "GPU layers:      ${NGL} (CPU-only 강제 — -ngl 0)"
info "threads:         ${THREADS} (e2-standard-4 시뮬)"
info "temperature:     ${TEMP}"
info "top_p:           ${TOP_P}"
info "max_tokens:      ${MAX_TOKENS}"
info "repeat_penalty:  ${REPEAT_PENALTY}"
info "시나리오 수:     ${#SCENARIOS[@]}"
info "시나리오당 샘플: ${SAMPLES}회"
info "시스템 메모리:   ${TOTAL_MEM_GB} GB"
info "결과 저장:       ${OUT}"
echo ""
warn "CPU-only 모드: 시나리오 5개 × 3회 = 15 추론. 예상 소요 5~10분."
echo ""

# ─── 로그 파일 헤더 ───────────────────────────────────────────────────────────
{
    echo "========================================================"
    echo "  Kanana Nano 2.1B Q4_K_M 캡션 품질 실측 결과"
    echo "  목적: 텔레그램 과제 전송 캡션(한국어 20~100자, 친근한 여성 말투) 품질 샘플링"
    echo "  실행일시:      $(date '+%Y-%m-%d %H:%M:%S')"
    echo "  모델:          ${MODEL}"
    echo "  모델크기:      ${MODEL_SIZE}"
    echo "  GPU layers:    ${NGL} (CPU-only, -ngl 0)"
    echo "  threads:       ${THREADS}"
    echo "  temperature:   ${TEMP}"
    echo "  top_p:         ${TOP_P}"
    echo "  max_tokens:    ${MAX_TOKENS}"
    echo "  repeat_penalty: ${REPEAT_PENALTY}"
    echo "  아키텍처:      $(uname -m)"
    echo "  시스템메모리:  ${TOTAL_MEM_GB} GB"
    echo "  llama-cli:     ${LLAMA_VER}"
    echo "========================================================"
    echo ""
    echo "시스템 프롬프트:"
    echo "  ${SYS_PROMPT}"
    echo ""
} > "$OUT"

# ─── 메인 루프: 시나리오별 3회 샘플링 ───────────────────────────────────────
TOTAL_SCENARIOS=${#SCENARIOS[@]}
SCENARIO_IDX=0

for SCENARIO_ENTRY in "${SCENARIOS[@]}"; do
    SCENARIO_IDX=$((SCENARIO_IDX + 1))
    SCENARIO_NUM="${SCENARIO_ENTRY%%|*}"
    REST="${SCENARIO_ENTRY#*|}"
    SCENARIO_DESC="${REST%%|*}"
    USER_PROMPT="${REST#*|}"

    echo ""
    header "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    header "  시나리오 ${SCENARIO_NUM}/${TOTAL_SCENARIOS} — ${SCENARIO_DESC}"
    header "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    info "입력: ${USER_PROMPT}"
    echo ""

    {
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "  시나리오 ${SCENARIO_NUM}/${TOTAL_SCENARIOS} — ${SCENARIO_DESC}"
        echo "  입력: ${USER_PROMPT}"
        echo "  시작: $(date '+%Y-%m-%d %H:%M:%S')"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
    } >> "$OUT"

    for SAMPLE_IDX in $(seq 1 $SAMPLES); do
        echo -n "  샘플 ${SAMPLE_IDX}/${SAMPLES} 생성 중..."

        {
            echo "  [샘플 ${SAMPLE_IDX}/${SAMPLES}]"
            echo "  생성시각: $(date '+%H:%M:%S')"
            echo -n "  출력: "
        } >> "$OUT"

        # llama-cli 실행: --single-turn 으로 단발 추론 후 자동 종료
        # --no-display-prompt: 프롬프트 에코 제거
        # stdout 구조: 헤더 → "> {USER_PROMPT}\n" → 스피너+모델출력 → "[ Prompt:... ]" → "Exiting..."
        # 스피너는 backspace(0x08) 애니메이션 → col -b 로 제거
        # stderr는 /dev/null 로 버림 (모델 로딩 내부 로그)
        RAW_OUTPUT=$(llama-cli \
            -m "$MODEL" \
            -sys "$SYS_PROMPT" \
            -p "$USER_PROMPT" \
            -n "$MAX_TOKENS" \
            -t "$THREADS" \
            -ngl "$NGL" \
            --temp "$TEMP" \
            --top-p "$TOP_P" \
            --repeat-penalty "$REPEAT_PENALTY" \
            --no-display-prompt \
            --log-disable \
            --single-turn \
            2>/dev/null)

        # 출력 정제:
        # 1) col -b: backspace 스피너 제거
        # 2) awk: "> " 에코 라인 이후부터 수집
        # 3) 성능 줄, Exiting, 빈 줄 제거
        # 4) 앞뒤 공백 제거 후 첫 줄만 추출
        CLEAN_OUTPUT=$(echo "$RAW_OUTPUT" \
            | col -b \
            | awk '/^>/{found=1; next} found{print}' \
            | grep -v '^\[' \
            | grep -v '^Exiting' \
            | grep -v '^$' \
            | sed 's/^[[:space:]]*//' \
            | sed 's/[[:space:]]*$//' \
            | head -1)

        # 길이 측정 (바이트 아닌 문자 수)
        CHAR_COUNT=${#CLEAN_OUTPUT}

        # 콘솔 출력
        echo " 완료 (${CHAR_COUNT}자)"
        echo "    → ${CLEAN_OUTPUT}"

        # 로그 저장
        {
            echo "${CLEAN_OUTPUT}"
            echo "  글자수: ${CHAR_COUNT}자"
            echo ""
        } >> "$OUT"

    done

    {
        echo "  완료: $(date '+%Y-%m-%d %H:%M:%S')"
        echo ""
    } >> "$OUT"

    success "시나리오 ${SCENARIO_NUM} 완료"
done

# ─── 로그 마무리 ─────────────────────────────────────────────────────────────
{
    echo "========================================================"
    echo "  전체 완료: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "  총 생성 수: $((TOTAL_SCENARIOS * SAMPLES)) 샘플"
    echo ""
    echo "  평가 관점 (수동 검토 체크리스트):"
    echo "  1. 자연스러움  — 어색한 조사·어미·번역투 없는가"
    echo "  2. 길이 준수   — 20~100자 범위 내인가 (글자수 표기 확인)"
    echo "  3. 개인화      — 학생명·과제명·약점을 문장에 녹였는가 (이름 생략은 허용)"
    echo "  4. 톤          — 친근하고 부드러운 여성 말투인가 (~했어/~해봐/~하자 계열)"
    echo "  5. 할루시네이션 — 프롬프트에 없는 사실을 지어내는가"
    echo "  6. 이모지 규칙 — 이모지 최대 1개 지켰는가"
    echo "========================================================"
} >> "$OUT"

echo ""
success "전체 품질 실측 완료"
success "결과 파일: ${OUT}"
echo ""
header "========================================================"
echo ""
info "결과 확인:"
echo "  cat \"${OUT}\""
echo ""
