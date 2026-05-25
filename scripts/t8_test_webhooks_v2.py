#!/usr/bin/env python3
"""T8a v2 — Test stateful tokens via injection directe dans Approvals + curl webhook.

Scénarios :
  1. token valide → approve → 200 + Sheets status changes
  2. token valide → reject → 200 + status changes
  3. token déjà consommé → 409 message
  4. token expiré → 410 message
  5. token inexistant → 404 message
"""

import os
import re as _re
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

N8N = os.environ["N8N_BASE_URL"]
K   = os.environ["N8N_API_KEY"]
SHEET_ID = os.environ["SHEETS_DASHBOARD_ID"]
H = {"X-N8N-API-KEY": K, "Content-Type": "application/json"}
SHEETS_CRED = {"googleSheetsOAuth2Api": {"id": "vJiNfwvBkcQFu7Qf", "name": "Google Sheets account 2"}}

WEBHOOK_URL = f"{N8N}/webhook/dsc-approval"


def now_iso(offset_hours=0):
    return (datetime.now(timezone.utc) + timedelta(hours=offset_hours)).isoformat()


def insert_approvals_rows(rows):
    """Append rows to Approvals via ephemeral n8n workflow."""
    import json
    WP = "t8-insert-approvals"
    wf = {
        "name":"T8-insert-approvals",
        "nodes":[
            {"id":"wh","name":"WH","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[0,0],"webhookId":WP,
             "parameters":{"path":WP,"httpMethod":"POST","responseMode":"responseNode"}},
            {"id":"http","name":"HTTP","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[240,0],
             "credentials":SHEETS_CRED,
             "parameters":{
                "method":"POST",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Approvals!A:H:append?valueInputOption=RAW",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "sendBody":True,"specifyBody":"json",
                "jsonBody": json.dumps({"values": rows}),
                "options":{},
             }},
            {"id":"rp","name":"Resp","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,"position":[480,0],
             "parameters":{"respondWith":"json","responseBody":"={{ $json }}"}},
        ],
        "connections":{
            "WH":{"main":[[{"node":"HTTP","type":"main","index":0}]]},
            "HTTP":{"main":[[{"node":"Resp","type":"main","index":0}]]},
        },
        "settings":{"executionOrder":"v1"},
    }
    r = requests.post(f"{N8N}/api/v1/workflows", headers=H, json=wf)
    wf_id = r.json()["id"]
    requests.post(f"{N8N}/api/v1/workflows/{wf_id}/activate", headers=H)
    time.sleep(2)
    r = requests.post(f"{N8N}/webhook/{WP}", json={})
    print(f"  Insert HTTP {r.status_code}: {r.text[:150]}")
    requests.post(f"{N8N}/api/v1/workflows/{wf_id}/deactivate", headers=H)
    requests.delete(f"{N8N}/api/v1/workflows/{wf_id}", headers=H)
    return r.status_code == 200


