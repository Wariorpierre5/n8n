#!/usr/bin/env python3
"""T9-Instagram setup — automatise tout sauf le clic 'Allow' dans le browser.

Usage:
    python3 scripts/t9_setup_instagram.py <META_APP_ID> <META_APP_SECRET>

Workflow:
  1. Build OAuth URL with scopes (instagram_basic, content_publish, pages_*).
  2. Open browser to that URL.
  3. Spin up local HTTP server on :8765 to capture ?code=... from redirect.
  4. Exchange code → short-lived user token.
  5. Extend → long-lived user token (~60 days).
  6. GET /me/accounts → list user's Pages.
  7. For each Page → GET ?fields=instagram_business_account.
  8. Save everything in .env + persist credential.
  9. Print summary.

Prerequisites (user-side):
  - IG account converted to Business
  - Facebook Page created + linked to IG
  - Meta Developer App created with Instagram Graph API product added
  - In App Settings → Facebook Login → Valid OAuth Redirect URIs : add
      http://localhost:8765/callback
"""

import json
import os
import re
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

GRAPH_VERSION = "v23.0"
GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"

REDIRECT_URI = "https://dailysmilecare.com/_oauth_callback.html"
# Local server still listens on 8765 — the dailysmilecare.com page bounces the code there via JS.
SCOPES = [
    "instagram_basic",
    "instagram_content_publish",
    "pages_show_list",
    "pages_read_engagement",
    "business_management",
]

_captured_code = {"code": None, "error": None}


class OAuthHandler(BaseHTTPRequestHandler):
    """Catches the redirect from Meta with ?code=... or ?error=..."""

    def log_message(self, fmt, *args):
        pass  # silence default logging

    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        if "code" in qs:
            _captured_code["code"] = qs["code"][0]
            body = b"""<!doctype html><meta charset=utf-8>
<title>OK</title>
<style>body{font-family:-apple-system,sans-serif;background:#f0f4ff;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.card{background:#fff;padding:40px 48px;border-radius:16px;box-shadow:0 4px 32px rgba(0,0,0,0.08);text-align:center;max-width:480px}
.ok{width:80px;height:80px;border-radius:50%;background:#16a34a;color:#fff;font-size:40px;display:flex;align-items:center;justify-content:center;margin:0 auto 20px;font-weight:800}
h1{font-size:1.4rem;margin:0 0 8px;color:#1a1a2e}
p{color:#666;font-size:0.95rem;margin:0}</style>
<div class=card><div class=ok>&#10003;</div><h1>OAuth OK</h1><p>Tu peux revenir au terminal, le script continue.</p></div>"""
        elif "error" in qs:
            _captured_code["error"] = qs.get("error_description", [qs["error"][0]])[0]
            body = (b"<h1>Error</h1><pre>" + _captured_code["error"].encode() + b"</pre>")
        else:
            body = b"<h1>?</h1>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)


def wait_for_code(timeout=300):
    server = HTTPServer(("127.0.0.1", 8765), OAuthHandler)
    t = threading.Thread(target=server.handle_request, daemon=True)
    t.start()
    start = time.time()
    while time.time() - start < timeout:
        if _captured_code["code"] or _captured_code["error"]:
            break
        time.sleep(0.5)
    server.server_close()
    if _captured_code["error"]:
        raise RuntimeError(f"OAuth error: {_captured_code['error']}")
    if not _captured_code["code"]:
        raise TimeoutError("OAuth code not received within 5 minutes")
    return _captured_code["code"]


