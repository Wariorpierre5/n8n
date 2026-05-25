#!/usr/bin/env python3
"""T9 — Orchestrateur Python pour publier sur YouTube Shorts.

Pipeline pour chaque row Content_Calendar (status=approved, platform=youtube_shorts, permalink=empty) :
  1. Lit le youtube_shorts_script.txt depuis Drive
  2. Construit prompt Veo (realisme docu + reference image persona)
  3. Submit + poll Veo
  4. Download MP4 local + sauvegarde dans personas/videos/<persona>_<date>.mp4
  5. Upload MP4 → Drive (dans le dossier persona staging)
  6. Trigger n8n YouTube-Upload → retourne permalink YouTube
  7. Update Content_Calendar.permalink + status=published

Coût estimé : ~$1.60 par Veo 3.1 Lite 8s.
"""

import base64
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

N8N = os.environ["N8N_BASE_URL"]
K   = os.environ["N8N_API_KEY"]
SHEET_ID = os.environ["SHEETS_DASHBOARD_ID"]
STAGING_ID = os.environ["DRIVE_STAGING_FOLDER_ID"]
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
YT_UPLOAD_WEBHOOK = f"{N8N}/webhook/dsc-youtube-upload"
H = {"X-N8N-API-KEY": K, "Content-Type": "application/json"}
SHEETS_CRED = {"googleSheetsOAuth2Api": {"id": "vJiNfwvBkcQFu7Qf", "name": "Google Sheets account 2"}}
DRIVE_CRED  = {"googleDriveOAuth2Api":  {"id": "Sirms4q3Rl05Mlj6", "name": "Google Drive account"}}

VEO_MODEL = "veo-3.1-lite-generate-preview"
VEO_PREDICT = f"https://generativelanguage.googleapis.com/v1beta/models/{VEO_MODEL}:predictLongRunning?key={GEMINI_KEY}"

VIDEOS_DIR = ROOT / "personas" / "videos"
VIDEOS_DIR.mkdir(parents=True, exist_ok=True)


# ─── Helpers ephemeral n8n workflows ────────────────────────────────────

def run_ephemeral(name, nodes, connections, webhook_path, post_body=None, timeout=60):
    """Create + activate + trigger + cleanup an n8n workflow. Returns response body."""
    wf = {"name": name, "nodes": nodes, "connections": connections, "settings": {"executionOrder": "v1"}}
    r = requests.post(f"{N8N}/api/v1/workflows", headers=H, json=wf)
    if r.status_code >= 400:
        raise RuntimeError(f"Create workflow failed: {r.status_code} {r.text[:300]}")
    wf_id = r.json()["id"]
    try:
        requests.post(f"{N8N}/api/v1/workflows/{wf_id}/activate", headers=H)
        time.sleep(2)
        r = requests.post(f"{N8N}/webhook/{webhook_path}", json=post_body or {}, timeout=timeout)
        if r.status_code != 200:
            raise RuntimeError(f"Trigger failed: {r.status_code} {r.text[:300]}")
        try: return r.json()
        except: return {"raw": r.text}
    finally:
        requests.post(f"{N8N}/api/v1/workflows/{wf_id}/deactivate", headers=H)
        requests.delete(f"{N8N}/api/v1/workflows/{wf_id}", headers=H)


def sheets_get(range_name):
    """Read a Sheets range. Returns array of arrays."""
    WP = "t9-sheets-get-" + str(int(time.time() * 1000))[-8:]
    res = run_ephemeral(
        "T9-SheetsGet",
        nodes=[
            {"id":"wh","name":"WH","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[0,0],"webhookId":WP,
             "parameters":{"path":WP,"httpMethod":"POST","responseMode":"responseNode"}},
            {"id":"h","name":"H","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[240,0],
             "credentials":SHEETS_CRED,
             "parameters":{
                "method":"GET",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/{range_name}",
                "authentication":"predefinedCredentialType","nodeCredentialType":"googleSheetsOAuth2Api","options":{},
             }},
            {"id":"r","name":"R","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,"position":[480,0],
             "parameters":{"respondWith":"json","responseBody":"={{ $json }}"}},
        ],
        connections={
            "WH":{"main":[[{"node":"H","type":"main","index":0}]]},
            "H":{"main":[[{"node":"R","type":"main","index":0}]]},
        },
        webhook_path=WP,
    )
    return res.get("values", [])


