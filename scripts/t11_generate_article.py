#!/usr/bin/env python3
"""T11 — Génère un article persona via Claude + render HTML.

Usage:
    python3 scripts/t11_generate_article.py <persona_name>
    e.g. python3 scripts/t11_generate_article.py ashley

Output : blog/posts/<slug>.html (overwrite existing)

Coût estimé : ~$0.10 par article (Claude Sonnet 4.6, ~3k tokens out).
"""

import csv
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
ANTHROPIC_CRED = {"anthropicApi": {"id": "EefN2CGrd138d9jV", "name": "Anthropic account 2"}}

# Persona → assigned product (id from quiz catalog, slug for output file)
PERSONA_CONFIG = {
    "ashley":  {"product_id": 2,  "slug": "post-aquasonic-ashley"},
    "tyler":   {"product_id": 17, "slug": "post-philips-4100-tyler"},
    "priya":   {"product_id": 8,  "slug": "post-oralb-pro1000-priya"},
    "dorothy": {"product_id": 3,  "slug": "post-sonicare-4100-dorothy"},
    "linda":   {"product_id": 4,  "slug": "post-sonicare-5300-linda"},
    "jordan":  {"product_id": 5,  "slug": "post-sonicare-7300-jordan"},
    "ethan":   {"product_id": 16, "slug": "post-ranvoo-ethan"},
    "sophia":  {"product_id": 13, "slug": "post-oralb-io9-sophia"},
    "raymond": {"product_id": 12, "slug": "post-sonicare-6500-raymond"},
    "marcus":  {"product_id": 10, "slug": "post-sonicare-9900-marcus"},
}


def load_persona_md(name):
    """Read full persona .md content."""
    path = ROOT / "personas" / f"{name.lower()}.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def load_products():
    """Load products from CSV, return list of dicts indexed by enumeration (1-based, matching quiz)."""
    path = ROOT / "data" / "data_products.csv"
    rows = []
    seen_urls = set()
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            url = r.get("lien", "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            rows.append({
                "id": len(rows) + 1,
                "brand": r.get("Marque", "").strip(),
                "model": r.get("Modele", "").strip(),
                "price": r.get("Prix vente", "").strip().lstrip("$"),
                "amazon_url": url,
                "category": r.get("categorie", "").strip(),
            })
    return rows


# === Claude proxy via persistent n8n workflow ===

PROXY_PATH = "dsc-claude-proxy"

def ensure_claude_proxy():
    """Create/activate persistent n8n Claude proxy workflow. Returns workflow ID."""
    name = "DailySmileCare-Claude-Proxy"
    r = requests.get(f"{N8N}/api/v1/workflows", headers=H)
    for w in r.json().get("data", []):
        if w["name"] == name:
            if not w.get("active"):
                requests.post(f"{N8N}/api/v1/workflows/{w['id']}/activate", headers=H)
                time.sleep(2)
            return w["id"]
    wf = {
        "name": name,
        "nodes": [
            {"id":"wh","name":"Webhook","type":"n8n-nodes-base.webhook","typeVersion":2,
             "position":[0,0],"webhookId":PROXY_PATH,
             "parameters":{"path":PROXY_PATH,"httpMethod":"POST","responseMode":"responseNode"}},
            {"id":"c","name":"Call","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,
             "position":[240,0],"credentials":ANTHROPIC_CRED,
             "parameters":{
                "method":"POST",
                "url":"https://api.anthropic.com/v1/messages",
                "authentication":"predefinedCredentialType","nodeCredentialType":"anthropicApi",
                "sendHeaders":True,"specifyHeaders":"keypair",
                "headerParameters":{"parameters":[{"name":"anthropic-version","value":"2023-06-01"}]},
                "sendBody":True,"specifyBody":"json",
                "jsonBody":"={{ JSON.stringify($json.body) }}",
                "options":{"timeout":180000},
             }},
            {"id":"r","name":"R","type":"n8n-nodes-base.respondToWebhook","typeVersion":1,"position":[480,0],
             "parameters":{"respondWith":"json","responseBody":"={{ $json }}"}},
        ],
        "connections":{
            "Webhook":{"main":[[{"node":"Call","type":"main","index":0}]]},
            "Call":{"main":[[{"node":"R","type":"main","index":0}]]},
        },
        "settings":{"executionOrder":"v1"},
    }
    r = requests.post(f"{N8N}/api/v1/workflows", headers=H, json=wf)
    wf_id = r.json()["id"]
    requests.post(f"{N8N}/api/v1/workflows/{wf_id}/activate", headers=H)
    time.sleep(2)
    return wf_id


