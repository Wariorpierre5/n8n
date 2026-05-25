#!/usr/bin/env python3
"""T17 — Setup Drive amazon_reports/ + build Affiliate-Sync workflow + test avec CSV sample.

Workflow Affiliate-Sync :
  Webhook/Schedule
  → List files in DailySmileCare/amazon_reports/ (most recent first)
  → Download CSV content
  → Parse (col 'amazon_short_url' = clé) + lookup product_id in Products sheet
  → Append rows to Affiliate_Tracking (date, product_id, amazon_short_url, clicks, conversions, commission_usd, last_updated)

CSV expected format (flexible, header-aware):
  date,amazon_short_url,clicks,conversions,commission_usd
  2026-05-25,https://amzn.to/3PFV8Tm,15,2,3.36
  ...
"""

import base64
import csv
import io
import json
import os
import re
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
SHEET_ID = os.environ["SHEETS_DASHBOARD_ID"]
DRIVE_ROOT = os.environ["DRIVE_ROOT_FOLDER_ID"]
H = {"X-N8N-API-KEY": K, "Content-Type": "application/json"}
SHEETS_CRED = {"googleSheetsOAuth2Api": {"id": "vJiNfwvBkcQFu7Qf", "name": "Google Sheets account 2"}}
DRIVE_CRED  = {"googleDriveOAuth2Api":  {"id": "Sirms4q3Rl05Mlj6", "name": "Google Drive account"}}


def run_ephemeral(name, nodes, connections, webhook_path, post_body=None, timeout=60):
    wf = {"name": name, "nodes": nodes, "connections": connections, "settings": {"executionOrder": "v1"}}
    r = requests.post(f"{N8N}/api/v1/workflows", headers=H, json=wf)
    if r.status_code >= 400: raise RuntimeError(f"Create wf failed: {r.text[:300]}")
    wf_id = r.json()["id"]
    try:
        requests.post(f"{N8N}/api/v1/workflows/{wf_id}/activate", headers=H)
        time.sleep(2)
        r = requests.post(f"{N8N}/webhook/{webhook_path}", json=post_body or {}, timeout=timeout)
        if r.status_code != 200: raise RuntimeError(f"Trigger failed: {r.text[:300]}")
        try: return r.json()
        except: return {"raw": r.text}
    finally:
        requests.post(f"{N8N}/api/v1/workflows/{wf_id}/deactivate", headers=H)
        requests.delete(f"{N8N}/api/v1/workflows/{wf_id}", headers=H)


def update_env(updates):
    env_path = ROOT / ".env"
    content = env_path.read_text(encoding="utf-8")
    for key, val in updates.items():
        if re.search(rf"^{key}=", content, re.M):
            content = re.sub(rf"^{key}=.*$", f"{key}={val}", content, flags=re.M)
        else:
            content += f"\n{key}={val}\n"
    env_path.write_text(content, encoding="utf-8")


