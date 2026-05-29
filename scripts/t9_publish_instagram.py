#!/usr/bin/env python3
"""T9 — Publish approved Instagram content from the daily pipeline.

For chaque row Content_Calendar (platform=instagram_reel, status=approved, permalink vide) :
  1. Fetch instagram_reel_script.txt from Drive
  2. Upload persona portrait to Hostinger
  3. Create IG media container (image + caption from script)
  4. Publish
  5. Update Sheets : permalink + status=published

Pas de génération image scene-spécifique pour l'instant — on poste le portrait persona
en image principale, avec le script comme caption. Quand T7b sera fait (image Imagen 4
par contenu), on remplacera l'image.
"""

import ftplib
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

N8N = os.environ["N8N_BASE_URL"]
K   = os.environ["N8N_API_KEY"]
SHEET_ID = os.environ["SHEETS_DASHBOARD_ID"]
STAGING_ID = os.environ["DRIVE_STAGING_FOLDER_ID"]
IG_ID = os.environ["IG_BUSINESS_ACCOUNT_ID"]
PAGE_TOKEN = os.environ["META_PAGE_TOKEN"]
GRAPH = "https://graph.facebook.com/v23.0"

H = {"X-N8N-API-KEY": K, "Content-Type": "application/json"}
SHEETS_CRED = {"googleSheetsOAuth2Api": {"id": "vJiNfwvBkcQFu7Qf", "name": "Google Sheets account 2"}}
DRIVE_CRED  = {"googleDriveOAuth2Api":  {"id": "Sirms4q3Rl05Mlj6", "name": "Google Drive account"}}


def run_ephemeral(name, nodes, connections, webhook_path, post_body=None, timeout=60):
    wf = {"name": name, "nodes": nodes, "connections": connections, "settings": {"executionOrder": "v1"}}
    r = requests.post(f"{N8N}/api/v1/workflows", headers=H, json=wf)
    if r.status_code >= 400: raise RuntimeError(f"Create wf: {r.text[:300]}")
    wf_id = r.json()["id"]
    try:
        requests.post(f"{N8N}/api/v1/workflows/{wf_id}/activate", headers=H)
        time.sleep(2)
        r = requests.post(f"{N8N}/webhook/{webhook_path}", json=post_body or {}, timeout=timeout)
        if r.status_code != 200: raise RuntimeError(f"Trigger: {r.text[:300]}")
        try: return r.json()
        except: return {"raw": r.text}
    finally:
        requests.post(f"{N8N}/api/v1/workflows/{wf_id}/deactivate", headers=H)
        requests.delete(f"{N8N}/api/v1/workflows/{wf_id}", headers=H)


def sheets_get(range_name):
    WP = "ig-sg-" + str(int(time.time() * 1000))[-8:]
    res = run_ephemeral("T9-IG-SheetsGet", nodes=[
        {"id":"wh","name":"WH","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[0,0],"webhookId":WP,
         "parameters":{"path":WP,"httpMethod":"POST","responseMode":"responseNode"}},
        {"id":"h","name":"H","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[240,0],
         "credentials":SHEETS_CRED,
         "parameters":{"method":"GET",
            "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/{range_name}",
            "authentication":"predefinedCredentialType","nodeCredentialType":"googleSheetsOAuth2Api","options":{}}},
        {"id":"r","name":"R","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,"position":[480,0],
         "parameters":{"respondWith":"json","responseBody":"={{ $json }}"}},
    ], connections={
        "WH":{"main":[[{"node":"H","type":"main","index":0}]]},
        "H":{"main":[[{"node":"R","type":"main","index":0}]]},
    }, webhook_path=WP)
    return res.get("values", [])


