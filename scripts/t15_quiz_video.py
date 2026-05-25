#!/usr/bin/env python3
"""T15 — Vidéo quiz evergreen.

Génère 1 clip Veo 3.1 Lite (9:16, 8s) avec un prompt evergreen autour du quiz
"find your perfect toothbrush", upload Drive + YouTube unlisted.

Pour les formats 1:1 et 16:9 (architecture spec), à ajouter plus tard quand
Instagram / X seront unlocked.

Coût : ~$1.60.
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
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
DRIVE_ROOT = os.environ["DRIVE_ROOT_FOLDER_ID"]  # DailySmileCare/
YT_UPLOAD_WEBHOOK = f"{N8N}/webhook/dsc-youtube-upload"
H = {"X-N8N-API-KEY": K, "Content-Type": "application/json"}
DRIVE_CRED = {"googleDriveOAuth2Api": {"id": "Sirms4q3Rl05Mlj6", "name": "Google Drive account"}}

VEO_MODEL = "veo-3.1-lite-generate-preview"
VEO_PREDICT = f"https://generativelanguage.googleapis.com/v1beta/models/{VEO_MODEL}:predictLongRunning?key={GEMINI_KEY}"

VIDEOS_DIR = ROOT / "personas" / "videos"
VIDEOS_DIR.mkdir(parents=True, exist_ok=True)


# Reuse the run_ephemeral helper pattern from T9
def run_ephemeral(name, nodes, connections, webhook_path, post_body=None, timeout=60):
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


def ensure_quiz_video_folder():
    """Create or find DailySmileCare/quiz_video/<date>/ folder."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    WP = "t15-ensure-folder-" + str(int(time.time()))[-6:]
    js = f"""
const today = '{today}';
const drive_root = '{DRIVE_ROOT}';

const ensure = async (name, parent) => {{
  const q = `name='${{name}}' and mimeType='application/vnd.google-apps.folder' and '${{parent}}' in parents and trashed=false`;
  // We can't call helpers.* here — return params for HTTP nodes to chain
  return {{name, parent, q}};
}};

return [{{ json: {{ today, drive_root }} }}];
"""
    # Simpler: just do search + create chain in HTTP nodes
    return run_ephemeral(
        "T15-EnsureQuizFolder",
        nodes=[
            {"id":"wh","name":"WH","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[0,0],"webhookId":WP,
             "parameters":{"path":WP,"httpMethod":"POST","responseMode":"responseNode"}},
            # Search quiz_video under DailySmileCare
            {"id":"sq","name":"SearchQV","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[240,0],"credentials":DRIVE_CRED,
             "parameters":{
                "method":"GET",
                "url":f"https://www.googleapis.com/drive/v3/files?q=name%3D%27quiz_video%27+and+mimeType%3D%27application%2Fvnd.google-apps.folder%27+and+%27{DRIVE_ROOT}%27+in+parents+and+trashed%3Dfalse&fields=files(id)",
                "authentication":"predefinedCredentialType","nodeCredentialType":"googleDriveOAuth2Api","options":{},
             }},
            {"id":"rq","name":"ResolveQV","type":"n8n-nodes-base.code","typeVersion":2,"position":[480,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":
                "const files = $input.first().json.files || []; "
                "return [{ json: { qv_id: files[0] && files[0].id, needs_create: files.length === 0 } }];"}},
            {"id":"if1","name":"IfCreateQV","type":"n8n-nodes-base.if","typeVersion":2,"position":[720,0],
             "parameters":{"conditions":{"options":{"caseSensitive":True,"leftValue":"","typeValidation":"loose"},
                "conditions":[{"leftValue":"={{ $json.needs_create }}","rightValue":True,
                               "operator":{"type":"boolean","operation":"equals"}}],
                "combinator":"and"}}},
            {"id":"cq","name":"CreateQV","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[960,-100],"credentials":DRIVE_CRED,
             "parameters":{
                "method":"POST",
                "url":"https://www.googleapis.com/drive/v3/files",
                "authentication":"predefinedCredentialType","nodeCredentialType":"googleDriveOAuth2Api",
                "sendBody":True,"specifyBody":"json",
                "jsonBody": json.dumps({"name":"quiz_video","mimeType":"application/vnd.google-apps.folder","parents":[DRIVE_ROOT]}),
                "options":{},
             }},
            {"id":"mq","name":"MergeQV","type":"n8n-nodes-base.code","typeVersion":2,"position":[1200,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":
                "const j = $input.first().json; "
                "const qv_id = j.id || j.qv_id; "
                f"return [{{ json: {{ qv_id, today: '{today}' }} }}];"}},
            # Create date folder under quiz_video
            {"id":"cd","name":"CreateDate","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[1440,0],"credentials":DRIVE_CRED,
             "parameters":{
                "method":"POST",
                "url":"https://www.googleapis.com/drive/v3/files",
                "authentication":"predefinedCredentialType","nodeCredentialType":"googleDriveOAuth2Api",
                "sendBody":True,"specifyBody":"json",
                "jsonBody": "={{ JSON.stringify({ name: $json.today, mimeType: 'application/vnd.google-apps.folder', parents: [$json.qv_id] }) }}",
                "options":{},
             }},
            {"id":"rp","name":"R","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,"position":[1680,0],
             "parameters":{"respondWith":"json","responseBody":"={{ { date_folder_id: $json.id, quiz_video_id: $node['MergeQV'].json.qv_id, date: $node['MergeQV'].json.today } }}"}},
        ],
        connections={
            "WH":{"main":[[{"node":"SearchQV","type":"main","index":0}]]},
            "SearchQV":{"main":[[{"node":"ResolveQV","type":"main","index":0}]]},
            "ResolveQV":{"main":[[{"node":"IfCreateQV","type":"main","index":0}]]},
            "IfCreateQV":{"main":[
                [{"node":"CreateQV","type":"main","index":0}],
                [{"node":"MergeQV","type":"main","index":0}],
            ]},
            "CreateQV":{"main":[[{"node":"MergeQV","type":"main","index":0}]]},
            "MergeQV":{"main":[[{"node":"CreateDate","type":"main","index":0}]]},
            "CreateDate":{"main":[[{"node":"R","type":"main","index":0}]]},
        },
        webhook_path=WP,
    )


