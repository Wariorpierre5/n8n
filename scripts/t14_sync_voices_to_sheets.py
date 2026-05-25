#!/usr/bin/env python3
"""T14 — Synchronise personas/voices.json → colonne voice_id du tab Personas."""

import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

N8N_BASE = os.environ["N8N_BASE_URL"]
N8N_KEY  = os.environ["N8N_API_KEY"]
SHEET_ID = os.environ["SHEETS_DASHBOARD_ID"]
H = {"X-N8N-API-KEY": N8N_KEY, "Content-Type": "application/json"}
SHEETS_CRED = {"googleSheetsOAuth2Api": {"id": "vJiNfwvBkcQFu7Qf", "name": "Google Sheets account 2"}}

voices = json.loads((ROOT / "personas" / "voices.json").read_text(encoding="utf-8"))

# Personas in id order 1..10 → write voice_name to col F (voice_id)
values_F = [[voices[str(i)]["voice_name"]] for i in range(1, 11)]

WEBHOOK_PATH = "t14-sync-voices"

workflow = {
    "name": "T14-sync-voices",
    "nodes": [
        {
            "id":"wh","name":"WH","type":"n8n-nodes-base.webhook","typeVersion":2,
            "position":[0,0],"webhookId":"t14-sync-voices",
            "parameters":{"path":WEBHOOK_PATH,"httpMethod":"POST","responseMode":"responseNode"},
        },
        {
            "id":"upd","name":"UpdateVoiceIds","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
            "position":[240,0],"credentials":SHEETS_CRED,
            "parameters":{
                "method":"PUT",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Personas!F2:F11?valueInputOption=USER_ENTERED",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "sendBody":True,"specifyBody":"json",
                "jsonBody": json.dumps({"values": values_F}),
                "options":{},
            },
        },
        {
            "id":"resp","name":"Respond","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,
            "position":[480,0],
            "parameters":{"respondWith":"json","responseBody":"={{ { ok: true, updated: $node['UpdateVoiceIds'].json } }}"},
        },
    ],
    "connections":{
        "WH":{"main":[[{"node":"UpdateVoiceIds","type":"main","index":0}]]},
        "UpdateVoiceIds":{"main":[[{"node":"Respond","type":"main","index":0}]]},
    },
    "settings":{"executionOrder":"v1"},
}

print(f"Upload {len(values_F)} voice_ids → Personas!F2:F11")
r = requests.post(f"{N8N_BASE}/api/v1/workflows", headers=H, json=workflow)
wf_id = r.json()["id"]; print(f"  workflow id={wf_id}")
requests.post(f"{N8N_BASE}/api/v1/workflows/{wf_id}/activate", headers=H)
time.sleep(2)
r = requests.post(f"{N8N_BASE}/webhook/{WEBHOOK_PATH}", json={})
print(f"  trigger HTTP {r.status_code}")
print(f"  response: {r.text[:300]}")
requests.post(f"{N8N_BASE}/api/v1/workflows/{wf_id}/deactivate", headers=H)
requests.delete(f"{N8N_BASE}/api/v1/workflows/{wf_id}", headers=H)
print("  ✓ workflow nettoyé")
