#!/usr/bin/env python3
"""T9-TikTok setup — OAuth flow pour récupérer access + refresh token.

Usage:
    python3 scripts/t9_setup_tiktok.py [<CLIENT_KEY> <CLIENT_SECRET>]
    (par défaut lit depuis .env)

Le redirect URI est https://dailysmilecare.com/_oauth_callback.html
qui bounce automatiquement vers localhost:8765 via JS.
"""

import os
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

AUTH_URL  = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
USER_URL  = "https://open.tiktokapis.com/v2/user/info/"

REDIRECT_URI = "https://dailysmilecare.com/_oauth_callback.html"
SCOPES = "user.info.basic,video.upload,video.publish"

_captured = {"code": None, "error": None}


class OAuthHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        if "code" in qs:
            _captured["code"] = qs["code"][0]
            body = b"<h1>OK</h1><p>TikTok OAuth captured. You can return to terminal.</p>"
        elif "error" in qs:
            _captured["error"] = qs.get("error_description", [qs["error"][0]])[0]
            body = b"<h1>Error</h1><pre>" + _captured["error"].encode() + b"</pre>"
        else:
            body = b"<h1>?</h1>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)


def wait_for_code(timeout=300):
    server = HTTPServer(("127.0.0.1", 8765), OAuthHandler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    start = time.time()
    while time.time() - start < timeout:
        if _captured["code"] or _captured["error"]: break
        time.sleep(0.5)
    server.server_close()
    if _captured["error"]:
        raise RuntimeError(f"OAuth error: {_captured['error']}")
    if not _captured["code"]:
        raise TimeoutError("OAuth code not received within 5 minutes")
    return _captured["code"]


def exchange_code(client_key, client_secret, code):
    r = requests.post(TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"exchange_code {r.status_code}: {r.text[:400]}")
    data = r.json()
    if "error" in data and data.get("error"):
        raise RuntimeError(f"token exchange error: {data}")
    return data


def get_user_info(access_token):
    r = requests.get(USER_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        params={"fields": "open_id,union_id,avatar_url,display_name,username,follower_count,video_count"},
        timeout=15,
    )
    if r.status_code != 200:
        return None
    return r.json().get("data", {}).get("user", {})


def update_env(updates):
    import re as _re
    env_path = ROOT / ".env"
    content = env_path.read_text(encoding="utf-8")
    for key, val in updates.items():
        if _re.search(rf"^{key}=", content, _re.M):
            content = _re.sub(rf"^{key}=.*$", f"{key}={val}", content, flags=_re.M)
        else:
            content += f"\n{key}={val}\n"
    env_path.write_text(content, encoding="utf-8")


def main():
    if len(sys.argv) >= 3:
        client_key, client_secret = sys.argv[1], sys.argv[2]
    else:
        client_key    = os.environ["TIKTOK_CLIENT_KEY"]
        client_secret = os.environ["TIKTOK_CLIENT_SECRET"]

    print("=== T9-TikTok Setup ===\n")

    # 1. Build OAuth URL
    params = {
        "client_key": client_key,
        "scope": SCOPES,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "state": "dsc-tiktok-setup",
    }
    auth_url = f"{AUTH_URL}?{urlencode(params)}"

    print("1. Opening browser to TikTok OAuth consent…")
    print(f"   {auth_url[:120]}…\n")
    webbrowser.open(auth_url)
    print("   ⏳ Waiting for you to click 'Authorize' in the browser (timeout 5 min)…")
    code = wait_for_code(timeout=300)
    print(f"   ✓ Got authorization code (len={len(code)})\n")

    # 2. Exchange code → access + refresh token
    print("2. Exchanging code → access + refresh tokens…")
    tok = exchange_code(client_key, client_secret, code)
    access_token  = tok["access_token"]
    refresh_token = tok.get("refresh_token", "")
    open_id       = tok.get("open_id", "")
    expires_in    = tok.get("expires_in", 0)
    print(f"   ✓ Access token len={len(access_token)} expires in {expires_in // 3600}h")
    print(f"   ✓ Refresh token len={len(refresh_token)}")
    print(f"   ✓ Open ID = {open_id}\n")

    # 3. Get user info to confirm account
    print("3. Verifying user info…")
    info = get_user_info(access_token)
    if info:
        print(f"   ✓ Username : @{info.get('username', '?')}")
        print(f"     Display name : {info.get('display_name', '?')}")
        print(f"     Followers : {info.get('follower_count', '?')}, videos : {info.get('video_count', '?')}")
    else:
        print(f"   ⚠ Could not fetch user info — but tokens are valid")
    print()

    # 4. Save
    print("4. Saving to .env…")
    update_env({
        "TIKTOK_CLIENT_KEY":     client_key,
        "TIKTOK_CLIENT_SECRET":  client_secret,
        "TIKTOK_ACCESS_TOKEN":   access_token,
        "TIKTOK_REFRESH_TOKEN":  refresh_token,
        "TIKTOK_OPEN_ID":        open_id,
    })
    print("   ✓ .env updated\n")

    print("=== ✅ Setup complete ===")
    print(f"  Client Key        : {client_key}")
    print(f"  Open ID           : {open_id}")
    print(f"  Access token      : expires in {expires_in // 3600}h (~24h)")
    print(f"  Refresh token     : long-lived (~365 days)")
    print()
    print("Pour publier une vidéo : voir docs ou demande-moi de coder le test.")


if __name__ == "__main__":
    main()
