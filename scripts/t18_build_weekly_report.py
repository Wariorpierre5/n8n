#!/usr/bin/env python3
"""T18 — Workflow `DailySmileCare-v2-Weekly-Report`.

Trigger : webhook (test) + Schedule lundi 13h UTC (~08h ET en EST, 09h en EDT)
→ Lit Cost_Tracker + Social_Performance + Affiliate_Tracking + Personas
→ Filtre 7 derniers jours, agrège (total cost, revenu réel, top persona/plateforme, ROI brut)
→ Build email HTML récap
→ Envoie Gmail
→ Append ligne dans Weekly_Report
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

# ─── Aggregation JS ────────────────────────────────────────────────────

AGGREGATE_JS = r"""
// Inputs:
//   $node['ReadCostTracker'].json.values
//   $node['ReadSocialPerf'].json.values
//   $node['ReadAffiliate'].json.values
//   $node['ReadPersonas'].json.values
// Cutoff = 7 days ago.

const now = new Date();
const cutoff = new Date(now.getTime() - 7 * 24 * 3600 * 1000);
const cutoffISO = cutoff.toISOString().slice(0, 10);
const todayISO = now.toISOString().slice(0, 10);
// ISO week
const yearStart = new Date(Date.UTC(now.getUTCFullYear(), 0, 1));
const dayOfYear = Math.floor((now - yearStart) / (24 * 3600 * 1000)) + 1;
const weekNum = Math.ceil(dayOfYear / 7);
const week_iso = `${now.getUTCFullYear()}-W${String(weekNum).padStart(2, '0')}`;

// Personas → id => name
const pRows = ($node['ReadPersonas'].json.values || []).slice(1);
const personaName = {};
for (const r of pRows) { personaName[r[0]] = r[1]; }

// Cost_Tracker : date, content_id, in, out, gemini, cost_usd_total
const costRows = ($node['ReadCostTracker'].json.values || []).slice(1)
  .filter(r => r[0] && r[0] >= cutoffISO);
let total_cost = 0;
const cost_by_persona = {};
const cost_by_platform = {};
for (const r of costRows) {
  const c = parseFloat(r[5] || '0');
  total_cost += c;
  // content_id format: YYYY-MM-DD-pN-runid-platform
  const cid = r[1] || '';
  const m = cid.match(/-p(\d+)-[^-]+-(\w+)$/);
  if (m) {
    const pid = m[1]; const platform = m[2];
    const pname = personaName[pid] || `p${pid}`;
    cost_by_persona[pname]  = (cost_by_persona[pname]  || 0) + c;
    cost_by_platform[platform] = (cost_by_platform[platform] || 0) + c;
  }
}

// Affiliate_Tracking : content_id (=product_id), amazon_short_url, clicks, conversions, commission_usd, last_updated
const affRows = ($node['ReadAffiliate'].json.values || []).slice(1)
  .filter(r => r[5] && r[5].slice(0, 10) >= cutoffISO);
let total_clicks = 0, total_conversions = 0, total_commission = 0;
const clicks_by_product = {};
for (const r of affRows) {
  const clicks = parseFloat(r[2] || '0');
  const conv   = parseFloat(r[3] || '0');
  const comm   = parseFloat(r[4] || '0');
  total_clicks += clicks; total_conversions += conv; total_commission += comm;
  clicks_by_product[r[0]] = (clicks_by_product[r[0]] || 0) + clicks;
}

// Social_Performance : content_id, platform, views, likes, saves, comments, clicks_amazon, conversions
const socRows = ($node['ReadSocialPerf'].json.values || []).slice(1);
let total_views = 0, total_engagements = 0;
const views_by_platform = {};
for (const r of socRows) {
  const platform = r[1] || '';
  const views = parseFloat(r[2] || '0');
  const eng   = parseFloat(r[3] || '0') + parseFloat(r[4] || '0') + parseFloat(r[5] || '0');
  total_views += views; total_engagements += eng;
  views_by_platform[platform] = (views_by_platform[platform] || 0) + views;
}

