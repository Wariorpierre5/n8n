#!/usr/bin/env python3
"""T8b — Construit le workflow `DailySmileCare-v2-Approval-Mailer`.

Pipeline :
  ManualTrigger / Schedule(09h00 ET)
  → ReadCalendar (pending_approval seulement)
  → ReadCostTracker (pour coût par content_id)
  → PrepareApprovalsAndEmail (génère 3 tokens × N contenus + HTML email)
  → AppendApprovals (batch insert)
  → SendGmail
  → Respond
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
GMAIL_CRED  = {"gmailOAuth2": {"id": "tEVhfPjmCZsQVwA8", "name": "Gmail account"}}

GMAIL_RECIPIENT = "affiliatetrentecinq@gmail.com"
WEBHOOK_BASE = f"{N8N}/webhook/dsc-approval"

# Bootstrap revenue constants from ARCHITECTURE §8
TRAFIC_BY_PLATFORM = {
    "instagram_reel": 80,
    "youtube_shorts": 250,
    "x": 30,
    "tiktok": 200,
    "snapchat": 50,
}

# Build everything (Approvals rows + email HTML) in a single Code node
PREPARE_JS = r"""
const calRows = $node['ReadCalendar'].json.values || [];
const costRows = $node['ReadCostTracker'].json.values || [];
const personasRows = $node['ReadPersonas'].json.values || [];

// Maps
const costByContentId = {};
for (let i = 1; i < costRows.length; i++) {
  const r = costRows[i];
  if (r && r[1]) costByContentId[r[1]] = parseFloat(r[5] || '0');
}
const personaById = {};
for (let i = 1; i < personasRows.length; i++) {
  const r = personasRows[i];
  if (r && r[0]) personaById[r[0]] = { id: r[0], name: r[1], region: r[3] };
}

// Filter Content_Calendar to pending_approval
const pending = [];
for (let i = 1; i < calRows.length; i++) {
  const r = calRows[i];
  if (r && r[5] === 'pending_approval') {
    pending.push({
      content_id: r[0],
      date: r[1],
      persona_id: r[2],
      platform: r[3],
      type: r[4],
      status: r[5],
    });
  }
}

if (pending.length === 0) {
  return [{ json: { skip: true, message: 'Aucun contenu pending_approval' } }];
}

// Constants for revenue estimate (architecture §8)
const TRAFIC = __TRAFIC_JSON__;
const CTR = 0.012, CONV = 0.025, COMMISSION = 0.03, PANIER = 80;

function genToken() {
  // Random token: 22 chars urlsafe
  let out = '';
  const chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_';
  for (let i = 0; i < 22; i++) out += chars[Math.floor(Math.random() * chars.length)];
  return 'tok_' + out;
}

const nowISO = new Date().toISOString();
const expISO = new Date(Date.now() + 48 * 3600 * 1000).toISOString();
const ACTIONS = ['approve', 'reject', 'edit'];
const approvalsRows = [];
const cards = [];

for (const c of pending) {
  const persona = personaById[c.persona_id] || { name: 'Persona ' + c.persona_id, region: '?' };
  const cost = costByContentId[c.content_id] || 0;
  const traffic = TRAFIC[c.platform] || 50;
  const revenueMid = traffic * CTR * CONV * COMMISSION * PANIER;
  const revenueLow = revenueMid * 0.5;
  const revenueHigh = revenueMid * 2.3;

  const tokens = {};
  for (const action of ACTIONS) {
    const tok = genToken();
    tokens[action] = tok;
    approvalsRows.push([tok, c.content_id, action, expISO, nowISO, '', '', '']);
  }

  cards.push({
    persona_name: persona.name,
    platform: c.platform,
    content_id: c.content_id,
    cost: cost,
    revenue_low: revenueLow,
    revenue_high: revenueHigh,
    approve_url: '__WEBHOOK_BASE__?token=' + tokens.approve,
    reject_url:  '__WEBHOOK_BASE__?token=' + tokens.reject,
    edit_url:    '__WEBHOOK_BASE__?token=' + tokens.edit,
  });
}

// Build HTML email
const PLATFORM_LABELS = {
  x: 'X (Twitter)',
  youtube_shorts: 'YouTube Shorts',
  instagram_reel: 'Instagram Reel',
  tiktok: 'TikTok',
  snapchat: 'Snapchat',
};

