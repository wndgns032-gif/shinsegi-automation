import asyncio, sys, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import aiohttp
from edge_tts.drm import DRM
from edge_tts import constants as ETC
from src.tts import _date_header

TEXT = "안녕하세요. 오늘도 좋은 하루 보내세요."

VARIANTS = {
    "plain": f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='ko-KR'><voice name='ko-KR-SunHiNeural'><prosody pitch='-2Hz' rate='-6%'>{TEXT}</prosody></voice></speak>",
    "break": f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='ko-KR'><voice name='ko-KR-SunHiNeural'><prosody pitch='-2Hz' rate='-6%'>{TEXT}<break time='260ms'/></prosody></voice></speak>",
    "mstts": f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xmlns:mstts='https://www.w3.org/2001/mstts' xml:lang='ko-KR'><voice name='ko-KR-SunHiNeural'><mstts:express-as style='gentle'><prosody pitch='-2Hz' rate='-6%'>{TEXT}</prosody></mstts:express-as></voice></speak>",
}

async def run(name, ssml):
    url = (f"{ETC.WSS_URL}&ConnectionId={uuid.uuid4().hex.upper()}"
           f"&Sec-MS-GEC={DRM.generate_sec_ms_gec()}&Sec-MS-GEC-Version={ETC.SEC_MS_GEC_VERSION}")
    audio = bytearray()
    err = None
    try:
        async with aiohttp.ClientSession(trust_env=True) as s:
            async with s.ws_connect(url, compress=15, headers=DRM.headers_with_muid(ETC.WSS_HEADERS)) as ws:
                await ws.send_str(f"X-Timestamp:{_date_header()}\r\nContent-Type:application/json; charset=utf-8\r\nPath:speech.config\r\n\r\n"
                    '{"context":{"synthesis":{"audio":{"metadataoptions":{"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"true"},'
                    '"outputFormat":"audio-24khz-48kbitrate-mono-mp3"}}}}\r\n')
                await ws.send_str(f"X-RequestId:{uuid.uuid4().hex.upper()}\r\nContent-Type:application/ssml+xml\r\n"
                                  f"X-Timestamp:{_date_header()}Z\r\nPath:ssml\r\n\r\n{ssml}")
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.BINARY:
                        hlen = int.from_bytes(msg.data[:2], "big")
                        audio.extend(msg.data[hlen:])
                    elif msg.type == aiohttp.WSMsgType.TEXT:
                        if "Path:turn.end" in msg.data:
                            break
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    print(f"{name}: bytes={len(audio)} err={err}")

async def main():
    for k, v in VARIANTS.items():
        await run(k, v)

asyncio.run(main())