def call_claude(messages, system, model="claude-sonnet-4-6", max_tokens=6000, temperature=0.7):
    """Send a Claude API request via the n8n proxy. Returns parsed text + usage."""
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": messages,
    }
    r = requests.post(f"{N8N}/webhook/{PROXY_PATH}", json=body, timeout=240)
    if r.status_code != 200:
        raise RuntimeError(f"Claude proxy {r.status_code}: {r.text[:300]}")
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"Anthropic error: {data['error']}")
    text_block = next((c for c in data.get("content", []) if c.get("type") == "text"), None)
    if not text_block:
        raise RuntimeError(f"No text in Claude response: {json.dumps(data)[:300]}")
    return {
        "text": text_block["text"],
        "tokens_in": data.get("usage", {}).get("input_tokens", 0),
        "tokens_out": data.get("usage", {}).get("output_tokens", 0),
    }


# === Article generation ===

SYSTEM_PROMPT = """You are a senior affiliate-content writer for DailySmileCare, an Amazon-affiliate blog about electric toothbrushes targeting an American audience. Your articles are persona-targeted reviews that read as honest first-person recommendations rather than sales pitches. You write in American English. You output strict JSON only — no markdown fences, no preamble."""


def build_article_prompt(persona_name, persona_md, product, all_products):
    # Comparison products: pick 3 from the catalog (avoid the same product)
    comp = [p for p in all_products if p["id"] != product["id"]][:4]
    comp_str = "\n".join([f"- {p['brand']} {p['model']} (${p['price']}) — {p['amazon_url']}" for p in comp])

    user_prompt = f"""Generate a complete article in JSON for persona "{persona_name}", reviewing the {product['brand']} {product['model']} (${product['price']}).

PERSONA PROFILE (full markdown):
---
{persona_md[:3500]}
---

ASSIGNED PRODUCT:
- Brand: {product['brand']}
- Model: {product['model']}
- Price: ${product['price']}
- Amazon URL: {product['amazon_url']}

COMPETITORS FOR COMPARISON TABLE (pick 3 of these):
{comp_str}

TARGET STRUCTURE (matching the brand's existing article style):
- title: SEO-optimized, includes year 2026, persona-relevant angle, ~60-70 chars
- meta_description: ~150 chars, action-oriented
- intro: 1 paragraph opening with persona-specific hook (e.g. "Your dentist just flagged your kid's gums…")
- sections: array of 5 H2 sections, each with:
    - h2: section title
    - paragraphs: array of strings (2-4 per section)
    - h3_blocks: optional array of {{h3, paragraphs, bullets}} for sub-structure
    - bullets: optional top-level bullet list (used if no h3_blocks)
- comparison_table: array of 4 rows comparing the assigned product vs 3 competitors. Each row: [brand_model, price, key_feature_1, key_feature_2, verdict_short]
- testimonials: array of 3 short blockquotes in the persona's voice
- bottom_line_h2: title for the final section
- bottom_line: 2-3 paragraphs closing with strong CTA
- amazon_cta_text: button text for Amazon link, ~5-7 words

WRITING STYLE REQUIREMENTS:
- First-person voice of the persona where it makes sense ("As a {persona_name}, I…")
- Honest, conversational tone — never salesy
- Reference specific persona pain points + life context
- US English, action verbs, specific numbers
- Each section should be 150-300 words
- Total article target: 1500-2200 words

OUTPUT (strict JSON, no markdown fences):
{{
  "title": "...",
  "meta_description": "...",
  "intro": "...",
  "sections": [
    {{"h2": "...", "paragraphs": ["..."], "h3_blocks": [{{"h3": "...", "paragraphs": [...], "bullets": [...]}}], "bullets": [...]}}
  ],
  "comparison_table": {{
    "headers": ["Brush", "Price", "Feature A", "Feature B", "Verdict"],
    "rows": [["...", "$X", "...", "...", "..."]]
  }},
  "testimonials": ["...", "...", "..."],
  "bottom_line_h2": "...",
  "bottom_line": "...",
  "amazon_cta_text": "..."
}}"""
    return user_prompt


def parse_json_response(text):
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    return json.loads(cleaned)


# === HTML render ===

