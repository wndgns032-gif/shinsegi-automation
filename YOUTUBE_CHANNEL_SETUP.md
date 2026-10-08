# YouTube 채널 분리 — 완료 (2026-10-08)

## 최종 상태 (4/4 인증 완료, 검증 통과)

| 언어 | 채널명 | 핸들 | 계정 | 영상수 |
|---|---|---|---|---|
| 한국어 | 지혜의 길 | `@wisdompathroad` | 로이 개인 | 72 |
| 영어 | wisdompath | `@wisdompath-en` | 로이 개인 | 0 |
| 중국어 | shinsegi 中文 | `@shinsegi-zh` | shinsegimedia | 0 |
| 프랑스어 | shinsegi Français | `@shinsegi-fr` | shinsegimedia | 3 |

## 변경 내용

### 계정 분리
```
shinsegimedia@gmail.com  →  중국어(@shinsegi-zh), 프랑스어(@shinsegi-fr)
로이 개인 Gmail          →  한국어(@wisdompathroad), 영어(@wisdompath-en)
```

### GitHub
- 저장소를 **public** 으로 전환 → GitHub Actions cron 활성화
- 시크릿 점검 완료 (시크릿 4개 모두 차단 확인)
- `data/threads_app.json` 시크릿 커밋 이력에서 제거 (git 추적 제외)
- GitHub Secrets **29개 갱신** (EN / ZH_CN 토큰 포함)

### 워크플로
- `fable.yml` cron: `20 10 * * *` → `17 10 * * *`
  (GitHub 스케줄러는 `:00` / `:30` 이 혼잡해 실행이 대량 폐기됨)
- `repository_dispatch` 추가 — private 한계 우회용
  (현재는 public 이라 cron 이 동작하지만, private 로 되돌리면 필요)
- env 블록에 `YOUTUBE_ZH_CN_REFRESH_TOKEN` / `YOUTUBE_EN_REFRESH_TOKEN` 추가
  (secret 을 등록해도 env 로 전달하지 않으면 쓸 수 없었음)

## 과정 중 해결한 문제들

| 문제 | 원인 | 해결 |
|---|---|---|
| cron 이 안 돌았음 | **무료 계정 + private 저장소** 는 schedule 비활성화 | public 전환 |
| 403 access_denied | OAuth 동의 화면이 테스트 상태 | 테스트 사용자에 계정 추가 |
| 127.0.0.1 안 됨 | IPv6(::1) 우선 + `HTTP_PROXY=127.0.0.1:6222` 가 콜백을 빼앗아감 | 프록시 제거 + `run_local_server(host="localhost")` |
| 채널 검증 실패 | YouTube 핸들은 **대소문자를 구분하지 않음** | `_norm_handle()` 로 정규화 |
| 한국어가 계속 중국어로 감 | Google 이 직전 계정(shinsegimedia) 재사용 | 재인증 시 개인 계정 선택 |

## 안전장치 (앞으로 유용)

### 1. 채널 자동 차단
`config/youtube_channels.yaml` 의 `blocked_languages` 로 언어를 차단할 수 있다.
토큰이 다른 채널을 가리킬 때 publisher 가 업로드를 건너뛴다.

```yaml
blocked_languages:
  - ko
```
→ 재인증 성공 시 `youtube_auth.py` 가 자동으로 제거한다.

### 2. 핸들 검증
`expected_handles` 로 채널을 고정한다. 다른 채널에 묶이면 **토큰 저장을 거부**한다.
대소문자는 무시한다 (YouTube 특성).

### 3. config 는 클라우드에서도 읽힌다
`config/youtube_channels.yaml` 가 git 추적 상태라
GitHub Actions runner 도 같은 config 를 읽는다.
→ 차단/검증 로직이 로컬과 클라우드에서 **동일하게** 동작한다.

## 재인증 방법

```powershell
cd "C:\Users\ROYcp\WorkBuddy\2026-09-18-20-03-59\sns-automation"
.\scripts\youtube_auth.cmd ko        # 또는 en / zh-cn / fr
```

또는 `scripts\youtube_auth.cmd` 더블클릭 (기본값 ko).

### 주의
1. **인자를 안 넣으면 ko** 로 실행된다.
2. Google 이 직전 계정을 자동 선택할 수 있다 → **Gmail 주소부터 확인**
3. 계정 선택 화면이 안 뜨면:
   - https://myaccount.google.com/connections 에서 이 앱 권한 삭제
   - 다시 실행 → 반드시 선택 화면이 뜬다
4. **계정 단위 revoke 금지** — 그 계정의 모든 언어 토큰이 죽는다

### 인증 후 반드시
```powershell
python scripts\setup_github_secrets.py
```
새 토큰이 GitHub Secrets 에 올라가지 않으면 클라우드가 옛 토큰으로 업로드한다.

## 진단 도구

```powershell
python scripts\youtube_auth.py status   # 채널 매핑 + 토큰 상태
python scripts\youtube_auth.py plan     # 재인증 플랜
python scripts\diag_localhost.py        # localhost/IPv6/프록시 진단
```

## 변경 이력
- 2026-10-07 20:00 — 채널 재배치 요청, config 분리
- 2026-10-07 21:00 — public 전환 + cron 분기
- 2026-10-08 12:00 — OAuth 403 해결 (테스트 사용자)
- 2026-10-08 12:45 — zh/en/fr 인증 성공
- 2026-10-08 13:55 — ko 인증 성공, **4/4 완료**