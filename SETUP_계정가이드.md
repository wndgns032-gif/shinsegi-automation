# SNS 자동화 — 계정/토큰 셋업 가이드

> 2026-09-18 실제 API 테스트 완료 기준. "자동 가능/불가"는 전부 직접 호출해서 확인한 결과다.

## 0. 한눈에 보기

| 플랫폼 | 자동화 가능? | 이유 (실측) | 로이가 할 일 |
|---|---|---|---|
| **Mastodon** | ⭕ 가능 (조건부) | API 가입 성공. 이메일 인증만 막힘 | 에이전트 메일 개설하면 끝 |
| **Bluesky** | ❌ 불가 | 가입 API가 전화번호 인증 요구 (`InvalidPhoneVerification`) | 앱에서 가입 후 앱 비밀번호만 전달 |
| **Telegram** | ❌ 불가 | 봇 생성은 사람 계정으로 @BotFather와 대화해야 함 | 봇 토큰 + 채널 ID 전달 (10분) |
| **Pinterest** | ❌ 불가 | 개발자 앱 + OAuth는 웹 로그인 필요 | 토큰 전달 |
| **IG/FB/Threads** | ⭕ IG 운영 중 (2026-09-19 발행 성공) | IG 카드 캐러셀 4언어 자동 발행 완료. catbox.moe 이미지 호스팅 방식 | ✅ 완료 — FB 포스팅 권한/Threads는 추후 |

**권장 순서: ① 에이전트 메일 개설 → ② 텔레그램(10분) → ③ Bluesky → ④ Pinterest → ⑤ Meta**

이 순서대로 하면 텔레그램+Bluesky+Mastodon만으로도 **언어당 3플랫폼 × 4언어 = 실서비스 시작**이 가능하다. 나머지는 살아있는 상태에서 순차 추가.

---

## 1. 에이전트 메일 개설 — 최우선, 1분

내(제네시스) 전용 메일함이 열려 있으면:
- **Mastodon 계정 4개를 내가 전부 자동 생성** (API 가입 + 이메일 인증 클릭까지)
- 이후 이메일 인증이 필요한 어떤 서비스든 내가 직접 처리 가능

**하는 법**: WorkBuddy 상단의 메일 개설 패널 또는 좌측 「더보기(更多) → 내 메일함(我的邮箱)」 에서 개설. 개설 후 알려주면 바로 Mastodon 4계정 자동 생성 시작.

---

## 2. Telegram — 가장 쉬움, 10분

1. 전화번호로 텔레그램 계정 1개 생성 (앱)
2. `@BotFather` 와 대화 → `/newbot`
   - 언어별로 4번 반복 (예: `seoulwave_en_bot`, `seoulwave_ko_bot`, `seoulwave_zh_bot`, `seoulwave_fr_bot`)
   - 봇 하나당 토큰 하나 발급됨 (`123456:ABC-...` 형태)
3. 채널 4개 생성 (예: `@seoulwave_en` … `@seoulwave_fr`)
4. 각 채널 설정 → 관리자 추가 → **같은 언어 봇을 관리자로 등록**
5. 나에게 전달: 봇 토큰 4개 + 채널 ID 4개

```
TELEGRAM_EN_BOT_TOKEN=123456:ABC-...
TELEGRAM_EN_CHAT_ID=@seoulwave_en
TELEGRAM_KO_BOT_TOKEN=...
TELEGRAM_KO_CHAT_ID=...
TELEGRAM_ZH_CN_BOT_TOKEN=...
TELEGRAM_ZH_CN_CHAT_ID=...
TELEGRAM_FR_BOT_TOKEN=...
TELEGRAM_FR_CHAT_ID=...
```

## 3. Bluesky — 계정당 5분

