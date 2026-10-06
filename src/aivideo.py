"""AI 영상 클립 생성 — MiniMax H3 계열 **무료 HuggingFace ZeroGPU 스페이스** 폴백 체인.

역할: 기존 "정지 이미지 + 카메라 무빙" 장면을 **실제 움직이는 AI 클립**으로 보강하는
선택적 레이어. 여러 무료 스페이스를 순서대로 시도하고, 전부 실패하면 None 을 돌려준다.
호출부(shortform.build_clip)는 None 이면 기존 무료 모션(켄번스/크로스페이드)으로 폴백한다.
→ 이 모듈이 망가져도 숏폼 파이프라인은 절대 중단되지 않는다.

2026-09-21 검증 근거:
  · MiniMax H3 = 영상+사운드 동시 생성, 24fps / 4~15초 / 한국어 포함 11개 언어.
  · 무료 스페이스들은 ZeroGPU(a10g)에서 실행되며 Gradio API 로 비동기 호출 가능.
  · 한계 ① 비로그인 쿼터는 매우 작음 → HF_TOKEN(무료 계정) 있으면 할당량 증가
    한계 ② 큰 캔버스는 "ZeroGPU illegal duration" 거절 → 작은 캔버스로 자동 폴백
  · 라이선스: H3 **가중치 자체 호스팅**은 한국·EU·영국·미국 제외.
    여기서는 호스티드 데모(서비스)를 호출만 하고 가중치를 내려받지 않는다.

설계: 스페이스마다 /generate 파라미터 시그니처가 다르므로,
      /gradio_api/info 를 읽어 **라벨 키워드로 인자를 자동 매핑**한다.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

# ── 무료 스페이스 후보 (앞에서부터 시도) ────────────────────────
# 모두 MiniMax H3 계열 데모. 2026-09-21 실측:
#   · multimodalart/minimax-h3        : 익명 제출 수락(하트비트) → 실질적으로 유일한 무료 경로
#   · MiniMaxAI / akhaliq             : ZeroGPU 풀 혼잡 시 "at capacity" 일시 거절
#   · hugging-apps/…-flashgen-4step   : 익명 쿼터 소진 → HF_TOKEN 필요
#   · observantdistressed/…           : dataframe 컴포넌트 필요 → 제외
SPACES = [
    "multimodalart/minimax-h3",
    "MiniMaxAI/MiniMax-H3-Turbo-Lora",
    "akhaliq/MiniMax-H3-Turbo-Lora",
    "hugging-apps/minimax-h3-flashgen-4step",
]
ENDPOINT_PREF = ("/generate", "/generate_submit", "/output_video")

# Canvas 가 자유 입력(Textbox)이지만 내부에서 목록 검증하는 스페이스용 폴백.
# (enum 이 비어 있을 때 이 값을 사용 — 실측 에러 메시지의 허용 목록과 동일)
KNOWN_CANVAS = [
    "960x544 · 16:9 fast", "1024x576 · 16:9 fast", "1152x640 · 16:9",
    "544x544 · 1:1 fast", "768x576 · 4:3 fast",
]
DEFAULT_CANVAS = KNOWN_CANVAS[0]

DEFAULT_DURATION = 4          # 초 (무료 티어 예산상 짧게 뽑고 루프로 채운다)
DEFAULT_STEPS = 20
SUBMIT_TIMEOUT = 45
POLL_TIMEOUT = 1500           # 스트림 1회 최대 25분 (ZeroGPU 대기열 포함)
TOTAL_BUDGET = 1200           # gen_clip 전체 예산(초) — 초과하면 남은 스페이스는 건너뛴다
INFO_TTL = 6 * 3600           # 스페이스 시그니처 캐시(초)

_SPEC_CACHE: dict[str, dict | None] = {}


def enabled() -> bool:
    """환경변수로 켜짐 여부.

    off/0/false  = 끔
    on/1/true    = 토큰 없이도 익명 시도
    anon         = on 과 동일 (명시적)
    auto(기본)   = HF_TOKEN 이 있을 때만 시도
    """
    mode = _env("SHORTFORM_AI_CLIPS", "auto").lower()
    if mode in ("off", "0", "false", "none"):
        return False
    if mode in ("on", "1", "true", "always", "anon"):
        return True
    return bool(_env("HF_TOKEN"))


def _env(key: str, default: str = "") -> str:
    import os
    return os.getenv(key, default) or default


def _host(space_id: str) -> str:
    return "https://" + space_id.replace("/", "-").replace("_", "-").lower() + ".hf.space"


def _headers(space_host: str = "") -> dict:
    h = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    tok = _env("HF_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


# ─────────────────────────────────────────────────────────────
# 스페이스 시그니처 조회 + 인자 자동 매핑
# ─────────────────────────────────────────────────────────────
def _enum_of(param: dict) -> list:
    for key in ("python_type", "type"):
        v = param.get(key)
        if isinstance(v, dict):
            for k2 in ("enum", "choices", "options"):
                if isinstance(v.get(k2), list):
                    return v[k2]
    for k2 in ("choices", "enum"):
        if isinstance(param.get(k2), list):
            return param[k2]
    return []


def _spec(space_id: str) -> dict | None:
    """{'host':..., 'endpoint':..., 'params':[{label, type, minimum, maximum, enum}]}"""
    now = time.time()
    c = _SPEC_CACHE.get(space_id)
    if c and c.get("_at", 0) + INFO_TTL > now:
        return c.get("spec")
    host = _host(space_id)
    spec = None
    try:
        d = requests.get(host + "/gradio_api/info",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=35).json()
        eps = d.get("named_endpoints", {}) or {}
        for want in ENDPOINT_PREF:
            if want in eps:
                params = []
                for p in eps[want].get("parameters", []):
                    label = p.get("label") or p.get("parameter_name") or ""
                    params.append({
                        "label": str(label),
                        "lower": str(label).lower(),
                        "min": p.get("minimum"),
                        "max": p.get("maximum"),
                        "default": p.get("parameter_default"),
                        "enum": _enum_of(p),
                    })
                spec = {"host": host, "endpoint": want, "params": params}
                break
    except Exception:  # noqa: BLE001
        spec = None
    _SPEC_CACHE[space_id] = {"spec": spec, "_at": now}
    return spec


def _pick_canvas(enum: list) -> str | None:
    """우리 밴드(1.5:1)에 가장 가깝고 ZeroGPU 예산 안에 드는 캔버스 선택.

    우선순위: fast/turbo(증류 모델 = GPU 시간 절반 이하) > 비율 1.5 근접 > 작은 면적.
    2026-10-03 실측: 스페이스에 4:3 가로 옵션(768x576 fast 등)이 생겨서
    16:9 우선이던 기존 스코어를 실제 비율 거리 기반으로 교체.
    """
    if not enum:
        return None
    def score(s: str) -> tuple:
        t = str(s).lower()
        fast = 1 if ("fast" in t or "turbo" in t) else 0
        m = __import__("re").search(r"(\d{3,4})\s*x\s*(\d{3,4})", t)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            dist = abs(w / h - 1.5)
            area = w * h
        else:
            dist, area = 9.9, 9_999_999
        return (fast, -dist, -area)
    return sorted((str(x) for x in enum), key=score, reverse=True)[0]


def _build_args(spec: dict, prompt: str, seed: int, duration: int, steps: int) -> list | None:
    """라벨 키워드로 인자 자동 매핑. prompt 를 못 찾으면 None."""
    args: list = []
    has_prompt = False
    for p in spec["params"]:
        lo = p["lower"]
        if "prompt" in lo and "upsample" not in lo and "enhance" not in lo and not has_prompt:
            args.append(prompt)
            has_prompt = True
        elif "first" in lo and "frame" in lo:
            args.append(None)
        elif "last" in lo and "frame" in lo:
            args.append(None)
        elif "canvas" in lo or "resolution" in lo or "size" in lo:
            # 드롭다운(enum)이면 최적 옵션, 자유 입력(Textbox)이면 기본 문자열
            args.append(_pick_canvas(p["enum"]) or DEFAULT_CANVAS)
        elif "duration" in lo or ("length" in lo and "sound" not in lo):
            args.append(duration)
        elif "step" in lo:
            args.append(steps)
        elif "seed" in lo:
            args.append(seed)
        elif "turbo" in lo:
            args.append(True)          # 7-step LoRA → 빠르고 저예산
        elif "upsample" in lo or "enhance" in lo or "match" in lo:
            args.append(False)
        elif "lora" in lo or "style" in lo or "reference" in lo or "voice" in lo \
                or "music" in lo or "scene" in lo or "motion" in lo or "subject" in lo:
            args.append(None)
        else:
            args.append(None)
    return args if has_prompt else None


# ─────────────────────────────────────────────────────────────
# 생성
# ─────────────────────────────────────────────────────────────
def _download(url_or_path: str, host: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        u = url_or_path if url_or_path.startswith("http") else f"{host}/gradio_api/file={url_or_path}"
        r = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=180, stream=True)
        if not r.ok:
            return False
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
        return dest.exists() and dest.stat().st_size > 20000
    except Exception:  # noqa: BLE001
        return False


def _first_video(data) -> str | None:
    if not data:
        return None
    if isinstance(data, dict):
        for k in ("url", "path", "video"):
            v = data.get(k)
            if isinstance(v, str) and v.endswith((".mp4", ".webm", ".mov")):
                return v
            if isinstance(v, dict):
                got = _first_video(v)
                if got:
                    return got
        return None
    if isinstance(data, list):
        for item in data:
            got = _first_video(item)
            if got:
                return got
    if isinstance(data, str) and data.endswith((".mp4", ".webm", ".mov")):
        return data
    return None


def gen_clip(prompt: str, dest: Path, *, duration: int = DEFAULT_DURATION,
             steps: int = DEFAULT_STEPS, seed: int | None = None,
             spaces: list[str] | None = None) -> tuple[Path | None, str]:
    """한 장면용 AI 클립 생성. 성공 시 (경로, 'space@endpoint'), 실패 시 (None, 사유).

    TOTAL_BUDGET(기본 20분) 안에서 여러 무료 스페이스를 순차 시도한다.
    예산을 넘기면 남은 스페이스는 건너뛰고 즉시 폴백 — 파이프라인 지연을 막는다.
    """
    seed = seed if seed is not None else int(time.time()) % 100000
    try:
        budget = float(_env("SHORTFORM_AI_CLIP_BUDGET", str(TOTAL_BUDGET)))
    except ValueError:
        budget = TOTAL_BUDGET
    deadline = time.time() + budget
    reasons: list[str] = []
    for space_id in (spaces or SPACES):
        if time.time() > deadline:
            reasons.append(f"예산 {budget:.0f}s 초과 — 남은 스페이스 건너뜀")
            break
        spec = _spec(space_id)
        if not spec:
            reasons.append(f"{space_id}: 스펙 조회 실패")
            continue
        args = _build_args(spec, prompt, seed, duration, steps)
        if args is None:
            reasons.append(f"{space_id}: prompt 파라미터 없음")
            continue
        host, ep = spec["host"], spec["endpoint"]
        try:
            r = requests.post(host + f"/gradio_api/call{ep}", headers=_headers(host),
                              json={"data": args}, timeout=SUBMIT_TIMEOUT)
            if not r.ok:
                reasons.append(f"{space_id}: HTTP {r.status_code}")
                continue
            event_id = (r.json() or {}).get("event_id")
            if not event_id:
                reasons.append(f"{space_id}: event_id 없음")
                continue
        except Exception as e:  # noqa: BLE001
            reasons.append(f"{space_id}: submit {type(e).__name__}")
            continue

        try:
            with requests.get(f"{host}/gradio_api/call{ep}/{event_id}",
                              headers=_headers(host), stream=True, timeout=POLL_TIMEOUT) as resp:
                event = ""
                for raw in resp.iter_lines(decode_unicode=True):
                    if raw is None:
                        continue
                    line = raw.strip()
                    if line.startswith("event:"):
                        event = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        payload = line.split(":", 1)[1].strip()
                        if event in ("error", "failed"):
                            try:
                                msg = json.loads(payload).get("error") or payload
                            except Exception:  # noqa: BLE001
                                msg = payload
                            reasons.append(f"{space_id}: {str(msg)[:90]}")
                            break
                        if event == "complete":
                            try:
                                data = json.loads(payload)
                            except Exception:  # noqa: BLE001
                                data = None
                            got = _first_video(data)
                            if not got:
                                reasons.append(f"{space_id}: 결과에 영상 없음")
                                break
                            if _download(got, host, dest):
                                return dest, f"{space_id}{ep}"
                            reasons.append(f"{space_id}: 다운로드 실패")
                            break
                else:
                    reasons.append(f"{space_id}: 스트림 종료(결과 없음)")
        except Exception as e:  # noqa: BLE001
            reasons.append(f"{space_id}: poll {type(e).__name__}")
    return None, " | ".join(reasons)[:400] or "unknown"
