#!/usr/bin/env python3
"""T7a — Construit le pipeline social MVP dans le workflow DailySmileCare-v2.

Pipeline (14 nœuds) :
  Webhook → InitContext → ReadSheets → ResolvePersona →
  CallClaude → ParseClaude →
  CreateDateFolder → CreatePersonaFolder →
  PrepareFiles → UploadFiles (loop) →
  BuildSheetsRows → AppendCostTracker → AppendContentCalendar →
  Respond

Génère 5 contenus plateforme par persona (X, YT Shorts, IG Reel, TikTok, Snap).
Pas d'image ni d'audio dans T7a — uniquement textes (DoD strict).
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
STAGING_ID = os.environ["DRIVE_STAGING_FOLDER_ID"]
WF_ID    = os.environ["N8N_WORKFLOW_ID_V2"]

H = {"X-N8N-API-KEY": N8N_KEY, "Content-Type": "application/json"}
SHEETS_CRED   = {"googleSheetsOAuth2Api": {"id": "vJiNfwvBkcQFu7Qf", "name": "Google Sheets account 2"}}
DRIVE_CRED    = {"googleDriveOAuth2Api": {"id": "Sirms4q3Rl05Mlj6", "name": "Google Drive account"}}
ANTHROPIC_CRED= {"anthropicApi": {"id": "EefN2CGrd138d9jV", "name": "Anthropic account 2"}}

WEBHOOK_PATH = "dailysmile-v2-daily"

# JavaScript for the InitContext node
INIT_JS = """
const now = new Date();
const yyyy = now.getUTCFullYear();
const mm = String(now.getUTCMonth() + 1).padStart(2, '0');
const dd = String(now.getUTCDate()).padStart(2, '0');
const today = `${yyyy}-${mm}-${dd}`;
const dom = now.getUTCDate();
const persona_index = ((dom - 1) % 10) + 1; // 1..10 rotating with day-of-month
const run_id = `${today}-p${persona_index}-${Date.now().toString(36)}`;
return [{ json: { today, dom, persona_index, run_id, staging_id: '%STAGING_ID%' } }];
""".replace("%STAGING_ID%", STAGING_ID)

# Resolve persona+product from Sheets batchGet response
RESOLVE_JS = """
const input = $input.first().json;
const ctx = $node['InitContext'].json;
const valueRanges = input.valueRanges || [];

const personasRows = (valueRanges.find(v => v.range && v.range.indexOf('Personas') === 0) || {}).values || [];
const productsRows = (valueRanges.find(v => v.range && v.range.indexOf('Products') === 0) || {}).values || [];

const pHeaders = personasRows[0] || [];
const prHeaders = productsRows[0] || [];

const rowToObj = (headers, row) => Object.fromEntries(headers.map((h, i) => [h, row[i] != null ? row[i] : '']));

const targetId = String(ctx.persona_index);
const persona = personasRows.slice(1)
  .map(r => rowToObj(pHeaders, r))
  .find(p => String(p.id) === targetId);
if (!persona) throw new Error('Persona not found. target=' + targetId + ' available=' + personasRows.slice(1).map(r => r[0]).join(','));

const products = productsRows.slice(1).map(r => rowToObj(prHeaders, r));
const product = products.find(p => (p.target_persona_ids || '').split(',').map(s => s.trim()).includes(persona.name));
if (!product) throw new Error('Product not found for persona ' + persona.name + '. Products with target_persona_ids: ' + products.filter(p => p.target_persona_ids).map(p => p.name + '=' + p.target_persona_ids).join(' | '));

return [{ json: { ...ctx, persona, product } }];
"""

# Anthropic Claude prompt — request structured JSON output
CLAUDE_SYSTEM = (
    "You are an affiliate-marketing copywriter for DailySmileCare, an Amazon-affiliate "
    "blog about electric toothbrushes targeting an American audience. You write in the "
    "FIRST PERSON voice of the assigned persona. Each post mentions the assigned product "
    "by name once, sounds like a friend-to-friend recommendation, and avoids sales cliches. "
    "Output strictly valid JSON, no markdown fences, no preamble."
)

CLAUDE_USER_TEMPLATE_RAW = """Generate 5 social media content variations for today's persona.

