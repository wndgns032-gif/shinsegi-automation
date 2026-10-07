# YouTube 채널 재배치 — 로이 행동 가이드 (2026-10-07)

## 현재 상태 (확인 완료)

| 언어 | 채널 | 계정 | 영상수 |
|---|---|---|---|
| 한국어(ko) | `@shinsegi-kr` "shinsegi 한국어" | **shinsegimedia** | 3 |
| 프랑스어(fr) | `@shinsegi-fr` "shinsegi Français" | **shinsegimedia** | 2 |
| 영어(en) | — | 미생성/미인증 | 0 |
| 중국어(zh) | — | 미생성/미인증 | 0 |

**즉 한국어 채널은 이미 shinsegimedia 계정에 있다.** 원하는 상태로 바꾸려면
한국어 토큰을 **개인 계정의 채널로 재인증**해야 한다.

---

## ⚠️ 먼저 알아야 할 YouTube 구조 (중요)

### 1. 채널은 "계정"이 아니라 "계정 아래의 자식"이다
Google 계정 1개 = YouTube 채널 N개를 가질 수 있다.
예: 개인 Gmail → 채널 A, 채널 B

### 2. 영상은 채널에 영구 귀속된다
**채널을 다른 계정으로 옮기는 것은 불가능하다.** (YouTube 정책)
→ 원하는 결과를 얻으려면 **새로 만들어야 한다**

### 3. 그래서 선택지는 둘뿐

| 방법 | 결과 |代价 |
|---|---|---|
| **A. 새 채널 생성** (권장) | 개인 계정에 `@shinsegi-ko` 새 채널 생성 → 한국어 업로드 | 기존 한국어 영상 3개는 그대로 방치 |
| **B. 그대로 유지** | 한국어=shinsegimedia, 프랑스어=zh=shinsegimedia | 요청하신 분리 미실현 |

→ 영상 3개밖에 없으므로 **A가 현실적**이다. 새 채널이 더 깨끗하다.

---

## 실행 절차

### Step 1. 로이가 먼저 할 일 (브라우저)

1. **개인 Google 계정**으로 YouTube 로그인
2. 우측 상단 프로필 → **"채널 만들기"**
3. 이름 입력 (예: `shinsegi 한국어`)
4. 핸들 지정 (예: `@shinsegi-ko-personal`)
   - YouTube가 사용 가능 여부를 알려준다
5. 생성 완료

> 브랜드 계정(shinsegimedia)에서는 아직 fr, zh 채널만 있으면 된다.
> 한국어/영어는 개인 계정 아래에 둔다.

### Step 2. 핸들을 config 에 기록
새 채널 핸들이 확정되면 `config/youtube_channels.yaml` 의 `expected_handles` 를 채운다.

### Step 3. 인증 (로이 또는 내가 실행)
```bash
python scripts/youtube_auth.py ko
```
브라우저가 열리면:
1. **개인 계정**으로 로그인
2. 계정 선택 화면에서 **개인 계정** 선택
3. Step 1에서 만든 **한국어 채널** 선택
4. "권한 허용"

→ `YOUTUBE_KO_REFRESH_TOKEN` 이 해당 채널로 저장됨

같은 방식:
```bash
python scripts/youtube_auth.py en      # 개인 계정 영어 채널
python scripts/youtube_auth.py zh-cn   # shinsegimedia 중국어 채널
```

### Step 4. 확인
```bash
python scripts/youtube_auth.py status
```
각 언어가 어떤 채널에 붙었는지 표시된다.

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
그래서 `expected_handles` 검증이 있다. 다른 채널에 실수로 묶이면
**토큰 저장을 거부**한다.

### ⚠️ 개인 계정 채널의 공개 설정
`videos.insert` 는 채널이 **공개(Public)** 상태여야 한다.
기본값이 Public 인지 확인한다.

---

## 즉시 확인
```bash
python scripts/youtube_auth.py plan      # 채널 매핑 확인
python scripts/youtube_auth.py status    # 현재 토큰 → 채널 상태
```

## 변경 이력
- 2026-10-07: config/youtube_channels.yaml 신설. 채널 매핑을 하드코딩에서
  config 기반으로 분리. `plan` / `status` 명령 추가.