// Estimated revenue (bootstrap formula §8) — based on Cost_Tracker (1 row per generated content)
// trafic_avg = 100 vues estim, CTR=1.2%, conv=2.5%, comm=3%, panier=$80
const CTR = 0.012, CONV = 0.025, COMM = 0.03, PANIER = 80;
const VIEWS_BY_PF = { x: 30, youtube_shorts: 250, instagram_reel: 80, tiktok: 200, snapchat: 50 };
let revenue_estimated = 0;
for (const r of costRows) {
  const cid = r[1] || '';
  const m = cid.match(/-(\w+)$/);
  const platform = m ? m[1] : 'unknown';
  const traffic = VIEWS_BY_PF[platform] || 50;
  revenue_estimated += traffic * CTR * CONV * COMM * PANIER;
}

// Top performers
const topKey = obj => {
  const e = Object.entries(obj).sort((a, b) => b[1] - a[1]);
  return e[0] ? e[0][0] : '—';
};
const top_persona  = topKey(cost_by_persona);
const top_platform = topKey(cost_by_platform);
const top_article  = topKey(clicks_by_product);  // product_id of most-clicked product

const roi_brut = total_commission - total_cost;

return [{ json: {
  week_iso,
  cutoff: cutoffISO,
  totals: {
    cost_usd:           Number(total_cost.toFixed(4)),
    commission_usd:     Number(total_commission.toFixed(2)),
    revenue_estimated:  Number(revenue_estimated.toFixed(2)),
    roi_brut:           Number(roi_brut.toFixed(2)),
    content_pieces:     costRows.length,
    affiliate_records:  affRows.length,
    clicks:             total_clicks,
    conversions:        total_conversions,
    social_views:       total_views,
    social_engagements: total_engagements,
  },
  top: { persona: top_persona, platform: top_platform, article_product_id: top_article },
  by_persona:  cost_by_persona,
  by_platform: cost_by_platform,
  weekly_row: [
    week_iso,
    Number(revenue_estimated.toFixed(2)),
    top_persona,
    top_article,
    top_platform,
    Number(total_cost.toFixed(4)),
  ],
} }];
"""

BUILD_EMAIL_JS = r"""
const a = $input.first().json;
const t = a.totals;

const rowHTML = (label, value, color = '#1a1a2e') => `
  <tr><td style="padding:6px 0;color:#666;font-size:0.85rem;">${label}</td><td style="padding:6px 0;text-align:right;color:${color};font-weight:700;font-size:0.95rem;">${value}</td></tr>`;

const subject = `[Weekly Report ${a.week_iso}] ${t.content_pieces} contenus • ${t.clicks} clicks • $${t.commission_usd} commissions`;

