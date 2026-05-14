# 출력 포맷 벤치마크

## 참고 기준
- ChatGPT Canvas: 긴 글과 코드 작업을 별도 작업면에서 편집하고, 코드 작업은 디버그·리뷰 같은 단축 동작을 제공함.
- Claude Artifacts: 재사용 가능한 큰 산출물을 대화와 분리된 전용 영역에 표시함.
- Codex: 장시간 작업의 진행 상황을 사용자가 실시간으로 확인하는 흐름을 강조함.

## ChapterStudio_V1 반영
- 슬라이드는 테스트 강의 1개 기준 iframe 카드 5개로 분리함.
- 퀴즈는 슬라이드 안 실습과 분리된 5개 평가 산출물로 표시함.
- 핵심노트는 heading/bullets 블록으로 분해해 한 덩어리 문단을 피함.
- 과제는 title/steps/rubric으로 나눔.
- 음성대본은 slide_idx별 script_text로 나눔.
- DB 저장은 Phase 5 DBRouter에서 수행하므로 현재 HTML은 테이블 매핑 미리보기만 표시함.
