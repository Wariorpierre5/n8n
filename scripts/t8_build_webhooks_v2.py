#!/usr/bin/env python3
"""T8a (v2 — stateful tokens) — Webhook d'approbation sans crypto.

Modèle : tokens UUID-like générés au moment de l'envoi (mailer T8b),
stockés dans l'onglet Approvals avec exp_at + consumed_at. Le webhook lookup
le token, vérifie exp et consumed, applique l'action.

Schéma Approvals (8 colonnes) :
  A token | B content_id | C action | D exp_at | E created_at | F consumed_at | G ip | H user_agent
"""

import json
import os
import re
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
H = {"X-N8N-API-KEY": K, "Content-Type": "application/json"}

SHEETS_CRED = {"googleSheetsOAuth2Api": {"id": "vJiNfwvBkcQFu7Qf", "name": "Google Sheets account 2"}}
WEBHOOK_PATH = "dsc-approval"


def rewrite_approvals_header():
    """Set Approvals header to the 8-column schema."""
    new_header = ["token","content_id","action","exp_at","created_at","consumed_at","ip","user_agent"]
    WP = "t8-set-header"
    wf = {
        "name":"T8-set-approvals-header",
        "nodes":[
            {"id":"wh","name":"WH","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[0,0],"webhookId":WP,
             "parameters":{"path":WP,"httpMethod":"POST","responseMode":"responseNode"}},
            # Clear old header first (rows 1)
            {"id":"clear","name":"Clear","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[240,0],
             "credentials":SHEETS_CRED,
             "parameters":{
                "method":"POST",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Approvals!A1:Z1:clear",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "sendBody":True,"specifyBody":"json","jsonBody":"={{ JSON.stringify({}) }}",
                "options":{},
             }},
            {"id":"set","name":"Set","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[480,0],
             "credentials":SHEETS_CRED,
             "parameters":{
                "method":"PUT",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Approvals!A1:H1?valueInputOption=RAW",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "sendBody":True,"specifyBody":"json",
                "jsonBody": json.dumps({"values":[new_header]}),
                "options":{},
             }},
            {"id":"rp","name":"Resp","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,"position":[720,0],
             "parameters":{"respondWith":"json","responseBody":"={{ $json }}"}},
        ],
        "connections":{
            "WH":{"main":[[{"node":"Clear","type":"main","index":0}]]},
            "Clear":{"main":[[{"node":"Set","type":"main","index":0}]]},
            "Set":{"main":[[{"node":"Resp","type":"main","index":0}]]},
        },
        "settings":{"executionOrder":"v1"},
    }
    r = requests.post(f"{N8N}/api/v1/workflows", headers=H, json=wf)
    wf_id = r.json()["id"]
    requests.post(f"{N8N}/api/v1/workflows/{wf_id}/activate", headers=H)
    time.sleep(2)
    r = requests.post(f"{N8N}/webhook/{WP}", json={})
    print(f"  Header rewrite: HTTP {r.status_code}")
    requests.post(f"{N8N}/api/v1/workflows/{wf_id}/deactivate", headers=H)
    requests.delete(f"{N8N}/api/v1/workflows/{wf_id}", headers=H)


# === JS for the webhook workflow ===

LOOKUP_JS = """
const whJson = $node['Webhook'].json;
const query = whJson.query || {};
const headers = whJson.headers || {};
const token = (query.token || '').trim();

const approvalsResp = $input.first().json;
const rows = approvalsResp.values || [];
// Header at row 0; data row 1+ → indices in array: token=0, content_id=1, action=2, exp_at=3, created_at=4, consumed_at=5

if (!token) {
  return [{ json: { ok: false, reason: 'missing_token', http: 400, token } }];
}

let rowIdx = -1;
let row = null;
for (let i = 1; i < rows.length; i++) {
  if (rows[i][0] === token) { rowIdx = i; row = rows[i]; break; }
}
if (rowIdx === -1) {
  return [{ json: { ok: false, reason: 'token_not_found', http: 404, token } }];
}

const [tk, content_id, action, exp_at, created_at, consumed_at] = row;
const now = new Date();
const expDate = new Date(exp_at);

if (consumed_at && consumed_at.length > 0) {
  return [{ json: { ok: false, reason: 'already_consumed', http: 409, token, content_id, action, consumed_at } }];
}
if (isNaN(expDate.getTime())) {
  return [{ json: { ok: false, reason: 'bad_exp_at', http: 400, token } }];
}
if (expDate < now) {
  return [{ json: { ok: false, reason: 'expired', http: 410, token, content_id, action, exp_at } }];
}

const sheetRow = rowIdx + 1; // 1-based; header is row 1, so data row 2..
const ip = (headers['x-forwarded-for'] || headers['x-real-ip'] || 'unknown').split(',')[0].trim();
const ua = (headers['user-agent'] || 'unknown').slice(0, 200);
return [{ json: {
  ok: true, token, content_id, action,
  approvals_sheet_row: sheetRow,
  ip, ua,
  now_iso: now.toISOString(),
} }];
"""