const html = `<!DOCTYPE html>
<html><body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;background:#f0f4ff;margin:0;padding:24px 12px;color:#1a1a2e">
<table cellspacing="0" cellpadding="0" border="0" style="max-width:640px;margin:0 auto;width:100%;background:#fff;border-radius:12px;border:1px solid #e2e8f0">
  <tr><td style="padding:24px 28px;">
    <div style="font-size:0.8rem;color:#666;text-transform:uppercase;letter-spacing:1px;font-weight:700;margin-bottom:4px">Weekly Report</div>
    <h1 style="font-size:1.4rem;font-weight:900;margin:0 0 4px;color:#1a1a2e">${a.week_iso}</h1>
    <p style="font-size:0.85rem;color:#888;margin:0 0 22px">7 derniers jours (depuis ${a.cutoff})</p>

    <div style="background:#eff6ff;border-radius:8px;padding:18px 20px;margin-bottom:18px;">
      <div style="font-size:0.75rem;font-weight:700;color:#2563eb;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px">Synthèse</div>
      <table style="width:100%;border-collapse:collapse;">
        ${rowHTML('Coût IA total', `$${t.cost_usd.toFixed(4)}`, '#dc2626')}
        ${rowHTML('Commissions Amazon (réel)', `$${t.commission_usd.toFixed(2)}`, '#16a34a')}
        ${rowHTML('Revenu estimé (modèle)', `$${t.revenue_estimated.toFixed(2)}`)}
        ${rowHTML('ROI brut', `$${t.roi_brut.toFixed(2)}`, t.roi_brut >= 0 ? '#16a34a' : '#dc2626')}
      </table>
    </div>

    <div style="display:flex;gap:12px;margin-bottom:18px;">
      <div style="flex:1;background:#f8f9fa;border-radius:8px;padding:14px;">
        <div style="font-size:0.7rem;color:#888;text-transform:uppercase">Contenus générés</div>
        <div style="font-size:1.6rem;font-weight:800">${t.content_pieces}</div>
      </div>
      <div style="flex:1;background:#f8f9fa;border-radius:8px;padding:14px;">
        <div style="font-size:0.7rem;color:#888;text-transform:uppercase">Clicks Amazon</div>
        <div style="font-size:1.6rem;font-weight:800">${t.clicks}</div>
      </div>
      <div style="flex:1;background:#f8f9fa;border-radius:8px;padding:14px;">
        <div style="font-size:0.7rem;color:#888;text-transform:uppercase">Conversions</div>
        <div style="font-size:1.6rem;font-weight:800">${t.conversions}</div>
      </div>
    </div>

    <div style="display:flex;gap:12px;margin-bottom:18px;">
      <div style="flex:1;background:#fff8e1;border-radius:8px;padding:14px;">
        <div style="font-size:0.7rem;color:#888;text-transform:uppercase">Top persona</div>
        <div style="font-size:1.1rem;font-weight:800">${a.top.persona}</div>
      </div>
      <div style="flex:1;background:#fff8e1;border-radius:8px;padding:14px;">
        <div style="font-size:0.7rem;color:#888;text-transform:uppercase">Top plateforme</div>
        <div style="font-size:1.1rem;font-weight:800">${a.top.platform}</div>
      </div>
      <div style="flex:1;background:#fff8e1;border-radius:8px;padding:14px;">
        <div style="font-size:0.7rem;color:#888;text-transform:uppercase">Top produit</div>
        <div style="font-size:1.1rem;font-weight:800">#${a.top.article_product_id}</div>
      </div>
    </div>

    <p style="font-size:0.75rem;color:#999;text-align:center;margin-top:24px;border-top:1px solid #eee;padding-top:12px;">
      DailySmileCare — pipeline weekly summary<br>
      Vue détaillée : <a href="https://docs.google.com/spreadsheets/d/${'__SHEET_ID__'}/edit" style="color:#2563eb">Dashboard Sheets</a>
    </p>
  </td></tr>
</table>
</body></html>`;