def sheets_update_cell(range_name, value):
    """PUT a single cell value."""
    WP = "t9-sheets-put-" + str(int(time.time() * 1000))[-8:]
    res = run_ephemeral(
        "T9-SheetsPut",
        nodes=[
            {"id":"wh","name":"WH","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[0,0],"webhookId":WP,
             "parameters":{"path":WP,"httpMethod":"POST","responseMode":"responseNode"}},
            {"id":"h","name":"H","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[240,0],
             "credentials":SHEETS_CRED,
             "parameters":{
                "method":"PUT",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/{range_name}?valueInputOption=RAW",
                "authentication":"predefinedCredentialType","nodeCredentialType":"googleSheetsOAuth2Api",
                "sendBody":True,"specifyBody":"json",
                "jsonBody": json.dumps({"values": [[value]]}),
                "options":{},
             }},
            {"id":"r","name":"R","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,"position":[480,0],
             "parameters":{"respondWith":"json","responseBody":"={{ $json }}"}},
        ],
        connections={
            "WH":{"main":[[{"node":"H","type":"main","index":0}]]},
            "H":{"main":[[{"node":"R","type":"main","index":0}]]},
        },
        webhook_path=WP,
    )
    return res


def drive_find_file(name, parent_id):
    """Search Drive for a file with given name + parent. Returns first match's id."""
    WP = "t9-drive-find-" + str(int(time.time() * 1000))[-8:]
    q = f"name='{name}' and '{parent_id}' in parents and trashed=false"
    res = run_ephemeral(
        "T9-DriveFind",
        nodes=[
            {"id":"wh","name":"WH","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[0,0],"webhookId":WP,
             "parameters":{"path":WP,"httpMethod":"POST","responseMode":"responseNode"}},
            {"id":"h","name":"H","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[240,0],
             "credentials":DRIVE_CRED,
             "parameters":{
                "method":"GET",
                "url":"https://www.googleapis.com/drive/v3/files",
                "authentication":"predefinedCredentialType","nodeCredentialType":"googleDriveOAuth2Api",
                "sendQuery":True,"specifyQuery":"keypair",
                "queryParameters":{"parameters":[
                    {"name":"q","value":q},
                    {"name":"fields","value":"files(id,name,mimeType)"},
                ]},
                "options":{},
             }},
            {"id":"r","name":"R","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,"position":[480,0],
             "parameters":{"respondWith":"json","responseBody":"={{ $json }}"}},
        ],
        connections={
            "WH":{"main":[[{"node":"H","type":"main","index":0}]]},
            "H":{"main":[[{"node":"R","type":"main","index":0}]]},
        },
        webhook_path=WP,
    )
    files = res.get("files", [])
    return files[0]["id"] if files else None


def drive_download_text(file_id):
    """Download a Drive file as text."""
    WP = "t9-drive-text-" + str(int(time.time() * 1000))[-8:]
    res = run_ephemeral(
        "T9-DriveText",
        nodes=[
            {"id":"wh","name":"WH","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[0,0],"webhookId":WP,
             "parameters":{"path":WP,"httpMethod":"POST","responseMode":"responseNode"}},
            {"id":"h","name":"H","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[240,0],
             "credentials":DRIVE_CRED,
             "parameters":{
                "method":"GET",
                "url":f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media",
                "authentication":"predefinedCredentialType","nodeCredentialType":"googleDriveOAuth2Api","options":{},
             }},
            {"id":"r","name":"R","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,"position":[480,0],
             "parameters":{"respondWith":"text","responseBody":"={{ $json.data ? $json.data : $json }}"}},
        ],
        connections={
            "WH":{"main":[[{"node":"H","type":"main","index":0}]]},
            "H":{"main":[[{"node":"R","type":"main","index":0}]]},
        },
        webhook_path=WP,
    )
    return res.get("raw", "") if isinstance(res, dict) else str(res)


