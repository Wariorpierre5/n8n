#!/usr/bin/env python3
"""T11b — Génère 1 image scène par article (Imagen 4 Standard, 16:9) et patch les
HTML existants pour l'insérer en haut, juste sous le hero gradient.

Coût : 11 × $0.04 = ~$0.44.
"""

import base64
import os
import re
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
MODEL = "imagen-4.0-generate-001"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:predict?key={GEMINI_KEY}"

OUT_DIR = ROOT / "blog" / "images" / "articles"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Mapping persona → (slug, prompt fitting the article angle + product + scene)
ARTICLES = [
    {
        "slug": "post-aquasonic-ashley",
        "alt":  "Ashley, busy Ohio mom, holding the Aquasonic Black Series in her family bathroom",
        "prompt": (
            "Editorial lifestyle photograph, 16:9 horizontal banner. A 34-year-old white American woman "
            "with medium-brown hair in a loose ponytail, faint laugh lines, no makeup, gentle natural smile, "
            "standing in a typical suburban Ohio family bathroom. She holds an Aquasonic Black Series electric "
            "toothbrush (matte black body, silver accent ring, white sonic head). 4 colorful kids' toothbrushes "
            "visible on the counter beside her. Warm morning natural light from a window, kid's drawing pinned "
            "on the mirror behind her. Heather-gray pullover. Real, unstaged, smartphone-quality grain. "
            "50mm photo, documentary feel."
        ),
    },
    {
        "slug": "post-philips-4100-tyler",
        "alt":  "Tyler, 22-year-old college student in his Nashville bathroom with a Sonicare 4100 Rose",
        "prompt": (
            "Editorial lifestyle photograph, 16:9 horizontal banner. A 22-year-old white American man, lean, "
            "medium overgrown hair, faint fading teen acne, faded band tee, leaning against the counter in a "
            "cramped lived-in Nashville college apartment bathroom. He holds the Philips Sonicare 4100 Rose "
            "(soft blush-pink body, teal LED, white brush head). Counter is cluttered with hair product, energy "
            "drink can, string lights in the doorframe. Warm yellow lighting, real and unstyled. 50mm photo, "
            "documentary candid feel."
        ),
    },
    {
        "slug": "post-oralb-pro1000-priya",
        "alt":  "Priya, 31-year-old pregnant Seattle woman, holding the Oral-B Pro 1000",
        "prompt": (
            "Editorial lifestyle photograph, 16:9 horizontal banner. A 31-year-old South Asian American woman, "
            "visibly pregnant around 22 weeks, in a clean modern Seattle apartment bathroom. Thick dark wavy "
            "hair in a casual low bun, warm medium-brown skin, small gold nose stud, fitted Lululemon top and "
            "maternity leggings. She holds the Oral-B Pro 1000 (white body, dark navy grip band, round white "
            "head with blue bristles, green LED), free hand resting on her belly. Soft morning light, white "
            "tile, calm and reassured mood. 50mm photo, candid lifestyle."
        ),
    },
    {
        "slug": "post-sonicare-4100-dorothy",
        "alt":  "Dorothy, 68-year-old retired nurse in her Phoenix bathroom with a Sonicare 4100 Rechargeable",
        "prompt": (
            "Editorial lifestyle photograph, 16:9 horizontal banner. A 68-year-old white American woman, "
            "petite, silver-white short hair neatly blow-dried, sun-spotted skin, bright blue eyes with deep "
            "smile lines, in a sunny Phoenix bathroom. She holds the Philips Sonicare 4100 Rechargeable "
            "(white minimalist body, teal accent stripe, white head). Soft floral blouse, careful arthritic grip "
            "visible on the brush. White tile, a single cactus on the windowsill, soft natural morning light. "
            "50mm photo, real and warm."
        ),
    },
    {
        "slug": "post-sonicare-5300-linda",
        "alt":  "Linda, 58-year-old Black woman managing diabetes, with the Sonicare ProtectiveClean 5300",
        "prompt": (
            "Editorial lifestyle photograph, 16:9 horizontal banner. A 58-year-old Black American woman, full "
            "build, natural hair in loose twists with silver strands, deep warm brown skin, reading glasses "
            "pushed up on her forehead, deep burgundy button-down shirt. In her Houston bathroom with beige tile, "
            "she holds the Philips Sonicare ProtectiveClean 5300 (clean white with sky-blue accent panel, teal "
            "LED, white head with pale blue ring). Steady confident grip, calm resolute smile. Soft natural "
            "light, 50mm photo, grounded and real."
        ),
    },
    {
        "slug": "post-sonicare-7300-jordan",
        "alt":  "Jordan, 26-year-old Austin athlete, Sonicare 7300, fitness aesthetic",
        "prompt": (
            "Editorial lifestyle photograph, 16:9 horizontal banner. A 26-year-old biracial Black-white "
            "American man, lean and visibly athletic, post-workout flush, fitted sage-green merino t-shirt, "
            "Oura Ring visible on right index finger. In a clean minimal Austin apartment bathroom with white "
            "surfaces. He holds the Philips Sonicare 7300 (dark navy body with rubber grip, LED display, "
            "white head with teal ring). Natural medium hair slightly compressed one side (just woke up). "
            "Soft natural light, 50mm photo, candid lifestyle."
        ),
    },
    {
        "slug": "post-ranvoo-ethan",
        "alt":  "Ethan, 38-year-old eco-conscious Portland dad, RANVOO AirJet X5",
        "prompt": (
            "Editorial lifestyle photograph, 16:9 horizontal banner. A 38-year-old white American man, lean, "
            "dark brown hair with early gray temples, short maintained beard with gray threading, crow's feet, "
            "moss-green Patagonia fleece. In a clean minimalist Portland bathroom with white surfaces, a small "
            "potted plant on the windowsill, no clutter. He holds the RANVOO AirJet X5 (sleek matte-white "
            "cylindrical body, thin black accent band, white brush head). Light relaxed one-handed grip, "
            "relaxed natural smile. Soft natural light, 50mm photo, intentional and real."
        ),
    },
    {
        "slug": "post-oralb-io9-sophia",
        "alt":  "Sophia, 45-year-old Latina Invisalign patient, Oral-B iO 9 in a marble Chicago bathroom",
        "prompt": (
            "Editorial lifestyle photograph, 16:9 horizontal banner. A 45-year-old Latina woman, slim and toned, "
            "dark brown straight glossy hair to collarbones, warm olive skin with light makeup, polished blazer "
            "with sleeves pushed up. In her marble Chicago apartment bathroom, frameless mirror, warm vanity "
            "lighting. She holds the Oral-B iO 9 (premium pearl-white body, chrome accent, small LED display, "
            "round white head with dense micro-bristles, green pressure LED). Poised appearance-aware smile, "
            "careful around the mouth (Invisalign aware). 50mm editorial photograph, premium aesthetic."
        ),
    },
    {
        "slug": "post-sonicare-6500-raymond",
        "alt":  "Raymond, 61-year-old heart-attack survivor, Sonicare 6500 ProtectiveClean in his Minneapolis bathroom",
        "prompt": (
            "Editorial lifestyle photograph, 16:9 horizontal banner. A 61-year-old Black American man, build "
            "once athletic now slightly softened, closely cropped silver-white hair, deep-set warm eyes, "
            "pronounced lines between brows, navy plaid flannel shirt tucked in. Faint scar near collarbone "
            "visible above the collar. In a neat Minneapolis bathroom with white tile, clear counter. He holds "
            "the Philips Sonicare ProtectiveClean 6500 (clean white with navy accent panel, teal 3-zone LED, "
            "white head with navy ring). Deliberate methodical grip, quiet determined smile. Soft natural light, "
            "50mm photo, grounded and real."
        ),
    },
    {
        "slug": "post-sonicare-9900-marcus",
        "alt":  "Marcus, polished Black executive in his Atlanta penthouse en-suite with the DiamondClean 9900",
        "prompt": (
            "Editorial lifestyle photograph, 16:9 horizontal banner. A polished Black American man in his early "
            "50s, closely cropped fade with salt-and-pepper temples, deep mahogany skin, clean-shaven structured "
            "jaw, white dress shirt with rolled sleeves. In his Atlanta penthouse en-suite bathroom: large-format "
            "marble tile, frameless mirror, warm recessed lighting, glass charging dock visible on counter. He "
            "holds the Philips Sonicare DiamondClean 9900 (pearl white soft-touch body, chrome accent band, "
            "white head, silver Sonicare logo). Composed confident smile, premium aesthetic. 50mm editorial photo."
        ),
    },
    {
        "slug": "best-electric-toothbrush-comparison-2026",
        "alt":  "Lineup of best electric toothbrushes 2026 on a marble counter",
        "prompt": (
            "Editorial product lifestyle photograph, 16:9 horizontal banner. A clean marble bathroom counter "
            "with 5 different premium electric toothbrushes lined up: one matte black Aquasonic with silver ring, "
            "one white Philips Sonicare with teal stripe, one Oral-B with chrome accent, one premium Sonicare "
            "DiamondClean with pearl finish, one matte-white RANVOO with thin black band. Soft morning natural "
            "light through a window. A glass of water and a hand towel visible in the soft background. "
            "Editorial product photography, 50mm, real and aspirational, not over-styled."
        ),
    },
]


