#!/usr/bin/env python3
"""T13 (Imagen edition) — Regénération des 10 reference images persona via Imagen 4 Standard.

Différences vs version Pollinations :
- Prompts retravaillés : SANS brosse à dents, focus identitaire pur (visage, expression, environnement)
- Modèle Imagen 4 Standard ($0.04 / image, ~$0.40 pour les 10)
- Aspect ratio 3:4 (portrait), résolution native ~1024×1408
- Photoréalisme éditorial 50mm
"""

import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
N8N_BASE = os.environ["N8N_BASE_URL"]
N8N_KEY  = os.environ["N8N_API_KEY"]
SHEET_ID = os.environ["SHEETS_DASHBOARD_ID"]
H = {"X-N8N-API-KEY": N8N_KEY, "Content-Type": "application/json"}
SHEETS_CRED = {"googleSheetsOAuth2Api": {"id": "vJiNfwvBkcQFu7Qf", "name": "Google Sheets account 2"}}

MODEL = "imagen-4.0-generate-001"
ASPECT = "3:4"
PREDICT_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:predict?key={GEMINI_KEY}"

OUT_DIR = ROOT / "personas" / "images"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Prompts retravaillés — sans brosse à dent, focus visage / identité / ambiance
PERSONAS = [
    {"id":"1","name":"Ashley","prompt":
        "A photorealistic editorial portrait of a 34-year-old white American woman with medium-brown "
        "hair in a loose ponytail, a few strands escaping around her face. Faint laugh lines at the "
        "corners of her eyes, slight undereye circles, fair complexion. Minimal makeup. Warm natural "
        "smile. She wears a heather-gray pullover. Soft natural lighting from a frosted bathroom window "
        "mixed with warm overhead light. White or beige tiled suburban Ohio bathroom in the soft "
        "background, a mirror behind her. Candid lifestyle photograph, 50mm lens, f/2.2, real and "
        "unstaged, no studio softening."},
    {"id":"2","name":"Dorothy","prompt":
        "A photorealistic editorial portrait of a 68-year-old white American woman, petite, around 5'4\", "
        "with silver-white short blow-dried hair. Deep smile lines, sun-spotted skin from years in "
        "Phoenix, bright blue sharp eyes. She wears a soft floral blouse in muted pinks and blues. "
        "Warm genuine smile. Soft natural morning light, white tile bathroom in soft background, a "
        "single cactus on the windowsill. Candid lifestyle photograph, 50mm lens, f/2.5, real not staged."},
    {"id":"3","name":"Ethan","prompt":
        "A photorealistic editorial portrait of a 38-year-old white American man, around 6'0\", lean "
        "and casually fit. Dark brown hair with early gray at the temples, slightly overgrown. A short "
        "well-maintained beard with visible gray threading. Crow's feet at the corners of his eyes. "
        "He wears a moss-green Patagonia fleece. Relaxed natural smile. Clean minimalist Portland "
        "bathroom in the soft background — white surfaces, no clutter, a small potted plant on the "
        "windowsill. 50mm lens, f/2.2, candid editorial, real and intentional."},
    {"id":"4","name":"Jordan","prompt":
        "A photorealistic editorial portrait of a 26-year-old biracial Black-white American man, around "
        "5'11\", lean and visibly athletic. Natural medium-length hair slightly compressed on one side "
        "(just woke up). Clear skin with a slight post-workout flush. An Oura Ring visible on his right "
        "index finger. He wears a fitted short-sleeve sage-green merino t-shirt. Relaxed natural smile. "
        "Clean minimal Austin apartment bathroom in soft background, white surfaces, minimal products "
        "on the counter, no clutter. 50mm lens, f/2.2, candid lifestyle, real and unstaged."},
    {"id":"5","name":"Linda","prompt":
        "A photorealistic editorial portrait of a 58-year-old Black American woman, medium height, "
        "around 5'6\", with a full sturdy build. Natural hair in loose twists with silver strands at "
        "the roots. Deep warm brown skin. Reading glasses pushed up on her forehead. She wears a neat "
        "button-down shirt in deep burgundy. Calm resolute smile. Warm tidy Houston bathroom in soft "
        "background, beige or white tile, clear counter. 50mm lens, f/2.5, candid editorial, real and "
        "grounded."},
    {"id":"6","name":"Marcus","prompt":
        "A photorealistic editorial portrait of a polished Black American man in his early 50s, "
        "approximately 6'1\", lean and well-groomed. Closely cropped hair with a precise fade, "
        "salt-and-pepper at the temples. Deep mahogany skin, clean-shaven structured jaw. He wears a "
        "white dress shirt with the collar open and sleeves rolled to the forearm — end of a long day, "
        "still composed. Composed confident smile. Atlanta penthouse en-suite bathroom in soft "
        "background: large-format marble tile, frameless mirror, warm recessed lighting. 50mm lens, "
        "f/2.5, editorial photograph, premium aesthetic, real."},
    {"id":"7","name":"Priya","prompt":
        "A photorealistic editorial portrait of a 31-year-old South Asian American woman, visibly "
        "pregnant at approximately 22 weeks, around 5'5\". The round bump of mid-pregnancy clearly "
        "visible. Warm medium-brown skin with a pregnancy glow. Thick dark brown wavy hair worn in a "
        "casual low bun. A small gold nose stud. She wears a fitted Lululemon top with high-waisted "
        "maternity leggings. Calm reassured smile, free hand resting naturally on her belly. Clean "
        "modern Seattle apartment bathroom in soft background, white tile, soft light. 50mm lens, "
        "f/2.2, candid lifestyle, real and unstaged."},
    {"id":"8","name":"Raymond","prompt":
        "A photorealistic editorial portrait of a 61-year-old Black American man, around 6'0\", with "
        "a build that was once more athletic and is now slightly softened. Closely cropped silver-white "
        "hair. Deep-set eyes with genuine warmth. Pronounced lines between his brows. A thin barely "
        "visible scar near his collarbone (cardiac catheterization entry point), partially visible "
        "above his collar — not hidden. He wears a neat navy plaid flannel shirt, tucked in. Quiet "
        "determined smile. Neat uncluttered Minneapolis bathroom in soft background, white tile, "
        "a family photo softly blurred in the background mirror reflection. 50mm lens, f/2.5, "
        "editorial photograph, real and grounded."},
    {"id":"9","name":"Sophia","prompt":
        "A photorealistic editorial portrait of a 45-year-old Latina woman, around 5'7\", slim and "
        "toned. Dark brown straight glossy hair worn down to her collarbones. Warm olive skin with "
        "light makeup. She wears a polished blazer with the sleeves pushed up — getting ready for work. "
        "Poised appearance-aware smile, careful around the mouth (she is mid-Invisalign treatment and "
        "conscious of her smile). Marble Chicago apartment bathroom in soft background: frameless "
        "mirror, uncluttered counter, warm vanity lighting. 50mm lens, f/2.5, editorial photograph, "
        "premium aesthetic, real."},
    {"id":"10","name":"Tyler","prompt":
        "A photorealistic editorial portrait of a 22-year-old white American man, around 5'10\", lean. "
        "Slightly underdeveloped jawline, the last traces of teen acne fading on his chin. Medium-length "
        "hair, slightly overgrown. A small tattoo barely visible on his forearm. He wears a faded "
        "band tee and joggers — morning routine, no effort made. Relaxed easy grin. Cramped lived-in "
        "Nashville college apartment bathroom in soft background: slightly cluttered counter, a string "
        "light in the doorframe, warm yellow-toned light. 50mm lens, f/2.2, candid lifestyle, real "
        "and unstyled."},
]


