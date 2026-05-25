#!/usr/bin/env python3
"""T8b — Test du mailer end-to-end.

Étapes :
  1. Reset Content_Calendar (toutes lignes → pending_approval)
  2. Clear Approvals (garde header)
  3. Activate mailer + trigger via webhook
  4. Vérifier : Approvals contient 15 nouveaux tokens (5 contenus × 3 actions)
  5. Vérifier : Gmail sent (l'utilisateur valide visuellement)
"""

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
MAILER_WF = os.environ["N8N_WORKFLOW_ID_APPROVAL_MAILER"]
WEBHOOK_WF = os.environ["N8N_WORKFLOW_ID_APPROVAL_WEBHOOKS"]
H = {"X-N8N-API-KEY": K, "Content-Type": "application/json"}
SHEETS_CRED = {"googleSheetsOAuth2Api": {"id": "vJiNfwvBkcQFu7Qf", "name": "Google Sheets account 2"}}


def reset_state():
    """Reset Content_Calendar to pending + clear Approvals data rows."""
    WP = "t8-reset-all"
    wf = {
        "name":"T8-reset-all",
        "nodes":[
            {"id":"wh","name":"WH","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[0,0],"webhookId":WP,
             "parameters":{"path":WP,"httpMethod":"POST","responseMode":"responseNode"}},
            {"id":"r1","name":"R1","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[240,0],
             "credentials":SHEETS_CRED,
             "parameters":{
                "method":"GET",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Content_Calendar!A1:G1000",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api","options":{},
             }},
            {"id":"c1","name":"C1","type":"n8n-nodes-base.code","typeVersion":2,"position":[480,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":
                "const rows = ($input.first().json.values || []);"
                "const dataCount = rows.length - 1;"
                "const values = Array.from({length: dataCount}, () => ['pending_approval']);"
                "return [{ json: { dataCount, values } }];"}},
            {"id":"u1","name":"U1","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[720,0],
             "credentials":SHEETS_CRED,
             "parameters":{
                "method":"PUT",
                "url":"=https://sheets.googleapis.com/v4/spreadsheets/" + SHEET_ID + "/values/Content_Calendar!F2:F{{ $json.dataCount + 1 }}?valueInputOption=RAW",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "sendBody":True,"specifyBody":"json",
                "jsonBody":"={{ JSON.stringify({ values: $json.values }) }}",
                "options":{},
             }},
            # Clear Approvals data (rows 2:1000)
            {"id":"clr","name":"ClearApprovals","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[960,0],"credentials":SHEETS_CRED,
             "parameters":{
                "method":"POST",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Approvals!A2:H10000:clear",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "sendBody":True,"specifyBody":"json","jsonBody":"={{ JSON.stringify({}) }}",
                "options":{},
             }},
            {"id":"rp","name":"Resp","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,"position":[1200,0],
             "parameters":{"respondWith":"json","responseBody":"={{ $json }}"}},
        ],
        "connections":{
            "WH":{"main":[[{"node":"R1","type":"main","index":0}]]},
            "R1":{"main":[[{"node":"C1","type":"main","index":0}]]},
            "C1":{"main":[[{"node":"U1","type":"main","index":0}]]},
            "U1":{"main":[[{"node":"ClearApprovals","type":"main","index":0}]]},
            "ClearApprovals":{"main":[[{"node":"Resp","type":"main","index":0}]]},
        },
        "settings":{"executionOrder":"v1"},
    }
    r = requests.post(f"{N8N}/api/v1/workflows", headers=H, json=wf)
    wf_id = r.json()["id"]
    requests.post(f"{N8N}/api/v1/workflows/{wf_id}/activate", headers=H)
    time.sleep(2)
    r = requests.post(f"{N8N}/webhook/{WP}", json={})
    print(f"  Reset HTTP {r.status_code}: {r.text[:150]}")
    requests.post(f"{N8N}/api/v1/workflows/{wf_id}/deactivate", headers=H)
    requests.delete(f"{N8N}/api/v1/workflows/{wf_id}", headers=H)