const PLATFORM_ICONS = {
  x: '𝕏', youtube_shorts: '▶', instagram_reel: '📷', tiktok: '♪', snapchat: '👻',
};

const cardsHTML = cards.map(c => `
<table cellspacing="0" cellpadding="0" border="0" style="width:100%;background:#fff;border:1px solid #e2e8f0;border-radius:12px;margin-bottom:16px">
  <tr><td style="padding:16px 20px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <div style="font-size:0.75rem;color:#666;text-transform:uppercase;letter-spacing:0.5px;font-weight:700">
        ${PLATFORM_ICONS[c.platform] || '•'} ${PLATFORM_LABELS[c.platform] || c.platform}
      </div>
      <div style="font-size:0.7rem;color:#888;font-family:monospace">${c.content_id}</div>
    </div>
    <div style="font-size:1.1rem;font-weight:800;color:#1a1a2e;margin-bottom:14px">${c.persona_name}</div>
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:18px;font-size:0.85rem;color:#444">
      <span>💰 <strong>$${c.cost.toFixed(4)}</strong></span>
      <span>📈 <strong>~50%</strong></span>
      <span>💵 <strong>$${c.revenue_low.toFixed(2)}–$${c.revenue_high.toFixed(2)}</strong></span>
    </div>
    <div>
      <a href="${c.approve_url}" style="display:inline-block;background:#16a34a;color:#fff;text-decoration:none;padding:10px 18px;border-radius:6px;font-weight:700;margin-right:6px;font-size:0.85rem">✓ Approve</a>
      <a href="${c.reject_url}"  style="display:inline-block;background:#dc2626;color:#fff;text-decoration:none;padding:10px 18px;border-radius:6px;font-weight:700;margin-right:6px;font-size:0.85rem">✗ Reject</a>
      <a href="${c.edit_url}"    style="display:inline-block;background:#f59e0b;color:#fff;text-decoration:none;padding:10px 18px;border-radius:6px;font-weight:700;font-size:0.85rem">✎ Edit</a>
    </div>
  </td></tr>
</table>
`).join('');

const subject = `[DAILY APPROVAL] ${pending.length} contenu${pending.length>1?'s':''} prévu${pending.length>1?'s':''} pour ${pending[0].date}`;

const htmlBody = `<!DOCTYPE html>
<html><body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;background:#f0f4ff;margin:0;padding:24px 12px;color:#1a1a2e">
<table cellspacing="0" cellpadding="0" border="0" style="max-width:640px;margin:0 auto;width:100%">
  <tr><td>
    <h1 style="font-size:1.4rem;font-weight:900;margin:0 0 6px">${pending.length} contenu${pending.length>1?'s':''} à valider</h1>
    <p style="font-size:0.85rem;color:#666;margin:0 0 22px">Approuve, rejette ou marque pour édition. Les liens expirent dans 48h.</p>
    ${cardsHTML}
    <p style="font-size:0.75rem;color:#888;text-align:center;margin-top:24px">DailySmileCare — automation pipeline</p>
  </td></tr>
</table>
</body></html>`;

