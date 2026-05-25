#!/usr/bin/env python3
"""T8a — Construit le workflow `DailySmileCare-v2-Approval-Webhooks`.

Un webhook unique `/webhook/dsc-approval` qui accepte 3 actions (approve/reject/edit)
via query string. Le token HMAC porte (content_id, action, exp). Verify + idempotence
(check token_hash dans Approvals) + update Content_Calendar.status + log.
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
HMAC_KEY = os.environ["APPROVAL_HMAC_KEY"]
H = {"X-N8N-API-KEY": K, "Content-Type": "application/json"}

SHEETS_CRED = {"googleSheetsOAuth2Api": {"id": "vJiNfwvBkcQFu7Qf", "name": "Google Sheets account 2"}}

WEBHOOK_PATH = "dsc-approval"

# === JS pour les Code nodes ===

VERIFY_JS = r"""
const KEY_HEX = '__HMAC_KEY__';

const query = $input.first().json.query || {};
const tokenB64 = (query.token || '').trim();

function b64urlDecode(s) {
  // unpad
  s = s.replace(/-/g, '+').replace(/_/g, '/');
  while (s.length % 4) s += '=';
  return Buffer.from(s, 'base64').toString('utf8');
}

function fail(reason, http = 400) {
  return [{ json: { ok: false, reason, http, raw_token: tokenB64 } }];
}

if (!tokenB64) return fail('missing_token');

let raw;
try { raw = b64urlDecode(tokenB64); } catch (e) { return fail('malformed_b64'); }
const parts = raw.split('|');
if (parts.length !== 4) return fail('malformed_payload');

const [content_id, action, expStr, sig] = parts;
if (!['approve', 'reject', 'edit'].includes(action)) return fail('bad_action');

const exp = parseInt(expStr, 10);
if (isNaN(exp)) return fail('bad_exp');
if (exp < Math.floor(Date.now() / 1000)) return fail('expired', 410);

const crypto = require('crypto');
const payload = `${content_id}|${action}|${expStr}`;
const expectedSig = crypto.createHmac('sha256', Buffer.from(KEY_HEX, 'hex'))
  .update(payload).digest('hex').slice(0, 32);
if (sig !== expectedSig) return fail('bad_signature');

const token_hash = crypto.createHash('sha256').update(tokenB64).digest('hex');

return [{
  json: {
    ok: true,
    content_id,
    action,
    exp,
    token_hash,
    raw_token: tokenB64,
    http: 200,
  },
}];
""".replace("__HMAC_KEY__", HMAC_KEY)


CHECK_REUSE_JS = """
const verified = $node['VerifyToken'].json;
const approvalsResp = $input.first().json;
const rows = approvalsResp.values || [];
// Approvals header is row[0]; data starts row[1]. Column B (index 1) is token_hash.
const dataRows = rows.slice(1);
const used = dataRows.some(r => r[1] === verified.token_hash);
return [{ json: { ...verified, reused: used } }];
"""


FIND_AND_UPDATE_JS = """
const verified = $node['VerifyToken'].json;
const calendarResp = $input.first().json;
const rows = calendarResp.values || [];
// Find row index in Content_Calendar where col A (content_id) === verified.content_id
let rowIdx = -1;
for (let i = 1; i < rows.length; i++) {
  if (rows[i][0] === verified.content_id) { rowIdx = i; break; }
}
if (rowIdx === -1) {
  return [{ json: { ...verified, error: 'content_id_not_found' } }];
}

// Sheets is 1-based and includes header row, so target row = rowIdx + 1
const sheetRow = rowIdx + 1;
const targetRange = `Content_Calendar!F${sheetRow}`;

const statusMap = {
  approve: 'approved',
  reject:  'rejected',
  edit:    'needs_edit',
};
const newStatus = statusMap[verified.action];

return [{
  json: {
    ...verified,
    rowIdx, sheetRow, targetRange, newStatus,
  },
}];
"""


BUILD_APPROVAL_ROW_JS = r"""
const verified = $node['FindAndUpdate'].json;
const headers = $input.first().json.headers || {};

const ip = (headers['x-forwarded-for'] || headers['x-real-ip'] || 'unknown').split(',')[0].trim();
const ua = (headers['user-agent'] || 'unknown').slice(0, 200);
const ts = new Date().toISOString();

return [{ json: {
  approvalRow: [
    verified.content_id,
    verified.token_hash,
    verified.action,
    ts,
    ip,
    ua,
  ],
  ...verified,
} }];
"""


BUILD_HTML_JS = r"""
// Build HTML response based on the upstream branch
const isReused = $node['CheckReuse'] && $node['CheckReuse'].json && $node['CheckReuse'].json.reused;
const verified = $node['VerifyToken'].json;

