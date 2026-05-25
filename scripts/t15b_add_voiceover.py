#!/usr/bin/env python3
"""T15b — Ajoute une voix-off US au clip quiz Veo existant via Gemini TTS + ffmpeg.

Steps:
  1. Generate TTS WAV via Gemini TTS (voice 'Kore', US English, enthousiaste)
  2. Mix : mute Veo audio + overlay TTS via ffmpeg
  3. Upload nouveau MP4 → Drive (même date folder que T15)
  4. Re-upload YouTube (nouveau unlisted)
"""

import base64
import json
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

N8N = os.environ["N8N_BASE_URL"]
K   = os.environ["N8N_API_KEY"]
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
H = {"X-N8N-API-KEY": K, "Content-Type": "application/json"}
DRIVE_CRED = {"googleDriveOAuth2Api": {"id": "Sirms4q3Rl05Mlj6", "name": "Google Drive account"}}
YT_UPLOAD_WEBHOOK = f"{N8N}/webhook/dsc-youtube-upload"

VOICEOVER_TEXT = (
    "Picking an electric toothbrush shouldn't require a PhD. "
    "Take our quiz at dailysmilecare.com — we figured it out for you."
)
SPEAKING_STYLE = (
    "Read this with dry, self-aware humor — like a casual US American friend "
    "delivering a smart-ass observation. Conversational pace, slight smirk in the voice, "
    "natural and unscripted feel. NOT enthusiastic, NOT salesy. Think podcast host energy."
)
VOICE = "Fenrir"  # excitable young male — more humour energy

# Locate the most recent ORIGINAL Veo MP4 (without "_voiceover_" suffix)
VIDEOS_DIR = ROOT / "personas" / "videos"
veo_files = sorted(
    [p for p in VIDEOS_DIR.glob("quiz_promo_*.mp4") if "voiceover" not in p.name],
    key=lambda p: p.stat().st_mtime,
)
if not veo_files:
    print("✗ Aucun quiz_promo_*.mp4 original (sans voiceover) trouvé")
    sys.exit(1)
VEO_MP4 = veo_files[-1]
print(f"  Source vidéo : {VEO_MP4.relative_to(ROOT)}")

# Drive date folder from T15 — find via Drive search
TODAY = time.strftime("%Y-%m-%d", time.gmtime())


def pcm_to_wav(pcm_bytes, sample_rate=24000):
    num_channels = 1; bits_per_sample = 16
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    sub2 = len(pcm_bytes)
    chunk = 36 + sub2
    header = b"RIFF" + struct.pack("<I", chunk) + b"WAVE"
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, num_channels, sample_rate, byte_rate, block_align, bits_per_sample)
    data = b"data" + struct.pack("<I", sub2) + pcm_bytes
    return header + fmt + data