def exchange_code(app_id, app_secret, code):
    r = requests.get(f"{GRAPH}/oauth/access_token", params={
        "client_id": app_id,
        "client_secret": app_secret,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"exchange_code {r.status_code}: {r.text[:300]}")
    return r.json()["access_token"]


def extend_token(app_id, app_secret, short_token):
    r = requests.get(f"{GRAPH}/oauth/access_token", params={
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_token,
    }, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"extend_token {r.status_code}: {r.text[:300]}")
    data = r.json()
    return data["access_token"], data.get("expires_in", 60 * 24 * 3600)


def list_pages(user_token):
    r = requests.get(f"{GRAPH}/me/accounts", params={"access_token": user_token}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"list_pages {r.status_code}: {r.text[:300]}")
    return r.json().get("data", [])


def get_ig_account(page_id, page_token):
    r = requests.get(f"{GRAPH}/{page_id}", params={
        "fields": "instagram_business_account,name",
        "access_token": page_token,
    }, timeout=30)
    if r.status_code != 200: return None
    return r.json()


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
    if len(sys.argv) < 3:
        print("Usage: python3 t9_setup_instagram.py <META_APP_ID> <META_APP_SECRET>")
        sys.exit(1)
    app_id = sys.argv[1]
    app_secret = sys.argv[2]

    print("=== T9-Instagram Setup ===\n")
    print("Prereq côté ton app Meta :")
    print(f"  → App Settings → Facebook Login → Valid OAuth Redirect URIs : {REDIRECT_URI}")
    print()

    # 1. Build OAuth URL
    auth_params = {
        "client_id": app_id,
        "redirect_uri": REDIRECT_URI,
        "scope": ",".join(SCOPES),
        "response_type": "code",
        "state": "dsc-setup",
    }
    auth_url = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth?{urlencode(auth_params)}"

    print("1. Opening browser to Meta OAuth consent…")
    print(f"   {auth_url[:120]}…\n")
    webbrowser.open(auth_url)
    print("   ⏳ Waiting for you to click 'Allow' in the browser (timeout 5 min)…")
    code = wait_for_code(timeout=300)
    print(f"   ✓ Got authorization code (len={len(code)})\n")

    # 2. Exchange code → short-lived token
    print("2. Exchanging code → short-lived token…")
    short_token = exchange_code(app_id, app_secret, code)
    print(f"   ✓ Short token len={len(short_token)}\n")

    # 3. Extend → long-lived
    print("3. Extending → long-lived token (~60 days)…")
    long_token, expires_in = extend_token(app_id, app_secret, short_token)
    print(f"   ✓ Long token len={len(long_token)}, expires in {expires_in // 3600}h\n")

    # 4. List Pages
    print("4. Listing Pages tied to this user…")
    pages = list_pages(long_token)
    if not pages:
        raise RuntimeError("No Facebook Pages found — link Instagram to a FB Page first")
    for p in pages:
        print(f"   • {p['name']} (id={p['id']})")
    page = pages[0]  # default: first Page; ask user to choose if multiple
    if len(pages) > 1:
        print(f"\n   ⚠ Multiple Pages found, using first: {page['name']}")
    page_id = page["id"]
    page_token = page["access_token"]

    # 5. Get IG Business Account
    print(f"\n5. Fetching Instagram Business Account on Page '{page['name']}'…")
    info = get_ig_account(page_id, page_token)
    ig_account = (info or {}).get("instagram_business_account")
    if not ig_account:
        print(f"   ✗ No Instagram Business linked to Page {page_id}")
        print(f"     Vérifie sur ig → Settings → Linked accounts → Facebook")
        sys.exit(2)
    ig_id = ig_account["id"]
    print(f"   ✓ IG Business Account id = {ig_id}\n")

    # 6. Save everything
    print("6. Saving to .env…")
    update_env({
        "META_APP_ID":          app_id,
        "META_APP_SECRET":      app_secret,
        "META_LONG_LIVED_TOKEN": long_token,
        "META_PAGE_ID":         page_id,
        "META_PAGE_TOKEN":      page_token,
        "IG_BUSINESS_ACCOUNT_ID": ig_id,
    })
    print("   ✓ .env updated\n")

    print("=== ✅ Setup complete ===\n")
    print(f"  App ID                : {app_id}")
    print(f"  Page                  : {page['name']} (id={page_id})")
    print(f"  Instagram Business ID : {ig_id}")
    print(f"  Long-lived token      : expires in ~{expires_in // 86400} days")
    print()
    print("Prochaine étape : test d'un post Instagram via Python ou n8n.")


if __name__ == "__main__":
    main()
