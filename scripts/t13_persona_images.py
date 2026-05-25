#!/usr/bin/env python3
"""T13 — Génération des 10 reference images persona via Pollinations.ai (FLUX).

Sortie :
- personas/images/<name>.png   : 10 PNG carrés 1024x1024
- Sheets Personas : image_ref_url + prompt_seed peuplés

Pollinations est gratuit, no key. Modèle FLUX (qualité photorealiste correcte).
Le seed est dérivé du nom du persona (hash md5 tronqué) pour permettre
la regénération identique si besoin.
"""

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

N8N_BASE = os.environ["N8N_BASE_URL"]
N8N_KEY  = os.environ["N8N_API_KEY"]
SHEET_ID = os.environ["SHEETS_DASHBOARD_ID"]
H = {"X-N8N-API-KEY": N8N_KEY, "Content-Type": "application/json"}
SHEETS_CRED = {"googleSheetsOAuth2Api": {"id": "vJiNfwvBkcQFu7Qf", "name": "Google Sheets account 2"}}

OUT_DIR = ROOT / "personas" / "images"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Distilled prompts — under ~600 chars each, focused on the key persona visual
# (age, ethnicity, gender, location, key features, product, lighting).
PERSONAS = [
    {"id": "1", "name": "Ashley", "prompt":
        "A 34-year-old white American woman in a suburban Ohio bathroom, warm natural smile, "
        "medium-brown hair in a loose ponytail, faint laugh lines, minimal makeup, "
        "heather-gray pullover, holding an Aquasonic Black Series electric toothbrush "
        "(matte black body, silver accent ring, white sonic head) raised to chin height. "
        "White tile bathroom, warm overhead lighting, candid lifestyle 50mm photo, real not styled."},
    {"id": "2", "name": "Dorothy", "prompt":
        "A 68-year-old white American woman in a sunny Phoenix bathroom, warm genuine smile, "
        "silver-white short blow-dried hair, smile lines and sun-spotted skin, bright blue eyes, "
        "soft floral blouse, holding a Philips Sonicare 4100 Rechargeable electric toothbrush "
        "(white minimalist body, teal accent stripe, white brush head) raised to mouth, "
        "arthritic but careful grip. White tile, soft natural light, cactus on windowsill, 50mm lifestyle photo."},
    {"id": "3", "name": "Ethan", "prompt":
        "A 38-year-old white American man in a clean minimalist Portland bathroom, relaxed natural smile, "
        "dark brown hair with early gray at temples, short maintained beard with gray threading, lean build, "
        "moss green Patagonia fleece, holding a RANVOO AirJet X5 electric toothbrush "
        "(sleek matte-white cylindrical body, thin black accent band, white brush head) raised to mouth, "
        "light one-handed grip. White surfaces no clutter, small potted plant, 50mm photo."},
    {"id": "4", "name": "Jordan", "prompt":
        "A 26-year-old biracial Black-white man in a clean minimal Austin apartment bathroom, relaxed smile, "
        "natural medium hair slightly compressed one side, lean athletic build with post-workout flush, "
        "Oura Ring on right index finger, fitted sage-green merino t-shirt, holding a Philips Sonicare 7300 "
        "(dark navy body with rubber grip, small LED display, white brush head with teal ring) raised to mouth, "
        "relaxed one-handed grip. White surfaces, minimal counter, 50mm photo."},
    {"id": "5", "name": "Linda", "prompt":
        "A 58-year-old Black American woman in a Houston bathroom, calm resolute smile, "
        "natural hair in loose twists with silver strands, deep warm brown skin, reading glasses on forehead, "
        "deep burgundy button-down, holding a Philips Sonicare ProtectiveClean 5300 electric toothbrush "
        "(clean white with sky-blue accent panel, teal LED, white brush head) raised to mouth, "
        "steady confident grip. Beige white tile, clear counter, 50mm photo."},
    {"id": "6", "name": "Marcus", "prompt":
        "A polished Black American man in his early 50s in an Atlanta penthouse en-suite bathroom, "
        "composed confident smile, closely cropped fade with salt-and-pepper temples, deep mahogany skin, "
        "clean-shaven structured jaw, white dress shirt with rolled sleeves, "
        "holding a Philips Sonicare DiamondClean 9900 (pearl white soft-touch body with chrome accent, "
        "white brush head, silver Sonicare logo) raised to mouth. Large marble tile, frameless mirror, "
        "warm recessed lighting, 50mm editorial photo."},
    {"id": "7", "name": "Priya", "prompt":
        "A 31-year-old South Asian American woman visibly pregnant at 22 weeks in a clean modern Seattle "
        "apartment bathroom, calm reassured smile, thick dark wavy hair worn loose, warm medium-brown skin "
        "with pregnancy glow, small gold nose stud, fitted Lululemon top with maternity leggings, "
        "holding an Oral-B Pro 1000 (white body, dark navy grip band, round white brush head with blue "
        "bristles, green LED) raised to mouth, free hand resting on belly. White tile minimal soft light, 50mm photo."},
    {"id": "8", "name": "Raymond", "prompt":
        "A 61-year-old Black American man in a Minneapolis bathroom, quiet determined smile, "
        "closely cropped silver-white hair, deep-set warm eyes, lines between brows, "
        "navy plaid flannel tucked in, faint scar near collarbone visible above the collar, "
        "holding a Philips Sonicare ProtectiveClean 6500 (clean white with navy accent panel, teal 3-zone LED, "
        "white brush head) raised steadily to mouth, deliberate methodical grip. "
        "Neat white tile, clear counter, family photo softly blurred in mirror reflection, 50mm photo."},
    {"id": "9", "name": "Sophia", "prompt":
        "A 45-year-old Latina woman in a Chicago apartment bathroom, poised appearance-aware smile, "
        "dark brown straight glossy hair to collarbones, warm olive skin with light makeup, "
        "polished blazer with sleeves pushed up, holding an Oral-B iO 9 electric toothbrush "
        "(premium pearl-white body with chrome accent, small LED display, round white brush head with dense "
        "micro-bristles, green 3-color pressure LED) raised to mouth, practiced confident grip. "
        "Marble bathroom, frameless mirror, warm vanity lighting, 50mm editorial photo."},
    {"id": "10", "name": "Tyler", "prompt":
        "A 22-year-old white American man in a cramped Nashville college apartment bathroom, relaxed easy grin, "
        "medium-length slightly overgrown hair, lean build, slightly underdeveloped jawline with last fading "
        "teen acne, small forearm tattoo, faded band tee and joggers, holding a Philips Sonicare 4100 Rose "
        "(soft blush-pink body with darker rose rubber grip, teal LED, white brush head) raised to mouth, "
        "completely relaxed grip. Cluttered lived-in bathroom, string lights in doorframe, "
        "warm yellow lighting, real not styled, 50mm photo."},
]