def ensure_reports_folder():
    """Create DailySmileCare/amazon_reports/ if missing. Returns folder ID."""
    existing = os.environ.get("DRIVE_AMAZON_REPORTS_FOLDER_ID")
    if existing:
        return existing
    WP = "t17-ensure-folder-" + str(int(time.time()))[-6:]
    res = run_ephemeral(
        "T17-EnsureReports",
        nodes=[
            {"id":"wh","name":"WH","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[0,0],"webhookId":WP,
             "parameters":{"path":WP,"httpMethod":"POST","responseMode":"responseNode"}},
            {"id":"s","name":"Search","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[240,0],"credentials":DRIVE_CRED,
             "parameters":{"method":"GET",
                "url":f"https://www.googleapis.com/drive/v3/files?q=name%3D%27amazon_reports%27+and+%27{DRIVE_ROOT}%27+in+parents+and+trashed%3Dfalse&fields=files(id)",
                "authentication":"predefinedCredentialType","nodeCredentialType":"googleDriveOAuth2Api","options":{}}},
            {"id":"c","name":"C","type":"n8n-nodes-base.code","typeVersion":2,"position":[480,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":
                "const f = $input.first().json.files || []; "
                "return [{ json: { id: f[0] && f[0].id, needs_create: f.length === 0 } }];"}},
            {"id":"if","name":"If","type":"n8n-nodes-base.if","typeVersion":2,"position":[720,0],
             "parameters":{"conditions":{"options":{"caseSensitive":True,"leftValue":"","typeValidation":"loose"},
                "conditions":[{"leftValue":"={{ $json.needs_create }}","rightValue":True,
                               "operator":{"type":"boolean","operation":"equals"}}],"combinator":"and"}}},
            {"id":"cr","name":"Create","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[960,-100],"credentials":DRIVE_CRED,
             "parameters":{"method":"POST",
                "url":"https://www.googleapis.com/drive/v3/files",
                "authentication":"predefinedCredentialType","nodeCredentialType":"googleDriveOAuth2Api",
                "sendBody":True,"specifyBody":"json",
                "jsonBody": json.dumps({"name":"amazon_reports","mimeType":"application/vnd.google-apps.folder","parents":[DRIVE_ROOT]}),
                "options":{}}},
            {"id":"m","name":"Merge","type":"n8n-nodes-base.code","typeVersion":2,"position":[1200,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":
                "const j = $input.first().json; "
                "return [{ json: { folder_id: j.id || j.id_existing || j.id } }];"}},
            {"id":"rp","name":"R","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,"position":[1440,0],
             "parameters":{"respondWith":"json","responseBody":"={{ { folder_id: $json.id || $node['C'].json.id } }}"}},
        ],
        connections={
            "WH":{"main":[[{"node":"Search","type":"main","index":0}]]},
            "Search":{"main":[[{"node":"C","type":"main","index":0}]]},
            "C":{"main":[[{"node":"If","type":"main","index":0}]]},
            "If":{"main":[
                [{"node":"Create","type":"main","index":0}],
                [{"node":"R","type":"main","index":0}],
            ]},
            "Create":{"main":[[{"node":"R","type":"main","index":0}]]},
        },
        webhook_path=WP,
    )
    folder_id = res.get("folder_id")
    if not folder_id:
        raise RuntimeError(f"Folder ensure failed: {res}")
    update_env({"DRIVE_AMAZON_REPORTS_FOLDER_ID": folder_id})
    return folder_id


def upload_sample_csv(folder_id):
    """Upload a sample CSV to the amazon_reports folder for testing."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # 5 sample rows using real product short URLs from quiz catalog
    sample = "date,amazon_short_url,clicks,conversions,commission_usd\n"
    sample += f"{today},https://amzn.to/3PFV8Tm,42,3,3.60\n"   # Aquasonic (Ashley)
    sample += f"{today},https://amzn.to/4tgErfv,18,1,12.90\n"  # DiamondClean 9900 (Marcus)
    sample += f"{today},https://amzn.to/4cjbZUF,67,5,6.30\n"   # 4100 Rose (Tyler)
    sample += f"{today},https://amzn.to/4m52Q5z,29,2,3.00\n"   # Oral-B Pro 1000 (Priya)
    sample += f"{today},https://amzn.to/4bJfVho,11,0,0.00\n"   # RANVOO (Ethan)

    b64 = base64.b64encode(sample.encode()).decode()
    file_name = f"sample_amazon_report_{today}.csv"

    WP = "t17-upload-csv-" + str(int(time.time()))[-6:]
    decode_js = """
const b64 = $node['Webhook'].json.body.b64;
return [{ json: { fileName: $node['Webhook'].json.body.fileName, parent: $node['Webhook'].json.body.parent },
  binary: { data: { data: b64, mimeType: 'text/csv', fileName: $node['Webhook'].json.body.fileName } } }];
