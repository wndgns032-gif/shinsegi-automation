"""HuggingFace 무료 계정 + 액세스 토큰 설정 (2026-09-22 정비).

무료 ZeroGPU 쿼터로 shortform AI 클립(src/aivideo.py)을 쓰기 위한 준비.

사용법:
  python scripts/hf_setup.py open     # 창 띄우기 → 사람이 가입/CAPTCHA → 로그인 감지 시 토큰까지 자동
  python scripts/hf_setup.py token    # 로그인 상태에서 토큰만 발급
  python scripts/hf_setup.py save hf_xxx   # 토큰을 .env 에 기록
  python scripts/hf_setup.py status   # 로그인 여부 확인

설계 메모:
- 세션은 data/_hfprofile (Chrome 전용 프로필) 에 유지된다. → 재실행해도 로그인 유지
- 이미지 CAPTCHA 는 자동 우회하지 않는다. 창을 띄워 두고 사람이 푼다.
- 로그인 감지 후에는 https://huggingface.co/settings/tokens/new?tokenType=read 로 이동해
  read 토큰을 만들고 .env 의 HF_TOKEN 에 자동 기록한다.
"""
from __future__ import annotations

import json
import re
import secrets
import string
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent          # sns-automation/
DATA = ROOT / "data"
PROFILE = DATA / "_hfprofile"
ACCOUNT = DATA / "hf_account.json"
ENV_PATH = ROOT / ".env"

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]
EMAIL = "xkyb9964@agent.qq.com"      # 에이전트 메일(확인 메일 수신용)
WAIT_LOGIN_SEC = 1800                # 사람이 가입+메일확인 마칠 때까지 최대 30분 대기
TOKEN_NAME = "shinsegi-zero-gpu"


# ────────────────────────────── helpers ──────────────────────────────
def chrome() -> str:
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    raise SystemExit("Chrome/Edge 를 찾을 수 없음")


def load_account() -> dict:
    if ACCOUNT.exists():
        return json.loads(ACCOUNT.read_text(encoding="utf-8"))
    pw = "".join(secrets.choice(string.ascii_letters + string.digits + "!@#$%^&*")
                 for _ in range(18))
    acc = {"email": EMAIL, "username": "shinsegi-media-" + secrets.token_hex(2),
           "fullname": "Shinsegi Media", "password": pw}
    ACCOUNT.write_text(json.dumps(acc, ensure_ascii=False, indent=2), encoding="utf-8")
    return acc


def save_token(tok: str) -> None:
    tok = tok.strip()
    txt = ENV_PATH.read_text(encoding="utf-8")
    txt = re.sub(r"^#?\s*HF_TOKEN=.*$", f"HF_TOKEN={tok}", txt, flags=re.M)
    if "HF_TOKEN=" not in txt:
        txt = txt.rstrip() + f"\n\n# HuggingFace 무료 계정 토큰\nHF_TOKEN={tok}\n"
    ENV_PATH.write_text(txt, encoding="utf-8")
    print(f"[ok] .env HF_TOKEN 갱신 ({tok[:10]}...)")


def _probe_login(pg) -> bool:
    """전달받은 단일 탭으로 로그인 여부만 확인(탭 반복 개폐 금지 → 창 깜빡임 원인)."""
    try:
        pg.goto("https://huggingface.co/settings/tokens",
                wait_until="domcontentloaded", timeout=45000)
        pg.wait_for_timeout(2000)
        ok = ("login" not in pg.url) and ("join" not in pg.url)
        return ok
    except Exception:
        return False