return [{
  json: {
    skip: false,
    pending_count: pending.length,
    approvals_rows: approvalsRows,
    subject,
    htmlBody,
  },
}];
""".replace("__TRAFIC_JSON__", json.dumps(TRAFIC_BY_PLATFORM)) \
   .replace("__WEBHOOK_BASE__", WEBHOOK_BASE)


def build_workflow():
    return {
        "name":"DailySmileCare-v2-Approval-Mailer",
        "nodes":[
            # 0. Webhook trigger (for testing) — Schedule will replace it later
            {"id":"trg","name":"Trigger","type":"n8n-nodes-base.webhook","typeVersion":2,
             "position":[0,0],"webhookId":"dsc-mailer-run",
             "parameters":{"path":"dsc-mailer-run","httpMethod":"POST","responseMode":"lastNode"}},

            # 1. Read Content_Calendar
            {"id":"r_cal","name":"ReadCalendar","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[240,0],"credentials":SHEETS_CRED,
             "parameters":{
                "method":"GET",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Content_Calendar!A1:G1000",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "options":{},
             }},

            # 2. Read Cost_Tracker
            {"id":"r_ct","name":"ReadCostTracker","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[480,0],"credentials":SHEETS_CRED,
             "parameters":{
                "method":"GET",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Cost_Tracker!A1:F1000",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "options":{},
             }},

            # 3. Read Personas (for name lookup)
            {"id":"r_p","name":"ReadPersonas","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[720,0],"credentials":SHEETS_CRED,
             "parameters":{
                "method":"GET",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Personas!A1:H11",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "options":{},
             }},

            # 4. Build approvals rows + email HTML
            {"id":"prep","name":"Prepare","type":"n8n-nodes-base.code","typeVersion":2,
             "position":[960,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":PREPARE_JS}},

            # 5. IF skip (no pending)
            {"id":"if_skip","name":"AnyPending","type":"n8n-nodes-base.if","typeVersion":2,
             "position":[1200,0],
             "parameters":{
                "conditions":{"options":{"caseSensitive":True,"leftValue":"","typeValidation":"loose"},
                    "conditions":[{"leftValue":"={{ $json.skip }}","rightValue":True,
                                   "operator":{"type":"boolean","operation":"equals"}}],
                    "combinator":"and"},
             }},

            # 6. (has pending) Append tokens to Approvals
            {"id":"app_ap","name":"AppendApprovals","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[1440,150],"credentials":SHEETS_CRED,
             "parameters":{
                "method":"POST",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Approvals!A:H:append?valueInputOption=RAW",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "sendBody":True,"specifyBody":"json",
                "jsonBody":"={{ JSON.stringify({ values: $json.approvals_rows }) }}",
                "options":{},
             }},

            # 7. Send Gmail
            {"id":"gm","name":"SendGmail","type":"n8n-nodes-base.gmail","typeVersion":2.1,
             "position":[1680,150],"credentials":GMAIL_CRED,
             "parameters":{
                "resource":"message",
                "operation":"send",
                "sendTo": GMAIL_RECIPIENT,
                "subject": "={{ $node['Prepare'].json.subject }}",
                "emailType": "html",
                "message": "={{ $node['Prepare'].json.htmlBody }}",
                "options":{},
             }},
        ],
        "connections":{
            "Trigger":         {"main":[[{"node":"ReadCalendar","type":"main","index":0}]]},
            "ReadCalendar":    {"main":[[{"node":"ReadCostTracker","type":"main","index":0}]]},
            "ReadCostTracker": {"main":[[{"node":"ReadPersonas","type":"main","index":0}]]},
            "ReadPersonas":    {"main":[[{"node":"Prepare","type":"main","index":0}]]},
            "Prepare":         {"main":[[{"node":"AnyPending","type":"main","index":0}]]},
            "AnyPending":      {"main":[
                [],  # true (skip) → no further action
                [{"node":"AppendApprovals","type":"main","index":0}],  # false (has pending)
            ]},
            "AppendApprovals": {"main":[[{"node":"SendGmail","type":"main","index":0}]]},
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
    print("=== T8b — Build & deploy mailer ===\n")
    # Delete existing
    r = requests.get(f"{N8N}/api/v1/workflows", headers=H)
    for w in r.json().get("data", []):
        if w["name"] == "DailySmileCare-v2-Approval-Mailer":
            print(f"  ↻ suppression existant id={w['id']}")
            try: requests.post(f"{N8N}/api/v1/workflows/{w['id']}/deactivate", headers=H)
            except: pass
            requests.delete(f"{N8N}/api/v1/workflows/{w['id']}", headers=H)

    r = requests.post(f"{N8N}/api/v1/workflows", headers=H, json=build_workflow())
    if r.status_code >= 400:
        print(r.text[:500]); sys.exit(1)
    wf_id = r.json()["id"]
    update_env({"N8N_WORKFLOW_ID_APPROVAL_MAILER": wf_id})
    print(f"  ✓ Workflow créé id={wf_id}")
    print(f"\n→ Pour tester : ouvre n8n UI et clique 'Execute workflow' sur 'DailySmileCare-v2-Approval-Mailer'")
    print(f"  URL : {N8N}/workflow/{wf_id}")


if __name__ == "__main__":
    main()