return [{ json: {
  ...a,
  subject,
  htmlBody: html,
} }];
""".replace("__SHEET_ID__", SHEET_ID)


def build_workflow():
    return {
        "name":"DailySmileCare-v2-Weekly-Report",
        "nodes":[
            {"id":"wh","name":"Webhook","type":"n8n-nodes-base.webhook","typeVersion":2,
             "position":[0,0],"webhookId":"dsc-weekly-report",
             "parameters":{"path":"dsc-weekly-report","httpMethod":"POST","responseMode":"responseNode"}},

            # Read 4 sheets in series (could parallelize but simpler in series)
            {"id":"rct","name":"ReadCostTracker","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[240,0],"credentials":SHEETS_CRED,
             "parameters":{"method":"GET",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Cost_Tracker!A1:F10000",
                "authentication":"predefinedCredentialType","nodeCredentialType":"googleSheetsOAuth2Api","options":{}}},
            {"id":"rsp","name":"ReadSocialPerf","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[480,0],"credentials":SHEETS_CRED,
             "parameters":{"method":"GET",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Social_Performance!A1:H10000",
                "authentication":"predefinedCredentialType","nodeCredentialType":"googleSheetsOAuth2Api","options":{}}},
            {"id":"raf","name":"ReadAffiliate","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[720,0],"credentials":SHEETS_CRED,
             "parameters":{"method":"GET",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Affiliate_Tracking!A1:F10000",
                "authentication":"predefinedCredentialType","nodeCredentialType":"googleSheetsOAuth2Api","options":{}}},
            {"id":"rp","name":"ReadPersonas","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[960,0],"credentials":SHEETS_CRED,
             "parameters":{"method":"GET",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Personas!A1:H11",
                "authentication":"predefinedCredentialType","nodeCredentialType":"googleSheetsOAuth2Api","options":{}}},

            # Aggregate
            {"id":"agg","name":"Aggregate","type":"n8n-nodes-base.code","typeVersion":2,"position":[1200,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":AGGREGATE_JS}},

            # Build email HTML
            {"id":"em","name":"BuildEmail","type":"n8n-nodes-base.code","typeVersion":2,"position":[1440,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":BUILD_EMAIL_JS}},

            # Append row to Weekly_Report
            {"id":"awr","name":"AppendWeekly","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[1680,-100],"credentials":SHEETS_CRED,
             "parameters":{"method":"POST",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Weekly_Report!A:F:append?valueInputOption=RAW",
                "authentication":"predefinedCredentialType","nodeCredentialType":"googleSheetsOAuth2Api",
                "sendBody":True,"specifyBody":"json",
                "jsonBody":"={{ JSON.stringify({ values: [$json.weekly_row] }) }}",
                "options":{}}},

            # Send Gmail
            {"id":"gm","name":"SendGmail","type":"n8n-nodes-base.gmail","typeVersion":2.1,
             "position":[1680,100],"credentials":GMAIL_CRED,
             "parameters":{
                "resource":"message","operation":"send",
                "sendTo":GMAIL_RECIPIENT,
                "subject":"={{ $node['BuildEmail'].json.subject }}",
                "emailType":"html",
                "message":"={{ $node['BuildEmail'].json.htmlBody }}",
                "options":{}}},

            # Respond
            {"id":"r","name":"Respond","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,
             "position":[1920,0],
             "parameters":{"respondWith":"json","responseBody":
                "={{ { ok: true, week_iso: $node['Aggregate'].json.week_iso, totals: $node['Aggregate'].json.totals, top: $node['Aggregate'].json.top } }}"}},
        ],
        "connections":{
            "Webhook":         {"main":[[{"node":"ReadCostTracker","type":"main","index":0}]]},
            "ReadCostTracker": {"main":[[{"node":"ReadSocialPerf","type":"main","index":0}]]},
            "ReadSocialPerf":  {"main":[[{"node":"ReadAffiliate","type":"main","index":0}]]},
            "ReadAffiliate":   {"main":[[{"node":"ReadPersonas","type":"main","index":0}]]},
            "ReadPersonas":    {"main":[[{"node":"Aggregate","type":"main","index":0}]]},
            "Aggregate":       {"main":[[{"node":"BuildEmail","type":"main","index":0}]]},
            "BuildEmail":      {"main":[
                [
                    {"node":"AppendWeekly","type":"main","index":0},
                    {"node":"SendGmail","type":"main","index":0},
                ],
            ]},
            "AppendWeekly":    {"main":[[{"node":"Respond","type":"main","index":0}]]},
            "SendGmail":       {"main":[[{"node":"Respond","type":"main","index":0}]]},
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
    print("=== T18 — Weekly Report workflow ===\n")
    name = "DailySmileCare-v2-Weekly-Report"
    r = requests.get(f"{N8N}/api/v1/workflows", headers=H)
    for w in r.json().get("data", []):
        if w["name"] == name:
            print(f"  ↻ suppression existant id={w['id']}")
            try: requests.post(f"{N8N}/api/v1/workflows/{w['id']}/deactivate", headers=H)
            except: pass
            requests.delete(f"{N8N}/api/v1/workflows/{w['id']}", headers=H)

    r = requests.post(f"{N8N}/api/v1/workflows", headers=H, json=build_workflow())
    if r.status_code >= 400: print(r.text[:500]); sys.exit(1)
    wf_id = r.json()["id"]
    update_env({"N8N_WORKFLOW_ID_WEEKLY": wf_id})
    print(f"  ✓ Workflow id={wf_id}")

    requests.post(f"{N8N}/api/v1/workflows/{wf_id}/activate", headers=H)
    time.sleep(3)

    print("\n=== Trigger test ===")
    r = requests.post(f"{N8N}/webhook/dsc-weekly-report", json={}, timeout=120)
    print(f"HTTP {r.status_code}")
    print(json.dumps(r.json() if r.status_code == 200 else r.text, indent=2)[:1500])


if __name__ == "__main__":
    main()
