import asyncio, edge_tts

async def main():
    vs = await edge_tts.list_voices()
    lines = [f'{v["ShortName"]} | {v["Gender"]} | {v["FriendlyName"]}' for v in vs]
    open("_voices.txt", "w", encoding="utf-8").write("\n".join(lines))
    sel = [l for l in lines if l.startswith(("ko-", "fr-FR-", "zh-CN-", "en-US-"))]
    open("_voices_sel.txt", "w", encoding="utf-8").write("\n".join(sel))
    print("total", len(lines), "sel", len(sel))

asyncio.run(main())