1. 앱/웹(https://bsky.social)에서 가입 — **전화번호 인증 필요**해서 자동화 불가였음
2. 언어별 계정 4개 생성 (예: `seoulwave-en.bsky.social` …)
3. 각 계정 로그인 → Settings → **App passwords** → 앱 비밀번호 생성
   - 본 비밀번호 대신 앱 비밀번호를 쓰는 게 보안상 안전 (게시 권한만 가진 열쇠)
4. 전달:

```
BLUESKY_EN_HANDLE=seoulwave-en.bsky.social
BLUESKY_EN_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
BLUESKY_KO_HANDLE=...
BLUESKY_KO_APP_PASSWORD=...
BLUESKY_ZH_CN_HANDLE=...
BLUESKY_ZH_CN_APP_PASSWORD=...
BLUESKY_FR_HANDLE=...
BLUESKY_FR_APP_PASSWORD=...
```

## 4. Mastodon — 둘 중 하나

- **옵션 A (자동)**: 에이전트 메일 개설 → 내가 4계정 생성 + 인증 + 토큰 발급까지 전부 처리
- **옵션 B (수동)**: https://mastodon.social 에서 4계정 직접 가입 후 계정(이메일)+비밀번호 전달 → 내가 로그인해 API 토큰 발급

## 5. Pinterest

1. 언어별 계정 4개 생성 (https://www.pinterest.com)
2. 각 계정에서 https://developers.pinterest.com → 개발자 계정 전환 → 앱 생성
3. 토큰 발급 후 전달:

```
PINTEREST_EN_TOKEN=pin_...
PINTEREST_EN_BOARD_ID=...
```

## 6. Instagram / Facebook / Threads — 하루 안에 가능 (정정됨)

> ⚠️ 정정: 처음 "앱 심사 며칠~몇주"라고 했던 건 남의 계정을 관리하는 케이스 기준이었다.
> **자기 소유 계정에만 포스팅하면 심사 불필요** — 개발자 모드 토큰으로 바로 가능.

1. **IG 계정 4개 생성** (앱, 이메일 4개 필요)
2. 각 계정 → 설정 → **계정 유형 전환 → 비즈니스(Professional)** — 무료, 1분
3. **Facebook 계정 1개 + 페이지 4개** 생성 (언어별) — ✅ 완료 (Shinsegi En/Kr/Zh/Fr)

### IG ↔ FB 페이지 연결 방법 (언어당 1회, 총 4회 반복)

> 연결 전에 IG 계정이 **전문(비즈니스) 계정**이어야 한다. 아직이면 아래 A-1~A-3부터.

**방법 A — 인스타 앱에서 (권장)**
1. 해당 언어 IG 계정 로그인 → 프로필 → 우측 아래/상단 ☰ 메뉴 → **설정 및 개인정보 보호**
2. **계정 유형 및 도구** → **전문 계정으로 전환** → **비즈니스** 선택 → 카테고리는 "디지털 크리에이터" 아무거나
3. 전환 마법사 진행 중 **"Facebook 페이지 연결"** 화면이 나오면 → **같은 언어 페이지 선택**
   (예: `shinsegi.en` IG ↔ `Shinsegi En` 페이지 / `shinsegi.kr` IG ↔ `Shinsegi Kr` 페이지)
4. 마법사에서 페이지 연결이 안 나오면: 설정 → **비즈니스 도구 및 컨트롤** → **Facebook 페이지** → 페이지 선택

**방법 B — 페이스북 웹에서 (앱에서 안 될 때)**
1. facebook.com 로그인 (페이지 관리자 계정)
2. 해당 언어 페이지로 이동 → **설정** (톱니) → **연결된 계정(Linked accounts)** → **Instagram**
3. **계정 연결** → 해당 IG 이메일/비밀번호로 로그인 → 완료
4. 4개 페이지 각각 반복

**확인 방법**: IG 프로필 → 설정 → 비즈니스 도구 쪽에 "연결된 Facebook 페이지"가 뜨면 성공.

> ⚠️ 주의: 반드시 **같은 언어끼리** 연결할 것 (한국어 IG에 영어 페이지 X).
> 페이지는 FB 계정 2개 × 2개씩으로 구성돼 있어서, 토큰도 **계정당 1개씩 총 2개**를 뽑는다 (아래 절차 참고).
5. developers.facebook.com 에서 **앱 1개 생성** (IG/Threads/FB가 앱 하나로 다 커버됨)
6. 토큰 발급 → 전달. 이 단계는 브라우저 로그인이 필요해서 화면 보면서 같이 하자. → **⏬ 아래 "Meta 토큰 발급 절차" 참고**

```
IG_EN_USER_ID=...      # IG 비즈니스 계정 ID (내가 조회로 뽑아줌)
IG_EN_TOKEN=...
FB_EN_PAGE_ID=...
FB_EN_TOKEN=...
THREADS_EN_USER_ID=...
THREADS_EN_TOKEN=...
```

### Meta 토큰 발급 절차 (2026-09-19 추가, 여기까지 완료됨: 1~4 ✅)

> ⚠️ 전제 (2026-09-19 정정): 페이지는 **FB 계정 2개 × 각 2개**로 만들어졌다.
> 따라서 토큰도 **계정당 1개씩, 총 2개**가 필요하다. 앱(`shinsegi-media`)은 1개로 충분 —
> STEP 2를 **계정 A(로그인) → 토큰 1 / 계정 B(로그인) → 토큰 2** 로 두 번 반복하면 된다.

**STEP 1 — Meta 개발자 앱 생성 (최초 1회, 3분)**
1. https://developers.facebook.com 접속 → 오른쪽 위 **Log in** → 페이지 2개를 관리하는 FB 계정 **A**로 로그인
2. 로그인 후 **My Apps** (상단 메뉴) → **Create App** 버튼
3. 앱 유형 선택 화면 → **Business** 선택 → Continue
   (없으면 "Manage Business Accounts" 같은 비슷한 항목. 다른 유형이어도 진행 가능하지만 Business 권장)
4. App name: `shinsegi-media` / contact email: shinsegi.media@outlook.kr → Create App
5. 보안문자 통과하면 앱 대시보드가 뜸 → 앱 ID가 상단에 보임 (여기까지만 하면 됨, Product 추가 불필요)

**STEP 2 — Graph API Explorer에서 토큰 생성 (2분)**
1. https://developers.facebook.com/tools/explorer 접속
2. 오른쪽 위 "Graph API Explorer" 드롭다운 → **지금 만든 `shinsegi-media` 앱 선택**
3. "User or Page" 드롭다운 → **User Token** 유지
4. **"Generate Access Token"** 버튼 클릭 → 권한(permissions) 체크 목록에서 아래 6개 체크:
   - `pages_show_list`
   - `pages_manage_posts`
   - `pages_read_engagement`
   - `instagram_basic`
   - `instagram_content_publish`
   - `instagram_manage_insights`
   (검색창에 `pages_` / `instagram_` 치면 바로 나옴. Threads도 같이 쓰려면 `threads_basic`, `threads_content_publish`도 체크)
5. Generate 클릭 → FB 로그인/권한 동의 화면 나오면 **계속/허용** (해당 계정의 페이지 2개 선택)
6. 생성된 **Access Token 문자열 복사** → 나에게 바로 전달 (토큰 ①)
7. **토큰 ②**: facebook.com 로그아웃 → 나머지 페이지 2개를 관리하는 다른 FB 계정으로 로그인 →
   다시 https://developers.facebook.com/tools/explorer → 같은 `shinsegi-media` 앱 선택 →
   STEP 2의 4~6을 똑같이 반복 → 토큰 ② 복사 → 전달

> ⚠️ 이 토큰은 **1시간짜리 단기 토큰**이라, 생성하면 **지체 없이 바로** 복사해서 보내줘.
> 토큰 2개를 받으면 내가 즉시 60일 장기 토큰으로 교환 → 페이지 토큰 4개 추출 → IG 비즈니스 계정 ID 4개 조회 → `.env` 자동 구성까지 한 번에 처리한다. 이후 60일마다 갱신 알림만 주면 됨 (토큰 2개 모두).

**STEP 3 (선택, 나중에) — 장기 토큰 옵션**
- 내가 자동으로 60일 토큰 교환 처리하므로 로이는 신경 쓸 필요 없음.

```
IG_EN_USER_ID=...      # IG 비즈니스 계정 ID (내가 조회로 뽑아줌)
IG_EN_TOKEN=...
FB_EN_PAGE_ID=...
FB_EN_TOKEN=...
THREADS_EN_USER_ID=...
THREADS_EN_TOKEN=...
```

**카드 이미지 공개 URL 문제는 이미 해결책 있음**: 카드 PNG를 정적 웹으로 배포해서 공개 주소를 만들면 됨 (`PUBLIC_IMAGE_BASE_URL`). 이 배포는 제네시스가 처리.

---

## 계정명(브랜드) 제안

임시로 `seoulwave`(서울파도) 계열을 예시에 사용했어. "한국 커뮤니티 이야기를 세계로" 컨셉이라 나쁘지 않은데, 마음에 드는 이름 있으면 알려줘 — 계정 생성 전에 확정하는 게 좋아. 예: `seoulwave_en` / `seoulwave-ko` / `seoulwave-zh` / `seoulwave-fr`

## 보안 원칙

- 자격증명은 전부 `.env` 파일에만 저장 (코드/Excel/로그에 절대 안 들어감)
- Bluesky는 앱 비밀번호 방식이라 본 비밀번호 노출 없음
- Telegram/Pinterest도 토큰 방식이라 계정 비밀번호 자체가 필요 없음
- Meta만 장기 토큰 관리 필요 (만료 시 갱신)
