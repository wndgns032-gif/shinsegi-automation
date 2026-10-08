# YouTube OAuth 인증 — 403 액세스 차단 해결

## 오류 메시지

```
액세스 차단됨: shinsegi은(는) Google 인증 절차를 완료하지 않았습니다
Wisdom Path / shinsegi에서 Google의 인증 절차를 완료하지 않았습니다.
앱은 현재 테스트 중이며 개발자가 승인한 테스터만 앱에 액세스할 수 있습니다.

403 오류: access_denied
```

## 원인 (정확)

Google Cloud 프로젝트 `shinsegi` 의 **OAuth 동의 화면(consent screen)이
"테스트 중(Testing)" 상태**다.

테스트 상태에서는 **"테스트 사용자(Test users)"에 등록된 계정만** OAuth 접근이 가능하다.
개인 Gmail 계정(로이 개인)과 shinsegimedia 계정 어느 쪽도 등록되어 있지 않아
`access_denied` 로 막힌 것이다.

> 참고: `fr` 채널 인증은 이전에 성공했다. 그때는 우연히 테스트 사용자에
> 등록돼 있었거나, 앱 상태가 달랐던 것. 현재는 어느 계정도 등록이 안 된 상태.

## 해결 방법 (Google Cloud Console)

### Step 1. 동의 화면 열기
1. https://console.cloud.google.com/
2. 프로젝트 선택: **shinsegi** (우측 상단)
3. 좌측 메뉴 → **API 및 서비스** → **OAuth 동의 화면**

### Step 2-A. 앱을 "운영 중" 으로 (권장)
**게시 상태(Publishing status)** 를 **"운영 중(In production)"** 으로 변경.

이렇게 하면 테스트 사용자 제한이 없어진다.
- 검증이 필요할 수 있음 (YouTube API 는 일반적으로 즉시 승인됨)
- 앱 이름/설명/스크린샷 요구될 수 있음 → 대충 기입 후 제출

### Step 2-B. 테스트 사용자에 계정 추가 (더 간단)
게시 상태를 바꾸지 않고, 사용할 계정만 등록:
1. 같은 **OAuth 동의 화면** 페이지 하단
2. **테스트 사용자** 섹션 → "테스트 사용자 추가" 클릭
3. 아래 계정들을 **모두** 추가:
   - `shinsegimedia@gmail.com` (프랑스어·중국어)
   - 로이 개인 Gmail 주소
4. "저장"

> ⚠️ 테스트 사용자는 **최대 100개**까지 추가 가능.
> 테스트 상태로도 실제 업로드엔 문제가 없다.

### Step 3. OAuth 클라이언트에서 스코프 확인
1. 좌측 메뉴 → **API 및 서비스** → **사용 설정**
2. **YouTube Data API v3** 이 **사용 설정** 되어 있는지 확인
   (비활성이면 활성화해야 uploads 가 동작한다)

### Step 4. 다시 인증
```powershell
cd "C:\Users\ROYcp\WorkBuddy\2026-09-18-20-03-59\sns-automation"
.\scripts\youtube_auth.cmd zh-cn
```

## 검증
성공하면 이렇게 나옵니다:
```
[ok] zh-cn 연결 완료 — 채널: shinsegi 中文 (@shinsegi-zh)
     YOUTUBE_ZH_CN_REFRESH_TOKEN 저장됨
```

확인:
```powershell
python scripts/youtube_auth.py status
```

---

## 참고: 403 vs 다른 오류 구분

| 오류 | 의미 | 해결 |
|---|---|---|
| `403 access_denied` + "앱은 테스트 중" | 테스트 사용자 미등록 | 위 Step 2 |
| `youtubeSignupRequired` (401) | 계정 아래에 YouTube 채널 없음 | 채널 생성 후 재인증 |
| `ERR_CONNECTION_REFUSED` | 콜백 서버가 이미 죽음 | 서버를 **먼저** 띄우고 URL을 열 것 (아래) |
| `There is no access token` | 콜백을 받지 못함 (시간 초과) | 30분 안에 완료 or 서버 재시작 |

## `ERR_CONNECTION_REFUSED` 주의 (중국어 건에서 발생)

이건 OAuth 문제가 아니라 **콜백 서버가 죽은 것**이다.
인증 창이 이미 닫혔거나(30분 경과) 프로세스가 끝난 상태에서
브라우저가 URL 을 열면 이 에러가 난다.

**순서:**
1. `.\scripts\youtube_auth.cmd zh-cn` 실행 → **창을 열어둔 채**
2. 표시된 URL 복사
3. **즉시** (30분 이내) 브라우저에서 열기
4. 로그인 → 채널 선택 → 권한 허용
5. "액세스 거부" 화면 → 정상 (서버가 토큰 받음)
6. 창이 자동으로 결과를 표시

## 변경 이력
- 2026-10-08 — 403 access_denied 진단. OAuth 동의 화면이 테스트 상태라
  테스트 사용자 미등록이 원인. Console 에서 게시 상태 변경 또는 계정 추가 필요.