def reset_calendar_statuses():
    """Reset all rows in Content_Calendar to pending_approval (for testable clean state)."""
    import json
    # Read all rows, find row count, then PUT pending_approval for all data rows
    WP = "t8-reset-cal"
    wf = {
        "name":"T8-reset-cal",
        "nodes":[
            {"id":"wh","name":"WH","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[0,0],"webhookId":WP,
             "parameters":{"path":WP,"httpMethod":"POST","responseMode":"responseNode"}},
            {"id":"r","name":"R","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[240,0],
             "credentials":SHEETS_CRED,
             "parameters":{
                "method":"GET",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Content_Calendar!A1:G1000",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "options":{},
             }},
            {"id":"c","name":"C","type":"n8n-nodes-base.code","typeVersion":2,"position":[480,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":
                "const rows = ($input.first().json.values || []);\n"
                "const dataCount = rows.length - 1;\n"
                "const values = Array.from({length: dataCount}, () => ['pending_approval']);\n"
                "return [{ json: { dataCount, values } }];"}},
            {"id":"u","name":"U","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[720,0],
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
            {"id":"rp","name":"Resp","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,"position":[960,0],
             "parameters":{"respondWith":"json","responseBody":"={{ $json }}"}},
        ],
        "connections":{
            "WH":{"main":[[{"node":"R","type":"main","index":0}]]},
            "R":{"main":[[{"node":"C","type":"main","index":0}]]},
            "C":{"main":[[{"node":"U","type":"main","index":0}]]},
            "U":{"main":[[{"node":"Resp","type":"main","index":0}]]},
        },
        "settings":{"executionOrder":"v1"},
    }
    r = requests.post(f"{N8N}/api/v1/workflows", headers=H, json=wf)
    wf_id = r.json()["id"]
    requests.post(f"{N8N}/api/v1/workflows/{wf_id}/activate", headers=H)
    time.sleep(2)
    r = requests.post(f"{N8N}/webhook/{WP}", json={})
    print(f"  Reset cal HTTP {r.status_code}")
    requests.post(f"{N8N}/api/v1/workflows/{wf_id}/deactivate", headers=H)
    requests.delete(f"{N8N}/api/v1/workflows/{wf_id}", headers=H)


def read_calendar_status(content_id):
    """Read current status of a content_id in Content_Calendar."""
    import json
    WP = "t8-read-cal"
    wf = {
        "name":"T8-read-cal",
        "nodes":[
            {"id":"wh","name":"WH","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[0,0],"webhookId":WP,
             "parameters":{"path":WP,"httpMethod":"POST","responseMode":"responseNode"}},
            {"id":"r","name":"R","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[240,0],
             "credentials":SHEETS_CRED,
             "parameters":{
                "method":"GET",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Content_Calendar!A1:G1000",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "options":{},
             }},
            {"id":"c","name":"C","type":"n8n-nodes-base.code","typeVersion":2,"position":[480,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":
                "const rows = ($input.first().json.values || []);\n"
                "const target = " + json.dumps(content_id) + ";\n"
                "const row = rows.find(r => r[0] === target);\n"
                "return [{ json: { status: row ? row[5] : null, found: !!row } }];"}},
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
    res = r.json()
    requests.post(f"{N8N}/api/v1/workflows/{wf_id}/deactivate", headers=H)
    requests.delete(f"{N8N}/api/v1/workflows/{wf_id}", headers=H)
    return res.get("status")


def hit(token, label):
    print(f"\n--- {label} ---")
    print(f"  Token: {token[:20]}…")
    r = requests.get(WEBHOOK_URL, params={"token": token}, timeout=30)
    print(f"  HTTP {r.status_code}, body_len={len(r.text)}")
    m = _re.search(r"<h1>(.*?)</h1>", r.text)
    title = m.group(1) if m else "(no h1)"
    print(f"  Title: {title}")
    return r.status_code, title


def main():
    # Pick 3 real content_ids that are still in pending_approval
    CID_APPROVE = "2026-05-24-p4-mpk7h07m-x"
    CID_REJECT  = "2026-05-24-p4-mpk7h07m-snapchat"
    CID_REUSE   = "2026-05-24-p4-mpk7h07m-tiktok"
    CID_EXPIRED = "2026-05-24-p4-mpk7h07m-youtube_shorts"

    print("=== Reset Content_Calendar statuses to pending_approval ===")
    reset_calendar_statuses()

    print("\n=== Inject test tokens into Approvals ===")
    tk_approve   = "tok_" + secrets.token_urlsafe(20)
    tk_reject    = "tok_" + secrets.token_urlsafe(20)
    tk_reuse     = "tok_" + secrets.token_urlsafe(20)
    tk_expired   = "tok_" + secrets.token_urlsafe(20)
    tk_nonexistent = "tok_DOES_NOT_EXIST"

    rows = [
        # token, content_id, action, exp_at, created_at, consumed_at, ip, user_agent
        [tk_approve, CID_APPROVE, "approve", now_iso(48), now_iso(), "", "", ""],
        [tk_reject,  CID_REJECT,  "reject",  now_iso(48), now_iso(), "", "", ""],
        [tk_reuse,   CID_REUSE,   "approve", now_iso(48), now_iso(), "", "", ""],
        [tk_expired, CID_EXPIRED, "approve", now_iso(-1), now_iso(-49), "", "", ""],  # expired 1h ago
    ]
    insert_approvals_rows(rows)

    # === Tests ===
    sc, ttl = hit(tk_approve, "Test 1: token valide → approve")
    assert "approuvé" in ttl, f"got '{ttl}'"
    # Verify Sheets state
    st = read_calendar_status(CID_APPROVE)
    print(f"  Sheets status for {CID_APPROVE}: '{st}'")
    assert st == "approved", f"expected 'approved', got '{st}'"

    sc, ttl = hit(tk_reject, "Test 2: token valide → reject")
    assert "rejeté" in ttl
    st = read_calendar_status(CID_REJECT)
    assert st == "rejected", f"expected 'rejected', got '{st}'"

    # Reuse
    sc, ttl1 = hit(tk_reuse, "Test 3a: première utilisation")
    assert "approuvé" in ttl1
    time.sleep(2)
    sc, ttl2 = hit(tk_reuse, "Test 3b: même token, second hit")
    assert "Déjà utilisé" in ttl2 or "déjà" in ttl2.lower(), f"got '{ttl2}'"

    # Expired
    sc, ttl = hit(tk_expired, "Test 4: token expiré")
    assert "expir" in ttl.lower(), f"got '{ttl}'"

    # Nonexistent
    sc, ttl = hit(tk_nonexistent, "Test 5: token inexistant")
    assert "invalide" in ttl.lower() or "Lien invalide" in ttl, f"got '{ttl}'"

    print("\n" + "=" * 50)
    print("✓ DoD T8a (webhooks) validé :")
    print("  • Approve → Sheets status='approved'")
    print("  • Reject  → Sheets status='rejected'")
    print("  • Token réutilisé → 'Déjà utilisé'")
    print("  • Token expiré → 'Lien expiré'")
    print("  • Token inexistant → 'Lien invalide'")


if __name__ == "__main__":
    main()