def imagen_generate(prompt, aspect="16:9"):
    body = {
        "instances": [{"prompt": prompt}],
        "parameters": {"sampleCount": 1, "aspectRatio": aspect},
    }
    r = requests.post(URL, json=body, timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"Imagen {r.status_code}: {r.text[:300]}")
    pred = r.json().get("predictions", [])
    if not pred:
        raise RuntimeError(f"No predictions: {r.text[:300]}")
    return base64.b64decode(pred[0]["bytesBase64Encoded"])


def patch_article_html(article_slug, alt_text):
    """Insert <img class='hero-image'> after the hero div, add CSS for it."""
    html_path = ROOT / "blog" / "posts" / f"{article_slug}.html"
    html = html_path.read_text(encoding="utf-8")

    # Skip if already patched
    if 'class="hero-image"' in html:
        # Replace src to match new image
        html = re.sub(
            r'<img class="hero-image"[^>]*>',
            f'<img class="hero-image" src="/images/articles/{article_slug}.png" alt="{alt_text}" loading="eager">',
            html,
        )
    else:
        # Insert image tag right before the <div class="container">
        img_tag = f'<img class="hero-image" src="/images/articles/{article_slug}.png" alt="{alt_text}" loading="eager">'
        html = html.replace('<div class="container">', f'{img_tag}\n<div class="container">', 1)

        # Insert the CSS rule just before </style>
        css_rule = (
            ".hero-image { display: block; width: 100%; max-height: 480px; object-fit: cover; "
            "box-shadow: 0 2px 16px rgba(0,0,0,0.08); }\n"
            "@media (max-width: 600px) { .hero-image { max-height: 280px; } }\n"
        )
        html = html.replace("</style>", css_rule + "</style>", 1)

    html_path.write_text(html, encoding="utf-8")
    return html_path


