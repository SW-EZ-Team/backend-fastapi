"""공통 상수 모듈.

모든 모듈에서 공유하는 시스템 전역 상수를 정의한다.
매직 넘버를 분산 정의하지 않고 이 파일에서만 관리한다.
"""

import os

# PDF 업로드 크기 제한: 최대 1.5GB (1.5 * 2^30 bytes)
# 학술 자료/대용량 강의 교재 지원을 위해 크게 설정함
# 환경변수 MAX_PDF_UPLOAD_SIZE_BYTES로 재정의 가능 (.env 참조)
MAX_PDF_UPLOAD_SIZE_BYTES: int = int(
    os.getenv("MAX_PDF_UPLOAD_SIZE_BYTES", str(1_610_612_736))
)
