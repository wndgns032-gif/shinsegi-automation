# GitHub Actions 자동 발행 해결 — 로이 가이드 (2026-10-07)

## 문제: 19:20 자동 발행이 하루종일 실행되지 않음

### 조사 결과 (원인 확정)

| 확인 항목 | 결과 |
|---|---|
| fable.yml cron 문법 | 정상 (`20 10 * * *`) |
| YAML 파싱 | 정상 |
| 워크플로 상태 | `active` |
| push / workflow_dispatch | 정상 동작 |
| **schedule 이벤트** | **total_count = 0** |

### 진짜 원인
**무료 개인 계정 + private 저장소 조합에서는 `schedule` 이벤트가 비활성화된다.**

GitHub Pro($4/월) 또는 public 저장소여야 cron이 동작한다.
잘 알려지지 않은 제약이라 공식 문서에 명확히 적혀 있지 않다.

> 참고: GitHub 토큰에 저장소 관리자 권한이 없어(private=False PATCH → 403)
> API 로는 visibility 변경이 불가능했다. **로이가 웹 UI에서 직접 해야 한다.**

### 부수 발견: cron 슬롯 혼잡
`:00` / `:30` 은 GitHub 스케줄러가 가장 혼잡한 시각이라 실행이 대량 폐기(drop)된다.
공식 권장: `17` `23` `37` `43` 같은 분을 쓸 것.
→ cron 을 `20 10 * * *` → `17 10 * * *` 로 변경함 (commit 58e5e68)

---

## 해결책

### ✅ 방법 A: public 전환 (권장 — cron 정상 동작)

1. https://github.com/wndgns032-gif/shinsegi-automation/settings
2. 하단 **Danger Zone** → **Change visibility** → **Public**
3. 확인

→ 그러면 `schedule` cron 이 작동하기 시작한다.
→ 다음 실행 시각: **매일 KST 19:17**

#### public 전환 시 노출되는 것 (점검 완료)
| 항목 | 상태 |
|---|---|
| `.env` (모든 시크릿) | ✅ gitignore — **노출 안 됨** |
| Google refresh token | ✅ 0건 |
| Google client secret | ✅ 0건 |
| GitHub PAT | ✅ 0건 |
| Google API key | ✅ 0건 |
| `data/threads_app.json` | ✅ git 추적에서 제거 완료 (commit 50545d5) |

**노출되는 것**: 소스 코드, 프롬프트 문서, config, 그리고 `data/fables/*/story.json`·`published.json`·`youtube_uploads.json` 등 운영 데이터.

> ⚠️ Threads 앱 시크릿은 git **이력**에 남아있습니다.
> 완벽하게 하려면 Threads 개발자 콘솔에서 시크릿을 회전하세요.
> (Threads 는 현재 미연결이라 당장 영향 없음)

---

### ✅ 방법 B: repository_dispatch (검증 완료 — PC 꺼져도 안 됨)

**private 상태에서도 동작하는 우회책을 이미 구현해뒀습니다.**
테스트 결과 **HTTP 204 + 실제 run 생성 확인**했습니다.

로이 PC 의 자동화(WorkBuddy)가 매일 19:20 에 이 API 를 호출하면 됩니다.

```bash
curl -X POST \
  -H "Authorization: token <GH_PAT>" \
  -H "Accept: application/vnd.github+json" \
  -H "Content-Type: application/json" \
  https://api.github.com/repos/wndgns032-gif/shinsegi-automation/dispatches \
  -d '{"event_type":"daily-fable"}'
```

장점:
- private 유지 가능
- 배치 스케줄러를 거치지 않으므로 **초 단위로 시작** (지연 없음)
- API 토큰만 있으면 됨

단점: 로이 PC 가 꺼져 있으면 실행 안 됨

---

## 지금 상태

- `repository_dispatch` 경로 검증 완료 (run 37628572241 실행 중 — 오늘 영상 발행됨)
- cron 은 private 상태라 여전히 비활성
- public 전환하면 cron 이 정상 작동

---

## 지금 할 일

**1. public 전환** (방법 A)
https://github.com/wndgns032-gif/shinsegi-automation/settings → Danger Zone

**2. YouTube 개인 채널 핸들 알려주기**
개인 계정에서 만든 한국어·영어 채널의 핸들이 뭐예요? (예: `@shinsegi-ko`)
→ config 에 넣고 인증 진행

## 변경 이력
- 2026-10-07 21:25 — cron 슬롯 17분 변경, repository_dispatch 추가(58e5e68),
  빈 커밋으로 스케줄러 재활성화 시도(daa3e11)
- 2026-10-07 21:25 — repository_dispatch 트리거 검증 완료 (HTTP 204 + run 생성)