"""
    res = run_ephemeral(
        "T17-UploadCSV",
        nodes=[
            {"id":"wh","name":"Webhook","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[0,0],"webhookId":WP,
             "parameters":{"path":WP,"httpMethod":"POST","responseMode":"responseNode"}},
            {"id":"c","name":"Decode","type":"n8n-nodes-base.code","typeVersion":2,"position":[240,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":decode_js}},
            {"id":"u","name":"Upload","type":"n8n-nodes-base.googleDrive","typeVersion":3,"position":[480,0],
             "credentials":DRIVE_CRED,
             "parameters":{"resource":"file","operation":"upload","name":"={{ $json.fileName }}",
                "driveId":{"__rl":True,"value":"My Drive","mode":"list"},
                "folderId":{"__rl":True,"value":"={{ $json.parent }}","mode":"id"},
                "options":{}}},
            {"id":"r","name":"R","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,"position":[720,0],
             "parameters":{"respondWith":"json","responseBody":"={{ $json }}"}},
        ],
        connections={
            "Webhook":{"main":[[{"node":"Decode","type":"main","index":0}]]},
            "Decode":{"main":[[{"node":"Upload","type":"main","index":0}]]},
            "Upload":{"main":[[{"node":"R","type":"main","index":0}]]},
        },
        webhook_path=WP,
        post_body={"b64": b64, "fileName": file_name, "parent": folder_id},
        timeout=60,
    )
    return res.get("id"), file_name


# === Build persistent Affiliate-Sync workflow ===

SYNC_PARSE_JS = """
// Inputs:
//   - $node['ListFiles'].json.files : list of CSV files in amazon_reports (sorted)
//   - $node['DownloadLatest'].json  : raw CSV body (text) — note: depends on response format
//   - $node['ReadProducts'].json.values : Products sheet

const files = $node['ListFiles'].json.files || [];
if (files.length === 0) {
  return [{ json: { skip: true, reason: 'no_csv_in_amazon_reports' } }];
}

// Most recent file (Drive list is already ordered by modifiedTime desc)
const latest = files[0];

// CSV body comes from the StashCSV node (which normalized the download response)
const csv = $node['StashCSV'].json.csvText || '';
if (!csv.trim()) {
  return [{ json: { skip: true, reason: 'empty_csv', file: latest.name } }];
}

// Parse CSV (header-aware, flexible column names)
const lines = csv.trim().split(/\\r?\\n/);
const header = lines[0].split(',').map(h => h.trim().toLowerCase());

const findCol = (...candidates) => {
  for (const c of candidates) {
    const i = header.indexOf(c);
    if (i !== -1) return i;
  }
  return -1;
};
const colDate    = findCol('date', 'day', 'report_date');
const colUrl     = findCol('amazon_short_url', 'url', 'short_url', 'link');
const colAsin    = findCol('asin');
const colClicks  = findCol('clicks');
const colConv    = findCol('conversions', 'items_ordered', 'items_shipped', 'quantity');
const colCommiss = findCol('commission_usd', 'earnings', 'commission', 'fees');

// Products sheet → map by amazon_short_url
const prodRows = ($node['ReadProducts'].json.values || []).slice(1);
const productByUrl = {};
for (const r of prodRows) {
  // Products header: id, brand, model, asin, amazon_short_url (col E = idx 4), ...
  const url = (r[4] || '').trim();
  if (url) productByUrl[url] = { product_id: r[0], asin: r[3] || '' };
}

const nowIso = new Date().toISOString();
const appendRows = [];