def _try_tokens(ctx) -> str | None:
    """로그인된 세션에서 read 토큰 1개 발급."""
    pg = ctx.new_page()
    tok = ""
    try:
        pg.goto("https://huggingface.co/settings/tokens/new?tokenType=read",
                wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(3500)

        # 토큰 이름
        for sel in pg.query_selector_all("input[type='text'], input:not([type])"):
            try:
                sel.fill(TOKEN_NAME, timeout=2500)
                break
            except Exception:
                continue
        pg.wait_for_timeout(500)

        # 역할 Read (이미 URL 로 지정되지만, UI 라디오가 있으면 확실히)
        for label in ("Read", "읽기"):
            try:
                pg.get_by_text(label, exact=True).first.click(timeout=2000)
                break
            except Exception:
                continue

        # 생성 버튼
        clicked = False
        for txt in ("Create token", "토큰 생성", "Create"):
            try:
                pg.get_by_role("button", name=txt).first.click(timeout=3000)
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            try:
                pg.click("button[type='submit']", timeout=3000)
            except Exception:
                pass

        pg.wait_for_timeout(6000)
        (DATA / "_hf_token_page.png").write_bytes(pg.screenshot(full_page=False))

        body = pg.inner_text("body")
        m = re.search(r"hf_[A-Za-z0-9]{20,}", body)
        if m:
            tok = m.group(0)
        if not tok:  # 복사용 input value
            for sel in pg.query_selector_all("input"):
                v = sel.input_value() or ""
                if v.startswith("hf_"):
                    tok = v
                    break
        return tok or None
    except Exception as e:
        print("  token 단계 예외:", e)
        return None
    finally:
        print("  token url:", pg.url)
        try:
            pg.close()
        except Exception:
            pass


# ────────────────────────────── commands ─────────────────────────────
JOIN_CLICK_WORDS = ("sign up", "create account", "continue", "next", "가입", "계속",
                    "다음", "회원가입", "시작")


def _fill_join_form(pg, acc: dict) -> None:
    """CAPTCHA 를 사람이 푼 뒤 나타나는 입력 폼을 채워준다(제출은 아래에서)."""
    def put(keys, value):
        for sel in pg.query_selector_all("input"):
            if (sel.get_attribute("type") or "text") in ("hidden", "checkbox", "radio"):
                continue
            ident = " ".join(filter(None, [
                sel.get_attribute("name") or "", sel.get_attribute("id") or "",
                sel.get_attribute("placeholder") or "", sel.get_attribute("autocomplete") or "",
            ])).lower()
            if any(k in ident for k in keys):
                try:
                    cur = sel.input_value()
                    if cur and cur != value:
                        continue
                    sel.fill(value, timeout=2500)
                    return True
                except Exception:
                    continue
        return False

    put(("email", "이메일"), acc["email"])
    put(("password", "비밀번호"), acc["password"])
    put(("username", "사용자", "handle"), acc["username"])
    put(("fullname", "full name", "name", "이름"), acc["fullname"])
    for cb in pg.query_selector_all("input[type='checkbox']"):
        try:
            if not cb.is_checked():
                cb.check(timeout=1200)
        except Exception:
            pass


def _click_join(pg) -> bool:
    for sel in pg.query_selector_all("button"):
        try:
            if not sel.is_visible():
                continue
            t = (sel.inner_text() or "").lower()
            typ = sel.get_attribute("type") or ""
            if typ == "submit" or any(w in t for w in JOIN_CLICK_WORDS):
                sel.click(timeout=2500)
                return True
        except Exception:
            continue
    return False


def _captcha_visible(pg) -> bool:
    """CAPTCHA(그림 선택)가 화면에 있으면 True — 이때 클릭하면 페이지가 리로드되어
    사람이 푸는 도중의 진행이 리셋된다(= 창 깜빡임의 주원인)."""
    sels = ["iframe[src*='captcha' i]", "iframe[title*='captcha' i]",
            "iframe[src*='turnstile' i]", "[class*='captcha' i]",
            "[id*='captcha' i]"]
    for s in sels:
        try:
            el = pg.query_selector(s)
            if el and el.is_visible():
                return True
        except Exception:
            continue
    return False


def cmd_open() -> None:
    wait = int(sys.argv[2]) if len(sys.argv) > 2 else WAIT_LOGIN_SEC
    acc = load_account()
    print("=" * 62, flush=True)
    print("  HuggingFace 무료 가입 — 아래 값을 그대로 복사해서 쓰면 됩니다", flush=True)
    print("=" * 62, flush=True)
    print(f"  이메일   : {acc['email']}", flush=True)
    print(f"  사용자명 : {acc['username']}", flush=True)
    print(f"  이름     : {acc['fullname']}", flush=True)
    print(f"  비밀번호 : {acc['password']}", flush=True)
    print("-" * 62, flush=True)
    print("  * 그림 CAPTCHA 만 직접 풀어주세요. 폼 입력은 자동입니다.", flush=True)
    print("  * CAPTCHA 푸는 동안에는 버튼을 누르지 않습니다.", flush=True)
    print("  * 가입 후 메일함(agent.qq.com) 확인 링크도 클릭해주세요.", flush=True)
    print("  * 로그인 감지되면 read 토큰 발급 → .env 저장까지 자동 진행", flush=True)
    print(f"  (최대 {wait // 60}분 대기)", flush=True)
    print("=" * 62, flush=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), executable_path=chrome(), headless=False,
            viewport={"width": 1280, "height": 900}, args=["--no-sandbox"])
        dead = {"v": False}
        ctx.on("close", lambda: dead.__setitem__("v", True))
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto("https://huggingface.co/join", wait_until="domcontentloaded", timeout=60000)

        probe = None                 # 로그인 검사 전용 탭 1개만 재사용
        last_click = 0.0             # 제출 클릭 쿨다운
        deadline = time.time() + wait
        last_print = 0
        while time.time() < deadline and not dead["v"]:
            time.sleep(15)
            if probe is None:
                try:
                    probe = ctx.new_page()
                except Exception:
                    print("[exit] 브라우저가 닫혔습니다. 다시 실행하세요.", flush=True)
                    return
            if _probe_login(probe):
                print("\n[ok] 로그인 확인됨 — 토큰 발급 진행", flush=True)
                tok = _try_tokens(ctx)
                if tok:
                    save_token(tok)
                    print("[done] HF_TOKEN 설정 완료", flush=True)
                else:
                    print("[warn] 토큰 자동 추출 실패. 창에서 토큰을 복사해", flush=True)
                    print("       python scripts/hf_setup.py save hf_xxx 로 넣어주세요", flush=True)
                ctx.close()
                return
            try:
                n = len([s for s in pg.query_selector_all("input")
                         if (s.get_attribute("type") or "text") != "hidden"])
                if n >= 2:
                    _fill_join_form(pg, acc)
                    # CAPTCHA가 보이거나 쿨다운 중이면 클릭하지 않는다
                    if (time.time() - last_click > 30) and not _captcha_visible(pg):
                        if _click_join(pg):
                            last_click = time.time()
            except Exception:
                pass
            left = int(deadline - time.time())
            if int(time.time()) - last_print > 120:
                last_print = int(time.time())
                print(f"  ... 로그인 대기 중 ({left // 60}분 {left % 60}초 남음) url={pg.url[:60]}", flush=True)
        if dead["v"]:
            print("[exit] 브라우저가 닫혔습니다. 다시 실행하세요.", flush=True)
        else:
            print("[timeout] 로그인 미확인. 다시 실행하세요.", flush=True)
        try:
            ctx.close()
        except Exception:
            pass


def cmd_token() -> None:
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), executable_path=chrome(), headless=False,
            viewport={"width": 1280, "height": 900}, args=["--no-sandbox"])
        probe = ctx.new_page()
        if not _probe_login(probe):
            print("로그인 안 됨 — python scripts/hf_setup.py open 먼저")
            ctx.close()
            return
        tok = _try_tokens(ctx)
        if tok:
            save_token(tok)
        else:
            print("[warn] 토큰 추출 실패 — 직접 복사 후 save 명령 사용")
        ctx.close()


def cmd_save() -> None:
    tok = sys.argv[2] if len(sys.argv) > 2 else ""
    if not tok.startswith("hf_"):
        raise SystemExit("사용법: python scripts/hf_setup.py save hf_xxxxxxxx")
    save_token(tok)


def cmd_status() -> None:
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), executable_path=chrome(), headless=True,
            args=["--no-sandbox"])
        probe = ctx.new_page()
        ok = _probe_login(probe)
        print("logged_in:", ok)
        ctx.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "open"
    {"open": cmd_open, "token": cmd_token, "save": cmd_save,
     "status": cmd_status}[cmd]()
