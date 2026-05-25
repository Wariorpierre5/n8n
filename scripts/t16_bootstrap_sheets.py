#!/usr/bin/env python3
"""T16 — Bootstrap du classeur DailySmileCare_Dashboard.

Crée un workflow n8n temporaire (webhook trigger + 2 HTTP Request nodes
qui appellent l'API Google Sheets via OAuth2 du credential existant
"Google Sheets account 2"), l'active, le déclenche, puis nettoie.

Résultat : 9 onglets créés + Personas (10 rows) + Products (17 rows) peuplés.
"""

import csv
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

# OAuth2 credential to reuse — "Google Sheets account 2"
SHEETS_CRED_ID   = "vJiNfwvBkcQFu7Qf"
SHEETS_CRED_NAME = "Google Sheets account 2"

# ─── Data ──────────────────────────────────────────────────────────────

PERSONAS = [
    # id, name, brand_focus,                                  region,            accent,                       voice_id, image_ref_url, prompt_seed
    ["1",  "Ashley",  "Aquasonic Black Series Ultra Whitening", "Ohio",            "General American (Midwest)", "",       "",            ""],
    ["2",  "Dorothy", "Philips Sonicare 4100 Rechargeable",     "Phoenix, AZ",     "Southwestern neutral",       "",       "",            ""],
    ["3",  "Ethan",   "RANVOO AirJet X5",                       "Portland, OR",    "Pacific Northwest neutral",  "",       "",            ""],
    ["4",  "Jordan",  "Philips Sonicare 7300",                  "Austin, TX",      "Texas mild",                 "",       "",            ""],
    ["5",  "Linda",   "Philips Sonicare ProtectiveClean 5300",  "Houston, TX",     "Texan / Gulf",               "",       "",            ""],
    ["6",  "Marcus",  "Philips Sonicare DiamondClean 9900",     "Atlanta, GA",     "Southern mild",              "",       "",            ""],
    ["7",  "Priya",   "Oral-B Pro 1000",                        "Seattle, WA",     "Pacific Northwest neutral",  "",       "",            ""],
    ["8",  "Raymond", "Philips Sonicare ProtectiveClean 6500",  "Minneapolis, MN", "Upper Midwest / Minnesota",  "",       "",            ""],
    ["9",  "Sophia",  "Oral-B iO 9",                            "Chicago, IL",     "Chicago / Midwestern",       "",       "",            ""],
    ["10", "Tyler",   "Philips Sonicare 4100 Rose",             "Nashville, TN",   "Southern (Tennessee)",       "",       "",            ""],
]
PERSONAS_HEADER = ["id", "name", "brand_focus", "region", "accent", "voice_id", "image_ref_url", "prompt_seed"]

# Persona → product id (from quiz scoring catalog in blog/quiz.html)
PERSONA_TO_PRODUCT = {
    "Ashley":2, "Dorothy":3, "Ethan":16, "Jordan":5, "Linda":4,
    "Marcus":10, "Priya":8, "Raymond":12, "Sophia":13, "Tyler":17,
}
PRODUCT_TO_PERSONAS = {}
for p_name, prod_id in PERSONA_TO_PRODUCT.items():
    PRODUCT_TO_PERSONAS.setdefault(prod_id, []).append(p_name)

# Read data_products.csv to build Products tab
def load_products():
    csv_path = ROOT / "data" / "data_products.csv"
    rows = []
    # The CSV order matches quiz product ids 1..17 with one duplicate at row 6 (ProtectiveClean 5300)
    # We dedupe by amazon short URL.
    seen_urls = set()
    quiz_id = 0
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            short_url = r.get("lien", "").strip()
            full_url  = r.get("Lien fabriquant", "").strip()
            if not short_url or short_url in seen_urls:
                continue
            seen_urls.add(short_url)
            quiz_id += 1
            brand = r.get("Marque", "").strip()
            model = r.get("Modele", "").strip()
            price = r.get("Prix vente", "").replace("$","").strip()
            comm  = r.get("pourcentage", "").strip()
            tps   = PRODUCT_TO_PERSONAS.get(quiz_id, [])
            tps_str = ",".join(tps)
            rows.append([
                str(quiz_id),
                brand,
                model,
                "",              # asin — non disponible dans CSV, à enrichir post-MVP
                short_url,
                full_url,
                comm,
                price,
                tps_str,
            ])
    return rows

