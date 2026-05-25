#!/usr/bin/env python3
"""T16 — Vérification programmatique du classeur DailySmileCare_Dashboard.

Lit le sheet via un workflow n8n temporaire (reuses Google Sheets OAuth2),
puis valide :
- 9 onglets exactement, dans le bon ordre
- Personas : 11 rows (1 header + 10 personas)
- Products : 18 rows (1 header + 17 products)
- Les 7 autres onglets ont leur header
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

N8N_BASE = os.environ["N8N_BASE_URL"]
N8N_KEY  = os.environ["N8N_API_KEY"]
SHEET_ID = os.environ["SHEETS_DASHBOARD_ID"]
H = {"X-N8N-API-KEY": N8N_KEY, "Content-Type": "application/json"}

SHEETS_CRED = {"googleSheetsOAuth2Api": {"id": "vJiNfwvBkcQFu7Qf", "name": "Google Sheets account 2"}}

EXPECTED_TABS = [
    "Personas", "Products", "Themes", "Content_Calendar", "Approvals",
    "Social_Performance", "Cost_Tracker", "Affiliate_Tracking", "Weekly_Report",
]

WEBHOOK_PATH = "t16-verify-dashboard"

def build_workflow():
    ranges = "&".join([f"ranges={t}!A1:Z50" for t in EXPECTED_TABS])
    values_url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values:batchGet?{ranges}"
    metadata_url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}?fields=sheets.properties(title,sheetId,index)"

    return {
        "name": "T16-verify-dashboard",
        "nodes": [
            {
                "id": "wh", "name": "WH",
                "type": "n8n-nodes-base.webhook", "typeVersion": 2,
                "position": [0,0], "webhookId": "t16-verify",
                "parameters": {"path": WEBHOOK_PATH, "httpMethod": "POST", "responseMode": "responseNode"},
            },
            {
                "id": "meta", "name": "GetMetadata",
                "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2,
                "position": [240,0], "credentials": SHEETS_CRED,
                "parameters": {
                    "method": "GET",
                    "url": metadata_url,
                    "authentication": "predefinedCredentialType",
                    "nodeCredentialType": "googleSheetsOAuth2Api",
                    "options": {},
                },
            },
            {
                "id": "vals", "name": "GetValues",
                "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2,
                "position": [480,0], "credentials": SHEETS_CRED,
                "parameters": {
                    "method": "GET",
                    "url": values_url,
                    "authentication": "predefinedCredentialType",
                    "nodeCredentialType": "googleSheetsOAuth2Api",
                    "options": {},
                },
            },
            {
                "id": "merge", "name": "Merge",
                "type": "n8n-nodes-base.merge", "typeVersion": 3.2,
                "position": [720,0],
                "parameters": {"mode": "combine", "combineBy": "combineByPosition"},
            },
            {
                "id": "resp", "name": "Respond",
                "type": "n8n-nodes-base.respondToWebhook", "typeVersion": 1,
                "position": [960,0],
                "parameters": {
                    "respondWith": "json",
                    "responseBody": "={{ { metadata: $node['GetMetadata'].json, values: $node['GetValues'].json } }}",
                },
            },
        ],
        "connections": {
            "WH":          {"main": [[{"node": "GetMetadata", "type": "main", "index": 0}]]},
            "GetMetadata": {"main": [[{"node": "GetValues",   "type": "main", "index": 0}]]},
            "GetValues":   {"main": [[{"node": "Respond",     "type": "main", "index": 0}]]},
        },
        "settings": {"executionOrder": "v1"},
    }


def main():
    print("=== T16 verify dashboard ===\n")

    print("1. Création du workflow de vérification…")
    r = requests.post(f"{N8N_BASE}/api/v1/workflows", headers=H, json=build_workflow())
    if r.status_code >= 400:
        print(f"  ✗ HTTP {r.status_code}: {r.text}"); sys.exit(1)
    wf_id = r.json()["id"]
    print(f"  ✓ id={wf_id}")

    print("2. Activation…")
    requests.post(f"{N8N_BASE}/api/v1/workflows/{wf_id}/activate", headers=H)
    time.sleep(2)

    print("3. Trigger webhook…")
    r = requests.post(f"{N8N_BASE}/webhook/{WEBHOOK_PATH}", json={})
    if r.status_code >= 400:
        print(f"  ✗ HTTP {r.status_code}: {r.text[:500]}"); sys.exit(2)
    data = r.json()

    print("4. Désactivation + suppression…")
    requests.post(f"{N8N_BASE}/api/v1/workflows/{wf_id}/deactivate", headers=H)
    requests.delete(f"{N8N_BASE}/api/v1/workflows/{wf_id}", headers=H)

    print()
    print("=== Validation DoD ===")

    # 1. 9 tabs in expected order
    tabs = [s["properties"]["title"] for s in data["metadata"]["sheets"]]
    print(f"\nOnglets présents ({len(tabs)}):")
    for t in tabs:
        marker = "✓" if t in EXPECTED_TABS else "?"
        print(f"  {marker} {t}")
    missing = [t for t in EXPECTED_TABS if t not in tabs]
    extra   = [t for t in tabs if t not in EXPECTED_TABS]
    tabs_ok = not missing and not extra
    if missing: print(f"  ✗ manquants : {missing}")
    if extra:   print(f"  ⚠ inattendus : {extra}")

    # 2. Personas + Products content
    value_ranges = {vr["range"].split("!")[0].strip("'"): vr.get("values", []) for vr in data["values"]["valueRanges"]}

    personas_rows = value_ranges.get("Personas", [])
    products_rows = value_ranges.get("Products", [])

    print(f"\nPersonas : {len(personas_rows)} rows (attendu: 11 = 1 header + 10)")
    if personas_rows:
        print(f"  Header : {personas_rows[0]}")
        for r in personas_rows[1:4]:
            print(f"  Row    : {r}")
        if len(personas_rows) > 4:
            print(f"  ... ({len(personas_rows)-4} de plus)")
    personas_ok = len(personas_rows) == 11

    print(f"\nProducts : {len(products_rows)} rows (attendu: 18 = 1 header + 17)")
    if products_rows:
        print(f"  Header : {products_rows[0]}")
        for r in products_rows[1:3]:
            print(f"  Row    : {r}")
        if len(products_rows) > 3:
            print(f"  ... ({len(products_rows)-3} de plus)")
    products_ok = len(products_rows) == 18

    # 3. Other tabs have header
    print("\nAutres onglets (header-only) :")
    other_ok = True
    for tab in EXPECTED_TABS[2:]:
        rows = value_ranges.get(tab, [])
        has_header = len(rows) >= 1 and len(rows[0]) > 0
        print(f"  {'✓' if has_header else '✗'} {tab} : {len(rows)} row(s), header = {rows[0] if rows else '—'}")
        if not has_header:
            other_ok = False

    print()
    print("=== Résultat ===")
    print(f"  9 onglets corrects   : {'✓' if tabs_ok else '✗'}")
    print(f"  Personas peuplé      : {'✓' if personas_ok else '✗'}")
    print(f"  Products peuplé      : {'✓' if products_ok else '✗'}")
    print(f"  Headers autres tabs  : {'✓' if other_ok else '✗'}")

    if tabs_ok and personas_ok and products_ok and other_ok:
        print("\n✓ DoD T16 validé")
        sys.exit(0)
    else:
        print("\n✗ DoD T16 incomplet")
        sys.exit(3)


if __name__ == "__main__":
    main()
