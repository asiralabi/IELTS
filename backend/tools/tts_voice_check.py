"""Check every voice the TTS tables name against the ones edge-tts really has.

🔬 Written after five of the eighteen names in `app/services/tts.py` turned out
not to exist — `en-GB-BellaNeural`, `en-GB-EthanNeural`, and the whole
Australian pool. edge-tts answers an unknown voice with "No audio was
received", so the failure surfaces as a part with NO AUDIO rather than as a
wrong accent: a script needing a third same-gender British speaker, or any
Australian one, was silently unhearable. It cost 4 of 580 corpus parts and
would have done the same to a student in the app.

Not a unit test, because the answer lives on Microsoft's servers and the suite
must run offline. Run it when the voice tables change.

Usage:
  PYTHONIOENCODING=utf-8 python tools/tts_voice_check.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import tts


async def main() -> int:
    import edge_tts

    live = {v["ShortName"] for v in await edge_tts.list_voices()}

    named: dict[str, list[str]] = {
        "_DEFAULT_VOICE": [tts._DEFAULT_VOICE],
        "_FEMALE_VOICES": list(tts._FEMALE_VOICES),
        "_MALE_VOICES": list(tts._MALE_VOICES),
    }
    for key, pool in tts._ACCENT_VOICES.items():
        named[f"_ACCENT_VOICES{key}"] = list(pool)

    missing: list[str] = []
    for where, voices in named.items():
        if not voices:
            print(f"  EMPTY  {where} — a speaker routed here divides by zero")
            missing.append(where)
        for voice in voices:
            if voice not in live:
                print(f"  GONE   {where}: {voice}")
                missing.append(voice)

    total = sum(len(v) for v in named.values())
    if missing:
        print(f"\n{len(missing)} of {total} referenced voices are unusable.")
        print("edge-tts reports these as 'No audio was received', so the part "
              "ships with no sound at all.")
        return 1
    print(f"all {total} referenced voices exist ({len(live)} available in total)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
