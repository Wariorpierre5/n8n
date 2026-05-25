#!/usr/bin/env python3
"""Deploy all site files to Hostinger via FTP.

Structure locale  →  Structure distante (public_html)
-----------------     ----------------------------------
blog/index.html       index.html
blog/quiz.html        quiz.html
blog/posts/*          posts/*
blog/images/*         images/*
"""

import ftplib
import os
import tempfile

FTP_HOST = "217.196.55.180"
FTP_USER = "u138293812.dailysmilecare.com"
FTP_PASS = "R4g$HM$6pCGzQza"
REMOTE_DIR = "/public_html"
LOCAL_DIR = "/Users/lorisdessis/Brosse a dent"

OLD_DOMAIN = "dentalpick.netlify.app"
NEW_DOMAIN = "dailysmilecare.com"

# Fichiers à la racine : (chemin local relatif, chemin distant relatif)
ROOT_FILES = [
    ("blog/index.html", "index.html"),
    ("blog/quiz.html", "quiz.html"),
]

# Dossiers dans blog/ : (chemin local relatif, chemin distant relatif)
BLOG_DIRS = [
    ("blog/posts", "posts"),
    ("blog/images", "images"),
]


def fix_links(content):
    return content.replace(OLD_DOMAIN, NEW_DOMAIN)


def get_all_files():
    files = []

    # Fichiers racine
    for local_rel, remote_rel in ROOT_FILES:
        local_path = os.path.join(LOCAL_DIR, local_rel)
        if os.path.exists(local_path):
            files.append((local_path, remote_rel))

    # Dossiers blog/
    for local_dir_rel, remote_dir_rel in BLOG_DIRS:
        dirpath = os.path.join(LOCAL_DIR, local_dir_rel)
        if not os.path.exists(dirpath):
            continue
        for root, dirs, filenames in os.walk(dirpath):
            # Skip directories starting with "_" (e.g., _archive)
            dirs[:] = [d for d in dirs if not d.startswith("_")]
            for filename in filenames:
                full = os.path.join(root, filename)
                rel_to_dir = os.path.relpath(full, dirpath)
                remote_rel = os.path.join(remote_dir_rel, rel_to_dir)
                files.append((full, remote_rel))

    return files


def ensure_remote_dir(ftp, remote_path):
    parts = remote_path.strip("/").split("/")
    current = ""
    for part in parts:
        current += "/" + part
        try:
            ftp.mkd(current)
        except ftplib.error_perm:
            pass


def upload_file(ftp, local_path, remote_path):
    remote_dir = os.path.dirname(remote_path)
    if remote_dir and remote_dir != "/":
        ensure_remote_dir(ftp, remote_dir)

    if local_path.endswith(".html"):
        with open(local_path, "r", encoding="utf-8") as f:
            content = fix_links(f.read())
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".html", mode="w", encoding="utf-8")
        tmp.write(content)
        tmp.close()
        with open(tmp.name, "rb") as f:
            ftp.storbinary(f"STOR {remote_path}", f)
        os.unlink(tmp.name)
    else:
        with open(local_path, "rb") as f:
            ftp.storbinary(f"STOR {remote_path}", f)


def main():
    print(f"Connexion à {FTP_HOST}...")
    ftp = ftplib.FTP()
    ftp.connect(FTP_HOST, 21, timeout=30)
    ftp.login(FTP_USER, FTP_PASS)
    ftp.set_pasv(True)
    print("Connecté.\n")

    files = get_all_files()
    print(f"{len(files)} fichiers à déployer :\n")

    for local_path, remote_rel in files:
        remote_path = REMOTE_DIR + "/" + remote_rel.replace("\\", "/")
        upload_file(ftp, local_path, remote_path)
        print(f"  ✓ {remote_rel}")

    ftp.quit()
    print(f"\nDéploiement terminé → https://{NEW_DOMAIN}")


if __name__ == "__main__":
    main()
