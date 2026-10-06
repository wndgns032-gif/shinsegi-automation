# 다국어 SNS 콘텐츠 자동화 (MVP)

한국 커뮤니티 인기글 → DeepSeek 4개 언어 재창작 → 7개 SNS × 4개 언어(28계정) 자동 게시.
PRD: `../PRD_다국어_SNS_콘텐츠_자동화_MVP.md`

## 구조

```
sns-automation/
├── config/
│   ├── sources.yaml      # 크롤링 대상 커뮤니티 (현재 mock 소스만 활성)
│   ├── accounts.yaml     # 플랫폼별 필요한 .env 변수 목록 (문서)
│   └── prompts/          # base.md + 언어별(en/ko/zh-cn/fr).md — 로이 제공 규칙으로 교체
├── src/
│   ├── crawler.py        # 수집 + 조회수 1위 선정(중복 회피)
│   ├── generator.py      # DeepSeek 단일 호출 (키 없으면 목 콘텐츠)
│   ├── cards.py          # Instagram 텍스트 카드 렌더러 (1080x1350, 고정 템플릿)
│   ├── publishers/       # 7개 플랫폼 어댑터 (자격증명 없으면 자동 dry-run)
│   ├── reporter.py       # 성과 Excel (날짜×언어 스냅샷 누적)
│   ├── source_log.py     # 소스 Excel (사이트명/URL 내부 기록)
│   ├── scheduler.py      # KST 06:00/12:00 사이클, 10:00 성과 수집
│   └── main.py           # CLI 엔트리포인트
└── data/                 # Excel, 카드 이미지, errors.log
```

## 실행

```bash
cd sns-automation
PY="C:/Users/ROYcp/.workbuddy/binaries/python/envs/default/Scripts/python.exe"

$PY -m src.main run-cycle --cycle am      # 수집→생성→게시 (오전 사이클)
$PY -m src.main run-cycle --cycle pm      # 오후 사이클 (오전 사용글 자동 회피)
$PY -m src.main collect-metrics           # 성과 수집 → performance.xlsx
$PY -m src.main schedule                  # 상주 스케줄러 (KST 06/12/10시)

$PY -m src.main run-cycle --cycle am --mock   # 목 모드 (API 호출 없이 검증)
```

## 실운영 전환 체크리스트

1. `.env.example` → `.env` 복사 후 `DEEPSEEK_API_KEY` 입력
2. `config/prompts/*.md` 를 로이 제공 말투 규칙으로 교체
3. `config/sources.yaml` 에 실제 커뮤니티 URL + CSS 셀렉터 등록, mock 소스 비활성화
4. 28개 계정 자격증명을 `.env` 에 입력 (없는 계정은 자동 dry-run)
5. Instagram용 `PUBLIC_IMAGE_BASE_URL` 설정 — `data/cards` 디렉터리를 공개 URL로 서빙 필요
   (예: 클라우드 스토리지 동기화 또는 간단한 정적 서버)

## 알려진 제한 / TODO (첫 실사이클 오류 기준으로 보강)

- **성과 수집**: Bluesky·Mastodon만 구현됨. IG/Threads/FB/Pinterest/Telegram 지표는 각 API 권한 확보 후 추가
- **Instagram**: 이미지 공개 URL 필수 (Graph API 제약). Threads는 텍스트라 무관
- **크롤러 시간 파싱**: `YYYY-MM-DD HH:MM` 등 일반 형식만 지원. 사이트별 형식 다륨면 파서 추가
- **재시도 정책 없음**: 실패 시 `data/errors.log` 기록만. 실제 사례 보고 규칙 추가 (PRD 10장)
- **ZH-CN 폰트**: `msyh.ttc`(맑은 고딕 아닌微软雅黑) 사용. 없으면 깨짐 → 중문 폰트 설치 필요