let title, msg, color, icon;
if (!verified.ok) {
  title = 'Lien invalide';
  msg = `Le lien d'approbation n'est pas valide. Raison : ${verified.reason}`;
  color = '#dc2626'; icon = '✗';
} else if (isReused) {
  title = 'Lien déjà utilisé';
  msg = `Cette action a déjà été enregistrée. Aucune modification effectuée.`;
  color = '#f59e0b'; icon = '!';
} else {
  const action = verified.action;
  const verb = action === 'approve' ? 'approuvé' : action === 'reject' ? 'rejeté' : 'marqué pour édition';
  title = `Contenu ${verb}`;
  msg = `Action enregistrée pour ${verified.content_id}.`;
  color = action === 'approve' ? '#16a34a' : action === 'reject' ? '#dc2626' : '#f59e0b';
  icon = action === 'approve' ? '✓' : action === 'reject' ? '✗' : '✎';
}

const html = `<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>${title}</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif; background: #f0f4ff; min-height: 100vh; display: flex; align-items: center; justify-content: center; margin: 0; }
  .card { background: white; border-radius: 16px; padding: 40px 48px; box-shadow: 0 4px 32px rgba(0,0,0,0.08); max-width: 480px; text-align: center; }
  .icon { width: 80px; height: 80px; border-radius: 50%; background: ${color}; color: white; font-size: 40px; display: flex; align-items: center; justify-content: center; margin: 0 auto 24px; font-weight: 800; }
  h1 { font-size: 1.5rem; margin: 0 0 12px; color: #1a1a2e; }
  p { font-size: 0.95rem; color: #555; line-height: 1.5; margin: 0; }
  .meta { margin-top: 24px; font-size: 0.8rem; color: #888; font-family: monospace; }
</style></head>
<body><div class="card">
  <div class="icon">${icon}</div>
  <h1>${title}</h1>
  <p>${msg}</p>
  ${verified.content_id ? `<p class="meta">${verified.content_id}</p>` : ''}
</div></body></html>`;

