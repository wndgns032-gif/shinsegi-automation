"""중국어 G2P 비교 — misaki ZHG2P vs espeak(cmn). 결과는 _zh_report.txt 로 저장."""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

REP = BASE / "_zh_report.txt"
lines: list[str] = []


def log(*args) -> None:
    s = " ".join(str(a) for a in args)
    lines.append(s)
    print(s, flush=True)


from kokoro_onnx import Kokoro  # noqa: E402

TEXT = "不是你失败了，只是又找到了一种行不通的方法。最贵的包只背过两次，便宜的包天天背。"

k = Kokoro(str(BASE / "models" / "kokoro-v1.0.onnx"), str(BASE / "models" / "voices-v1.0.bin"))

try:
    from misaki.zh import ZHG2P
    g = ZHG2P()
    res = g(TEXT)
    log("ZHG2P type:", type(res))
    ps = res[0] if isinstance(res, tuple) else res
    log("phonemes:", repr(ps[:120]))
    known = "".join(p for p in ps if p in k.tokenizer.vocab)
    log("in-vocab:", len(known), "/", len(ps), repr(known[:80]))
except Exception as e:  # noqa: BLE001
    log("ZHG2P FAIL:", type(e).__name__, e)

for code in ("cmn", "zh-cn"):
    try:
        ph = k.tokenizer.phonemize(TEXT, code)
        log(f"espeak[{code}]:", repr(ph[:120]))
        known = "".join(p for p in ph if p in k.tokenizer.vocab)
        log(f"espeak[{code}] in-vocab:", len(known), "/", len(ph))
    except Exception as e:  # noqa: BLE001
        log(f"espeak[{code}] FAIL:", type(e).__name__, str(e)[:120])

REP.write_text("\n".join(lines), encoding="utf-8")
