import asyncio, sys, time, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import aiohttp
from edge_tts.drm import DRM
from edge_tts import constants as ETC
from src.tts import _ssml, profile_for, _date_header

async def main():
    prof = profile_for("ko")
    ssml = _ssml("안녕하세요. 오늘도 좋은 하루 보내세요.", prof)
    print("SSML:", ssml[:400])
    url = (f"{ETC.WSS_URL}&ConnectionId={uuid.uuid4().hex.upper()}"
           f"&Sec-MS-GEC={DRM.generate_sec_ms_gec()}&Sec-MS-GEC-Version={ETC.SEC_MS_GEC_VERSION}")
    print("URL:", url[:120])
    async with aiohttp.ClientSession(trust_env=True) as s:
        async with s.ws_connect(url, compress=15, headers=DRM.headers_with_muid(ETC.WSS_HEADERS)) as ws:
            await ws.send_str(f"X-Timestamp:{_date_header()}\r\nContent-Type:application/json; charset=utf-8\r\nPath:speech.config\r\n\r\n"
                '{"context":{"synthesis":{"audio":{"metadataoptions":{"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"false"},'
                '"outputFormat":"audio-24khz-48kbitrate-mono-mp3"}}}}\r\n')
            await ws.send_str(f"X-RequestId:{uuid.uuid4().hex.upper()}\r\nContent-Type:application/ssml+xml\r\n"
                              f"X-Timestamp:{_date_header()}Z\r\nPath:ssml\r\n\r\n{ssml}")
            n = 0
            async for msg in ws:
                n += 1
                if msg.type == aiohttp.WSMsgType.BINARY:
                    hlen = int.from_bytes(msg.data[:2], "big")
                    print(f"BIN len={len(msg.data)} hlen={hlen} head={msg.data[2:hlen][:200]!r}")
                else:
                    print(f"MSG {msg.type} {msg.data[:300]!r}")
                if n > 8:
                    break

asyncio.run(main())