return [{ json: { html } }];
"""


def build_workflow():
    return {
        "name": "DailySmileCare-v2-Approval-Webhooks",
        "nodes": [
            # 0. Webhook trigger (GET)
            {"id":"wh","name":"Webhook","type":"n8n-nodes-base.webhook","typeVersion":2,
             "position":[0,0],"webhookId":WEBHOOK_PATH,
             "parameters":{"path":WEBHOOK_PATH,"httpMethod":"GET","responseMode":"responseNode"}},

            # 1. Verify token
            {"id":"verify","name":"VerifyToken","type":"n8n-nodes-base.code","typeVersion":2,
             "position":[240,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":VERIFY_JS}},

            # 2. IF token valid
            {"id":"if_valid","name":"IsValid","type":"n8n-nodes-base.if","typeVersion":2,
             "position":[480,0],
             "parameters":{
                "conditions":{"options":{"caseSensitive":True,"leftValue":"","typeValidation":"loose"},
                    "conditions":[{"leftValue":"={{ $json.ok }}","rightValue":True,
                                   "operator":{"type":"boolean","operation":"equals"}}],
                    "combinator":"and"},
             }},

            # 3a. Valid branch: read Approvals to check reuse
            {"id":"read_appr","name":"ReadApprovals","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[720,-150],"credentials":SHEETS_CRED,
             "parameters":{
                "method":"GET",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Approvals!A1:F1000",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "options":{},
             }},

            # 3b. Check reuse
            {"id":"check_reuse","name":"CheckReuse","type":"n8n-nodes-base.code","typeVersion":2,
             "position":[960,-150],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":CHECK_REUSE_JS}},

            # 3c. IF reused
            {"id":"if_reused","name":"IsReused","type":"n8n-nodes-base.if","typeVersion":2,
             "position":[1200,-150],
             "parameters":{
                "conditions":{"options":{"caseSensitive":True,"leftValue":"","typeValidation":"loose"},
                    "conditions":[{"leftValue":"={{ $json.reused }}","rightValue":True,
                                   "operator":{"type":"boolean","operation":"equals"}}],
                    "combinator":"and"},
             }},

            # 4a. Fresh token branch: read Content_Calendar to find row
            {"id":"read_cal","name":"ReadCalendar","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[1440,-300],"credentials":SHEETS_CRED,
             "parameters":{
                "method":"GET",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Content_Calendar!A1:G1000",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "options":{},
             }},

            # 4b. Find row + compute update range
            {"id":"find_upd","name":"FindAndUpdate","type":"n8n-nodes-base.code","typeVersion":2,
             "position":[1680,-300],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":FIND_AND_UPDATE_JS}},

            # 4c. Update the status cell
            {"id":"upd_status","name":"UpdateStatus","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[1920,-300],"credentials":SHEETS_CRED,
             "parameters":{
                "method":"PUT",
                "url":"=https://sheets.googleapis.com/v4/spreadsheets/" + SHEET_ID + "/values/{{ $json.targetRange }}?valueInputOption=RAW",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "sendBody":True,"specifyBody":"json",
                "jsonBody":"={{ JSON.stringify({ values: [[$json.newStatus]] }) }}",
                "options":{},
             }},

            # 4d. Build the Approvals row payload (uses webhook headers)
            {"id":"build_row","name":"BuildApprovalRow","type":"n8n-nodes-base.code","typeVersion":2,
             "position":[2160,-300],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":BUILD_APPROVAL_ROW_JS}},

            # 4e. Append to Approvals
            {"id":"app_appr","name":"AppendApprovals","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[2400,-300],"credentials":SHEETS_CRED,
             "parameters":{
                "method":"POST",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Approvals!A:F:append?valueInputOption=RAW",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "sendBody":True,"specifyBody":"json",
                "jsonBody":"={{ JSON.stringify({ values: [$json.approvalRow] }) }}",
                "options":{},
             }},

            # 5. Build HTML response (called by all terminal branches)
            {"id":"html","name":"BuildHTML","type":"n8n-nodes-base.code","typeVersion":2,
             "position":[2640,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":BUILD_HTML_JS}},

            # 6. Respond
            {"id":"resp","name":"Respond","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,
             "position":[2880,0],
             "parameters":{
                "respondWith":"text",
                "responseBody":"={{ $json.html }}",
                "options":{"responseHeaders":{"entries":[
                    {"name":"Content-Type","value":"text/html; charset=utf-8"},
                ]}},
             }},
        ],
        "connections":{
            "Webhook":         {"main":[[{"node":"VerifyToken","type":"main","index":0}]]},
            "VerifyToken":     {"main":[[{"node":"IsValid","type":"main","index":0}]]},
            "IsValid":         {"main":[
                [{"node":"ReadApprovals","type":"main","index":0}],  # true → check reuse
                [{"node":"BuildHTML","type":"main","index":0}],      # false → respond invalid
            ]},
            "ReadApprovals":   {"main":[[{"node":"CheckReuse","type":"main","index":0}]]},
            "CheckReuse":      {"main":[[{"node":"IsReused","type":"main","index":0}]]},
            "IsReused":        {"main":[
                [{"node":"BuildHTML","type":"main","index":0}],      # true → respond already used
                [{"node":"ReadCalendar","type":"main","index":0}],   # false → proceed to update
            ]},
            "ReadCalendar":    {"main":[[{"node":"FindAndUpdate","type":"main","index":0}]]},
            "FindAndUpdate":   {"main":[[{"node":"UpdateStatus","type":"main","index":0}]]},
            "UpdateStatus":    {"main":[[{"node":"BuildApprovalRow","type":"main","index":0}]]},
            "BuildApprovalRow":{"main":[[{"node":"AppendApprovals","type":"main","index":0}]]},
            "AppendApprovals": {"main":[[{"node":"BuildHTML","type":"main","index":0}]]},
            "BuildHTML":       {"main":[[{"node":"Respond","type":"main","index":0}]]},
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
    print("=== T8a — Build & deploy DailySmileCare-v2-Approval-Webhooks ===\n")

    # Check if workflow exists; delete if so (for clean re-deploy)
    r = requests.get(f"{N8N}/api/v1/workflows", headers=H)
    for w in r.json().get("data", []):
        if w["name"] == "DailySmileCare-v2-Approval-Webhooks":
            print(f"  ↻ existant id={w['id']}, suppression…")
            try:
                requests.post(f"{N8N}/api/v1/workflows/{w['id']}/deactivate", headers=H)
            except: pass
            requests.delete(f"{N8N}/api/v1/workflows/{w['id']}", headers=H)

    print("1. Création du workflow…")
    r = requests.post(f"{N8N}/api/v1/workflows", headers=H, json=build_workflow())
    if r.status_code >= 400:
        print(r.status_code, r.text[:500]); sys.exit(1)
    wf_id = r.json()["id"]
    print(f"   id={wf_id}")
    update_env({"N8N_WORKFLOW_ID_APPROVAL_WEBHOOKS": wf_id})

    print("2. Activation…")
    r = requests.post(f"{N8N}/api/v1/workflows/{wf_id}/activate", headers=H)
    if r.status_code >= 400:
        print(r.status_code, r.text[:300]); sys.exit(1)
    print("   ✓ Actif")

    print(f"\n✓ Webhook URL : {N8N}/webhook/{WEBHOOK_PATH}?token=...")


if __name__ == "__main__":
    main()
