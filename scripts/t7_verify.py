#!/usr/bin/env python3
"""T7a — Vérification programmatique du DoD :
- /DailySmileCare/staging/2026-05-24/Jordan/ contient 5 fichiers .txt
- Cost_Tracker a au moins 1 nouvelle ligne (idéalement 5)
- Content_Calendar a 5 nouvelles lignes (status=pending_approval)
"""

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
K = os.environ["N8N_API_KEY"]
SHEET_ID = os.environ["SHEETS_DASHBOARD_ID"]
STAGING_ID = os.environ["DRIVE_STAGING_FOLDER_ID"]
H = {"X-N8N-API-KEY": K, "Content-Type": "application/json"}
SHEETS_CRED = {"googleSheetsOAuth2Api": {"id": "vJiNfwvBkcQFu7Qf", "name": "Google Sheets account 2"}}
DRIVE_CRED = {"googleDriveOAuth2Api": {"id": "Sirms4q3Rl05Mlj6", "name": "Google Drive account"}}

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
PERSONA = "Jordan"  # dom=24 → index=4 → Jordan

WP = "t7-verify"

WRAP_JS = """
const dateFolders = $node['SearchDate'].json.files || [];
const dateFolder = dateFolders.find(f => f.name === '__TODAY__');
const dateFolderId = dateFolder ? dateFolder.id : null;

const personaFolders = $node['SearchPersona'].json.files || [];
const personaFolder = personaFolders.find(f => f.name === '__PERSONA__');
const personaFolderId = personaFolder ? personaFolder.id : null;

const filesRaw = $node['ListFiles'].json.files || [];
const ct = $node['ReadCT'].json.values || [];
const cc = $node['ReadCC'].json.values || [];

return [{ json: {
  dateFolderId,
  personaFolderId,
  fileCount: filesRaw.length,
  files: filesRaw.map(f => ({ name: f.name, mimeType: f.mimeType })),
  cost_tracker_total: ct.length,
  cost_tracker_tail: ct.slice(-6),
  content_calendar_total: cc.length,
  content_calendar_tail: cc.slice(-6),
} }];
""".replace("__TODAY__", TODAY).replace("__PERSONA__", PERSONA)

def build_workflow():
    return {
        "name": "T7-verify",
        "nodes": [
            {"id":"wh","name":"WH","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[0,0],
             "webhookId":WP,"parameters":{"path":WP,"httpMethod":"POST","responseMode":"responseNode"}},
            {"id":"sd","name":"SearchDate","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[240,0],"credentials":DRIVE_CRED,
             "parameters":{"method":"GET","authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleDriveOAuth2Api",
                "url":f"https://www.googleapis.com/drive/v3/files?q=mimeType%3D%27application%2Fvnd.google-apps.folder%27+and+%27{STAGING_ID}%27+in+parents+and+trashed%3Dfalse&fields=files(id,name)",
                "options":{}}},
            {"id":"sp","name":"SearchPersona","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[480,0],"credentials":DRIVE_CRED,
             "parameters":{"method":"GET","authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleDriveOAuth2Api",
                "url":"=https://www.googleapis.com/drive/v3/files?q=mimeType%3D%27application%2Fvnd.google-apps.folder%27+and+%27{{ $node['SearchDate'].json.files.find(f => f.name === '" + TODAY + "').id }}%27+in+parents+and+trashed%3Dfalse&fields=files(id,name)",
                "options":{}}},
            {"id":"lf","name":"ListFiles","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[720,0],"credentials":DRIVE_CRED,
             "parameters":{"method":"GET","authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleDriveOAuth2Api",
                "url":"=https://www.googleapis.com/drive/v3/files?q=%27{{ $node['SearchPersona'].json.files.find(f => f.name === '" + PERSONA + "').id }}%27+in+parents+and+trashed%3Dfalse&fields=files(id,name,size,mimeType)",
                "options":{}}},
            {"id":"rct","name":"ReadCT","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[960,0],"credentials":SHEETS_CRED,
             "parameters":{"method":"GET","authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Cost_Tracker!A1:F100",
                "options":{}}},
            {"id":"rcc","name":"ReadCC","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[1200,0],"credentials":SHEETS_CRED,
             "parameters":{"method":"GET","authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Content_Calendar!A1:G100",
                "options":{}}},
            {"id":"wr","name":"Wrap","type":"n8n-nodes-base.code","typeVersion":2,"position":[1440,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":WRAP_JS}},
            {"id":"rp","name":"Resp","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,"position":[1680,0],
             "parameters":{"respondWith":"json","responseBody":"={{ $json }}"}},
        ],
        "connections":{
            "WH":{"main":[[{"node":"SearchDate","type":"main","index":0}]]},
            "SearchDate":{"main":[[{"node":"SearchPersona","type":"main","index":0}]]},
            "SearchPersona":{"main":[[{"node":"ListFiles","type":"main","index":0}]]},
            "ListFiles":{"main":[[{"node":"ReadCT","type":"main","index":0}]]},
            "ReadCT":{"main":[[{"node":"ReadCC","type":"main","index":0}]]},
            "ReadCC":{"main":[[{"node":"Wrap","type":"main","index":0}]]},
            "Wrap":{"main":[[{"node":"Resp","type":"main","index":0}]]},
        },
        "settings":{"executionOrder":"v1"},
    }


def main():
    print(f"=== T7a verify (today={TODAY}, persona={PERSONA}) ===\n")
    r = requests.post(f"{N8N}/api/v1/workflows", headers=H, json=build_workflow())
    wf_id = r.json()["id"]
    requests.post(f"{N8N}/api/v1/workflows/{wf_id}/activate", headers=H)
    time.sleep(2)
    r = requests.post(f"{N8N}/webhook/{WP}", json={})
    print(f"HTTP {r.status_code}")
    try:
        body = r.json()
        print(json.dumps(body, indent=2)[:4000])
    except Exception as e:
        print(f"Raw: {r.text[:2000]}")
        body = None
    requests.post(f"{N8N}/api/v1/workflows/{wf_id}/deactivate", headers=H)
    requests.delete(f"{N8N}/api/v1/workflows/{wf_id}", headers=H)

    if not body:
        sys.exit(2)

    print("\n=== DoD validation ===")
    files_ok = body.get("fileCount", 0) >= 5
    cc_rows = (body.get("content_calendar_total", 0) - 1)  # minus header
    ct_rows = (body.get("cost_tracker_total", 0) - 1)
    print(f"  Files in Drive/staging/{TODAY}/{PERSONA}/ : {body.get('fileCount')} (need ≥ 5) {'✓' if files_ok else '✗'}")
    print(f"  Cost_Tracker data rows                    : {ct_rows} {'✓' if ct_rows >= 1 else '✗'}")
    print(f"  Content_Calendar data rows                : {cc_rows} {'✓' if cc_rows >= 1 else '✗'}")
    if files_ok and ct_rows >= 1:
        print("\n✓ DoD T7a validé")
    else:
        print("\n✗ DoD T7a incomplet")


if __name__ == "__main__":
    main()
