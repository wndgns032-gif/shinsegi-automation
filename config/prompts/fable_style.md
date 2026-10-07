# Fable Image Style — 이미지 통일 규칙 (v1, 2026-10-07)

로이 지시: "영상에 나오는 이미지가 통일적이지 않아, 흑백 느낌으로 통일성 있게 해줘"

10장면이 **하나의 영상**으로 보여야 한다. 색, 재질, 조명, 화면 구도가 다르면
시청자는 "다른 영상이 이어지는 것"으로 느낀다. 여기선 **흑백(한 가지 색상 없음)** 으로
통일해 시선을 텍스트와 내레이션에 집중시키며, "한 권의 그림책" 같은 톤을 만든다.

---

## 1. 두 단계 전략

| 단계 | 방법 | 역할 |
|---|---|---|
| ① 프롬프트 | 아래 스타일 블록을 모든 장면에 강제 삽입 | 모델이 처음부터 흑백/같은 재질로 그리게 함 |
| ② 후처리 | `fablevideo._to_monochrome()` — PIL로 전 장면 그레이스케일 + 톤 커브 | 모델이 무시해도 **결과는 100% 흑백으로 통일** |

②가 최종 보장이므로, ①은 "아름다운 흑백"을 얻기 위한 수단이고 ②는 "일관성"의 수단이다.

---

## 2. 스타일 블록 (모든 장면에 동일 삽입)

`STYLE_PREFIX` — 모든 장면 프롬프트 맨 앞에 붙는다:

```
black and white pencil sketch illustration, monochrome, grayscale only,
hand-drawn graphite line art with soft crosshatching shading, vintage
storybook etching print, consistent medium and line weight across the
whole series
```

`STYLE_SUFFIX` — 모든 장면 프롬프트 맨 뒤에 붙는다:

```
strictly monochrome, no color, no hue, no tint, desaturated, grayscale,
soft even diffused light, gentle vignette darkening at the corners,
simple uncluttered background, subject centered, medium shot,
no text, no letters, no numbers, no watermark, no logo, no signature
```

### 왜 이런 단어들을 쓰는가
- `pencil sketch` + `graphite` + `etching print` → **재질(매체)** 을 하나로 고정
- `monochrome / grayscale only / no color / no hue` → **색을 차단**
- `consistent line weight` → 선 굵기가 달라서 생기는 "다른 만화 같은 느낌" 제거
- `soft even diffused light` → 조명 방향이 매 장면 바뀌는 문제 제거
- `medium shot, subject centered` → 원거리/근거리/사면이 제각각인 문제 제거

---

## 3. 주인공 일관성

- 주인공은 **영어 외형 한 줄**로만 (`characters`) 정의하고 모든 장면에 동일 문자열로 삽입.
- 模型이 매번 다른 동물을 그리면 안 되므로, 묘사는 **구체적 3요소**로 적는다:
  - `종명` (a small green turtle)
  - `의상/특징` (with a tiny blue backpack)
  - `크기감` (tiny, chubby, elderly …)
- **장르를 넘지 않는다.** 예: "an old wise owl" 라고 썼는데 우유곰이 나오면 안 된다.
- `real` 장면(현실 대입)은 **동물을 쓰지 않는다.** 이때는 `characters` 삽입을 건너뛴다.
  - 지금 코드가 모든 장면에 동물을 넣어서 "회사원 + 거북이" 같은 화면이 나온다.
  - **개정: `characters`는 quote/hook/fable/outro 에만 삽입, real 은 제외.**

---

## 4. act 별 이미지 지침 (모델에게 넘길 내용)

- `quote` — 명언의 **분위기만** 담은 고요한 장면. 주인공이 작게, 한 구석에. 텍스트는 렌더러가 올린다.
- `hook` — 주인공이 상황 앞에 서 있는 실루엣. 긴장감. 클로즈업 금지(전신 70%).
- `fable` ×5 — **하나의 연속된 이야기.** 이 5장에선主角의 **위치·동작·시간대가 이어져야 한다.**
  - 시간대 고정(아침빛 → 낮 → 저녁 → 밤 등 5단계로 점진 변화만 허용)
  - 카메라 각도 고정(같은 3/4 측면 시점)
- `real` ×2 — 동물을 **힌트로만** 쓸 수 있다(예: 거북이 모양의 인형, 그림자). 주인공은 사람.
  - 또는 동물 없이 인간 장면만.
- `outro` — 정상/출구/먼 곳을 바라보는 조용한 장면. `fable` 의 5번째 장면과 **배경을 이어받는다.**

---

## 5. 후처리(`_to_monochrome`)가 하는 일

`fablevideo.py` 에서 Pollinations 이미지를 받은 직후, 저장 직전에 실행한다.

1. `ImageOps.grayscale()` — 완전한 흑백.
2. `ImageEnhance.Contrast(1.08)` — 평평해진 회색 방지.
3. `ImageOps.autocontrast(cutoff=1)` — 장면별 명도 차이 흡수(어두운 장면/밝은 장면 격차 축소).
4. 미세한 **세피아 톤**(R=G+8, B=G−6 정도) — 완전히 기계적인 그레이가 아니라
   "양피지 같은 따뜻한 흑백" 느낌. **흑백 느낌** 요구를 만족시키면서 인쇄물의 질감을 살린다.
5. 크롭은 기존대로.

> 이 덕분에 ① 프롬프트를 무시하는 모델이거나 폴백 이미지도 최종적으로 같은 톤이 된다.

---

## 6. 금지 (프롬프트에 절대 넣지 말 것)

- ❌ 색 지정 (`golden light`, `warm muted colors`, `blue sky`, `snow-white fur` 등)
- ❌ 사진/3D/렌더링 표현 (`photorealistic`, `3D render`, `octane render`)
- ❌ 텍스트 (`text`, `letters`, `title`, `caption`, `watermark`)
- ❌ 여러 화자가 한 화면 (`two animals talking`) —主角 1마리만
- ❌ 화면 텍스트 공간을 비워두라는 지시 (렌더러가 자막을 올리므로 오히려 방해)
