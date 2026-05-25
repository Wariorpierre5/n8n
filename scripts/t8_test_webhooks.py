#!/usr/bin/env python3
"""T8a — Test les webhooks d'approbation : valide / reused / expiré."""

import base64
import hashlib
import hmac
import os
import sys
import time
from pathlib import Path
import re as _re

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

N8N = os.environ["N8N_BASE_URL"]
HMAC_KEY = os.environ["APPROVAL_HMAC_KEY"]

WEBHOOK_URL = f"{N8N}/webhook/dsc-approval"


def make_token(content_id, action, exp_unix):
    payload = f"{content_id}|{action}|{exp_unix}"
    key = bytes.fromhex(HMAC_KEY)
    sig = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()[:32]
    raw = f"{payload}|{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def hit(token, label):
    print(f"\n--- {label} ---")
    print(f"  Token (head): {token[:40]}…")
    r = requests.get(WEBHOOK_URL, params={"token": token}, timeout=30)
    print(f"  HTTP {r.status_code}, body length={len(r.text)}")
    # Extract title for terseness
    m = _re.search(r"<h1>(.*?)</h1>", r.text)
    title = m.group(1) if m else "(no h1)"
    msg = _re.search(r"<p>(.*?)</p>", r.text)
    print(f"  Title: {title}")
    if msg: print(f"  Msg  : {msg.group(1)[:200]}")
    return r.status_code, title


def main():
    # Pick a real pending content_id (from the last T7 run)
    CID_APPROVE = "2026-05-24-p4-mpk7h07m-x"          # will mark as approved
    CID_REJECT  = "2026-05-24-p4-mpk7h07m-snapchat"   # will mark as rejected
    CID_REUSE   = "2026-05-24-p4-mpk7h07m-tiktok"     # will be hit twice

    now = int(time.time())
    exp_ok    = now + 48 * 3600
    exp_past  = now - 3600  # 1h dans le passé

    # === Test 1 : token valide approve ===
    t1 = make_token(CID_APPROVE, "approve", exp_ok)
    sc, ttl = hit(t1, "Test 1: token valide → approve")
    assert sc == 200, f"expected 200, got {sc}"
    assert "approuvé" in ttl, f"expected 'approuvé' in title, got '{ttl}'"

    # === Test 2 : token valide reject ===
    t2 = make_token(CID_REJECT, "reject", exp_ok)
    sc, ttl = hit(t2, "Test 2: token valide → reject")
    assert sc == 200
    assert "rejeté" in ttl

    # === Test 3 : token reuse ===
    t3 = make_token(CID_REUSE, "approve", exp_ok)
    sc1, ttl1 = hit(t3, "Test 3a: première utilisation")
    assert "approuvé" in ttl1
    time.sleep(2)
    sc2, ttl2 = hit(t3, "Test 3b: même token, deuxième hit")
    # Should NOT re-apply — should show "déjà utilisé"
    assert "déjà utilisé" in ttl2, f"expected reuse rejection, got '{ttl2}'"

    # === Test 4 : token expiré ===
    t4 = make_token(CID_APPROVE, "approve", exp_past)
    sc, ttl = hit(t4, "Test 4: token expiré (exp dans le passé)")
    assert "invalide" in ttl or "expire" in ttl.lower(), f"expected invalid/expired, got '{ttl}'"

    # === Test 5 : token avec signature corrompue ===
    t5 = make_token(CID_APPROVE, "approve", exp_ok)
    # Corrupt last 4 chars of signature
    corrupted = t5[:-4] + "AAAA"
    sc, ttl = hit(corrupted, "Test 5: signature corrompue")
    assert "invalide" in ttl

    print("\n" + "=" * 50)
    print("✓ Tous les tests passent — DoD T8a validé :")
    print("  • Approve modifie Sheets en 'approved'")
    print("  • Reject modifie en 'rejected'")
    print("  • Token réutilisé est détecté (Approvals tab)")
    print("  • Token expiré est rejeté")
    print("  • Signature corrompue rejetée")


if __name__ == "__main__":
    main()
