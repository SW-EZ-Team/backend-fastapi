# Git 협업 컨벤션

## 개요

SW_project의 모든 레포는 이 문서에 정의된 Git 컨벤션을 따른다. 브랜치 전략, 커밋 메시지 형식, Merge 전략을 일관되게 유지함으로써 코드 이력을 명확하게 관리하고 팀 협업 흐름을 통일한다.

---

## 브랜치 전략

| 브랜치 | 역할 | 비고 |
|---|---|---|
| `main` | 최종 배포 브랜치 | 직접 push 금지, PR만 허용 |
| `develop` | 개발 통합 브랜치 | feature/fix/refactor 브랜치의 merge 대상 |
| `feature` | 새로운 기능 개발 | 예: `feature/login-page` |
| `fix` | 버그 수정 | 예: `fix/login-error` |
| `refactor` | 코드 리팩토링 | 예: `refactor/auth-module` |

### 브랜치 흐름

```
main      ●───────────────────────────────────────────────────► v(n버전)
           ↑                                              Rebase merge
develop   ●────────●────────●────────●──────────────────►
           ↑        ↑        ↑        ↑       Squash merge
           │  feature/12   fix/34  refactor/56
           │   ●──●─╯       ●──●──╯   ●──╯
           │
          (develop 기반 분기)
```

---

## 브랜치 네이밍 규칙

`{타입}/{작업내용}` 형식을 따른다.

- `feature/add-login-page`
- `fix/fix-null-pointer`
- `refactor/auth-module`

타입은 `feature`, `fix`, `refactor` 세 가지 중 하나를 사용한다.

### 개인별 브랜치 확장 규칙

팀원이 동시에 작업할 때는 브랜치 이름 앞에 **본인 식별자**를 붙여 충돌을 막는다. 포맷은 다음과 같다.

`{name}/{type}/{description}`

| 구성 요소 | 설명 | 예시 |
|---|---|---|
| `name` | 본인 영문 식별자 (팀 내 합의한 이니셜 또는 닉네임) | `ktk` |
| `type` | 작업 타입 (`feature` / `fix` / `refactor` / `docs` 중 하나) | `feature` |
| `description` | 작업 내용을 케밥 케이스로 | `setup-github-convention` |

**실제 적용 예시**
- `ktk/feature/setup-github-convention` — 깃 컨벤션 초기 셋업
- `ktk/fix/login-null-pointer` — 로그인 NPE 수정
- `ktk/refactor/module-split` — 모듈 분리 리팩터
- `ktk/docs/update-kanana-readme` — 모듈 README 갱신

**규칙**
- `name` 부분은 팀원마다 고유하며, 한 번 정하면 계속 같은 식별자를 쓴다.
- 분기 출발점은 여전히 `develop`. `main`에서 분기하지 않는다.
- 개인 브랜치에 바로 push 하고, 작업이 끝나면 `develop`으로 PR을 연다.
- PR이 Squash Merge 되면 개인 브랜치는 즉시 삭제한다.
- 기본 규칙인 `{type}/{description}` 포맷도 여전히 유효하다. 혼자 작업하는 경우에는 `name` 생략 가능하다.

---

## 작업 흐름

### 1. Issue 생성

작업 시작 전 GitHub Issue를 반드시 먼저 생성한다. 적절한 라벨을 부착한다 (`feature`, `bug`, `refactor` 등).

### 2. 브랜치 생성

`develop`에서 분기한다. 네이밍 규칙을 준수한다.

```bash
git checkout develop
git pull origin develop
git checkout -b feature/login
```

### 3. 커밋

커밋 메시지 형식을 따른다: `{깃모지} {타입}: {내용}`

```
✨ Feat: 로그인 페이지 UI 구현
🐛 Fix: 로그인 시 null pointer 오류 수정
```

### 4. PR 생성

Issue와 연결한다. PR 제목은 커밋 메시지 형식과 동일하게 작성한다.

### 5. 코드 리뷰 (필요 시)

Approve 후 Merge한다.

### 6. Merge

Merge 전략 섹션을 참고한다.

---

## 커밋 메시지 형식

형식: `{깃모지} {타입}: {내용}`

| 깃모지 | 타입 | 설명 |
|---|---|---|
| 🎉 | Start | Start New Project |
| ✨ | Feat | 새로운 기능을 추가 |
| 🐛 | Fix | 버그 수정 |
| 🎨 | Design | CSS 등 사용자 UI 디자인 변경 |
| ♻️ | Refactor | 코드 리팩토링 |
| 🔧 | Settings | Changing configuration files |
| 🗃️ | Comment | 필요한 주석 추가 및 변경 |
| ➕ | Dependency/Plugin | Add a dependency/plugin |
| 📝 | Docs | 문서 수정 |
| 🔀 | Merge | Merge branches |
| 🚀 | Deploy | Deploying stuff |
| 🚚 | Rename | 파일 혹은 폴더명을 수정하거나 옮기는 작업만인 경우 |
| 🔥 | Remove | 파일을 삭제하는 작업만 수행한 경우 |
| ⏪️ | Revert | 전 버전으로 롤백 |

### 커밋 예시

```
✨ Feat: 로그인 페이지 UI 구현
🐛 Fix: 로그인 시 null pointer 오류 수정
📝 Docs: README 설치 방법 갱신
♻️ Refactor: auth 모듈 책임 분리
```

---

## Merge 전략

### develop ← feature/fix/refactor: Squash and Merge

여러 커밋을 하나로 압축하여 develop 이력을 깔끔하게 유지한다.

### main ← develop: Rebase and Merge

선형 재배치 방식으로 배포 이력을 정리한다. 배포 준비가 완료된 시점에만 수행한다.

---

## 주의사항

- `main`, `develop` 브랜치에 **직접 push 금지**.
- 모든 작업은 **Issue → 브랜치 → PR** 순서로 진행한다. Issue 없이 브랜치를 만들지 않는다.
- 브랜치는 Merge 완료 후 **즉시 삭제**한다.

---

## 문서 메타

- 버전: v1.0
- 작성일: 2026-04-20
- 출처: 팀 Git Convention 노션
