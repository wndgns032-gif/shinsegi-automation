# YouTube 채널 재배치 — 로이 행동 가이드 (2026-10-07)

## 현재 상태 (확인 완료)

| 언어 | 채널 | 계정 | 영상수 | 상태 |
|---|---|---|---|---|
| 한국어(ko) | ~~`@shinsegi-kr`~~ → **`@shinsegi-zh` 로 개명** | shinsegimedia | 0 | ⛔ **차단됨** |
| 프랑스어(fr) | `@shinsegi-fr` "shinsegi Français" | shinsegimedia | 2 | ✅ 연결 |
| 중국어(zh-cn) | `@shinsegi-zh` "shinsegi 中文" | shinsegimedia | 0 | 인증 필요 |
| 영어(en) | — | 미생성 | 0 | 미연결 |

**2026-10-07 저녁 변경**: 로이가 기존 `@shinsegi-kr` 채널을
"shinsegi 中文" / `@shinsegi-zh` 로 개명했다. 기존 한국어 영상 3개는 삭제된 상태.

### ⚠️ 이 변경으로 생긴 위험 (코드에서 차단함)
기존 `YOUTUBE_KO_REFRESH_TOKEN` 은 이제 **`@shinsegi-zh`(중국어) 를 가리킨다.**
이 상태로 한국어 영상을 올리면 **중국어 채널에 한국어 영상이 게시**된다.
→ `config/youtube_channels.yaml` 의 `blocked_languages: [ko]` 로 업로드를 막았다.
→ `youtube_auth.py ko` 로 재인증하면 **자동으로 차단이 해제**된다.

---

## ⚠️ 먼저 알아야 할 YouTube 구조

### 1. 채널은 "계정"이 아니라 "계정 아래의 자식"
Google 계정 1개 = YouTube 채널 N개

### 2. 영상은 채널에 영구 귀속
**채널을 다른 계정으로 옮기는 것은 불가능.** → 새 채널을 만들어야 한다.

### 3. 목표 상태达成 방법
| 언어 | 목표 채널 | 방법 |
|---|---|---|
| 한국어 | 개인 계정의 새 채널 | 개인 계정에서 생성 후 ko 재인증 |
| 영어 | 개인 계정의 새 채널 | 개인 계정에서 생성 후 en 재인증 |
| 프랑스어 | shinsegimedia (현재 그대로) | ✅ 완료 |
| 중국어 | `@shinsegi-zh` (현재 그대로) | zh-cn 만 재인증 |

---

## 실행 절차

### Step 1. 로이가 먼저 할 일 (브라우저)

**A) 개인 계정에서 한국어·영어 채널 생성**
1. 개인 Google 계정으로 YouTube 로그인
2. 우측 상��� 프로필 → **"채널 만들기"**
3. 한국어 채널: 이름 `shinsegi 한국어`, 핸들 `@shinsegi-ko`
4. 영어 채널: 이름 `shinsegi English`, 핸들 `@shinsegi-en`
5. 생성 완료

**B) shinsegimedia 중국어 채널은 이미 있음** (`@shinsegi-zh`) → 추가 작업 없음

### Step 2. 핸들을 config 에 기록
새 핸들이 확정되면 `config/youtube_channels.yaml` 의 `expected_handles.ko` /
`.en` 을 채운다. (빈 값이어도 인증은 되지만, 다른 채널에 실수로 묶일 수 있음)

### Step 3. 인증 (1개씩 — 동시에 여러 언어 인증하면 계정이 섞인다)
```bash
python scripts/youtube_auth.py zh-cn   # shinsegimedia 로그인 → @shinsegi-zh 선택
python scripts/youtube_auth.py ko      # 개인 계정 로그인 → 한국어 채널 선택
python scripts/youtube_auth.py en      # 개인 계정 로그인 → 영어 채널 선택
```
인증 성공 시 `blocked_languages` 에서 해당 언어가 **자동 제거**된다.

### Step 4. 확인
```bash
python scripts/youtube_auth.py status
```
각 언어가 어느 채널에 붙었는지 표시된다.

---

## 주의사항 (실제 겪은 함정)

### ❌ 계정 단위 revoke 금지
`myaccount.google.com/connections` 에서 앱 권한을 삭제하면
**그 계정의 모든 언어 토큰이 한꺼번에 죽는다.**
언어 하나만 바꾸려면 **그 언어만 재인증**한다.

### ⚠️ Google 이 직전 계정을 재사용한다
`prompt=consent select_account` 를 넣어도 Google 이
마지막으로 쓴 신분을 자동 선택할 때가 있다.

그럴 때:
1. https://myaccount.google.com/connections
2. 해당 앱 권한 삭제
3. 인증 재실행 → 계정 선택 화면이 반드시 뜬다

### ⚠️ 채널명이 모두 'shinsegi' 라 구분은 핸들로만 된다
`expected_handles` 검증이 있다. 다른 채널에 실수로 묶이면 **토큰 저장을 거부**한다.

### ⚠️ 개인 계정 채널의 공개 설정
`videos.insert` 는 채널이 **공개(Public)** 상태여야 한다.

---

## 즉시 확인
```bash
python scripts/youtube_auth.py plan      # 채널 매핑 확인
python scripts/youtube_auth.py status    # 현재 토큰 → 채널 상태
```

## 변경 이력
- 2026-10-07: config/youtube_channels.yaml 신설. 채널 매핑을 하드코딩에서
  config 기반으로 분리. `plan` / `status` 명령 추가.
- 2026-10-07 저녁: 한국어 채널을 중국어로 개명함에 따라
  - `expected_handles.zh-cn = "@shinsegi-zh"` 확정
  - `blocked_languages = [ko]` 추가 (토큰이 중국어 채널을 가리키므로 차단)
  - 재인증 성공 시 자동 차단 해제 로직 추가