FIND_CAL_ROW_JS = """
const verified = $node['LookupToken'].json;
const calendarResp = $input.first().json;
const rows = calendarResp.values || [];
let rowIdx = -1;
for (let i = 1; i < rows.length; i++) {
  if (rows[i][0] === verified.content_id) { rowIdx = i; break; }
}
if (rowIdx === -1) {
  return [{ json: { ...verified, error: 'content_id_not_found' } }];
}
const sheetRow = rowIdx + 1;
const statusMap = { approve: 'approved', reject: 'rejected', edit: 'needs_edit' };
return [{ json: { ...verified, calendar_sheet_row: sheetRow, calendar_range: `Content_Calendar!F${sheetRow}`, new_status: statusMap[verified.action] || 'unknown' } }];
"""

BUILD_HTML_JS = r"""
const v = $node['LookupToken'].json;

let title, msg, color, icon;
if (!v.ok) {
  const reasonMap = {
    missing_token: 'Aucun token fourni',
    token_not_found: "Lien d'approbation invalide",
    already_consumed: 'Action déjà enregistrée',
    expired: 'Le lien a expiré (TTL 48h)',
    bad_exp_at: 'Token corrompu',
  };
  title = 'Lien invalide';
  msg = reasonMap[v.reason] || v.reason || 'Erreur inconnue';
  if (v.reason === 'already_consumed') { color = '#f59e0b'; icon = '!'; title = 'Déjà utilisé'; }
  else if (v.reason === 'expired')      { color = '#f59e0b'; icon = '!'; title = 'Lien expiré'; }
  else                                  { color = '#dc2626'; icon = '✗'; }
} else {
  const verb = v.action === 'approve' ? 'approuvé' : v.action === 'reject' ? 'rejeté' : 'marqué pour édition';
  title = `Contenu ${verb}`;
  msg = `Action enregistrée pour ${v.content_id}.`;
  color = v.action === 'approve' ? '#16a34a' : v.action === 'reject' ? '#dc2626' : '#f59e0b';
  icon = v.action === 'approve' ? '✓' : v.action === 'reject' ? '✗' : '✎';
}

const html = `<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>${title}</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif; background: #f0f4ff; min-height: 100vh; display: flex; align-items: center; justify-content: center; margin: 0; }
  .card { background: white; border-radius: 16px; padding: 40px 48px; box-shadow: 0 4px 32px rgba(0,0,0,0.08); max-width: 480px; text-align: center; }
  .icon { width: 80px; height: 80px; border-radius: 50%; background: ${color}; color: white; font-size: 40px; display: flex; align-items: center; justify-content: center; margin: 0 auto 24px; font-weight: 800; }
  h1 { font-size: 1.5rem; margin: 0 0 12px; color: #1a1a2e; }
  p { font-size: 0.95rem; color: #555; line-height: 1.5; margin: 0; }
  .meta { margin-top: 24px; font-size: 0.8rem; color: #888; font-family: monospace; word-break: break-all; }
</style></head>
<body><div class="card">
  <div class="icon">${icon}</div>
  <h1>${title}</h1>
  <p>${msg}</p>
  ${v.content_id ? `<p class="meta">${v.content_id}</p>` : ''}
</div></body></html>`;

return [{ json: { html } }];
"""


