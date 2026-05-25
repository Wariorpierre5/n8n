#!/usr/bin/env bash
# DailySmileCare — déploiement local
# Usage : ./scripts/deploy.sh "message de commit"
#
# Enchaîne :
#   1. git add blog/   (uniquement les fichiers déployés)
#   2. git commit avec le message passé en argument
#   3. git push origin master
#   4. python blog/deploy_hostinger.py  (upload FTP vers Hostinger)
#
# Pré-requis :
#   - être à la racine du repo (sinon le cd ci-dessous compense)
#   - python3 + ftplib (stdlib) disponibles
#   - identifiants Hostinger lus depuis le script Python (voir T5+)

set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Erreur : message de commit requis."
  echo "Usage : $0 \"message de commit\""
  exit 1
fi

COMMIT_MSG="$1"

# Aller à la racine du repo, peu importe d'où on lance le script
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== 1/3 git commit + push ==="
git add blog/

if git diff --staged --quiet; then
  echo "  Aucune modification staged dans blog/ — skip commit, deploy direct."
else
  git commit -m "$COMMIT_MSG"
  git push origin master
fi

echo
echo "=== 2/3 deploy FTP Hostinger ==="
python3 blog/deploy_hostinger.py

echo
echo "=== 3/3 OK ==="
echo "  → https://dailysmilecare.com/blog/quiz.html"