PRODUCTS_HEADER = ["id", "brand", "model", "asin", "amazon_short_url", "amazon_full_url", "commission_rate", "avg_price", "target_persona_ids"]
PRODUCTS = load_products()

# 9 tabs in the order they will appear
TABS = [
    "Personas",
    "Products",
    "Themes",
    "Content_Calendar",
    "Approvals",
    "Social_Performance",
    "Cost_Tracker",
    "Affiliate_Tracking",
    "Weekly_Report",
]

# Headers for the 7 empty tabs (architecture §7)
EMPTY_TAB_HEADERS = {
    "Themes":             ["id", "theme_title", "persona_ids", "related_product_ids", "status"],
    "Content_Calendar":   ["content_id", "date", "persona_id", "platform", "type", "status", "permalink"],
    "Approvals":          ["content_id", "token_hash", "action", "timestamp", "ip", "user_agent"],
    "Social_Performance": ["content_id", "platform", "views", "likes", "saves", "comments", "clicks_amazon", "conversions"],
    "Cost_Tracker":       ["date", "content_id", "tokens_claude_in", "tokens_claude_out", "calls_gemini", "cost_usd_total"],
    "Affiliate_Tracking": ["content_id", "amazon_short_url", "clicks", "conversions", "commission_usd", "last_updated"],
    "Weekly_Report":      ["week_iso", "revenue_estimated", "top_persona", "top_article", "top_platform", "total_cost"],
}

# ─── Build the n8n workflow ────────────────────────────────────────────

WEBHOOK_PATH = "t16-bootstrap-dashboard"

def build_workflow():
    """Return a workflow JSON ready to POST to n8n."""
    # Build the addSheet + deleteSheet (Sheet1) requests
    add_requests = [
        {"addSheet": {"properties": {"title": tab}}} for tab in TABS
    ]
    # Delete the default Sheet1 (sheetId=0 on a fresh spreadsheet)
    add_requests.append({"deleteSheet": {"sheetId": 0}})

    structure_body = {"requests": add_requests}

    # Build the values.batchUpdate for all tabs
    value_data = []
    # Personas
    value_data.append({
        "range": "Personas!A1",
        "values": [PERSONAS_HEADER] + PERSONAS,
    })
    # Products
    value_data.append({
        "range": "Products!A1",
        "values": [PRODUCTS_HEADER] + PRODUCTS,
    })
    # Headers-only for the 7 empty tabs
    for tab, header in EMPTY_TAB_HEADERS.items():
        value_data.append({
            "range": f"{tab}!A1",
            "values": [header],
        })
    values_body = {
        "valueInputOption": "USER_ENTERED",
        "data": value_data,
    }

    cred = {"googleSheetsOAuth2Api": {"id": SHEETS_CRED_ID, "name": SHEETS_CRED_NAME}}

    workflow = {
        "name": "T16-bootstrap-dashboard",
        "nodes": [
            {
                "id": "wh",
                "name": "Webhook Bootstrap",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 2,
                "position": [0, 0],
                "webhookId": "t16-bootstrap",
                "parameters": {
                    "path": WEBHOOK_PATH,
                    "httpMethod": "POST",
                    "responseMode": "responseNode",
                },
            },
            {
                "id": "structure",
                "name": "Create 9 Tabs",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 4.2,
                "position": [240, 0],
                "credentials": cred,
                "parameters": {
                    "method": "POST",
                    "url": f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}:batchUpdate",
                    "authentication": "predefinedCredentialType",
                    "nodeCredentialType": "googleSheetsOAuth2Api",
                    "sendBody": True,
                    "specifyBody": "json",
                    "jsonBody": json.dumps(structure_body),
                    "options": {},
                },
            },
            {
                "id": "values",
                "name": "Populate Values",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 4.2,
                "position": [480, 0],
                "credentials": cred,
                "parameters": {
                    "method": "POST",
                    "url": f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values:batchUpdate",
                    "authentication": "predefinedCredentialType",
                    "nodeCredentialType": "googleSheetsOAuth2Api",
                    "sendBody": True,
                    "specifyBody": "json",
                    "jsonBody": json.dumps(values_body),
                    "options": {},
                },
            },
            {
                "id": "response",
                "name": "Respond",
                "type": "n8n-nodes-base.respondToWebhook",
                "typeVersion": 1,
                "position": [720, 0],
                "parameters": {
                    "respondWith": "json",
                    "responseBody": "={{ { ok: true, tabs_created: 9, personas: 10, products: 17 } }}",
                },
            },
        ],
        "connections": {
            "Webhook Bootstrap": {"main": [[{"node": "Create 9 Tabs", "type": "main", "index": 0}]]},
            "Create 9 Tabs":    {"main": [[{"node": "Populate Values", "type": "main", "index": 0}]]},
            "Populate Values":  {"main": [[{"node": "Respond", "type": "main", "index": 0}]]},
        },
        "settings": {"executionOrder": "v1"},
    }
    return workflow