for (let i = 1; i < lines.length; i++) {
  const cells = lines[i].split(',').map(c => c.trim());
  if (cells.length < 2) continue;
  const url   = colUrl >= 0 ? cells[colUrl] : '';
  const asin  = colAsin >= 0 ? cells[colAsin] : '';
  const date  = colDate >= 0 ? cells[colDate] : nowIso.slice(0, 10);
  const clicks      = colClicks  >= 0 ? cells[colClicks]  : '0';
  const conversions = colConv    >= 0 ? cells[colConv]    : '0';
  const commission  = colCommiss >= 0 ? cells[colCommiss] : '0';

  // Match product via short_url, fallback to asin
  const product = productByUrl[url] || Object.values(productByUrl).find(p => p.asin && p.asin === asin) || {};
  const product_id = product.product_id || '';

  // Affiliate_Tracking schema: content_id, amazon_short_url, clicks, conversions, commission_usd, last_updated
  // We use product_id as content_id key (T17 tracks per-product).
  appendRows.push([
    product_id || `unknown_${url || asin}`,
    url || '',
    clicks,
    conversions,
    commission,
    nowIso,
  ]);
}

return [{ json: {
  skip: false,
  csv_file: latest.name,
  csv_file_id: latest.id,
  rows_parsed: appendRows.length,
  appendRows,
} }];
"""


def build_sync_workflow():
    folder_id = os.environ["DRIVE_AMAZON_REPORTS_FOLDER_ID"]
    return {
        "name": "DailySmileCare-v2-Affiliate-Sync",
        "nodes": [
            # Webhook trigger (for manual / Python test)
            {"id":"wh","name":"Webhook","type":"n8n-nodes-base.webhook","typeVersion":2,
             "position":[0,0],"webhookId":"dsc-affiliate-sync",
             "parameters":{"path":"dsc-affiliate-sync","httpMethod":"POST","responseMode":"responseNode"}},

            # 1. List files in amazon_reports/, sorted by modifiedTime desc, take latest
            {"id":"lf","name":"ListFiles","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[240,0],"credentials":DRIVE_CRED,
             "parameters":{"method":"GET",
                "url":f"https://www.googleapis.com/drive/v3/files?q=%27{folder_id}%27+in+parents+and+trashed%3Dfalse+and+mimeType%3D%27text%2Fcsv%27&orderBy=modifiedTime+desc&fields=files(id,name,modifiedTime)",
                "authentication":"predefinedCredentialType","nodeCredentialType":"googleDriveOAuth2Api","options":{}}},

            # 2. Download the latest CSV as text
            {"id":"dl","name":"DownloadLatest","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[480,0],"credentials":DRIVE_CRED,
             "parameters":{"method":"GET",
                "url":"=https://www.googleapis.com/drive/v3/files/{{ $json.files[0].id }}?alt=media",
                "authentication":"predefinedCredentialType","nodeCredentialType":"googleDriveOAuth2Api",
                "options":{"response":{"response":{"responseFormat":"text"}}}}},

            # 3. Stash csvText in json for the parse step
            {"id":"st","name":"StashCSV","type":"n8n-nodes-base.code","typeVersion":2,"position":[720,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":
                "const j = $input.first().json; "
                "const csvText = j.data || j.body || (typeof j === 'string' ? j : JSON.stringify(j)); "
                "return [{ json: { csvText } }];"}},

            # 4. Read Products sheet (to lookup product_id by amazon_short_url)
            {"id":"rp","name":"ReadProducts","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[960,0],"credentials":SHEETS_CRED,
             "parameters":{"method":"GET",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Products!A1:I18",
                "authentication":"predefinedCredentialType","nodeCredentialType":"googleSheetsOAuth2Api","options":{}}},

            # 5. Parse CSV + build append rows
            {"id":"pr","name":"Parse","type":"n8n-nodes-base.code","typeVersion":2,"position":[1200,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":SYNC_PARSE_JS}},

            # 6. IF skip
            {"id":"if","name":"IfSkip","type":"n8n-nodes-base.if","typeVersion":2,"position":[1440,0],
             "parameters":{"conditions":{"options":{"caseSensitive":True,"leftValue":"","typeValidation":"loose"},
                "conditions":[{"leftValue":"={{ $json.skip }}","rightValue":True,
                               "operator":{"type":"boolean","operation":"equals"}}],"combinator":"and"}}},

            # 7. Append to Affiliate_Tracking
            {"id":"ap","name":"AppendTracking","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[1680,150],"credentials":SHEETS_CRED,
             "parameters":{"method":"POST",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Affiliate_Tracking!A:F:append?valueInputOption=RAW",
                "authentication":"predefinedCredentialType","nodeCredentialType":"googleSheetsOAuth2Api",
                "sendBody":True,"specifyBody":"json",
                "jsonBody":"={{ JSON.stringify({ values: $json.appendRows }) }}",
                "options":{}}},

            # 8. Respond
            {"id":"r","name":"Respond","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,"position":[1920,0],
             "parameters":{"respondWith":"json","responseBody":
                "={{ { ok: true, skip: $node['Parse'].json.skip || false, csv_file: $node['Parse'].json.csv_file, rows_appended: $node['Parse'].json.rows_parsed || 0 } }}"}},
        ],
        "connections":{
            "Webhook":         {"main":[[{"node":"ListFiles","type":"main","index":0}]]},
            "ListFiles":       {"main":[[{"node":"DownloadLatest","type":"main","index":0}]]},
            "DownloadLatest":  {"main":[[{"node":"StashCSV","type":"main","index":0}]]},
            "StashCSV":        {"main":[[{"node":"ReadProducts","type":"main","index":0}]]},
            "ReadProducts":    {"main":[[{"node":"Parse","type":"main","index":0}]]},
            "Parse":           {"main":[[{"node":"IfSkip","type":"main","index":0}]]},
            "IfSkip":          {"main":[
                [{"node":"Respond","type":"main","index":0}],
                [{"node":"AppendTracking","type":"main","index":0}],
            ]},
            "AppendTracking":  {"main":[[{"node":"Respond","type":"main","index":0}]]},
        },
        "settings":{"executionOrder":"v1"},
    }


def deploy_sync_workflow():
    name = "DailySmileCare-v2-Affiliate-Sync"
    r = requests.get(f"{N8N}/api/v1/workflows", headers=H)
    for w in r.json().get("data", []):
        if w["name"] == name:
            try: requests.post(f"{N8N}/api/v1/workflows/{w['id']}/deactivate", headers=H)
            except: pass
            requests.delete(f"{N8N}/api/v1/workflows/{w['id']}", headers=H)
    r = requests.post(f"{N8N}/api/v1/workflows", headers=H, json=build_sync_workflow())
    if r.status_code >= 400: raise RuntimeError(r.text[:500])
    wf_id = r.json()["id"]
    requests.post(f"{N8N}/api/v1/workflows/{wf_id}/activate", headers=H)
    update_env({"N8N_WORKFLOW_ID_AFFILIATE_SYNC": wf_id})
    return wf_id


def main():
    print("=== T17 — Setup Drive + sample CSV + Affiliate-Sync workflow ===\n")

    print("1. Ensure DailySmileCare/amazon_reports/ folder…")
    folder_id = ensure_reports_folder()
    print(f"   ✓ folder id = {folder_id}")
    load_dotenv(ROOT / ".env", override=True)
    os.environ["DRIVE_AMAZON_REPORTS_FOLDER_ID"] = folder_id

    print("\n2. Upload sample CSV…")
    file_id, file_name = upload_sample_csv(folder_id)
    print(f"   ✓ uploaded {file_name} (id={file_id})")

    print("\n3. Deploy Affiliate-Sync workflow…")
    wf_id = deploy_sync_workflow()
    print(f"   ✓ workflow id = {wf_id}")

    print("\n4. Trigger sync…")
    time.sleep(3)
    r = requests.post(f"{N8N}/webhook/dsc-affiliate-sync", json={}, timeout=120)
    print(f"   HTTP {r.status_code}")
    print(f"   {r.text[:600]}")


if __name__ == "__main__":
    main()
