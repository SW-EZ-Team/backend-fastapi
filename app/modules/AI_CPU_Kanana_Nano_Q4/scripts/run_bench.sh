#!/usr/bin/env bash
# run_bench.sh — Kanana Nano 2.1B Q4_K_M 벤치마크 실행 + 결과 저장
# 사용법: ./run_bench.sh [모델경로] [스레드수]
# 예시:   ./run_bench.sh ./models/kanana-nano-2.1b-instruct-Q4_K_M.gguf 4
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
THREADS="${2:-4}"
RESULTS_DIR="${SCRIPT_DIR}/results"
OUT="${RESULTS_DIR}/bench_$(date +%Y%m%d_%H%M%S).log"

# ─── 사전 조건 확인 ──────────────────────────────────────────────────────────
echo ""
header "========================================================"
header "  Kanana Nano 2.1B 벤치마크 실행"
header "========================================================"
echo ""

# llama-bench 존재 확인
if ! command -v llama-bench &>/dev/null; then
    error "llama-bench를 찾을 수 없음"
    echo "  setup.sh를 먼저 실행하세요: ./setup.sh"
    exit 1
fi

# 모델 파일 존재 확인
if [[ ! -f "$MODEL" ]]; then
    error "모델 파일 없음: ${MODEL}"
    echo "  setup.sh를 먼저 실행하세요: ./setup.sh"
    echo "  또는 모델 경로를 직접 지정: ./run_bench.sh /path/to/model.gguf"
    exit 1
fi

# results 디렉터리 확인
mkdir -p "$RESULTS_DIR"

# ─── 실행 정보 출력 ──────────────────────────────────────────────────────────
info "llama-bench 경로: $(which llama-bench)"
info "모델:    ${MODEL}"
info "스레드:  ${THREADS}"
info "프롬프트 토큰:  512  (prompt eval)"
info "생성 토큰:      128  (generation)"
info "결과 저장:      ${OUT}"
echo ""

# 모델 크기 출력
MODEL_SIZE=$(du -sh "$MODEL" | cut -f1)
info "모델 크기: ${MODEL_SIZE}"

# 시스템 메모리 확인 (macOS)
TOTAL_MEM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo "0")
TOTAL_MEM_GB=$(echo "scale=1; ${TOTAL_MEM_BYTES} / 1073741824" | bc 2>/dev/null || echo "?")
info "시스템 메모리: ${TOTAL_MEM_GB} GB"
echo ""

# ─── 벤치마크 실행 ───────────────────────────────────────────────────────────
header "--- 벤치마크 시작 ---"
echo ""

# 로그 파일 헤더 기록
{
    echo "========================================================"
    echo "  Kanana Nano 2.1B Q4_K_M 벤치마크 결과"
    echo "  실행일시: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "  모델:     ${MODEL}"
    echo "  스레드:   ${THREADS}"
    echo "  아키텍처: $(uname -m)"
    echo "  macOS:    $(sw_vers -productVersion)"
    echo "  llama-bench: $(llama-bench --version 2>/dev/null || echo '버전 정보 없음')"
    echo "========================================================"
    echo ""
} > "$OUT"

# llama-bench 실행 (출력을 화면과 파일 동시 기록)
# -p: prompt eval 토큰 수 (512)
# -n: generation 토큰 수 (128)
# -t: 스레드 수
# -r: 반복 횟수 (3회 평균 — 안정적 수치를 위해)
llama-bench \
    -m "$MODEL" \
    -p 512 \
    -n 128 \
    -t "$THREADS" \
    -r 3 \
    2>&1 | tee -a "$OUT"

# ─── 수용 기준 체크 ───────────────────────────────────────────────────────────
echo "" | tee -a "$OUT"
header "--- 수용 기준 체크 ---" | tee -a "$OUT"
echo "" | tee -a "$OUT"

{
    echo "수용 기준 (Kanana Nano CPU 도입 결정 기준):"
    echo ""
    echo "  [1] 생성 속도 (generation t/s) >= 30 t/s  → 도입 추진"
    echo "      20~30 t/s                              → 스레드 조정 후 재측정 권장"
    echo "      < 20 t/s                               → 양자화 변경 또는 도입 보류"
    echo ""
    echo "  [2] 100토큰 캡션 생성 시간 <= 4초"
    echo "      generation t/s >= 25 이면 100토큰 / 25 = 4.0초 이내 충족"
    echo ""
    echo "  [3] 메모리 사용량 <= 2 GB"
    echo "      Q4_K_M 모델 파일 크기: ${MODEL_SIZE}"
    echo "      (모델 로드 시 실제 메모리는 파일 크기의 약 1.1~1.2배 예상)"
    echo ""
    echo "  결과 해석:"
    echo "    위 llama-bench 출력에서 'tg128' 행의 't/s' 열 = generation t/s"
    echo "    위 llama-bench 출력에서 'pp512' 행의 't/s' 열 = prompt eval t/s"
    echo ""
    echo "  스레드 조정 예시:"
    echo "    ./run_bench.sh ${MODEL} 2  (스레드 2)"
    echo "    ./run_bench.sh ${MODEL} 4  (스레드 4)"
    echo "    ./run_bench.sh ${MODEL} 6  (스레드 6)"
    echo ""
} | tee -a "$OUT"

success "결과 파일 저장 완료: ${OUT}"
echo ""
header "========================================================"