def sheets_update_cell(range_name, value):
    WP = "ig-sp-" + str(int(time.time() * 1000))[-8:]
    run_ephemeral("T9-IG-SheetsPut", nodes=[
        {"id":"wh","name":"WH","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[0,0],"webhookId":WP,
         "parameters":{"path":WP,"httpMethod":"POST","responseMode":"responseNode"}},
        {"id":"h","name":"H","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[240,0],
         "credentials":SHEETS_CRED,
         "parameters":{"method":"PUT",
            "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/{range_name}?valueInputOption=RAW",
            "authentication":"predefinedCredentialType","nodeCredentialType":"googleSheetsOAuth2Api",
            "sendBody":True,"specifyBody":"json","jsonBody": json.dumps({"values": [[value]]}),
            "options":{}}},
        {"id":"r","name":"R","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,"position":[480,0],
         "parameters":{"respondWith":"json","responseBody":"={{ $json }}"}},
    ], connections={
        "WH":{"main":[[{"node":"H","type":"main","index":0}]]},
        "H":{"main":[[{"node":"R","type":"main","index":0}]]},
    }, webhook_path=WP)


def drive_find_file(name, parent_id):
    WP = "ig-df-" + str(int(time.time() * 1000))[-8:]
    q = f"name='{name}' and '{parent_id}' in parents and trashed=false"
    res = run_ephemeral("T9-IG-DriveFind", nodes=[
        {"id":"wh","name":"WH","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[0,0],"webhookId":WP,
         "parameters":{"path":WP,"httpMethod":"POST","responseMode":"responseNode"}},
        {"id":"h","name":"H","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[240,0],
         "credentials":DRIVE_CRED,
         "parameters":{"method":"GET",
            "url":"https://www.googleapis.com/drive/v3/files",
            "authentication":"predefinedCredentialType","nodeCredentialType":"googleDriveOAuth2Api",
            "sendQuery":True,"specifyQuery":"keypair",
            "queryParameters":{"parameters":[
                {"name":"q","value":q},
                {"name":"fields","value":"files(id,name)"},
            ]},
            "options":{}}},
        {"id":"r","name":"R","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,"position":[480,0],
         "parameters":{"respondWith":"json","responseBody":"={{ $json }}"}},
    ], connections={
        "WH":{"main":[[{"node":"H","type":"main","index":0}]]},
        "H":{"main":[[{"node":"R","type":"main","index":0}]]},
    }, webhook_path=WP)
    files = res.get("files", [])
    return files[0]["id"] if files else None


def drive_download_text(file_id):
    WP = "ig-dt-" + str(int(time.time() * 1000))[-8:]
    res = run_ephemeral("T9-IG-DriveText", nodes=[
        {"id":"wh","name":"WH","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[0,0],"webhookId":WP,
         "parameters":{"path":WP,"httpMethod":"POST","responseMode":"responseNode"}},
        {"id":"h","name":"H","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[240,0],
         "credentials":DRIVE_CRED,
         "parameters":{"method":"GET",
            "url":f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media",
            "authentication":"predefinedCredentialType","nodeCredentialType":"googleDriveOAuth2Api","options":{}}},
        {"id":"r","name":"R","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,"position":[480,0],
         "parameters":{"respondWith":"text","responseBody":"={{ $json.data || $json }}"}},
    ], connections={
        "WH":{"main":[[{"node":"H","type":"main","index":0}]]},
        "H":{"main":[[{"node":"R","type":"main","index":0}]]},
    }, webhook_path=WP)
    return res.get("raw", "") if isinstance(res, dict) else str(res)


def upload_to_hostinger(local_path: Path, remote_name: str) -> str:
    host = os.environ["HOSTINGER_FTP_HOST"]
    user = os.environ["HOSTINGER_FTP_USER"]
    pwd  = os.environ["HOSTINGER_FTP_PASS"]
    ftp = ftplib.FTP()
    ftp.connect(host, 21, timeout=30)
    ftp.login(user, pwd)
    ftp.set_pasv(True)
    ftp.cwd("/public_html/images")
    with local_path.open("rb") as f:
        ftp.storbinary(f"STOR {remote_name}", f)
    ftp.quit()
    return f"https://dailysmilecare.com/images/{remote_name}"


