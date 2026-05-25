#!/usr/bin/env python3
"""T14 — Mapping des voix Gemini TTS par persona + sample audio par persona.

Sortie :
- personas/voices.json   : mapping {persona_id: {name, voice_name, speaking_style}}
- personas/voices/<name>.wav : un échantillon par persona, ~5 sec
- Mise à jour Sheets Personas.voice_id

Modèle : gemini-2.5-flash-preview-tts (audio 24kHz mono PCM 16-bit, on wrap en WAV).
Pas d'abonnement supplémentaire (free tier OK pour TTS).
"""

import base64
import json
import os
import struct
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
TTS_MODEL = "gemini-2.5-flash-preview-tts"
TTS_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{TTS_MODEL}:generateContent?key={GEMINI_KEY}"

# Each persona gets:
#   - voice_name      : one of Gemini's prebuilt voices
#   - speaking_style  : natural-language prefix injected at generation
# Voice picks aim for: gender + age + tone fit. They are NOT regional accent voices
# (Gemini TTS doesn't expose explicit US regional accents), so the regional intent
# is conveyed via the speaking_style prompt — and via text content choices at gen time.
VOICES = {
    "1":  {"name": "Ashley",  "voice_name": "Aoede",
           "sample_text": "Honestly, I just needed something that works without breaking the bank for the whole family.",
           "speaking_style": "Speak warmly and naturally, like a busy Ohio suburban mom giving an honest recommendation to a friend.",
           "region": "Ohio"},
    "2":  {"name": "Dorothy", "voice_name": "Sulafat",
           "sample_text": "After forty years as a nurse, I know which routines stick. This one stuck.",
           "speaking_style": "Speak calmly and steadily, in a slightly slower pace, like a 68-year-old retired nurse from Phoenix sharing wisdom.",
           "region": "Phoenix, AZ"},
    "3":  {"name": "Ethan",   "voice_name": "Charon",
           "sample_text": "I dug into the materials, the lifecycle data, and the company behind it before I bought.",
           "speaking_style": "Speak in a measured, thoughtful tone, like a 38-year-old eco-conscious Portland dad explaining a deliberate choice.",
           "region": "Portland, OR"},
    "4":  {"name": "Jordan",  "voice_name": "Puck",
           "sample_text": "Real talk — my Oura data showed my recovery was off, and gum health was the missing link.",
           "speaking_style": "Speak with energy and a casual, friendly cadence, like a 26-year-old Austin athlete sharing a fitness insight.",
           "region": "Austin, TX"},
    "5":  {"name": "Linda",   "voice_name": "Vindemiatrix",
           "sample_text": "When my doctor said gum disease and diabetes work together, I had to do something about it.",
           "speaking_style": "Speak with calm authority and warmth, like a 58-year-old Black woman from Houston managing her health with intention.",
           "region": "Houston, TX"},
    "6":  {"name": "Marcus",  "voice_name": "Iapetus",
           "sample_text": "When I commit to a daily ritual, the tool needs to match the standard. This one does.",
           "speaking_style": "Speak with composed authority, like a polished 52-year-old corporate executive from Atlanta — confident but never showy.",
           "region": "Atlanta, GA"},
    "7":  {"name": "Priya",   "voice_name": "Laomedeia",
           "sample_text": "I asked my OB what was safe during pregnancy — she pointed me here, and the bleeding stopped within a week.",
           "speaking_style": "Speak with gentle clarity, like a 31-year-old first-time pregnant Seattle professional being careful and informed.",
           "region": "Seattle, WA"},
    "8":  {"name": "Raymond", "voice_name": "Orus",
           "sample_text": "Heart attack at fifty-nine changed everything. Now I take every part of my health seriously, including this.",
           "speaking_style": "Speak deliberately and steadily, in a slightly lower register, like a 61-year-old Minneapolis heart-attack survivor with calm resolve.",
           "region": "Minneapolis, MN"},
    "9":  {"name": "Sophia",  "voice_name": "Autonoe",
           "sample_text": "Mid-Invisalign, I needed something that cleans around the aligners without scratching them. This was it.",
           "speaking_style": "Speak with polished, articulate clarity, like a 45-year-old Latina professional from Chicago in Invisalign treatment, image-aware and precise.",
           "region": "Chicago, IL"},
    "10": {"name": "Tyler",   "voice_name": "Fenrir",
           "sample_text": "Bought this because it was on sale, kept using it because it actually works. That's the whole story.",
           "speaking_style": "Speak with relaxed millennial casualness, like a 22-year-old Nashville college senior who isn't trying to sell anything.",
           "region": "Nashville, TN"},
}