def drive_upload_mp4(local_path, file_name, parent_id):
    """Upload MP4 to Drive via ephemeral n8n workflow."""
    with open(local_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    WP = "t9-drive-up-" + str(int(time.time() * 1000))[-8:]
    # Code node that decodes base64 to binary, then Drive upload
    decode_js = """
const b64 = $node['Webhook'].json.body.b64;
const fileName = $node['Webhook'].json.body.fileName;
const parent = $node['Webhook'].json.body.parent;
return [{
  json: { fileName, parent },
  binary: { data: { data: b64, mimeType: 'video/mp4', fileName } },
}];
"""
    res = run_ephemeral(
        "T9-DriveUpload",
        nodes=[
            {"id":"wh","name":"Webhook","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[0,0],"webhookId":WP,
             "parameters":{"path":WP,"httpMethod":"POST","responseMode":"responseNode"}},
            {"id":"c","name":"Decode","type":"n8n-nodes-base.code","typeVersion":2,"position":[240,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":decode_js}},
            {"id":"d","name":"Upload","type":"n8n-nodes-base.googleDrive","typeVersion":3,"position":[480,0],
             "credentials":DRIVE_CRED,
             "parameters":{
                "resource":"file","operation":"upload",
                "name":"={{ $json.fileName }}",
                "driveId":{"__rl":True,"value":"My Drive","mode":"list"},
                "folderId":{"__rl":True,"value":"={{ $json.parent }}","mode":"id"},
                "options":{},
             }},
            {"id":"r","name":"R","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,"position":[720,0],
             "parameters":{"respondWith":"json","responseBody":"={{ $json }}"}},
        ],
        connections={
            "Webhook":{"main":[[{"node":"Decode","type":"main","index":0}]]},
            "Decode":{"main":[[{"node":"Upload","type":"main","index":0}]]},
            "Upload":{"main":[[{"node":"R","type":"main","index":0}]]},
        },
        webhook_path=WP,
        post_body={"b64": b64, "fileName": file_name, "parent": parent_id},
        timeout=180,
    )
    return res.get("id") or res.get("fileId")


# ─── Veo ───────────────────────────────────────────────────────────────

def veo_generate(prompt, image_path=None, max_wait=420):
    """Submit Veo + poll. Returns local path to MP4."""
    body = {
        "instances": [{"prompt": prompt}],
        "parameters": {"aspectRatio": "9:16", "sampleCount": 1},
    }
    if image_path:
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        body["instances"][0]["image"] = {"bytesBase64Encoded": img_b64, "mimeType": "image/png"}

    print("  → POST Veo predictLongRunning…")
    r = requests.post(VEO_PREDICT, json=body, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Veo POST failed: {r.status_code} {r.text[:300]}")
    op_name = r.json()["name"]
    print(f"  operation: {op_name}")

    poll_url = f"https://generativelanguage.googleapis.com/v1beta/{op_name}?key={GEMINI_KEY}"
    start = time.time()
    while time.time() - start < max_wait:
        r = requests.get(poll_url, timeout=30)
        d = r.json()
        if d.get("done"):
            if d.get("error"):
                raise RuntimeError(f"Veo failed: {d['error']}")
            vids = d.get("response", {}).get("generateVideoResponse", {}).get("generatedSamples", [])
            if not vids:
                raise RuntimeError(f"No video in response: {d}")
            uri = vids[0]["video"]["uri"]
            print(f"  ✓ Done in {int(time.time()-start)}s — downloading…")
            r2 = requests.get(uri, headers={"x-goog-api-key": GEMINI_KEY}, timeout=180, stream=True)
            tmp = ROOT / "personas" / "videos" / f"veo_{int(time.time())}.mp4"
            with open(tmp, "wb") as f:
                for chunk in r2.iter_content(8192):
                    f.write(chunk)
            print(f"  ✓ Saved {tmp.stat().st_size // 1024} KB → {tmp.relative_to(ROOT)}")
            return tmp
        print(f"  … polling ({int(time.time()-start)}s)")
        time.sleep(15)
    raise TimeoutError("Veo polling timeout")


# ─── Main orchestration ─────────────────────────────────────────────────

def main():
    print("=== T9 — Publication YouTube Shorts ===\n")

    print("1. Lecture Content_Calendar + Personas + Products…")
    cal_rows  = sheets_get("Content_Calendar!A1:G1000")
    p_rows    = sheets_get("Personas!A1:H11")
    print(f"   Calendar: {len(cal_rows)} rows, Personas: {len(p_rows)} rows")

    # Build persona index
    p_header = p_rows[0]
    p_by_id = {}
    for r in p_rows[1:]:
        d = {h: (r[i] if i < len(r) else "") for i, h in enumerate(p_header)}
        p_by_id[d["id"]] = d

    # Filter pending YouTube
    pending = []
    for i, r in enumerate(cal_rows[1:], start=2):  # sheet 1-based, row 2+
        if len(r) < 7: r = r + [""] * (7 - len(r))
        if r[3] == "youtube_shorts" and r[5] == "approved" and not r[6]:
            pending.append({
                "row": i,
                "content_id": r[0], "date": r[1], "persona_id": r[2], "platform": r[3], "permalink": r[6],
            })
    print(f"   Pending YouTube : {len(pending)}\n")

    if not pending:
        print("   Aucun contenu approuvé pour YouTube — exit.")
        return

    for c in pending:
        print(f"\n--- {c['content_id']} ---")
        persona = p_by_id.get(c["persona_id"])
        if not persona:
            print(f"   ✗ persona id={c['persona_id']} introuvable, skip"); continue
        persona_name = persona["name"]
        portrait_path = ROOT / "personas" / "images" / f"{persona_name.lower()}.png"
        if not portrait_path.exists():
            print(f"   ✗ portrait local manquant : {portrait_path}, skip"); continue

        print(f"   Persona: {persona_name} ({persona['region']})")
        print(f"   Brand  : {persona['brand_focus']}")

        # 2. Locate script in Drive: staging/<date>/<persona>/youtube_shorts_script.txt
        print(f"   2. Recherche script Drive…")
        date_folder_id = drive_find_file(c["date"], STAGING_ID)
        if not date_folder_id:
            print(f"   ✗ date folder {c['date']} introuvable"); continue
        persona_folder_id = drive_find_file(persona_name, date_folder_id)
        if not persona_folder_id:
            print(f"   ✗ persona folder {persona_name} introuvable"); continue
        script_file_id = drive_find_file("youtube_shorts_script.txt", persona_folder_id)
        if not script_file_id:
            print(f"   ✗ script file introuvable"); continue
        print(f"   ✓ Script Drive id = {script_file_id}")

        # 3. Read script + extract punchy hook (Veo Lite caps at 8s — short phrase essential)
        print(f"   3. Lecture script + extraction hook…")
        script_text = drive_download_text(script_file_id) or ""
        # Strip common Claude script labels at start (Hook:, Story:, CTA:, Intro:, Part 1:, [Hook], **Hook**…)
        import re as _re
        cleaned = _re.sub(
            r'^[\*\[\(\s>]*(?:Hook|Story|CTA|Intro|Outro|Setup|Punchline|Part\s*\d+|Open(?:ing)?|Close|Beat)[\*\]\)\s]*[:\-—|]\s*',
            '',
            script_text.strip(),
            flags=_re.IGNORECASE,
        )
        # Take only the first sentence (up to first . / ! / ?) and cap at 12 words
        first_sentence = _re.split(r"[.!?]\s+", cleaned, maxsplit=1)[0].strip()
        words = first_sentence.split()
        if len(words) > 12:
            first_sentence = " ".join(words[:12])
        first_sentence = first_sentence.replace('"', "'").replace("\n", " ")
        if not first_sentence:
            first_sentence = f"Honestly, this {persona['brand_focus'].split()[0]} brush is great"
        print(f"   hook : \"{first_sentence}\"")

        veo_prompt = (
            f"Documentary-style smartphone selfie video of {persona_name}, "
            f"in their bathroom in {persona['region']}. "
            f"Natural real skin with visible pores, tiny imperfections, slight under-eye shadows, "
            f"no makeup, ordinary real person — not a model, not polished, no studio lighting. "
            f"Soft natural daylight from a window. "
            f"They look at the camera and say ONE single short sentence: \"{first_sentence}\". "
            f"Mouth movement matches the words exactly. They finish the sentence within 6 seconds. "
            f"Candid handheld feel, slight motion blur, smartphone grain. 9:16 vertical."
        )
        print(f"   prompt (start): {veo_prompt[:120]}…")

        # 4. Veo generate
        print(f"   4. Veo generation (~2-3 min, ~$1.60)…")
        try:
            mp4_path = veo_generate(veo_prompt, image_path=str(portrait_path), max_wait=420)
        except Exception as e:
            print(f"   ✗ Veo: {e}"); continue

        # 5. Upload to Drive
        print(f"   5. Upload MP4 → Drive (persona folder)…")
        mp4_name = f"youtube_shorts_{c['content_id']}.mp4"
        try:
            drive_id = drive_upload_mp4(str(mp4_path), mp4_name, persona_folder_id)
            print(f"   ✓ Drive file id = {drive_id}")
        except Exception as e:
            print(f"   ✗ Drive upload: {e}"); continue

        # 6. Trigger YouTube upload via n8n
        print(f"   6. n8n YouTube-Upload…")
        title = f"{persona_name}'s morning routine — DailySmileCare"
        description = (
            f"{persona_name} from {persona['region']} shares their daily routine with the "
            f"{persona['brand_focus']}.\n\n"
            f"Find your perfect toothbrush: https://dailysmilecare.com/quiz.html"
        )
        try:
            r = requests.post(YT_UPLOAD_WEBHOOK, json={
                "drive_file_id": drive_id,
                "title": title,
                "description": description,
                "tags": ["electric toothbrush", "morning routine", "DailySmileCare"],
            }, timeout=300)
            print(f"   HTTP {r.status_code}")
            yt_res = r.json()
            print(f"   Response: {json.dumps(yt_res, indent=2)[:400]}")
            permalink = yt_res.get("permalink")
            if not permalink:
                print(f"   ✗ Pas de permalink"); continue
        except Exception as e:
            print(f"   ✗ YouTube upload: {e}"); continue

        # 7. Update Sheets
        print(f"   7. Update Sheets…")
        sheets_update_cell(f"Content_Calendar!F{c['row']}", "published")
        sheets_update_cell(f"Content_Calendar!G{c['row']}", permalink)
        print(f"   ✓ {c['content_id']} → {permalink}")


if __name__ == "__main__":
    main()