PERSONA NAME: __PERSONA_NAME__
PERSONA REGION: __PERSONA_REGION__
PERSONA ACCENT: __PERSONA_ACCENT__
PERSONA BRAND FOCUS: __PERSONA_BRAND_FOCUS__

ASSIGNED PRODUCT: __PRODUCT_BRAND__ __PRODUCT_MODEL__

THEME OF THE DAY: pick a single distinctive angle (an observation, a problem solved, a small detail). Don't restate the persona's bio.

OUTPUT JSON (strict, all string fields):
{
  "content_theme": "short title of today's angle, 6-10 words",
  "x_post": "280 chars MAX, casual, includes a hook, mentions the product naturally",
  "youtube_shorts_script": "~75 words, structured: hook (first 5s) / story (15s) / CTA (10s). Plain text only.",
  "instagram_reel_script": "~50 words, hook / payoff / CTA, conversational",
  "tiktok_script": "~50 words, native casual TikTok voice, ends with a question or hook",
  "snapchat_caption": "60 chars MAX, friend-to-friend tone, no hashtags"
}

All copy in American English. Reference the product by brand+model at least once across these 5 variations. Do NOT include affiliate URLs (added externally)."""

# JavaScript code that builds the Claude request body via substitution
PREPARE_CLAUDE_BODY_JS = """
const ctx = $input.first().json;
const template = """ + json.dumps(CLAUDE_USER_TEMPLATE_RAW) + """;
const userText = template
  .replace('__PERSONA_NAME__',        ctx.persona.name)
  .replace('__PERSONA_REGION__',      ctx.persona.region)
  .replace('__PERSONA_ACCENT__',      ctx.persona.accent)
  .replace('__PERSONA_BRAND_FOCUS__', ctx.persona.brand_focus)
  .replace('__PRODUCT_BRAND__',       ctx.product.brand)
  .replace('__PRODUCT_MODEL__',       ctx.product.model);

const claude_body = {
  model: 'claude-sonnet-4-6',
  max_tokens: 1500,
  system: """ + json.dumps(CLAUDE_SYSTEM) + """,
  messages: [{ role: 'user', content: userText }],
};

return [{ json: { ...ctx, claude_body } }];
"""

# Parse Claude — extract JSON + token counts
PARSE_CLAUDE_JS = """
const resp = $input.first().json;
const ctx = $node['ResolvePersona'].json;

const usage = resp.usage || {};
const tokens_in = usage.input_tokens || 0;
const tokens_out = usage.output_tokens || 0;

const textBlock = (resp.content || []).find(c => c.type === 'text');
const raw = textBlock ? textBlock.text : '';

// Strip code fences if present
let cleaned = raw.trim();
if (cleaned.startsWith('```')) {
  cleaned = cleaned.replace(/^```(?:json)?\\s*/, '').replace(/\\s*```$/, '');
}

let parsed;
try { parsed = JSON.parse(cleaned); } catch (e) {
  throw new Error('Claude returned non-JSON: ' + cleaned.slice(0, 200));
}

return [{
  json: {
    ...ctx,
    tokens_in,
    tokens_out,
    content_theme: parsed.content_theme || '',
    posts: {
      x: parsed.x_post || '',
      youtube_shorts: parsed.youtube_shorts_script || '',
      instagram_reel: parsed.instagram_reel_script || '',
      tiktok: parsed.tiktok_script || '',
      snapchat: parsed.snapchat_caption || '',
    },
  },
}];
"""

# Prepare 5 file items for the Drive upload loop
PREPARE_FILES_JS = """
const parsed = $node['ParseClaude'].json;
const personaFolderId = $node['CreatePersonaFolder'].json.id;