def render_html(article, product, persona_name, persona_image_url):
    """Build full HTML matching the existing article template."""
    title = article["title"]
    meta_desc = article["meta_description"]
    intro = article["intro"]
    amazon_cta = article["amazon_cta_text"]
    amazon_url = product["amazon_url"]

    sections_html = []
    for sec in article.get("sections", []):
        section_html = [f'<h2>{html_escape(sec["h2"])}</h2>']
        for p in sec.get("paragraphs", []):
            section_html.append(f'<p>{html_escape(p)}</p>')
        for h3b in sec.get("h3_blocks", []) or []:
            section_html.append(f'<h3>{html_escape(h3b["h3"])}</h3>')
            for p in h3b.get("paragraphs", []) or []:
                section_html.append(f'<p>{html_escape(p)}</p>')
            if h3b.get("bullets"):
                bullets = "".join(f'<li>{html_escape(b)}</li>' for b in h3b["bullets"])
                section_html.append(f'<ul>{bullets}</ul>')
        if sec.get("bullets") and not sec.get("h3_blocks"):
            bullets = "".join(f'<li>{html_escape(b)}</li>' for b in sec["bullets"])
            section_html.append(f'<ul>{bullets}</ul>')
        sections_html.append("\n".join(section_html))

    comp = article.get("comparison_table", {})
    headers = comp.get("headers", [])
    rows = comp.get("rows", [])
    comp_html = ""
    if headers and rows:
        comp_html = "<h2>How It Compares to the Competition</h2>\n<table>\n"
        comp_html += "<tr>" + "".join(f"<th>{html_escape(h)}</th>" for h in headers) + "</tr>\n"
        for row in rows:
            comp_html += "<tr>" + "".join(f"<td>{html_escape(str(c))}</td>" for c in row) + "</tr>\n"
        comp_html += "</table>"

    testimonials_html = ""
    for t in article.get("testimonials", []):
        testimonials_html += f'<blockquote><em>"{html_escape(t)}"</em></blockquote>\n'

    bottom_h2 = article.get("bottom_line_h2", "The Bottom Line")
    bottom = article.get("bottom_line", "")

    cta_block = f'''<div class="cta-box">
  <div style="font-size:1.15rem;font-weight:800;margin-bottom:6px;">{html_escape(amazon_cta)}</div>
  <div style="font-size:0.95rem;opacity:0.85;margin-bottom:14px;">{html_escape(product["brand"])} {html_escape(product["model"])} — ${html_escape(product["price"])}</div>
  <a href="{amazon_url}" target="_blank" rel="noopener">Get it on Amazon →</a>
</div>'''

    sections_joined = "\n\n<hr>\n\n".join(sections_html)
    nav_title = title[:60]
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html_escape(title)} — DailySmileCare</title>
  <meta name="description" content="{html_escape(meta_desc)}" />
  <style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f8f9fa; color: #212529; line-height: 1.7; }}