def post_to_instagram(image_url, caption):
    # Step 1: container
    r = requests.post(f"{GRAPH}/{IG_ID}/media",
        data={"image_url": image_url, "caption": caption, "access_token": PAGE_TOKEN},
        timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"create container {r.status_code}: {r.text[:300]}")
    container_id = r.json()["id"]
    time.sleep(5)  # IG processing delay
    # Step 2: publish
    r = requests.post(f"{GRAPH}/{IG_ID}/media_publish",
        data={"creation_id": container_id, "access_token": PAGE_TOKEN},
        timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"publish {r.status_code}: {r.text[:300]}")
    media_id = r.json()["id"]
    # Fetch permalink
    r = requests.get(f"{GRAPH}/{media_id}",
        params={"fields": "permalink,id", "access_token": PAGE_TOKEN}, timeout=30)
    return media_id, r.json().get("permalink", "")


def main():
    print("=== T9 — Publish approved Instagram content ===\n")

    print("1. Read Content_Calendar + Personas…")
    cal = sheets_get("Content_Calendar!A1:G1000")
    personas = sheets_get("Personas!A1:H11")
    p_header = personas[0]
    p_by_id = {r[0]: {h: (r[i] if i < len(r) else "") for i, h in enumerate(p_header)} for r in personas[1:]}

    pending = []
    for i, r in enumerate(cal[1:], start=2):
        if len(r) < 7: r = r + [""] * (7 - len(r))
        if r[3] == "instagram_reel" and r[5] == "approved" and not r[6]:
            pending.append({
                "row": i,
                "content_id": r[0], "date": r[1], "persona_id": r[2], "platform": r[3],
            })
    print(f"   Pending IG : {len(pending)}\n")
    if not pending:
        print("   Aucun contenu IG approuvé en attente — exit.")
        return

    for c in pending:
        print(f"\n--- {c['content_id']} ---")
        persona = p_by_id.get(c["persona_id"])
        if not persona: print(f"   ✗ persona id={c['persona_id']} introuvable"); continue
        name = persona["name"]
        portrait = ROOT / "personas" / "images" / f"{name.lower()}.png"
        if not portrait.exists():
            print(f"   ✗ portrait absent : {portrait}"); continue

        # Locate script in Drive
        print(f"   Persona: {name} | Drive walk…")
        date_folder = drive_find_file(c["date"], STAGING_ID)
        if not date_folder: print(f"   ✗ date folder absent"); continue
        persona_folder = drive_find_file(name, date_folder)
        if not persona_folder: print(f"   ✗ persona folder absent"); continue
        script_id = drive_find_file("instagram_reel_script.txt", persona_folder)
        if not script_id: print(f"   ✗ script absent"); continue
        script = drive_download_text(script_id)
        print(f"   Script len = {len(script)}")

        # Build caption (script + persona credit + CTA + hashtags)
        caption = (
            f"{script.strip()}\n\n"
            f"— {name} 🦷\n\n"
            f"Find your perfect electric toothbrush in 30 seconds: dailysmilecare.com/quiz.html\n\n"
            f"#electrictoothbrush #oralcare #toothbrushreview #dailysmilecare #dentalhealth"
        )

        # Upload portrait
        print(f"   Upload portrait → Hostinger…")
        remote_name = f"ig-{c['content_id']}.png"
        image_url = upload_to_hostinger(portrait, remote_name)
        print(f"   ✓ {image_url}")

        # Post to IG
        print(f"   Posting to Instagram…")
        try:
            media_id, permalink = post_to_instagram(image_url, caption)
            print(f"   ✓ Posted! permalink = {permalink}")
        except Exception as e:
            print(f"   ✗ {e}"); continue

        # Update Sheets
        sheets_update_cell(f"Content_Calendar!F{c['row']}", "published")
        sheets_update_cell(f"Content_Calendar!G{c['row']}", permalink)
        print(f"   ✓ Sheets updated")


if __name__ == "__main__":
    main()
