# YouTube 채널 인증 — 실행 방법 (중요)

## ⚠️ 왜 로이가 직접 실행해야 하나

이 프로젝트의 자동화는 **샌드박스(격리된 네트워크)에서 실행**된다.
Google OAuth 는 인증 후 `http://127.0.0.1:<port>` 로 콜백을 보내는데,
샌드박스 안에서 띄운 서버에는 **로이의 브라우저가 접근할 수 없다.**

실측 확인:
- 샌드박스 안에서 서버는 정상 동작 (자기 자신 접속 200 OK)
- 그런데 로이의 브라우저가 열었을 때 콜백이 오지 않음 (20분 대기 후 타임아웃)
- 샌드박스를 경유해 실행하는 모든 방법이 차단됨
  (PowerShell Start-Process / cmd.exe / Start-Job / [Diagnostics.Process]::Start)

→ **로이의 PC 에서 직접 실행하는 방법만이 확실히 동작한다.**
→ 그래서 `scripts\youtube_auth.cmd` 를 만들었다.

---

## 실행 방법 (1개씩)

### 1. 파일 더블클릭
```
scripts\youtube_auth.cmd
```
더블클릭하면 `ko` 인자로 실행된다. 인자를 바꾸려면 PowerShell 에서:

### 2. PowerShell 에서 (언어 지정)
```powershell
cd "C:\Users\ROYcp\WorkBuddy\2026-09-18-20-03-59\sns-automation"
.\scripts\youtube_auth.cmd ko
```

순서대로 실행:
```powershell
.\scripts\youtube_auth.cmd zh-cn   # 1) shinsegimedia -> @shinsegi-zh
.\scripts\youtube_auth.cmd ko      # 2) 개인 계정   -> @WisdomPathroad
.\scripts\youtube_auth.cmd en      # 3) 개인 계정   -> @wisdompath-en
```

**절대 한 번에 여러 언어를 실행하지 마라** (계정이 섞인다).

---

## 창이 열리면

1. URL 이 표시됨 → **브라우저 주소창에 붙여넣기**
2. **계정을 먼저 선택** (Google 이 직전 계정을 자동 선택할 수 있음)
3. 그 다음 채널 선택
4. "권한 허용" 클릭
5. **"액세스 거부(Access blocked)" 화면이 뜬다 → 이게 정상입니다**
   (성공했다는 뜻. 로컬 서버가 토큰을 받은 뒤 원래 페이지로 못 돌아가는 것)
6. 창이 자동으로 닫히며 결과 표시

### 계정 선택 요약

| 언어 | Google 계정 | 채널 |
|---|---|---|
| zh-cn | **shinsegimedia** | `@shinsegi-zh` |
| ko | **로이 개인 계정** | `@WisdomPathroad` |
| en | **로이 개인 계정** | `@wisdompath-en` |
| fr | **shinsegimedia** | `@shinsegi-fr` |

> 잘못된 채널을 고르면 토큰 저장을 **거부**한다 (안전장치).
> `expected_handles` 가 config 에 설정돼 있음.

---

## 주의: 계정 단위 revoke 금지

`myaccount.google.com/connections` 에서 앱 권한을 삭제하면
**그 계정의 모든 언어 토큰이 한꺼번에 죽는다.**
언어 하나만 바꾸려면 그 언어만 재인증한다.

Google 이 직전 계정을 재사용하는 경우:
1. https://myaccount.google.com/connections
2. 해당 앱 권한 삭제
3. `.\scripts\youtube_auth.cmd ko` 다시 실행 → 선택 화면이 반드시 뜬다

---

## 완료 후 확인

```bash
python scripts/youtube_auth.py status
```

각 언어가 어느 채널에 붙었는지 표시된다.
인증에 성공하면 `blocked_languages` 에서 해당 언어가 **자동 제거**된다.

---

## 참조: 직접 python 을 쓸 수도 있다

```powershell
$env:YT_NO_BROWSER="1"
$env:YT_AUTH_TIMEOUT="1800"
& "C:\Users\ROYcp\.workbuddy\binaries\python\envs\default\Scripts\python.exe" `
    -u scripts\youtube_auth.py ko
```

## 변경 이력
- 2026-10-07 22:50 — cmd 배치 추가. 샌드박스 경유 실행이 전부 차단되어
  로이 PC 직접 실행 방식이 유일한 해법임을 확인(20분 대기 후에도 콜백 미수신 실측).