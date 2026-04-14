#!/usr/bin/env bash
# run_bench_cpu.sh — Metal GPU 가속 비활성화(-ngl 0) CPU-only 벤치마크
# GCP e2-highmem-2(x86, 2 vCPU, Metal 없음) 환경 시뮬레이션 목적
# 사용법: ./run_bench_cpu.sh [모델경로]
# 기존 run_bench.sh를 덮어쓰지 않음 (별도 파일 — idempotent)
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
OUT="${RESULTS_DIR}/bench_cpu_$(date +%Y%m%d_%H%M%S).log"

# ─── 사전 조건 확인 ──────────────────────────────────────────────────────────
echo ""
header "========================================================"
header "  Kanana Nano 2.1B CPU-only 벤치마크 (Metal 비활성화)"
header "  GCP e2-highmem-2 환경 시뮬레이션"
header "========================================================"
echo ""

if ! command -v llama-bench &>/dev/null; then
    error "llama-bench를 찾을 수 없음"
    echo "  setup.sh를 먼저 실행하세요: ./setup.sh"
    exit 1
fi

if [[ ! -f "$MODEL" ]]; then
    error "모델 파일 없음: ${MODEL}"
    echo "  setup.sh를 먼저 실행하세요: ./setup.sh"
    exit 1
fi

mkdir -p "$RESULTS_DIR"

# ─── 실행 정보 출력 ──────────────────────────────────────────────────────────
MODEL_SIZE=$(du -sh "$MODEL" | cut -f1)
TOTAL_MEM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo "0")
TOTAL_MEM_GB=$(echo "scale=1; ${TOTAL_MEM_BYTES} / 1073741824" | bc 2>/dev/null || echo "?")

info "llama-bench 경로: $(which llama-bench)"
info "모델:            ${MODEL} (${MODEL_SIZE})"
info "GPU layers:      0  (Metal 완전 비활성화 — -ngl 0)"
info "프롬프트 토큰:   512  (prompt eval)"
info "생성 토큰:       128  (generation)"
info "반복 횟수:       3회  (시나리오별)"
info "시스템 메모리:   ${TOTAL_MEM_GB} GB"
info "결과 저장:       ${OUT}"
echo ""
warn "CPU-only 모드는 Metal 대비 현저히 느립니다. 시나리오 3개 합산 약 5~15분 소요 예상."
echo ""

# ─── 로그 파일 헤더 ───────────────────────────────────────────────────────────
{
    echo "========================================================"
    echo "  Kanana Nano 2.1B Q4_K_M CPU-only 벤치마크 결과"
    echo "  목적:     GCP e2-highmem-2 (x86, 2 vCPU, Metal 없음) 시뮬레이션"
    echo "  실행일시: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "  모델:     ${MODEL}"
    echo "  모델크기: ${MODEL_SIZE}"
    echo "  GPU layers: 0 (Metal 완전 비활성화)"
    echo "  아키텍처: $(uname -m)"
    echo "  macOS:    $(sw_vers -productVersion 2>/dev/null || echo 'N/A')"
    echo "  시스템메모리: ${TOTAL_MEM_GB} GB"
    echo "========================================================"
    echo ""
} > "$OUT"

# ─── 시나리오 정의 ────────────────────────────────────────────────────────────
# 형식: "스레드수:설명"
declare -a SCENARIOS=(
    "2:e2-highmem-2 직접 재현 (2 vCPU)"
    "4:스레드 더 많은 환경 비교 (4 threads)"
    "8:M4 CPU-only 상한 (8 threads)"
)

SCENARIO_NUM=0

for SCENARIO in "${SCENARIOS[@]}"; do
    THREADS="${SCENARIO%%:*}"
    DESC="${SCENARIO#*:}"
    SCENARIO_NUM=$((SCENARIO_NUM + 1))

    echo ""
    header "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    header "  시나리오 ${SCENARIO_NUM}/3 — ${DESC}"
    header "  스레드: ${THREADS}  |  GPU layers: 0 (CPU only)"
    header "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    {
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "  시나리오 ${SCENARIO_NUM}/3 — ${DESC}"
        echo "  스레드: ${THREADS}  |  -ngl 0 (Metal 완전 비활성화)"
        echo "  시작: $(date '+%Y-%m-%d %H:%M:%S')"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
    } >> "$OUT"

    # llama-bench 실행 — -ngl 0 으로 Metal GPU layers 완전 차단
    # BLAS는 자동 로드될 수 있으며, 이는 실제 GCP x86 환경에서도 동일하므로 유지
    llama-bench \
        -m "$MODEL" \
        -p 512 \
        -n 128 \
        -t "$THREADS" \
        -ngl 0 \
        -r 3 \
        2>&1 | tee -a "$OUT"

    {
        echo ""
        echo "  완료: $(date '+%Y-%m-%d %H:%M:%S')"
        echo ""
    } >> "$OUT"

    success "시나리오 ${SCENARIO_NUM} 완료 (스레드: ${THREADS})"
    echo ""
done

# ─── 수용 기준 체크 섹션 ─────────────────────────────────────────────────────
{
    echo "========================================================"
    echo "  수용 기준 체크 (CPU-only 환경 기준)"
    echo "========================================================"
    echo ""
    echo "  기준값 (GCP e2-highmem-2 도입 판정):"
    echo ""
    echo "  생성 t/s >= 30   → GO     — e2-highmem-2 실현 가능"
    echo "  생성 t/s 15~30   → 조정   — 스레드 수 제약 or 양자화 조정 검토"
    echo "  생성 t/s < 15    → NO-GO  — e2-standard-4 상향 또는 Q3_K_M 검토"
    echo ""
    echo "  [주의] 이 머신(Apple M4, Metal 비활성)의 수치에 GCP 보정 계수 적용 필요:"
    echo "    GCP e2 (Cascade Lake/Ice Lake Xeon) IPC ≈ M4 대비 0.6~0.7배"
    echo "    실제 GCP 예상 t/s = (이 결과 t/s) × 0.65 (중간값 보정)"
    echo ""
    echo "  결과 해석:"
    echo "    각 시나리오의 tg128 행의 t/s 열 = generation t/s"
    echo "    각 시나리오의 pp512 행의 t/s 열 = prompt eval t/s"
    echo ""
    echo "  Metal 기준 결과 (비교용):"
    echo "    tg128: 111.11 t/s  (BLAS+MTL, 스레드 4, 2026-04-14)"
    echo "    pp512: 1500.51 t/s (BLAS+MTL, 스레드 4, 2026-04-14)"
    echo ""
} | tee -a "$OUT"

echo ""
success "전체 벤치마크 완료"
success "결과 파일: ${OUT}"
echo ""
header "========================================================"
echo ""
info "다음 명령으로 결과 확인:"
echo "  cat ${OUT}"
echo ""
info "Metal 결과와 비교:"
echo "  diff <(grep -E 'pp512|tg128' ${RESULTS_DIR}/bench_20260414_223801.log) <(grep -E 'pp512|tg128' ${OUT})"
echo ""
