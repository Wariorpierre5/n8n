#!/usr/bin/env python3
"""T9 — Workflow n8n `DailySmileCare-v2-YouTube-Upload`.

Webhook POST { drive_file_id, title, description, tags }
→ Drive download MP4 → YouTube upload (unlisted) → respond { permalink }
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
H = {"X-N8N-API-KEY": K, "Content-Type": "application/json"}

DRIVE_CRED   = {"googleDriveOAuth2Api":  {"id": "Sirms4q3Rl05Mlj6", "name": "Google Drive account"}}
YOUTUBE_CRED = {"youTubeOAuth2Api":      {"id": "KV9MNZ2440wxY2v2", "name": "YouTube account"}}

WEBHOOK_PATH = "dsc-youtube-upload"


def build_workflow():
    return {
        "name":"DailySmileCare-v2-YouTube-Upload",
        "nodes":[
            {"id":"wh","name":"Webhook","type":"n8n-nodes-base.webhook","typeVersion":2,
             "position":[0,0],"webhookId":WEBHOOK_PATH,
             "parameters":{"path":WEBHOOK_PATH,"httpMethod":"POST","responseMode":"responseNode"}},

            # 1. Download MP4 from Drive as binary
            {"id":"dl","name":"DriveDownload","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[240,0],"credentials":DRIVE_CRED,
             "parameters":{
                "method":"GET",
                "url":"=https://www.googleapis.com/drive/v3/files/{{ $json.body.drive_file_id }}?alt=media",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleDriveOAuth2Api",
                "options":{"response":{"response":{"responseFormat":"file","outputPropertyName":"data"}}},
             }},

            # 2. Upload to YouTube (resource=video, operation=upload)
            {"id":"yt","name":"YouTubeUpload","type":"n8n-nodes-base.youTube","typeVersion":1,
             "position":[480,0],"credentials":YOUTUBE_CRED,
             "parameters":{
                "resource":"video",
                "operation":"upload",
                "title":"={{ $node['Webhook'].json.body.title }}",
                "regionCode":"US",
                "categoryId":"22",  # People & Blogs
                "binaryProperty":"data",
                "options":{
                    "description":"={{ $node['Webhook'].json.body.description }}",
                    "tags":"={{ ($node['Webhook'].json.body.tags || []).join(',') }}",
                    "privacyStatus":"unlisted",
                    "madeForKids":False,
                },
             }},

            # 3. Build permalink + respond
            {"id":"code","name":"BuildResp","type":"n8n-nodes-base.code","typeVersion":2,
             "position":[720,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":
                "const v = $input.first().json;\n"
                "// n8n YouTube node returns { uploadId: <videoId> } — uploadId IS the final videoId\n"
                "const id = v.id || v.video_id || v.uploadId || (v.snippet && v.snippet.resourceId && v.snippet.resourceId.videoId);\n"
                "const permalink = id ? `https://youtu.be/${id}` : null;\n"
                "return [{ json: { ok: !!id, video_id: id, permalink, raw: v } }];"
             }},

            {"id":"resp","name":"Respond","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,
             "position":[960,0],
             "parameters":{"respondWith":"json","responseBody":"={{ $json }}"}},
        ],
        "connections":{
            "Webhook":      {"main":[[{"node":"DriveDownload","type":"main","index":0}]]},
            "DriveDownload":{"main":[[{"node":"YouTubeUpload","type":"main","index":0}]]},
            "YouTubeUpload":{"main":[[{"node":"BuildResp","type":"main","index":0}]]},
            "BuildResp":    {"main":[[{"node":"Respond","type":"main","index":0}]]},
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
    print("=== T9 — Build & deploy YouTube-Upload workflow ===\n")
    # Delete existing
    r = requests.get(f"{N8N}/api/v1/workflows", headers=H)
    for w in r.json().get("data", []):
        if w["name"] == "DailySmileCare-v2-YouTube-Upload":
            print(f"  ↻ suppression existant id={w['id']}")
            try: requests.post(f"{N8N}/api/v1/workflows/{w['id']}/deactivate", headers=H)
            except: pass
            requests.delete(f"{N8N}/api/v1/workflows/{w['id']}", headers=H)

    r = requests.post(f"{N8N}/api/v1/workflows", headers=H, json=build_workflow())
    if r.status_code >= 400:
        print(r.text[:500]); sys.exit(1)
    wf_id = r.json()["id"]
    update_env({"N8N_WORKFLOW_ID_YT_UPLOAD": wf_id})
    print(f"  ✓ id={wf_id}")

    requests.post(f"{N8N}/api/v1/workflows/{wf_id}/activate", headers=H)
    print(f"  ✓ Actif")
    print(f"\nWebhook URL: {N8N}/webhook/{WEBHOOK_PATH}")


if __name__ == "__main__":
    main()
