#!/usr/bin/env python3
"""Cleanup T11b — supprime les images articles + revert les HTML + revert template T11."""

import ftplib
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

POSTS_DIR = ROOT / "blog" / "posts"
IMG_DIR = ROOT / "blog" / "images" / "articles"

print("=== 1. Revert HTML articles : retire <img class='hero-image'> + CSS ===")
removed_html = 0
for html_path in POSTS_DIR.glob("*.html"):
    text = html_path.read_text(encoding="utf-8")
    new = text
    # Strip img tag
    new = re.sub(r'<img class="hero-image"[^>]*>\s*\n?', '', new)
    # Strip CSS rule (the 2 lines we injected)
    new = re.sub(
        r'\.hero-image \{[^}]+\}\s*\n@media \(max-width:\s*600px\) \{\s*\.hero-image \{[^}]+\}\s*\}\s*\n?',
        '',
        new,
    )
    if new != text:
        html_path.write_text(new, encoding="utf-8")
        removed_html += 1
        print(f"  ✓ {html_path.name}")
print(f"  Total: {removed_html} HTMLs cleaned")

print("\n=== 2. Delete local images blog/images/articles/ ===")
if IMG_DIR.exists():
    n = 0
    for f in IMG_DIR.iterdir():
        if f.is_file():
            f.unlink()
            n += 1
    print(f"  ✓ {n} fichiers supprimés")
    try:
        IMG_DIR.rmdir()
        print(f"  ✓ Dossier {IMG_DIR.relative_to(ROOT)} supprimé")
    except OSError as e:
        print(f"  Dossier conservé ({e})")
else:
    print("  Pas de dossier local")

print("\n=== 3. Delete remote /public_html/images/articles/ via FTP ===")
try:
    ftp = ftplib.FTP()
    ftp.connect(os.environ["HOSTINGER_FTP_HOST"], 21, timeout=30)
    ftp.login(os.environ["HOSTINGER_FTP_USER"], os.environ["HOSTINGER_FTP_PASS"])
    ftp.cwd("/public_html/images/articles")
    deleted = 0
    for name in ftp.nlst():
        if name in (".", ".."): continue
        try:
            ftp.delete(name); deleted += 1
        except Exception as e:
            print(f"    skip {name}: {e}")
    print(f"  ✓ {deleted} fichiers FTP supprimés")
    ftp.cwd("/public_html/images")
    try:
        ftp.rmd("articles")
        print(f"  ✓ Dossier articles/ supprimé")
    except Exception as e:
        print(f"  Dossier articles/ non supprimé : {e}")
    ftp.quit()
except Exception as e:
    print(f"  ✗ FTP error: {e}")

print("\n=== 4. Revert t11_generate_article.py template ===")
t11 = ROOT / "scripts" / "t11_generate_article.py"
text = t11.read_text(encoding="utf-8")
text = text.replace(
    '.hero-image {{ display: block; width: 100%; max-height: 480px; object-fit: cover; box-shadow: 0 2px 16px rgba(0,0,0,0.08); }}\n@media (max-width: 600px) {{ .hero-image {{ max-height: 280px; }} }}\n',
    '',
)
text = text.replace(
    '\n{(f\'<img class="hero-image" src="/images/articles/{slug}.png" alt="{html_escape(title)}" loading="eager">\') if slug else \'\'}',
    '',
)
text = text.replace(
    'render_html(article, product, persona_name.capitalize(), None, slug=cfg["slug"])',
    'render_html(article, product, persona_name.capitalize(), None)',
)
text = text.replace(
    'def render_html(article, product, persona_name, persona_image_url, slug=None):',
    'def render_html(article, product, persona_name, persona_image_url):',
)
t11.write_text(text, encoding="utf-8")
print("  ✓ Template T11 revert")

print("\n✓ Cleanup complet. Run deploy pour pousser les HTMLs nettoyés sur Hostinger.")