def persona_seed(name):
    return int(hashlib.md5(name.encode()).hexdigest()[:8], 16) % 1000000


def imagen_generate(prompt):
    body = {
        "instances": [{"prompt": prompt}],
        "parameters": {"sampleCount": 1, "aspectRatio": ASPECT},
    }
    r = requests.post(PREDICT_URL, json=body, timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"Imagen HTTP {r.status_code}: {r.text[:300]}")
    pred = r.json().get("predictions", [])
    if not pred:
        raise RuntimeError("Imagen response had no predictions")
    img_b64 = pred[0].get("bytesBase64Encoded")
    if not img_b64:
        raise RuntimeError("Imagen response missing bytesBase64Encoded")
    return base64.b64decode(img_b64)


def generate_all():
    print(f"=== T13 (Imagen edition) — modèle {MODEL}, aspect {ASPECT} ===\n")
    results = []
    for p in PERSONAS:
        name = p["name"]
        prompt = p["prompt"]
        seed = persona_seed(name)
        out_path = OUT_DIR / f"{name.lower()}.png"
        try:
            print(f"  → #{p['id']:>2}  {name:<8}…", end="", flush=True)
            t0 = time.time()
            png = imagen_generate(prompt)
            out_path.write_bytes(png)
            dt = time.time() - t0
            kb = len(png) / 1024
            print(f" ✓ {kb:7.0f} KB ({dt:5.1f}s)")
            results.append({**p, "seed": seed, "path": str(out_path.relative_to(ROOT)), "skipped": False})
        except Exception as e:
            print(f" ✗ {str(e)[:200]}")
            results.append({**p, "seed": seed, "error": str(e)})
        # Polite spacing to stay under any rate limit
        time.sleep(2)
    return results


def update_sheets(results):
    by_id = {r["id"]: r for r in results}
    rows = []
    for i in range(1, 11):
        r = by_id[str(i)]
        image_ref = r.get("path", "")
        prompt_seed = f"{r['prompt']}|seed={r['seed']}|model={MODEL}|aspect={ASPECT}|service=google-ai-studio"
        rows.append([image_ref, prompt_seed])

    WEBHOOK_PATH = "t13-sync-images-imagen"
    workflow = {
        "name": "T13-sync-images-imagen",
        "nodes": [
            {"id":"wh","name":"WH","type":"n8n-nodes-base.webhook","typeVersion":2,
             "position":[0,0],"webhookId":WEBHOOK_PATH,
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

    print(f"\n  Upload nouveaux image_ref_url + prompt_seed → Personas!G2:H11")
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
    if successes:
        ok = update_sheets(results)
        if not ok:
            print("  ✗ Sync Sheets a échoué")
            sys.exit(3)
        print("\n  ✓ Sheets Personas G2:H11 mises à jour")

    print("\n=== Récap fichiers ===")
    for f in sorted(OUT_DIR.glob("*.png")):
        size = f.stat().st_size
        print(f"  {f.relative_to(ROOT)}  ({size//1024} KB)")

    estimated_cost = 0.04 * len(successes)
    print(f"\n=== Coût estimé Imagen 4 Standard : ${estimated_cost:.2f}  ({len(successes)} × $0.04) ===")

if __name__ == "__main__":
    main()