def drive_upload_mp4(local_path, file_name, parent_id):
    with open(local_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    WP = "t15-up-" + str(int(time.time()))[-6:]
    decode_js = """
const b64 = $node['Webhook'].json.body.b64;
const fileName = $node['Webhook'].json.body.fileName;
const parent = $node['Webhook'].json.body.parent;
return [{ json: { fileName, parent }, binary: { data: { data: b64, mimeType: 'video/mp4', fileName } } }];
"""
    res = run_ephemeral(
        "T15-DriveUpload",
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


def veo_generate_quiz_promo():
    """Submit Veo + poll. Returns local MP4 path."""
    prompt = (
        "Documentary-style smartphone footage. A confused person in a bathroom holding "
        "several different electric toothbrushes, looking back and forth between them with "
        "a slight frown. Then they smile and pick up a phone showing a website quiz interface. "
        "Final shot: relieved smile holding the chosen toothbrush. Natural skin, real bathroom, "
        "soft daylight, no studio polish, candid handheld feel, 9:16 vertical."
    )
    body = {
        "instances": [{"prompt": prompt}],
        "parameters": {"aspectRatio": "9:16", "sampleCount": 1},
    }
    print("  → POST Veo predictLongRunning…")
    r = requests.post(VEO_PREDICT, json=body, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Veo POST {r.status_code}: {r.text[:300]}")
    op_name = r.json()["name"]
    print(f"  operation: {op_name}")

    poll_url = f"https://generativelanguage.googleapis.com/v1beta/{op_name}?key={GEMINI_KEY}"
    start = time.time()
    while time.time() - start < 420:
        r = requests.get(poll_url, timeout=30)
        d = r.json()
        if d.get("done"):
            if d.get("error"):
                raise RuntimeError(f"Veo failed: {d['error']}")
            vids = d.get("response", {}).get("generateVideoResponse", {}).get("generatedSamples", [])
            if not vids:
                raise RuntimeError(f"No video: {d}")
            uri = vids[0]["video"]["uri"]
            print(f"  ✓ Done in {int(time.time()-start)}s — downloading…")
            r2 = requests.get(uri, headers={"x-goog-api-key": GEMINI_KEY}, timeout=180, stream=True)
            tmp = VIDEOS_DIR / f"quiz_promo_{int(time.time())}.mp4"
            with open(tmp, "wb") as f:
                for chunk in r2.iter_content(8192):
                    f.write(chunk)
            print(f"  ✓ {tmp.stat().st_size // 1024} KB → {tmp.relative_to(ROOT)}")
            return tmp
        print(f"  … polling ({int(time.time()-start)}s)")
        time.sleep(15)
    raise TimeoutError("Veo poll timeout")


def main():
    print("=== T15 — Vidéo quiz evergreen ===\n")

    print("1. Ensure Drive folder /DailySmileCare/quiz_video/<date>/…")
    folders = ensure_quiz_video_folder()
    date_folder_id = folders.get("date_folder_id")
    if not date_folder_id:
        print(f"   ✗ folder setup failed: {folders}"); sys.exit(1)
    print(f"   ✓ quiz_video id : {folders.get('quiz_video_id')}")
    print(f"   ✓ date folder id : {date_folder_id} (date={folders.get('date')})")

    print("\n2. Veo generation (~1-3 min, ~$1.60)…")
    mp4_path = veo_generate_quiz_promo()

    print("\n3. Upload MP4 → Drive…")
    mp4_name = f"quiz_promo_9x16_{int(time.time())}.mp4"
    drive_id = drive_upload_mp4(str(mp4_path), mp4_name, date_folder_id)
    print(f"   ✓ Drive file id = {drive_id}")

    print("\n4. n8n YouTube-Upload…")
    title = "Find Your Perfect Electric Toothbrush in 30 Seconds — DailySmileCare"
    description = (
        "Lost in the wall of electric toothbrushes? Take our 30-second quiz "
        "and get the 3 brushes that actually match your needs (sensitive teeth, travel, budget, etc).\n\n"
        "👉 https://dailysmilecare.com/quiz.html"
    )
    r = requests.post(YT_UPLOAD_WEBHOOK, json={
        "drive_file_id": drive_id,
        "title": title,
        "description": description,
        "tags": ["electric toothbrush", "quiz", "DailySmileCare", "find your toothbrush"],
    }, timeout=300)
    print(f"   HTTP {r.status_code}")
    try:
        yt = r.json()
        print(f"   Response: {json.dumps(yt, indent=2)[:400]}")
        permalink = yt.get("permalink")
    except Exception:
        print(f"   Raw: {r.text[:300]}")
        permalink = None

    if permalink:
        print(f"\n✓ T15 publié : {permalink}")
    else:
        print(f"\n⚠ Pas de permalink retourné mais l'upload peut être OK — vérifier YouTube Studio")


if __name__ == "__main__":
    main()