POLLI_MODEL = "flux"

def persona_seed(name):
    """Deterministic seed from persona name for reproducibility."""
    return int(hashlib.md5(name.encode()).hexdigest()[:8], 16) % 1000000

def fetch_pollinations(prompt, seed, width=1024, height=1024):
    encoded = quote(prompt, safe="")
    url = (f"https://image.pollinations.ai/prompt/{encoded}"
           f"?width={width}&height={height}&model={POLLI_MODEL}&seed={seed}&nologo=true&enhance=true")
    r = requests.get(url, timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"Pollinations HTTP {r.status_code}: {r.text[:200]}")
    if not r.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError(f"Bad content-type: {r.headers.get('content-type')}")
    if len(r.content) < 5000:
        raise RuntimeError(f"Suspiciously small image: {len(r.content)} bytes")
    return r.content, url

def generate_all():
    print(f"=== T13 — Génération images persona via Pollinations.ai (modèle {POLLI_MODEL}) ===\n")
    results = []
    for p in PERSONAS:
        name = p["name"]
        prompt = p["prompt"]
        seed = persona_seed(name)
        out_path = OUT_DIR / f"{name.lower()}.png"
        if out_path.exists() and out_path.stat().st_size > 5000:
            print(f"  ↻ #{p['id']:>2}  {name:<8} → {out_path.relative_to(ROOT)} (skip, déjà existant)")
            results.append({**p, "seed": seed, "path": str(out_path.relative_to(ROOT)), "skipped": True})
            continue
        try:
            print(f"  → #{p['id']:>2}  {name:<8} (seed={seed})…", end="", flush=True)
            t0 = time.time()
            img_bytes, url = fetch_pollinations(prompt, seed)
            out_path.write_bytes(img_bytes)
            dt = time.time() - t0
            kb = len(img_bytes) / 1024
            print(f" ✓ {kb:6.0f} KB ({dt:4.1f}s)")
            results.append({**p, "seed": seed, "url": url, "path": str(out_path.relative_to(ROOT)), "skipped": False})
        except Exception as e:
            print(f" ✗ ERREUR: {e}")
            results.append({**p, "seed": seed, "error": str(e)})
    return results

