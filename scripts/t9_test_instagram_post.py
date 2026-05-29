#!/usr/bin/env python3
"""T9 — Test post Instagram.

Upload Ashley's portrait to Hostinger (public URL),
crée un media container IG, publie, retourne l'URL du post.
"""

import ftplib
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

IG_ID = os.environ["IG_BUSINESS_ACCOUNT_ID"]
PAGE_TOKEN = os.environ["META_PAGE_TOKEN"]
GRAPH = "https://graph.facebook.com/v23.0"

PORTRAIT_LOCAL = ROOT / "personas" / "images" / "ashley.png"
REMOTE_FILENAME = "instagram-test-ashley.png"

CAPTION = (
    "Hi Instagram 👋\n\n"
    "Looking for an electric toothbrush that actually matches YOUR needs "
    "(sensitive gums, travel, budget, Invisalign, family of 4...)? We built "
    "a 30-second quiz that picks 3 brushes from 17 actually worth considering — "
    "no rankings paid by brands.\n\n"
    "🦷 Take the quiz: dailysmilecare.com/quiz.html\n\n"
    "#electrictoothbrush #oralcare #dentalhealth #toothbrushreview #dailysmilecare"
)


def upload_to_hostinger(local_path: Path, remote_name: str) -> str:
    """FTP upload local file to /public_html/images/<remote_name>, returns public URL."""
    host = os.environ["HOSTINGER_FTP_HOST"]
    user = os.environ["HOSTINGER_FTP_USER"]
    pwd  = os.environ["HOSTINGER_FTP_PASS"]
    print(f"  Upload {local_path.name} → /public_html/images/{remote_name} via FTP…")
    ftp = ftplib.FTP()
    ftp.connect(host, 21, timeout=30)
    ftp.login(user, pwd)
    ftp.set_pasv(True)
    ftp.cwd("/public_html/images")
    with local_path.open("rb") as f:
        ftp.storbinary(f"STOR {remote_name}", f)
    ftp.quit()
    return f"https://dailysmilecare.com/images/{remote_name}"


def create_media_container(image_url: str, caption: str) -> str:
    """Step 1 of IG publish: create a media container, returns container id."""
    r = requests.post(
        f"{GRAPH}/{IG_ID}/media",
        data={
            "image_url": image_url,
            "caption": caption,
            "access_token": PAGE_TOKEN,
        },
        timeout=60,
    )
    print(f"  Create container HTTP {r.status_code}")
    if r.status_code != 200:
        print(f"  {r.text[:500]}")
        raise RuntimeError("create_media_container failed")
    return r.json()["id"]


def publish_container(creation_id: str) -> str:
    """Step 2: publish the container. Returns the published media id."""
    r = requests.post(
        f"{GRAPH}/{IG_ID}/media_publish",
        data={"creation_id": creation_id, "access_token": PAGE_TOKEN},
        timeout=60,
    )
    print(f"  Publish HTTP {r.status_code}")
    if r.status_code != 200:
        print(f"  {r.text[:500]}")
        raise RuntimeError("publish_container failed")
    return r.json()["id"]


def get_post_permalink(media_id: str) -> str:
    r = requests.get(
        f"{GRAPH}/{media_id}",
        params={"fields": "permalink,id,media_type", "access_token": PAGE_TOKEN},
        timeout=30,
    )
    if r.status_code != 200:
        return ""
    return r.json().get("permalink", "")


def main():
    print("=== T9 — Test Instagram post ===\n")
    if not PORTRAIT_LOCAL.exists():
        print(f"✗ Missing {PORTRAIT_LOCAL}"); sys.exit(1)

    print("1. Upload image to Hostinger…")
    image_url = upload_to_hostinger(PORTRAIT_LOCAL, REMOTE_FILENAME)
    print(f"   ✓ {image_url}\n")

    # Verify the upload is accessible
    print("2. Vérif image accessible publiquement…")
    r = requests.head(image_url, timeout=15)
    print(f"   HTTP {r.status_code}, content-type: {r.headers.get('content-type')}\n")
    if r.status_code != 200:
        print(f"   ✗ Image pas reachable, abort"); sys.exit(2)

    print("3. Create Instagram media container…")
    container_id = create_media_container(image_url, CAPTION)
    print(f"   ✓ container id = {container_id}\n")

    # IG sometimes needs a moment to process the image — wait a bit
    print("4. Attente 5s avant publish (IG image processing)…")
    time.sleep(5)
    print()

    print("5. Publier le container…")
    media_id = publish_container(container_id)
    print(f"   ✓ Published! media id = {media_id}\n")

    print("6. Fetch permalink…")
    permalink = get_post_permalink(media_id)
    if permalink:
        print(f"   ✓ Live : {permalink}\n")
    else:
        print(f"   (pas de permalink immédiatement, parfois IG met ~30s)\n")

    print("=== ✅ Test Instagram réussi ===")
    print(f"  Va vérifier sur https://instagram.com/dailysmilecare")
    print(f"  Si tu veux supprimer ce post test, fais-le depuis l'app IG (3 dots → Delete)")


if __name__ == "__main__":
    main()