a {{ color: #2563eb; }}
.nav {{ background: #1a1a2e; padding: 14px 20px; }}
.nav a {{ color: white; font-weight: 700; font-size: 1rem; text-decoration: none; }}
.nav span {{ color: #aaa; margin: 0 8px; }}
.hero {{ background: linear-gradient(135deg, #1a1a2e 0%, #2563eb 100%); color: white; padding: 56px 20px 48px; text-align: center; }}
.hero h1 {{ font-size: 2rem; font-weight: 800; max-width: 760px; margin: 0 auto 12px; line-height: 1.3; }}
.hero p {{ font-size: 1.05rem; opacity: 0.85; max-width: 600px; margin: 0 auto; }}
.container {{ max-width: 820px; margin: 0 auto; padding: 40px 20px 60px; }}
.content h1 {{ font-size: 1.9rem; font-weight: 800; margin: 32px 0 16px; line-height: 1.3; color: #1a1a2e; }}
.content h2 {{ font-size: 1.4rem; font-weight: 700; margin: 36px 0 14px; color: #1a1a2e; border-left: 4px solid #2563eb; padding-left: 12px; }}
.content h3 {{ font-size: 1.15rem; font-weight: 700; margin: 28px 0 10px; color: #333; }}
.content p {{ margin-bottom: 16px; font-size: 1rem; color: #333; }}
.content ul {{ margin: 12px 0 20px 24px; }}
.content ul li {{ margin-bottom: 8px; font-size: 1rem; color: #333; }}
.content table {{ width: 100%; border-collapse: collapse; margin: 24px 0; font-size: 0.92rem; }}
.content table th {{ background: #1a1a2e; color: white; padding: 10px 14px; text-align: left; font-weight: 700; }}
.content table td {{ padding: 10px 14px; border-bottom: 1px solid #e9ecef; }}
.content table tr:nth-child(even) td {{ background: #f8f9fa; }}
.content hr {{ border: none; border-top: 2px solid #e9ecef; margin: 36px 0; }}
.content blockquote {{ border-left: 4px solid #2563eb; background: #eff6ff; padding: 16px 20px; margin: 20px 0; font-style: italic; color: #444; border-radius: 0 8px 8px 0; }}
.content a {{ color: #2563eb; font-weight: 600; }}
.content strong {{ color: #1a1a2e; }}
.cta-box {{ background: #1a1a2e; color: white; border-radius: 12px; padding: 28px 32px; margin: 40px 0; text-align: center; }}
.cta-box a {{ display: inline-block; background: #FF9900; color: #1a1a2e; padding: 14px 28px; border-radius: 8px; font-weight: 800; font-size: 1.05rem; text-decoration: none; margin-top: 8px; }}
.disclaimer {{ background: #fff8e1; border: 1px solid #ffe082; border-radius: 8px; padding: 14px 18px; margin: 32px 0 0; font-size: 0.83rem; color: #666; }}
footer {{ background: #1a1a2e; color: #aaa; text-align: center; padding: 28px 20px; font-size: 0.85rem; margin-top: 40px; }}
footer a {{ color: #ccc; }}
@media (max-width: 600px) {{ .hero h1 {{ font-size: 1.5rem; }} .content h1 {{ font-size: 1.4rem; }} }}
  </style>
</head>
<body>
<nav class="nav"><a href="../../index.html">🦷 DailySmileCare</a><span>/</span><span style="color:#ccc">{html_escape(nav_title)}…</span></nav>
<div class="hero"><h1>{html_escape(title)}</h1><p>{html_escape(meta_desc)}</p></div>
<div class="container">
  <div class="content">
<p>{html_escape(intro)}</p>

<hr>

{sections_joined}

<hr>

{comp_html}

<hr>

<h2>Real-life reactions</h2>

{testimonials_html}

<hr>

<h2>{html_escape(bottom_h2)}</h2>

<p>{html_escape(bottom)}</p>

{cta_block}

<p class="disclaimer">As an Amazon Associate, DailySmileCare earns from qualifying purchases. Prices and availability are subject to change without notice.</p>
  </div>
</div>
<footer>© 2026 DailySmileCare — <a href="../../index.html">Home</a> · <a href="../quiz.html">Find your brush</a></footer>
</body>
</html>'''


def html_escape(s):
    if s is None: return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# === Main ===

def generate_one(persona_name):
    persona_name_low = persona_name.lower()
    if persona_name_low not in PERSONA_CONFIG:
        raise ValueError(f"Unknown persona: {persona_name}. Available: {list(PERSONA_CONFIG)}")
    cfg = PERSONA_CONFIG[persona_name_low]
    print(f"\n=== Generating article for {persona_name.capitalize()} ===")

    persona_md = load_persona_md(persona_name_low)
    print(f"  Persona .md loaded: {len(persona_md)} chars")

    all_products = load_products()
    product = next((p for p in all_products if p["id"] == cfg["product_id"]), None)
    if not product:
        raise ValueError(f"Product id={cfg['product_id']} not found")
    print(f"  Product: {product['brand']} {product['model']} (${product['price']})")

    print(f"  Building Claude prompt…")
    user_prompt = build_article_prompt(persona_name, persona_md, product, all_products)
    print(f"  Calling Claude (proxy)…")
    t0 = time.time()
    resp = call_claude(
        messages=[{"role": "user", "content": user_prompt}],
        system=SYSTEM_PROMPT,
        max_tokens=8000,
    )
    print(f"  ✓ Claude returned in {time.time()-t0:.1f}s, tokens in={resp['tokens_in']} out={resp['tokens_out']}")
    cost = resp['tokens_in'] / 1_000_000 * 3 + resp['tokens_out'] / 1_000_000 * 15
    print(f"  Estimated cost: ${cost:.4f}")

    try:
        article = parse_json_response(resp["text"])
    except json.JSONDecodeError as e:
        print(f"  ✗ JSON parse error: {e}")
        debug_path = ROOT / "personas" / f"_debug_{persona_name_low}.txt"
        debug_path.write_text(resp["text"], encoding="utf-8")
        print(f"  Raw output saved to {debug_path.relative_to(ROOT)}")
        raise

    html = render_html(article, product, persona_name.capitalize(), None)
    out_path = ROOT / "blog" / "posts" / f"{cfg['slug']}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"  ✓ Saved: {out_path.relative_to(ROOT)}  ({len(html)//1024} KB, {len(article.get('sections', []))} sections)")
    return out_path


def main():
    if len(sys.argv) < 2:
        print("Usage: t11_generate_article.py <persona_name>")
        print(f"Personas: {', '.join(PERSONA_CONFIG)}")
        sys.exit(1)

    print("=== T11 — Setup Claude proxy ===")
    proxy_id = ensure_claude_proxy()
    print(f"  Proxy workflow id={proxy_id}")

    name = sys.argv[1]
    try:
        path = generate_one(name)
        print(f"\n✓ Article généré : {path.relative_to(ROOT)}")
        print(f"   Ouvre en local : open {path}")
    except Exception as e:
        print(f"\n✗ Échec : {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
