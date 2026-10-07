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

> ⚠️ **2026-10-07 실측에서 정정된 중요 원칙**
>
> **프롬프트가 길어질수록 flux 가 "무엇을 그릴지"를 희생한다.**
> 스타일 설명을 길게 쓰면 실제 장면 대신 **추상 패턴·기하학**이 나온다
> (실측: "거북이" → 등껍질 무늬만, "바위 벽을 오르는 두더지" → 타원만).
>
> → **스타일 토큰은 짧게 유지한다. 흑백 통일은 프롬프트가 아니라 후처리가 보장한다.**

`STYLE_PREFIX` — 모든 장면 프롬프트 맨 앞에 붙인다:

```
black and white pencil drawing, monochrome, graphite sketch,
hand-drawn line art, no color, no border, no frame, no text
```

`STYLE_SUFFIX` — 모든 장면 프롬프트 맨 뒤에 붙인다:

```
monochrome, grayscale, no color, no frame, no border, no text,
no watermark, simple background, subject clearly visible,
full-bleed scene, edge to edge
```

### 조립 순서 — 이것도 중요하다 (실측)
```
STYLE_PREFIX , <장면 묘사> , <characters> , STYLE_SUFFIX
                  ↑ 먼저        ↑ 뒤에
```
`characters`(주인물 묘사)를 **앞에** 넣으면 flux 가 클로즈업 얼굴에 고정돼
장면이 사라진다(바위만 꽉 찬 화면이 실제로 나왔음). **장면 묘사가 먼저, 캐릭터는 뒤.**

### 왜 짧게만 쓰나 — 각 어휘의 역할
- `pencil drawing` / `graphite sketch` → **재질(매체)** 을 하나로 고정
- `monochrome / grayscale / no color` → **색을 차단** (백업: 후처리)
- `no border / no frame` → 액자 방지 (백업: 9% 크롭)
- `subject clearly visible` → 클로즈업 과다 방지
- 긴 형용사 나열(`soft crosshatching shading, vintage etching print, ...`)은 **역효과** — 제거함

---

## 3. 주인공 일관성

- 주인공은 **영어 외형 한 줄**로만 (`characters`) 정의하고 모든 장면에 동일 문자열로 삽입.
- 模型이 매번 다른 동물을 그리면 안 되므로, 묘사는 **구체적 3요소**로 적는다:
  - `종명` (a small gray mole)
  - `의상/특징` (with tiny round glasses and a stubby shovel)
  - `크기감` (tiny / small / chubby / elderly …) — **형용사로만**
- ⚠️ **크기를 비교 표현으로 쓰지 말 것** — `about the size of a teacup` 처럼 비교 대상을 넣으면
  모델이 **그 물체를 그린다** (실제로 두더지 프롬프트에서 사람 얼굴이 나왔던 사례).
- **장르를 넘지 않는다.** 예: "an old wise owl" 라고 썼는데 우유곰이 나오면 안 된다.
- `real` 장면(현실 대입)은 **동물을 쓰지 않는다.** 이때는 `characters` 삽입을 건너뛴다.
  - 지금 코드가 모든 장면에 동물을 넣어서 "회사원 + 거북이" 같은 화면이 나온다.
  - **개정: `characters`는 quote/hook/fable/outro 에만 삽입, real 은 제외.**

## 3-2. 캐릭터 일관성 (2026-10-07 실측 + 로이 승인)

flux(stable)는 **캐릭터를 한 번만 언급하면 다른 동물/사람으로 그린다.**
실측: 두더지 우화 10장면 중 몇 장이 여우·사람으로 나옴. 프롬프트 단독으로는 100% 불가.

### 코드 측 대응 (구현됨)
1. `characters` 를 **프롬프트 앞뒤로 중복 삽입**:
   ```
   STYLE_PREFIX, <characters>, <장면 묘사>, <characters>,
   same character as every other scene, STYLE_SUFFIX
   ```
   캐릭터 중요도를 flux 가 무시하지 못하게 한다.
2. **자동 검수 후 재생성** (`scripts/check_fable_images.py --regen`)
   - 해상도/크기 편차 · 채도 · 휘도(자막 가독성) · 파일 크기를 **코드로 판정**
   - 실패 장면만 **다른 seed** 로 재생성 (같은 seed = 같은 그림이라 반드시 seed 변경)
   - `fablevideo.make_fable()` 에 자동 연결 — 첫 언어(ko)에서 1회만, 4개 언어가 이미지 공유

> 남는 한계: 장면의 "내용 부적합"(예:主角이 사람으로 나옴)은 픽셀 통계로 검출되지 않는다.
> 완전 자동 판정은 불가능하며, 검수는 색/크기/밝기 같은 **물리적 부조절**만 잡는다.

## 3-3. 액자 테두리 함정 (2026-10-07 실측)

- `vintage etching print` / `storybook print` 같은 표현을 넣으면 모델이 **액자·매트·벽화 액자**를 그리며
  화면 가장자리를_frames 로 감싼다. 프롬프트에 `no frame` 을 넣어도 효과가 제한적이라
  **후처리 크롭(`_to_monochrome` 의 9% each edge crop) 으로 제거**한다.
- 액자를 유발하는 단어는 프롬프트에서 빼는 게 좋다: `etching print`, `framed`, `portrait print`.
- 대신 형태/재질 어휘로 통일: `hand-drawn graphite line art with soft crosshatching shading`.

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
**이 단계가 "통일성"의 최종 보장**이다. 프롬프트는 그림을 유도할 뿐, 통일은 여기서 한다.

1. **액자/매트 9% 크롭** — 모델이 'vintage etching' 을 요구하면 액자·테두리·점형 여백을
   그리므로 가장자리 9%씩 잘라낸다(576x1024 → 474x840).
2. `ImageOps.grayscale()` — 완전한 흑백.
3. `ImageOps.autocontrast(cutoff=1)` — 장면별 명도 차이 흡수(어두운 장면/밝은 장면 격차 축소).
4. `ImageEnhance.Contrast(1.08)` — 평평해진 회색 방지.
5. 미세한 **세피아 톤**(R=G+6, B=G−6 정도) — 완전히 기계적인 그레이가 아니라
   "양피지 같은 따뜻한 흑백" 느낌. **흑백 느낌** 요구를 만족시키면서 인쇄물의 질감을 살린다.
6. 크롭은 기존대로.

> 이 덕분에 ① 프롬프트를 무시하는 모델이거나 폴백 이미지도 최종적으로 같은 톤이 된다.
> **주의**: 1번 크롭은 idempotent 하지 않다(적용할 때마다 9%씩 줄어든다).
> 캐시된 이미지에 재적용하지 말 것 — 신규 생성분에만 적용.

---

## 6. 금지 (프롬프트에 절대 넣지 말 것)

- ❌ 색 지정 (`golden light`, `warm muted colors`, `blue sky`, `snow-white fur` 등)
- ❌ 사진/3D/렌더링 표현 (`photorealistic`, `3D render`, `octane render`)
- ❌ 텍스트 (`text`, `letters`, `title`, `caption`, `watermark`)
- ❌ 여러 화자가 한 화면 (`two animals talking`) —主角 1마리만
- ❌ 화면 텍스트 공간을 비워두라는 지시 (렌더러가 자막을 올리므로 오히려 방해)