const files = [
  { fileName: 'x_post.txt',                content: parsed.posts.x || '' },
  { fileName: 'youtube_shorts_script.txt', content: parsed.posts.youtube_shorts || '' },
  { fileName: 'instagram_reel_script.txt', content: parsed.posts.instagram_reel || '' },
  { fileName: 'tiktok_script.txt',         content: parsed.posts.tiktok || '' },
  { fileName: 'snapchat_caption.txt',      content: parsed.posts.snapchat || '' },
];

// One item per file, each with binary payload for Drive upload
return files.map(f => ({
  json: {
    run_id: parsed.run_id,
    persona_name: parsed.persona.name,
    fileName: f.fileName,
    content: f.content,
    parent: personaFolderId,
  },
  binary: {
    data: {
      data: Buffer.from(f.content, 'utf-8').toString('base64'),
      mimeType: 'text/plain',
      fileName: f.fileName,
    },
  },
}));
"""

# Build the rows for Cost_Tracker and Content_Calendar
BUILD_SHEETS_ROWS_JS = """
// Inputs from upstream: tokens, persona, product, posts, content_theme
const ctx = $node['ParseClaude'].json;
const today = ctx.today;
const persona = ctx.persona;

// Claude Sonnet 4.6 pricing: $3 / Mtok in, $15 / Mtok out (rough; treat as estimate)
const cost = (ctx.tokens_in / 1_000_000) * 3 + (ctx.tokens_out / 1_000_000) * 15;

const platforms = ['x', 'youtube_shorts', 'instagram_reel', 'tiktok', 'snapchat'];
const costRows = platforms.map(p => [
  today,
  `${ctx.run_id}-${p}`,
  Math.round(ctx.tokens_in / platforms.length),
  Math.round(ctx.tokens_out / platforms.length),
  0,
  (cost / platforms.length).toFixed(4),
]);
const calendarRows = platforms.map(p => [
  `${ctx.run_id}-${p}`,
  today,
  persona.id,
  p,
  'social_post',
  'pending_approval',
  '',
]);

