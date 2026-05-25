#!/usr/bin/env python3
"""T7a — Setup Drive : crée DailySmileCare/ et DailySmileCare/staging/ (idempotent),
sauvegarde les IDs dans .env (DRIVE_ROOT_FOLDER_ID, DRIVE_STAGING_FOLDER_ID).

Utilise le credential OAuth2 'Google Drive account' déjà configuré dans n8n
(via un workflow webhook éphémère).
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

N8N_BASE = os.environ["N8N_BASE_URL"]
N8N_KEY  = os.environ["N8N_API_KEY"]
H = {"X-N8N-API-KEY": N8N_KEY, "Content-Type": "application/json"}
DRIVE_CRED = {"googleDriveOAuth2Api": {"id": "Sirms4q3Rl05Mlj6", "name": "Google Drive account"}}

WEBHOOK_PATH = "t7-setup-drive"

# JS body executed inside an n8n Code node — uses $request to call Drive API
# directly with the OAuth credential. But Code nodes don't auto-inject OAuth,
# so we'll use HTTP Request nodes + a Code node to glue.

def build_workflow():
    """Workflow that searches for the 2 folders (idempotent); creates only if missing."""
    return {
        "name": "T7-setup-drive",
        "nodes": [
            {"id":"wh","name":"WH","type":"n8n-nodes-base.webhook","typeVersion":2,
             "position":[0,0],"webhookId":WEBHOOK_PATH,
             "parameters":{"path":WEBHOOK_PATH,"httpMethod":"POST","responseMode":"responseNode"}},
            # 1. Search "DailySmileCare" at root
            {"id":"search_root","name":"SearchRoot","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[240,0],"credentials":DRIVE_CRED,
             "parameters":{
                "method":"GET",
                "url":"https://www.googleapis.com/drive/v3/files",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleDriveOAuth2Api",
                "sendQuery":True,"specifyQuery":"keypair",
                "queryParameters":{"parameters":[
                    {"name":"q","value":"name='DailySmileCare' and mimeType='application/vnd.google-apps.folder' and 'root' in parents and trashed=false"},
                    {"name":"fields","value":"files(id,name)"},
                    {"name":"spaces","value":"drive"},
                ]},
                "options":{},
             }},
            # 2. Resolve root: if found → use existing; else create
            {"id":"resolve_root","name":"ResolveRoot","type":"n8n-nodes-base.code","typeVersion":2,
             "position":[480,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":
                "const files = $input.first().json.files || [];\n"
                "if (files.length > 0) return [{ json: { root_id: files[0].id, root_created: false } }];\n"
                "return [{ json: { root_id: null, root_created: true } }];"
             }},
            # 3. If not found, create it
            {"id":"if_create_root","name":"IfCreateRoot","type":"n8n-nodes-base.if","typeVersion":2,
             "position":[720,0],
             "parameters":{
                "conditions":{"options":{"caseSensitive":True,"leftValue":"","typeValidation":"loose"},
                    "conditions":[{"leftValue":"={{ $json.root_created }}","rightValue":True,
                                   "operator":{"type":"boolean","operation":"equals"}}],
                    "combinator":"and"},
             }},
            {"id":"create_root","name":"CreateRoot","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[960,0],"credentials":DRIVE_CRED,
             "parameters":{
                "method":"POST",
                "url":"https://www.googleapis.com/drive/v3/files",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleDriveOAuth2Api",
                "sendBody":True,"specifyBody":"json",
                "jsonBody": json.dumps({"name":"DailySmileCare","mimeType":"application/vnd.google-apps.folder","parents":["root"]}),
                "options":{},
             }},
            # 4. Merge: pick root_id from either branch
            {"id":"merge_root","name":"MergeRoot","type":"n8n-nodes-base.code","typeVersion":2,
             "position":[1200,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":
                "const j = $input.first().json;\n"
                "const root_id = j.id || j.root_id;\n"
                "const created = !!j.id;\n"
                "return [{ json: { root_id, root_created: created } }];"
             }},
            # 5. Search "staging" under root
            {"id":"search_staging","name":"SearchStaging","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[1440,0],"credentials":DRIVE_CRED,
             "parameters":{
                "method":"GET",
                "url":"https://www.googleapis.com/drive/v3/files",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleDriveOAuth2Api",
                "sendQuery":True,"specifyQuery":"keypair",
                "queryParameters":{"parameters":[
                    {"name":"q","value":"=name='staging' and mimeType='application/vnd.google-apps.folder' and '{{ $json.root_id }}' in parents and trashed=false"},
                    {"name":"fields","value":"files(id,name)"},
                    {"name":"spaces","value":"drive"},
                ]},
                "options":{},
             }},
            # 6. Resolve staging
            {"id":"resolve_staging","name":"ResolveStaging","type":"n8n-nodes-base.code","typeVersion":2,
             "position":[1680,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":
                "const j = $input.first().json;\n"
                "const files = j.files || [];\n"
                "const root_id = $node['MergeRoot'].json.root_id;\n"
                "if (files.length > 0) return [{ json: { root_id, staging_id: files[0].id, staging_created: false } }];\n"
                "return [{ json: { root_id, staging_id: null, staging_created: true } }];"
             }},
            # 7. If staging not found, create
            {"id":"if_create_staging","name":"IfCreateStaging","type":"n8n-nodes-base.if","typeVersion":2,
             "position":[1920,0],
             "parameters":{
                "conditions":{"options":{"caseSensitive":True,"leftValue":"","typeValidation":"loose"},
                    "conditions":[{"leftValue":"={{ $json.staging_created }}","rightValue":True,
                                   "operator":{"type":"boolean","operation":"equals"}}],
                    "combinator":"and"},
             }},
            {"id":"create_staging","name":"CreateStaging","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[2160,0],"credentials":DRIVE_CRED,
             "parameters":{
                "method":"POST",
                "url":"https://www.googleapis.com/drive/v3/files",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleDriveOAuth2Api",
                "sendBody":True,"specifyBody":"json",
                "jsonBody": "={{ JSON.stringify({ name: 'staging', mimeType: 'application/vnd.google-apps.folder', parents: [$json.root_id] }) }}",
                "options":{},
             }},
            # 8. Final merge — pick staging_id
            {"id":"merge_staging","name":"MergeStaging","type":"n8n-nodes-base.code","typeVersion":2,
             "position":[2400,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":
                "const j = $input.first().json;\n"
                "const staging_id = j.id || j.staging_id;\n"
                "const root_id = $node['MergeRoot'].json.root_id;\n"
                "return [{ json: { dailysmilecare_id: root_id, staging_id, root_created: $node['MergeRoot'].json.root_created, staging_created: !!j.id } }];"
             }},
            # 9. Respond
            {"id":"resp","name":"Respond","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,
             "position":[2640,0],
             "parameters":{"respondWith":"json","responseBody":"={{ $json }}"}},
        ],
        "connections":{
            "WH":           {"main":[[{"node":"SearchRoot","type":"main","index":0}]]},
            "SearchRoot":   {"main":[[{"node":"ResolveRoot","type":"main","index":0}]]},
            "ResolveRoot":  {"main":[[{"node":"IfCreateRoot","type":"main","index":0}]]},
            "IfCreateRoot": {"main":[
                [{"node":"CreateRoot","type":"main","index":0}],  # true branch → create
                [{"node":"MergeRoot","type":"main","index":0}],   # false branch → skip to merge
            ]},
            "CreateRoot":   {"main":[[{"node":"MergeRoot","type":"main","index":0}]]},
            "MergeRoot":    {"main":[[{"node":"SearchStaging","type":"main","index":0}]]},
            "SearchStaging":{"main":[[{"node":"ResolveStaging","type":"main","index":0}]]},
            "ResolveStaging":{"main":[[{"node":"IfCreateStaging","type":"main","index":0}]]},
            "IfCreateStaging":{"main":[
                [{"node":"CreateStaging","type":"main","index":0}],
                [{"node":"MergeStaging","type":"main","index":0}],
            ]},
            "CreateStaging":{"main":[[{"node":"MergeStaging","type":"main","index":0}]]},
            "MergeStaging": {"main":[[{"node":"Respond","type":"main","index":0}]]},
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
    print("=== T7a — Setup Drive folder structure ===\n")
    print("1. Création du workflow éphémère…")
    r = requests.post(f"{N8N_BASE}/api/v1/workflows", headers=H, json=build_workflow())
    if r.status_code >= 400:
        print(r.status_code, r.text); sys.exit(1)
    wf_id = r.json()["id"]
    print(f"   id={wf_id}")

    requests.post(f"{N8N_BASE}/api/v1/workflows/{wf_id}/activate", headers=H)
    time.sleep(2)

    print("2. Trigger…")
    r = requests.post(f"{N8N_BASE}/webhook/{WEBHOOK_PATH}", json={})
    print(f"   HTTP {r.status_code}")
    body = None
    try:
        body = r.json()
        print(f"   Response: {json.dumps(body, indent=2)}")
    except Exception:
        print(f"   Raw: {r.text[:500]}")

    print("3. Cleanup…")
    requests.post(f"{N8N_BASE}/api/v1/workflows/{wf_id}/deactivate", headers=H)
    requests.delete(f"{N8N_BASE}/api/v1/workflows/{wf_id}", headers=H)

    if r.status_code != 200 or not body:
        print("✗ Setup échoué"); sys.exit(2)
    if "error" in body:
        print(f"✗ Erreur workflow: {body['error']}")
        sys.exit(2)

    root_id = body.get("dailysmilecare_id")
    staging_id = body.get("staging_id")
    if not root_id or not staging_id:
        print(f"✗ IDs manquants dans la réponse: {body}")
        sys.exit(2)

    print(f"\n   DailySmileCare folder ID : {root_id}  (created={body.get('root_created')})")
    print(f"   staging folder ID        : {staging_id}  (created={body.get('staging_created')})")

    print("\n4. Mise à jour .env…")
    update_env({
        "DRIVE_ROOT_FOLDER_ID": root_id,
        "DRIVE_STAGING_FOLDER_ID": staging_id,
    })
    print("   ✓ DRIVE_ROOT_FOLDER_ID + DRIVE_STAGING_FOLDER_ID ajoutés à .env")
    print("\n✓ Setup Drive terminé")


if __name__ == "__main__":
    main()
