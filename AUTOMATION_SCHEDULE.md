# 우화 쇼츠 자동 발행 — 하루 2회 (2026-10-08 변경)

## 발행 시각

| 시간 (KST) | cron (UTC) | 비고 |
|---|---|---|
| **08:07** | `7 23 * * *` | 오전편 |
| **18:13** | `13 9 * * *` | 오후편 |

> minute 을 0 이 아닌 7 / 13 으로 둔 이유:
> GitHub Actions 스케줄러는 `:00` / `:30` 이 사람이 몰려
> 실행이 대량 지연·폐기(drop)된다. 공식 권장값은 17 / 23 / 37 / 43.

GitHub cron 은 **UTC** 기준이다. KST = UTC+9 이므로 위 변환이 성립한다.

## 동작

```
story.json (명언 → 동물 우화 대본)
    ↓
이미지 10장 (Pollinations flux, 4개 언어 공용)
    ↓
mp4 4개 렌더 (fable_ko / en / zh-cn / fr)
    ↓
IG 릴스 + YouTube 쇼츠 동시 발행
```

### 채널 매핑
| 언어 | YouTube 채널 | 계정 | IG |
|---|---|---|---|
| 한국어 | 지혜의 길 @wisdompathroad | 개인 | shinsegi.kr |
| 영어 | wisdompath @wisdompath-en | 개인 | shinsegi.en |
| 중국어 | shinsegi 中文 @shinsegi-zh | shinsegimedia | shinsegi.zh |
| 프랑스어 | shinsegi Français @shinsegi-fr | shinsegimedia | shinsegi.fr |

## PC 를 꺼도 되는 이유

발행은 **GitHub Actions runner(리눅스 컨테이너)** 에서 실행된다.
로이 PC 는 저장소의 코드만 읽어갈 뿐, 실행에 관여하지 않는다.

실행 환경:
- `TTS_ENGINE=edge` (로컬 모델 없으므로 클라우드 edge-tts 사용)
- ffmpeg + CJK 폰트 자동 설치
- 모든 자격증명은 GitHub Secrets 로 주입

## 재실행해도 중복되지 않는다

단계마다 파일 마커가 있어, 재실행해도 이미 한 건은 건너뛴다.

| 마커 | 의미 |
|---|---|
| `story.json` | 대본 생성 완료 |
| `fable_<lang>.mp4` | 해당 언어 영상 렌더 완료 |
| `published.json` | 해당 언어 발행 완료 |

그래서 **어제 것이 안 됐을 때 같은 커밋을 다시 돌려도**
미발행분만 자동으로 발행된다 (보강 발행).

### 미발행 보강 발행
```bash
python -m src.main run-fable --date 2026-10-07      # 특정 날짜
python -m src.main fable-publish --date 2026-10-07  # 발행만
```

## 수동 발행

GitHub 저장소 → **Actions** → **Fable Production** → **Run workflow**

| 입력 | 값 | 의미 |
|---|---|---|
| `no_publish` | `false` / `true` | `true` 면 제작만(테스트) |
| `date` | `YYYY-MM-DD` | 비우면 오늘(KST) |

API 로도 가능:
```bash
curl -X POST -H "Authorization: token $PAT" \
  -H "Accept: application/vnd.github+json" \
  -H "Content-Type: application/json" \
  https://api.github.com/repos/wndgns032-gif/shinsegi-automation/actions/workflows/fable.yml/dispatches \
  -d '{"ref":"main","inputs":{"no_publish":"false","date":"2026-10-08"}}'
```

## cron 이 안 돌아도 우회 가능 (repository_dispatch)

private 저장소로 되돌리거나 cron 이 비활성화되면 로이 PC 자동화가
이걸 호출하면 된다. **배치 스케줄러를 거치지 않아 즉시 시작**된다.

```bash
curl -X POST -H "Authorization: token $PAT" \
  -H "Accept: application/vnd.github+json" \
  -H "Content-Type: application/json" \
  https://api.github.com/repos/wndgns032-gif/shinsegi-automation/dispatches \
  -d '{"event_type":"daily-fable"}'
```

## 알아둘 것

- **GitHub 스케줄러는 지연한다.** 5~30분 밀릴 수 있고, 시차의 성수기에는
  더 밀릴 수 있다. SLA 는 없다. 08:07 이라면 실제로는 08:07~08:40 사이.
- **오전편이 실패해도 오후편은 돈다.** 두 cron 은 독립적이다.
- **`concurrency` 로 동시 실행을 막는다.** 두 편이 겹쳐도 하나는 대기한다.
- **타임아웃 40분.** 이미지 10장 + 렌더 4개가 오래 걸릴 수 있다.

## 변경 이력
- 2026-10-05 — 하루 1편(19:20) 발행 구축
- 2026-10-06 — fable-publish.yml 을 fable.yml 로 통합
- 2026-10-07 — cron 을 20분 → 17분으로 변경 (스케줄러 혼잡 회피),
  `repository_dispatch` 추가
- 2026-10-08 — **하루 2회(08:07 / 18:13)로 변경** (로이 요청),
  `run-fable --date` 추가