def build_workflow():
    return {
        "name":"DailySmileCare-v2-Approval-Webhooks",
        "nodes":[
            # 0. Webhook GET
            {"id":"wh","name":"Webhook","type":"n8n-nodes-base.webhook","typeVersion":2,
             "position":[0,0],"webhookId":WEBHOOK_PATH,
             "parameters":{"path":WEBHOOK_PATH,"httpMethod":"GET","responseMode":"responseNode"}},

            # 1. Read Approvals
            {"id":"read_appr","name":"ReadApprovals","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[240,0],"credentials":SHEETS_CRED,
             "parameters":{
                "method":"GET",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Approvals!A1:H10000",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "options":{},
             }},

            # 2. Lookup token
            {"id":"lookup","name":"LookupToken","type":"n8n-nodes-base.code","typeVersion":2,
             "position":[480,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":LOOKUP_JS}},

            # 3. IF ok
            {"id":"if_ok","name":"IsValid","type":"n8n-nodes-base.if","typeVersion":2,
             "position":[720,0],
             "parameters":{
                "conditions":{"options":{"caseSensitive":True,"leftValue":"","typeValidation":"loose"},
                    "conditions":[{"leftValue":"={{ $json.ok }}","rightValue":True,
                                   "operator":{"type":"boolean","operation":"equals"}}],
                    "combinator":"and"},
             }},

            # 4. (valid branch) Read Content_Calendar to find row
            {"id":"read_cal","name":"ReadCalendar","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[960,-200],"credentials":SHEETS_CRED,
             "parameters":{
                "method":"GET",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Content_Calendar!A1:G1000",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "options":{},
             }},

            # 5. Find calendar row + compute update target
            {"id":"find_cal","name":"FindCalendarRow","type":"n8n-nodes-base.code","typeVersion":2,
             "position":[1200,-200],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":FIND_CAL_ROW_JS}},

            # 6. Update Content_Calendar status
            {"id":"upd_cal","name":"UpdateCalendarStatus","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[1440,-200],"credentials":SHEETS_CRED,
             "parameters":{
                "method":"PUT",
                "url":"=https://sheets.googleapis.com/v4/spreadsheets/" + SHEET_ID + "/values/{{ $json.calendar_range }}?valueInputOption=RAW",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "sendBody":True,"specifyBody":"json",
                "jsonBody":"={{ JSON.stringify({ values: [[$json.new_status]] }) }}",
                "options":{},
             }},

            # 7. Update Approvals row (consumed_at + ip + ua)
            {"id":"upd_appr","name":"UpdateApprovalsRow","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[1680,-200],"credentials":SHEETS_CRED,
             "parameters":{
                "method":"PUT",
                "url":"=https://sheets.googleapis.com/v4/spreadsheets/" + SHEET_ID + "/values/Approvals!F{{ $node['LookupToken'].json.approvals_sheet_row }}:H{{ $node['LookupToken'].json.approvals_sheet_row }}?valueInputOption=RAW",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "sendBody":True,"specifyBody":"json",
                "jsonBody":"={{ JSON.stringify({ values: [[$node['LookupToken'].json.now_iso, $node['LookupToken'].json.ip, $node['LookupToken'].json.ua]] }) }}",
                "options":{},
             }},

            # 8. Build HTML (called by both branches)
            {"id":"html","name":"BuildHTML","type":"n8n-nodes-base.code","typeVersion":2,
             "position":[1920,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":BUILD_HTML_JS}},

            # 9. Respond
            {"id":"resp","name":"Respond","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,
             "position":[2160,0],
             "parameters":{
                "respondWith":"text",
                "responseBody":"={{ $json.html }}",
                "options":{"responseHeaders":{"entries":[
                    {"name":"Content-Type","value":"text/html; charset=utf-8"},
                ]}},
             }},
        ],
        "connections":{
            "Webhook":      {"main":[[{"node":"ReadApprovals","type":"main","index":0}]]},
            "ReadApprovals":{"main":[[{"node":"LookupToken","type":"main","index":0}]]},
            "LookupToken":  {"main":[[{"node":"IsValid","type":"main","index":0}]]},
            "IsValid":      {"main":[
                [{"node":"ReadCalendar","type":"main","index":0}],   # true → proceed
                [{"node":"BuildHTML","type":"main","index":0}],      # false → respond error
            ]},
            "ReadCalendar":         {"main":[[{"node":"FindCalendarRow","type":"main","index":0}]]},
            "FindCalendarRow":      {"main":[[{"node":"UpdateCalendarStatus","type":"main","index":0}]]},
            "UpdateCalendarStatus": {"main":[[{"node":"UpdateApprovalsRow","type":"main","index":0}]]},
            "UpdateApprovalsRow":   {"main":[[{"node":"BuildHTML","type":"main","index":0}]]},
            "BuildHTML":            {"main":[[{"node":"Respond","type":"main","index":0}]]},
        },
        "settings":{"executionOrder":"v1"},
    }


def update_env(updates):
    env_path = ROOT / ".env"
    content = env_path.read_text(encoding="utf-8")
    for key, val in updates.items():
        if re.search(rf"^{key}=", content, re.M):
            content = re.sub(rf"^{key}=.*$", f"{key}={val}", content, flags=re.M)
        else:
            content += f"\n{key}={val}\n"
    env_path.write_text(content, encoding="utf-8")


def main():
    print("=== T8a v2 — Stateful tokens ===\n")

    # Delete previous webhook workflow
    r = requests.get(f"{N8N}/api/v1/workflows", headers=H)
    for w in r.json().get("data", []):
        if w["name"] == "DailySmileCare-v2-Approval-Webhooks":
            print(f"  ↻ suppression existant id={w['id']}")
            try: requests.post(f"{N8N}/api/v1/workflows/{w['id']}/deactivate", headers=H)
            except: pass
            requests.delete(f"{N8N}/api/v1/workflows/{w['id']}", headers=H)

    print("0. Rewrite Approvals header (8 colonnes)…")
    rewrite_approvals_header()

    print("1. Création du workflow…")
    r = requests.post(f"{N8N}/api/v1/workflows", headers=H, json=build_workflow())
    if r.status_code >= 400:
        print(r.text[:500]); sys.exit(1)
    wf_id = r.json()["id"]
    print(f"   id={wf_id}")
    update_env({"N8N_WORKFLOW_ID_APPROVAL_WEBHOOKS": wf_id})

    print("2. Activation…")
    requests.post(f"{N8N}/api/v1/workflows/{wf_id}/activate", headers=H)
    print("   ✓ Actif")

    print(f"\n✓ Webhook URL: {N8N}/webhook/{WEBHOOK_PATH}?token=<TOKEN>")


if __name__ == "__main__":
    main()