def main():
    print(f"=== T11b — Génération {len(ARTICLES)} images articles via Imagen 4 ===\n")
    total_kb = 0
    failures = []
    for art in ARTICLES:
        slug = art["slug"]
        out_path = OUT_DIR / f"{slug}.png"
        if out_path.exists() and out_path.stat().st_size > 50_000:
            print(f"  ↻ {slug} : déjà présent ({out_path.stat().st_size // 1024} KB), skip")
            patch_article_html(slug, art["alt"])
            total_kb += out_path.stat().st_size / 1024
            continue
        try:
            print(f"  → {slug}…", end="", flush=True)
            t0 = time.time()
            png = imagen_generate(art["prompt"])
            out_path.write_bytes(png)
            dt = time.time() - t0
            kb = len(png) / 1024
            total_kb += kb
            print(f" ✓ {kb:6.0f} KB ({dt:4.1f}s)")
            patch_article_html(slug, art["alt"])
        except Exception as e:
            print(f" ✗ {e}")
            failures.append((slug, str(e)))

    print(f"\n  Total : {len(ARTICLES) - len(failures)}/{len(ARTICLES)} images générées, {total_kb // 1024:.1f} MB")
    if failures:
        print(f"  Échecs : {failures}")
        sys.exit(2)

    print(f"\n=== Coût estimé : ${0.04 * (len(ARTICLES) - len(failures)):.2f} ===")
    print(f"\n  Prochaine étape : ./scripts/deploy.sh \"Ajout images hero articles\"")


if __name__ == "__main__":
    main()
