# 우화 쇼츠 자동 발행 — 하루 2회

## 발행 시각

| 시간 (KST) | 내용 |
|---|---|
| **08:07** | 오전편 |
| **18:13** | 오후편 |

PC를 꺼도 발행됩니다 — GitHub 서버에서 실행됩니다.

---

## ⚠️ GitHub cron 장애와 우회 방식

### 무슨 일이 있나

GitHub의 `schedule`(cron) 트리거가 **전 세계적으로 동작하지 않는** 플랫폼
장애가 있습니다 (2026년 8월부터 worldwide 이슈).

- 공개 저장소 / 유료 계정 / 분 슬롯(17분·43분) **모두 무관**
- 결과: `run` 이 아예 생성되지 않음
- 수동 `workflow_dispatch` 는 즉시 실행 → **스케줄러 내부 문제**로 확정
- githubstatus.com 은 Actions 를 정상(operational) 으로 표시 중

우리 저장소의 실측 (`event=schedule` 조회):
```
total_count = 0← public 저장소로 전환 후에도 여전히 0
```

### 해결: 자기 유지형 스케줄러

`.github/workflows/scheduler.yml` — **GitHub Actions 자신이 외부 스케줄러
역할을 맡습니다.** 공식 권장 해결책("외부 스케줄러가 dispatch API 호출")을
GitHub 안에서 구현한 것입니다.

**동작 원리**
1. public 저장소 러너는 최대 **5일** 실행 가능(무료)
2. 60초 간격으로 UTC 시각을 확인하며 루프
3. 슬롯 시각이 되면 `fable.yml` 을 API 로 dispatch
4. 4일 19시간 뒤 **자기 자신을 다시 dispatch** → 무한 재생

**슬롯 정의** (UTC 기준, KST = UTC+9)

| 슬롯 | KST | UTC | 트리거 윈도 |
|---|---|---|---|
| `am` | 08:07 | 23:07 (전날) | 07~42분 |
| `pm` | 18:13 | 09:13 | 13~48분 |

윈도가 35분인 이유: 지연·루프 드리프트를 흡수합니다.

### 중복 발행 방지 (2중 안전장치)

1. 슬롯 처리 이력을 `/tmp/slots.txt` 에 기록 → 당일 재트리거 차단
2. `fable.yml` 의 날짜별 마커(`story.json` / `published.json`) →
   같은 날짜로 중복 dispatch 되어도 중복 발행되지 않음

### 수동으로 스케줄러 켜기 (최초 1회)

GitHub Actions 탭 → **Fable Scheduler** → **Run workflow**

또는 API:
```bash
curl -X POST -H "Accept: application/vnd.github+json" \
  -H "Authorization: token <PAT>" \
  https://api.github.com/repos/wndgns032-gif/shinsegi-automation/actions/workflows/scheduler.yml/dispatches \
  -d '{"ref":"main"}'
```

> 스케줄러는 최대 5일 지속되므로 **5일에 한 번** 위 명령을 반복하면 됩니다.
> (자동 재생이므로 보통은 필요 없습니다)

### `fable.yml` 의 cron 은 남겨둔다

GitHub이 cron을 복구하면 그쪽이 더 단순하게 동작합니다.
둘 다 있어도 **중복 발행되지 않으므로** 그대로 둡니다.

---

## 동작 흐름

```
story.json (명언 → 동물 우화 대본, 지시형 톤)
    ↓
이미지 10장 (Pollinations flux, 4개 언어 공용)
    ↓
mp4 4개 렌더 (fable_ko / en / zh-cn / fr) — 40~60초
    ↓
IG 릴스 + YouTube 쇼츠 동시 발행
```

### 채널 매핑
| 언어 | YouTube 채널 | 계정 | IG |
|---|---|---|---|
| 한국어 | 지혜의 길 `@wisdompathroad` | 개인 | shinsegi.kr |
| 영어 | wisdompath `@wisdompath-en` | 개인 | shinsegi.en |
| 중국어 | shinsegi 中文 `@shinsegi-zh` | shinsegimedia | shinsegi.zh |
| 프랑스어 | shinsegi Français `@shinsegi-fr` | shinsegimedia | shinsegi.fr |

---

## 영상 사양 (확정)

| 항목 | 값 |
|---|---|
| 길이 | **40초 ~ 60초** (자동 조절) |
| 크기 | 1080×1920 (9:16) |
| 스타일 | 애니메이션 흑백 (curves + colorbalance + unsharp) |
| BGM | Pixabay License 무료음원 (낭독 시 자동 덕킹) |
| 자막 | 하단 92px / 명언 96px / 훅 76px |

---

## 재실행해도 중복되지 않는다

단계마다 파일 마커가 있어, 재실행해도 이미 한 건은 건너뛴다.

| 마커 | 의미 |
|---|---|
| `story.json` | 대본 생성 완료 |
| `fable_<lang>.mp4` | 해당 언어 영상 렌더 완료 |
| `published.json` | 해당 언어 발행 완료 |

그래서 **어제 것이 안 됐을 때 같은 커밋을 다시 돌려도**
미발행분만 자동으로 발행됩니다 (보강 발행).

### 보강 발행
```bash
python -m src.main run-fable --date 2026-10-09      # 특정 날짜
python -m src.main fable-publish --date 2026-10-09  # 발행만
```

---

## 수동 발행

GitHub 저장소 → **Actions** → **Fable Production** → **Run workflow**

| 입력 | 값 | 의미 |
|---|---|---|
| `no_publish` | `false` / `true` | `true` 면 제작만(테스트) |
| `date` | `YYYY-MM-DD` | 비우면 오늘(KST) |

---

## 자주 나는 문제

### Q. cron 이 안 도는 것 같아요
→ **정상입니다.** GitHub 플랫폼 장애입니다 (위 참조).
self-sustaining scheduler 가 대신 처리합니다.

### Q. 스케줄러가 멈췄어요 (5일 경과)
→ Actions 탭 → **Fable Scheduler** → **Run workflow** 한 번 클릭.

### Q. 실행이 오래 멈춰 있어요 (20분+)
→ GitHub runner 의 apt 가 느릴 때가 있습니다.
`Install system deps` 단계에서 멈추면 취소 후 다시 실행하세요.
이후에는 timeout 보호 덕분에 길게 정체되지 않습니다.

### Q. 이미지가 평범한 그라디언트예요
→ Pollinations 익명 쿼터(402) 초과입니다. 몇 시간 지나면 회복됩니다.
파이프라인은 폴백 이미지로 계속 진행됩니다.

---

## 변경 이력
- 2026-10-05 — 하루 1편(19:20) 발행 구축
- 2026-10-06 — fable-publish.yml 을 fable.yml 로 통합
- 2026-10-07 — cron 분을 20→17으로 변경, `repository_dispatch` 추가
- 2026-10-08 — 하루 2회(08:07 / 18:13)로 변경, `run-fable --date` 추가
- 2026-10-08 — **GitHub cron 플랫폼 장애 확인** → self-sustaining scheduler 도입,
  영상 길이 40~60초 강제, 지시형 대본톤 적용