def update_sheets(results):
    """Write image_ref_url (col G) and prompt_seed (col H) to Personas tab."""
    # Build values for G2:H11 (one row per persona, in id order 1..10)
    by_id = {r["id"]: r for r in results}
    rows = []
    for i in range(1, 11):
        r = by_id[str(i)]
        # image_ref_url: relative local path for now; will become a deployed URL later
        image_ref = r.get("path", "")
        # prompt_seed: the exact prompt + seed used (for reproducibility)
        prompt_seed = f"{r['prompt']}|seed={r['seed']}|model={POLLI_MODEL}|service=pollinations"
        rows.append([image_ref, prompt_seed])

    WEBHOOK_PATH = "t13-sync-images"
    workflow = {
        "name": "T13-sync-images",
        "nodes": [
            {"id":"wh","name":"WH","type":"n8n-nodes-base.webhook","typeVersion":2,
             "position":[0,0],"webhookId":"t13-sync-images",
             "parameters":{"path":WEBHOOK_PATH,"httpMethod":"POST","responseMode":"responseNode"}},
            {"id":"upd","name":"Update","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[240,0],"credentials":SHEETS_CRED,
             "parameters":{
                "method":"PUT",
                "url":f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/Personas!G2:H11?valueInputOption=RAW",
                "authentication":"predefinedCredentialType",
                "nodeCredentialType":"googleSheetsOAuth2Api",
                "sendBody":True,"specifyBody":"json",
                "jsonBody": json.dumps({"values": rows}),
                "options":{},
             }},
            {"id":"resp","name":"Respond","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,
             "position":[480,0],
             "parameters":{"respondWith":"json","responseBody":"={{ { ok: true, updated: $node['Update'].json } }}"}},
        ],
        "connections":{
            "WH":{"main":[[{"node":"Update","type":"main","index":0}]]},
            "Update":{"main":[[{"node":"Respond","type":"main","index":0}]]},
        },
        "settings":{"executionOrder":"v1"},
    }

    print(f"\n  Upload image_ref_url + prompt_seed → Personas!G2:H11")
    r = requests.post(f"{N8N_BASE}/api/v1/workflows", headers=H, json=workflow)
    wf_id = r.json()["id"]
    requests.post(f"{N8N_BASE}/api/v1/workflows/{wf_id}/activate", headers=H)
    time.sleep(2)
    r = requests.post(f"{N8N_BASE}/webhook/{WEBHOOK_PATH}", json={})
    print(f"  HTTP {r.status_code} — {r.text[:200]}")
    requests.post(f"{N8N_BASE}/api/v1/workflows/{wf_id}/deactivate", headers=H)
    requests.delete(f"{N8N_BASE}/api/v1/workflows/{wf_id}", headers=H)
    return r.status_code == 200

def main():
    results = generate_all()
    successes = [r for r in results if "error" not in r]
    failures = [r for r in results if "error" in r]
    print(f"\n  Générés : {len(successes)} / {len(PERSONAS)}")
    if failures:
        print(f"  Échecs   : {len(failures)}")
        for f in failures:
            print(f"    - {f['name']}: {f['error']}")
        sys.exit(2)
    ok = update_sheets(results)
    if not ok:
        print("  ✗ Sync Sheets a échoué")
        sys.exit(3)
    print("\n  ✓ Sheets Personas G2:H11 mises à jour")
    print("\n=== Récap fichiers ===")
    for f in sorted(OUT_DIR.glob("*.png")):
        print(f"  {f.relative_to(ROOT)}  ({f.stat().st_size//1024} KB)")

if __name__ == "__main__":
    main()