# ─── Orchestration ─────────────────────────────────────────────────────

def main():
    print(f"=== T16 bootstrap dashboard ===")
    print(f"Sheet ID : {SHEET_ID}")
    print(f"Personas : {len(PERSONAS)} rows")
    print(f"Products : {len(PRODUCTS)} rows")
    print(f"Tabs     : {len(TABS)}")
    print()

    # 1. Create workflow
    print("1. Création du workflow n8n…")
    wf = build_workflow()
    r = requests.post(f"{N8N_BASE}/api/v1/workflows", headers=H, json=wf)
    if r.status_code >= 400:
        print(f"  ✗ HTTP {r.status_code}")
        print(r.text)
        sys.exit(1)
    wf_id = r.json()["id"]
    print(f"  ✓ Workflow créé, id={wf_id}")

    # 2. Activate
    print("2. Activation du workflow…")
    r = requests.post(f"{N8N_BASE}/api/v1/workflows/{wf_id}/activate", headers=H)
    if r.status_code >= 400:
        print(f"  ✗ HTTP {r.status_code}")
        print(r.text)
        sys.exit(1)
    print("  ✓ Actif")

    # Brief delay so the webhook is fully registered
    time.sleep(2)

    # 3. Trigger webhook
    print("3. Trigger webhook…")
    webhook_url = f"{N8N_BASE}/webhook/{WEBHOOK_PATH}"
    print(f"  POST {webhook_url}")
    r = requests.post(webhook_url, json={"trigger": "bootstrap"})
    print(f"  HTTP {r.status_code}")
    if r.status_code >= 400:
        print(r.text[:1000])
        ok = False
    else:
        try:
            print(f"  Response: {json.dumps(r.json(), indent=2)}")
            ok = True
        except Exception:
            print(f"  Response (raw): {r.text[:500]}")
            ok = False

    # 4. Cleanup
    print("4. Désactivation + suppression du workflow temporaire…")
    requests.post(f"{N8N_BASE}/api/v1/workflows/{wf_id}/deactivate", headers=H)
    requests.delete(f"{N8N_BASE}/api/v1/workflows/{wf_id}", headers=H)
    print("  ✓ Nettoyé")

    if not ok:
        sys.exit(2)
    print()
    print("=== Bootstrap terminé ===")
    print(f"Vérifie visuellement : https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit")

if __name__ == "__main__":
    main()