return [{ json: { costRows, calendarRows } }];
"""


def build_workflow():
    return {
        "name": "DailySmileCare-v2",
        "nodes": [
            # 0. Webhook trigger
            {"id":"wh","name":"Webhook","type":"n8n-nodes-base.webhook","typeVersion":2,
             "position":[0,0],"webhookId":WEBHOOK_PATH,
             "parameters":{"path":WEBHOOK_PATH,"httpMethod":"POST","responseMode":"responseNode"}},

            # 1. Init context (date, persona_index, run_id)
            {"id":"init","name":"InitContext","type":"n8n-nodes-base.code","typeVersion":2,
             "position":[240,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":INIT_JS}},

            # 2. Read Sheets Personas + Products (ranges in URL — keypair collapses duplicates)
            {"id":"read","name":"ReadSheets","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[480,0],"credentials":SHEETS_CRED,
             "parameters":{
                "method":"GET",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values:batchGet?ranges=Personas!A1:H11&ranges=Products!A1:I18",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "options":{},
             }},

            # 3. Resolve today's persona + assigned product
            {"id":"resolve","name":"ResolvePersona","type":"n8n-nodes-base.code","typeVersion":2,
             "position":[720,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":RESOLVE_JS}},

            # 3b. Build the Claude request body (avoids nested {{ }} in HTTP node)
            {"id":"prep_claude","name":"PrepareClaudeBody","type":"n8n-nodes-base.code","typeVersion":2,
             "position":[840,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":PREPARE_CLAUDE_BODY_JS}},

            # 4. Call Claude
            {"id":"claude","name":"CallClaude","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[960,0],"credentials":ANTHROPIC_CRED,
             "parameters":{
                "method":"POST",
                "url":"https://api.anthropic.com/v1/messages",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"anthropicApi",
                "sendHeaders":True,"specifyHeaders":"keypair",
                "headerParameters":{"parameters":[
                    {"name":"anthropic-version","value":"2023-06-01"},
                ]},
                "sendBody":True,"specifyBody":"json",
                "jsonBody": "={{ JSON.stringify($json.claude_body) }}",
                "options":{},
             }},

            # 5. Parse Claude response (extract JSON + tokens)
            {"id":"parse","name":"ParseClaude","type":"n8n-nodes-base.code","typeVersion":2,
             "position":[1200,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":PARSE_CLAUDE_JS}},

            # 6. Create date folder under staging
            {"id":"date_folder","name":"CreateDateFolder","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[1440,0],"credentials":DRIVE_CRED,
             "parameters":{
                "method":"POST",
                "url":"https://www.googleapis.com/drive/v3/files",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleDriveOAuth2Api",
                "sendBody":True,"specifyBody":"json",
                "jsonBody": "={{ JSON.stringify({ name: $json.today, mimeType: 'application/vnd.google-apps.folder', parents: [$json.staging_id] }) }}",
                "options":{},
             }},

            # 7. Create persona folder under date folder
            {"id":"persona_folder","name":"CreatePersonaFolder","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[1680,0],"credentials":DRIVE_CRED,
             "parameters":{
                "method":"POST",
                "url":"https://www.googleapis.com/drive/v3/files",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleDriveOAuth2Api",
                "sendBody":True,"specifyBody":"json",
                "jsonBody": "={{ JSON.stringify({ name: $node['ParseClaude'].json.persona.name, mimeType: 'application/vnd.google-apps.folder', parents: [$json.id] }) }}",
                "options":{},
             }},

            # 8. Prepare 5 file items
            {"id":"prep","name":"PrepareFiles","type":"n8n-nodes-base.code","typeVersion":2,
             "position":[1920,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":PREPARE_FILES_JS}},

            # 9. Upload to Drive (loops over 5 items)
            {"id":"upload","name":"UploadFiles","type":"n8n-nodes-base.googleDrive","typeVersion":3,
             "position":[2160,0],"credentials":DRIVE_CRED,
             "parameters":{
                "resource":"file",
                "operation":"upload",
                "name":"={{ $json.fileName }}",
                "driveId":{"__rl":True,"value":"My Drive","mode":"list"},
                "folderId":{"__rl":True,"value":"={{ $json.parent }}","mode":"id"},
                "options":{},
             }},

            # 10. Build the rows for Sheets
            {"id":"rows","name":"BuildSheetsRows","type":"n8n-nodes-base.code","typeVersion":2,
             "position":[2400,0],
             "parameters":{"mode":"runOnceForAllItems","language":"javaScript","jsCode":BUILD_SHEETS_ROWS_JS}},

            # 11. Append Cost_Tracker rows
            {"id":"cost","name":"AppendCostTracker","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[2640,0],"credentials":SHEETS_CRED,
             "parameters":{
                "method":"POST",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Cost_Tracker!A:F:append?valueInputOption=USER_ENTERED",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "sendBody":True,"specifyBody":"json",
                "jsonBody": "={{ JSON.stringify({ values: $json.costRows }) }}",
                "options":{},
             }},

            # 12. Append Content_Calendar rows
            {"id":"cal","name":"AppendContentCalendar","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[2880,0],"credentials":SHEETS_CRED,
             "parameters":{
                "method":"POST",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Content_Calendar!A:G:append?valueInputOption=USER_ENTERED",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "sendBody":True,"specifyBody":"json",
                "jsonBody": "={{ JSON.stringify({ values: $node['BuildSheetsRows'].json.calendarRows }) }}",
                "options":{},
             }},

            # 13. Respond
            {"id":"resp","name":"Respond","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,
             "position":[3120,0],
             "parameters":{"respondWith":"json","responseBody":
                "={{ { ok: true, run_id: $node['ParseClaude'].json.run_id, persona: $node['ParseClaude'].json.persona.name, content_theme: $node['ParseClaude'].json.content_theme, files_uploaded: 5 } }}"}},
        ],
        "connections":{
            "Webhook":              {"main":[[{"node":"InitContext","type":"main","index":0}]]},
            "InitContext":          {"main":[[{"node":"ReadSheets","type":"main","index":0}]]},
            "ReadSheets":           {"main":[[{"node":"ResolvePersona","type":"main","index":0}]]},
            "ResolvePersona":       {"main":[[{"node":"PrepareClaudeBody","type":"main","index":0}]]},
            "PrepareClaudeBody":    {"main":[[{"node":"CallClaude","type":"main","index":0}]]},
            "CallClaude":           {"main":[[{"node":"ParseClaude","type":"main","index":0}]]},
            "ParseClaude":          {"main":[[{"node":"CreateDateFolder","type":"main","index":0}]]},
            "CreateDateFolder":     {"main":[[{"node":"CreatePersonaFolder","type":"main","index":0}]]},
            "CreatePersonaFolder":  {"main":[[{"node":"PrepareFiles","type":"main","index":0}]]},
            "PrepareFiles":         {"main":[[{"node":"UploadFiles","type":"main","index":0}]]},
            "UploadFiles":          {"main":[[{"node":"BuildSheetsRows","type":"main","index":0}]]},
            "BuildSheetsRows":      {"main":[[{"node":"AppendCostTracker","type":"main","index":0}]]},
            "AppendCostTracker":    {"main":[[{"node":"AppendContentCalendar","type":"main","index":0}]]},
            "AppendContentCalendar":{"main":[[{"node":"Respond","type":"main","index":0}]]},
        },
        "settings":{"executionOrder":"v1"},
    }


def main():
    print("=== T7a — Build & deploy workflow DailySmileCare-v2 ===\n")
    wf = build_workflow()

    # PUT update the existing workflow
    print(f"1. PUT update workflow {WF_ID}…")
    r = requests.put(f"{N8N_BASE}/api/v1/workflows/{WF_ID}", headers=H, json=wf)
    if r.status_code >= 400:
        print(f"  ✗ HTTP {r.status_code}: {r.text[:500]}"); sys.exit(1)
    print(f"  ✓ {len(wf['nodes'])} nœuds installés")

    # Activate
    print("2. Activation…")
    r = requests.post(f"{N8N_BASE}/api/v1/workflows/{WF_ID}/activate", headers=H)
    if r.status_code >= 400:
        print(f"  ✗ HTTP {r.status_code}: {r.text[:300]}"); sys.exit(1)
    print("  ✓ Actif")

    # Wait then trigger via webhook
    time.sleep(3)
    webhook_url = f"{N8N_BASE}/webhook/{WEBHOOK_PATH}"
    print(f"3. Trigger : POST {webhook_url}")
    r = requests.post(webhook_url, json={}, timeout=180)
    print(f"  HTTP {r.status_code}")
    try:
        body = r.json()
        print(f"  Response: {json.dumps(body, indent=2)}")
    except Exception:
        print(f"  Raw: {r.text[:1500]}")
        body = None

    if r.status_code != 200 or not body or "error" in body:
        print("\n  ✗ Trigger échoué — désactivation pour debug")
        requests.post(f"{N8N_BASE}/api/v1/workflows/{WF_ID}/deactivate", headers=H)
        sys.exit(2)

    print("\n✓ T7a déployé et déclenché avec succès")
    print(f"  Persona du jour : {body.get('persona', '?')}")
    print(f"  Theme           : {body.get('content_theme', '?')}")
    print(f"  Files uploaded  : {body.get('files_uploaded', '?')}")
    print(f"\nVérifie côté Drive : DailySmileCare/staging/{time.strftime('%Y-%m-%d')}/{body.get('persona','')}/")


if __name__ == "__main__":
    main()