OUT_DIR = ROOT / "personas" / "voices"
OUT_DIR.mkdir(parents=True, exist_ok=True)
VOICES_JSON_PATH = ROOT / "personas" / "voices.json"


def pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 24000) -> bytes:
    """Wrap raw PCM s16le mono into a WAV container."""
    num_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    subchunk2_size = len(pcm_bytes)
    chunk_size = 36 + subchunk2_size
    header = b"RIFF" + struct.pack("<I", chunk_size) + b"WAVE"
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, num_channels, sample_rate, byte_rate, block_align, bits_per_sample)
    data = b"data" + struct.pack("<I", subchunk2_size) + pcm_bytes
    return header + fmt + data


def synthesize(text, voice_name, style=None, max_retries=4):
    """Call Gemini TTS, return WAV bytes. Retries 429 with backoff."""
    full_text = f"{style}\n\n{text}" if style else text
    body = {
        "contents": [{"parts": [{"text": full_text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice_name}}
            },
        },
    }
    last_err = None
    for attempt in range(max_retries):
        r = requests.post(TTS_URL, json=body, timeout=120)
        if r.status_code == 200:
            data = r.json()
            parts = data["candidates"][0]["content"]["parts"]
            audio_part = next(p for p in parts if "inlineData" in p)
            pcm = base64.b64decode(audio_part["inlineData"]["data"])
            return pcm_to_wav(pcm, sample_rate=24000)
        if r.status_code == 429:
            wait = 30 * (attempt + 1)  # 30s, 60s, 90s, 120s
            print(f"      429 → backoff {wait}s (attempt {attempt+1}/{max_retries})")
            time.sleep(wait)
            last_err = f"HTTP 429 after {max_retries} retries"
            continue
        raise RuntimeError(f"TTS HTTP {r.status_code}: {r.text[:300]}")
    raise RuntimeError(last_err or "TTS failed")


def main():
    print("=== T14 — Voix TTS par persona ===\n")
    results = {}
    failures = []
    INTER_CALL_DELAY = 22  # seconds — Gemini TTS free tier is ~3 RPM, stay safely under

    # Resume: load existing voices.json if present
    if VOICES_JSON_PATH.exists():
        try:
            results = json.loads(VOICES_JSON_PATH.read_text(encoding="utf-8"))
        except Exception:
            results = {}

    pending = [pid for pid in VOICES if pid not in results or not (OUT_DIR / f"{VOICES[pid]['name'].lower()}.wav").exists()]
    print(f"  À traiter : {len(pending)} / {len(VOICES)} (resume mode)")
    print()

    for idx, pid in enumerate(pending):
        cfg = VOICES[pid]
        name = cfg["name"]
        voice = cfg["voice_name"]
        text = cfg["sample_text"]
        style = cfg["speaking_style"]
        out_path = OUT_DIR / f"{name.lower()}.wav"
        try:
            wav = synthesize(text, voice, style)
            out_path.write_bytes(wav)
            size_kb = len(wav) / 1024
            print(f"  ✓ #{pid:>2}  {name:<8} → {voice:<14} | {size_kb:>6.1f} KB | {out_path.relative_to(ROOT)}")
            results[pid] = {
                "name": name,
                "voice_name": voice,
                "speaking_style": style,
                "region": cfg["region"],
                "sample_text": text,
                "sample_path": str(out_path.relative_to(ROOT)),
            }
            # Save progress incrementally so we never lose work
            VOICES_JSON_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print(f"  ✗ #{pid:>2}  {name:<8} → {voice:<14} | ERREUR: {str(e)[:200]}")
            failures.append((name, str(e)))

        # Inter-call delay (except on last item)
        if idx < len(pending) - 1:
            print(f"      … sleep {INTER_CALL_DELAY}s to respect quota")
            time.sleep(INTER_CALL_DELAY)

    print(f"\n  ✓ Mapping écrit → {VOICES_JSON_PATH.relative_to(ROOT)}")

    print()
    print("=== Résultat T14 ===")
    print(f"  Personas traités : {len(results)} / {len(VOICES)}")
    print(f"  Échantillons WAV : {len(list(OUT_DIR.glob('*.wav')))} fichiers dans {OUT_DIR.relative_to(ROOT)}")
    if failures:
        print(f"  Échecs : {len(failures)}")
        for n, e in failures:
            print(f"    - {n}: {e}")
        sys.exit(2)
    else:
        print("  ✓ DoD T14 : 10 samples audio générés")


if __name__ == "__main__":
    main()