def count_approvals():
    WP = "t8-count-appr"
    wf = {
        "name":"T8-count-appr",
        "nodes":[
            {"id":"wh","name":"WH","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[0,0],"webhookId":WP,
             "parameters":{"path":WP,"httpMethod":"POST","responseMode":"responseNode"}},
            {"id":"r","name":"R","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[240,0],
             "credentials":SHEETS_CRED,
             "parameters":{
                "method":"GET",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Approvals!A1:H10000",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api","options":{},
             }},
            {"id":"c","name":"C","type":"n8n-nodes-base.code","typeVersion":2,"position":[480,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":
                "const rows = ($input.first().json.values || []);"
                "const dataRows = rows.slice(1);"
                "const actionCounts = {};"
                "dataRows.forEach(r => { const a = r[2]; actionCounts[a] = (actionCounts[a]||0)+1; });"
                "return [{ json: { total: dataRows.length, actions: actionCounts, sample: dataRows.slice(0, 3) } }];"}},
            {"id":"rp","name":"Resp","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,"position":[720,0],
             "parameters":{"respondWith":"json","responseBody":"={{ $json }}"}},
        ],
        "connections":{
            "WH":{"main":[[{"node":"R","type":"main","index":0}]]},
            "R":{"main":[[{"node":"C","type":"main","index":0}]]},
            "C":{"main":[[{"node":"Resp","type":"main","index":0}]]},
        },
        "settings":{"executionOrder":"v1"},
    }
    r = requests.post(f"{N8N}/api/v1/workflows", headers=H, json=wf)
    wf_id = r.json()["id"]
    requests.post(f"{N8N}/api/v1/workflows/{wf_id}/activate", headers=H)
    time.sleep(2)
    r = requests.post(f"{N8N}/webhook/{WP}", json={})
    requests.post(f"{N8N}/api/v1/workflows/{wf_id}/deactivate", headers=H)
    requests.delete(f"{N8N}/api/v1/workflows/{wf_id}", headers=H)
    return r.json()


def main():
    print("=== T8b — Test mailer end-to-end ===\n")

    print("1. Reset Content_Calendar + clear Approvals…")
    reset_state()

    print("2. Activate mailer + trigger via webhook…")
    requests.post(f"{N8N}/api/v1/workflows/{MAILER_WF}/activate", headers=H)
    time.sleep(2)
    r = requests.post(f"{N8N}/webhook/dsc-mailer-run", json={}, timeout=120)
    print(f"   HTTP {r.status_code}")
    print(f"   Body: {r.text[:400]}")
    if r.status_code != 200:
        print("   ✗ Mailer trigger échoué")
        sys.exit(1)

    print("\n3. Vérification Approvals…")
    time.sleep(2)
    counts = count_approvals()
    print(f"   Total tokens dans Approvals : {counts.get('total')}")
    print(f"   Par action                  : {counts.get('actions')}")
    print(f"   Échantillon (3 premières) : {json.dumps(counts.get('sample', []), indent=2)[:600]}")

    expected = 15  # 5 contenus pending × 3 actions
    ok_count = counts.get("total", 0) == expected and \
               counts.get("actions", {}).get("approve", 0) == 5 and \
               counts.get("actions", {}).get("reject", 0) == 5 and \
               counts.get("actions", {}).get("edit", 0) == 5

    print()
    print("=== DoD T8b ===")
    print(f"  Tokens créés (5×3=15)   : {counts.get('total')} {'✓' if ok_count else '✗'}")
    print(f"  Email Gmail envoyé      : à vérifier dans affiliate@trentecinq.fr ✉")
    print(f"\n  Vas ouvrir Gmail → check inbox pour l'email")
    print(f"  Subject attendu : [DAILY APPROVAL] 5 contenus prévus pour 2026-05-24")


if __name__ == "__main__":
    main()