def gemini_tts(text, voice=VOICE, style=SPEAKING_STYLE):
    """Call Gemini TTS, return WAV bytes."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={GEMINI_KEY}"
    full_text = f"{style}\n\n{text}" if style else text
    body = {
        "contents": [{"parts": [{"text": full_text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    r = requests.post(url, json=body, timeout=120)
    if r.status_code == 429:
        # rate limit — wait and retry once
        print("  TTS 429 → wait 30s + retry")
        time.sleep(30)
        r = requests.post(url, json=body, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"TTS HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    parts = data["candidates"][0]["content"]["parts"]
    audio_part = next(p for p in parts if "inlineData" in p)
    pcm = base64.b64decode(audio_part["inlineData"]["data"])
    return pcm_to_wav(pcm)


def ffmpeg_mux(video_in, audio_in, video_out):
    """
    Mute original audio of video_in, overlay audio_in, output video_out.
    Uses -shortest to clip to the shorter of (video, audio).
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_in),
        "-i", str(audio_in),
        "-map", "0:v:0",          # video from first input
        "-map", "1:a:0",          # audio from second input
        "-c:v", "copy",            # don't re-encode video
        "-c:a", "aac",             # encode audio as AAC
        "-b:a", "192k",
        "-shortest",
        str(video_out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{r.stderr[-1500:]}")
    return video_out


# ─── n8n helpers (reused from T9/T15) ──────────────────────────────────

def run_ephemeral(name, nodes, connections, webhook_path, post_body=None, timeout=60):
    wf = {"name": name, "nodes": nodes, "connections": connections, "settings": {"executionOrder": "v1"}}
    r = requests.post(f"{N8N}/api/v1/workflows", headers=H, json=wf)
    if r.status_code >= 400: raise RuntimeError(f"Create wf failed: {r.text[:300]}")
    wf_id = r.json()["id"]
    try:
        requests.post(f"{N8N}/api/v1/workflows/{wf_id}/activate", headers=H)
        time.sleep(2)
        r = requests.post(f"{N8N}/webhook/{webhook_path}", json=post_body or {}, timeout=timeout)
        if r.status_code != 200: raise RuntimeError(f"Trigger failed: {r.text[:300]}")
        try: return r.json()
        except: return {"raw": r.text}
    finally:
        requests.post(f"{N8N}/api/v1/workflows/{wf_id}/deactivate", headers=H)
        requests.delete(f"{N8N}/api/v1/workflows/{wf_id}", headers=H)


def find_quiz_date_folder():
    """Find DailySmileCare/quiz_video/<today>/ folder id."""
    DRIVE_ROOT = os.environ["DRIVE_ROOT_FOLDER_ID"]
    WP = "t15b-find-" + str(int(time.time()))[-6:]
    # Search quiz_video parent, then date subfolder
    return run_ephemeral(
        "T15b-FindFolder",
        nodes=[
            {"id":"wh","name":"WH","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[0,0],"webhookId":WP,
             "parameters":{"path":WP,"httpMethod":"POST","responseMode":"responseNode"}},
            {"id":"sq","name":"SearchQV","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[240,0],"credentials":DRIVE_CRED,
             "parameters":{
                "method":"GET",
                "url":f"https://www.googleapis.com/drive/v3/files?q=name%3D%27quiz_video%27+and+%27{DRIVE_ROOT}%27+in+parents+and+trashed%3Dfalse&fields=files(id)",
                "authentication":"predefinedCredentialType","nodeCredentialType":"googleDriveOAuth2Api","options":{},
             }},
            {"id":"c","name":"C","type":"n8n-nodes-base.code","typeVersion":2,"position":[480,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":
                "const f = $input.first().json.files || []; "
                "return [{ json: { qv_id: f[0] && f[0].id } }];"}},
            {"id":"sd","name":"SearchDate","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[720,0],"credentials":DRIVE_CRED,
             "parameters":{
                "method":"GET",
                "url":f"=https://www.googleapis.com/drive/v3/files?q=name%3D%27{TODAY}%27+and+%27{{{{ $json.qv_id }}}}%27+in+parents+and+trashed%3Dfalse&fields=files(id)",
                "authentication":"predefinedCredentialType","nodeCredentialType":"googleDriveOAuth2Api","options":{},
             }},
            {"id":"r","name":"R","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,"position":[960,0],
             "parameters":{"respondWith":"json","responseBody":"={{ { date_folder_id: $json.files && $json.files[0] && $json.files[0].id } }}"}},
        ],
        connections={
            "WH":{"main":[[{"node":"SearchQV","type":"main","index":0}]]},
            "SearchQV":{"main":[[{"node":"C","type":"main","index":0}]]},
            "C":{"main":[[{"node":"SearchDate","type":"main","index":0}]]},
            "SearchDate":{"main":[[{"node":"R","type":"main","index":0}]]},
        },
        webhook_path=WP,
    )


def drive_upload_mp4(local_path, file_name, parent_id):
    with open(local_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    WP = "t15b-up-" + str(int(time.time()))[-6:]
    decode_js = """
const b64 = $node['Webhook'].json.body.b64;
const fileName = $node['Webhook'].json.body.fileName;
const parent = $node['Webhook'].json.body.parent;
return [{ json: { fileName, parent }, binary: { data: { data: b64, mimeType: 'video/mp4', fileName } } }];
"""
    res = run_ephemeral(
        "T15b-DriveUpload",
        nodes=[
            {"id":"wh","name":"Webhook","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[0,0],"webhookId":WP,
             "parameters":{"path":WP,"httpMethod":"POST","responseMode":"responseNode"}},
            {"id":"c","name":"Decode","type":"n8n-nodes-base.code","typeVersion":2,"position":[240,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":decode_js}},
            {"id":"d","name":"Upload","type":"n8n-nodes-base.googleDrive","typeVersion":3,"position":[480,0],
             "credentials":DRIVE_CRED,
             "parameters":{"resource":"file","operation":"upload","name":"={{ $json.fileName }}",
                "driveId":{"__rl":True,"value":"My Drive","mode":"list"},
                "folderId":{"__rl":True,"value":"={{ $json.parent }}","mode":"id"},
                "options":{}}},
            {"id":"r","name":"R","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,"position":[720,0],
             "parameters":{"respondWith":"json","responseBody":"={{ $json }}"}},
        ],
        connections={
            "Webhook":{"main":[[{"node":"Decode","type":"main","index":0}]]},
            "Decode":{"main":[[{"node":"Upload","type":"main","index":0}]]},
            "Upload":{"main":[[{"node":"R","type":"main","index":0}]]},
        },
        webhook_path=WP, post_body={"b64":b64,"fileName":file_name,"parent":parent_id}, timeout=180,
    )
    return res.get("id")


def main():
    print("=== T15b — Voix-off + ffmpeg mux ===\n")

    print("1. Génération voix-off Gemini TTS…")
    wav_bytes = gemini_tts(VOICEOVER_TEXT)
    wav_path = VIDEOS_DIR / f"quiz_voiceover_{int(time.time())}.wav"
    wav_path.write_bytes(wav_bytes)
    print(f"   ✓ {len(wav_bytes)//1024} KB → {wav_path.relative_to(ROOT)}")

    print("\n2. ffmpeg : mute Veo audio + overlay voix-off…")
    out_mp4 = VIDEOS_DIR / f"quiz_promo_voiceover_{int(time.time())}.mp4"
    ffmpeg_mux(VEO_MP4, wav_path, out_mp4)
    print(f"   ✓ {out_mp4.stat().st_size//1024} KB → {out_mp4.relative_to(ROOT)}")

    print("\n3. Drive : find quiz_video/<date>/ folder…")
    folder_res = find_quiz_date_folder()
    date_folder_id = folder_res.get("date_folder_id")
    if not date_folder_id:
        print(f"   ✗ folder not found: {folder_res}")
        sys.exit(1)
    print(f"   ✓ date folder id = {date_folder_id}")

    print("\n4. Upload nouveau MP4 → Drive…")
    drive_id = drive_upload_mp4(str(out_mp4), out_mp4.name, date_folder_id)
    print(f"   ✓ Drive file id = {drive_id}")

    print("\n5. Re-upload YouTube (new unlisted)…")
    title = "Find Your Perfect Electric Toothbrush in 30 Seconds — DailySmileCare"
    description = (
        "Lost in the wall of electric toothbrushes? Take our 30-second quiz "
        "and get the 3 brushes that actually match your needs.\n\n"
        "👉 https://dailysmilecare.com/quiz.html"
    )
    r = requests.post(YT_UPLOAD_WEBHOOK, json={
        "drive_file_id": drive_id,
        "title": title,
        "description": description,
        "tags": ["electric toothbrush","quiz","DailySmileCare"],
    }, timeout=300)
    print(f"   HTTP {r.status_code}")
    try:
        yt = r.json()
        permalink = yt.get("permalink")
        print(f"   Response: {json.dumps(yt, indent=2)[:300]}")
        if permalink:
            print(f"\n✓ Nouvelle vidéo live : {permalink}")
            print(f"  (l'ancienne sans voix-off https://youtu.be/fHO6DvyKijI reste sur ta chaîne — tu peux la supprimer)")
    except Exception:
        print(f"   Raw: {r.text[:300]}")


if __name__ == "__main__":
    main()
