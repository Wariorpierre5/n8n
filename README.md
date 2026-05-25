# DailySmileCare

Site d'affiliation Amazon (brosses à dents électriques, marché US) — base d'un modèle dupliquable sur d'autres niches.
Architecture cible, contraintes et pipelines : [ARCHITECTURE.md](ARCHITECTURE.md).
Liste d'exécution Sonnet 4.6 depuis VS Code : [TASKS.md](TASKS.md).

---

## Déploiement

Le site est statique (HTML/CSS/JS), hébergé sur Hostinger, versionné sur GitHub (`Wariorpierre5/n8n`, branche `master`).

### Commande unique

```bash
./scripts/deploy.sh "message de commit"
```

Le script :
1. `git add blog/` — uniquement les fichiers déployés
2. `git commit -m "<message>"`
3. `git push origin master`
4. `python3 blog/deploy_hostinger.py` — upload FTP vers `public_html/`

Si rien n'a changé dans `blog/`, le commit est skippé et seul le deploy FTP s'exécute.

### Pré-requis

- Python 3 (stdlib `ftplib` suffit, pas de dépendance externe pour le deploy)
- Variables d'env du projet dans `.env` à la racine (gitignored)
- Accès réseau au FTP Hostinger (port 21, mode passif)

Le site est live sur https://dailysmilecare.com.

---

## Structure

```
blog/                       fichiers déployés sur Hostinger
  index.html                page d'accueil
  quiz.html                 quiz personnalisé Top 3
  posts/*.html              10 articles persona + 1 comparatif
  images/                   visuels du site
  deploy_hostinger.py       upload FTP des fichiers ci-dessus

personas/                   fiches Markdown des 10 personas (1 par fichier)
data/                       CSV produits + personas + comparatifs
scripts/                    scripts d'orchestration locale
  deploy.sh                 commit + push + deploy FTP
ARCHITECTURE.md             référence stable du système cible
TASKS.md                    backlog exécutable, ordonné MVP-first
.env                        variables sensibles (gitignored)
```

---

## Workflow de travail

1. Modifier les fichiers dans `blog/` (quiz, articles, index…)
2. Tester en local en ouvrant `blog/quiz.html` ou `blog/index.html` dans un navigateur
3. `./scripts/deploy.sh "ce que tu as changé"` — push + live en ~30 s

Pour l'automation complète (génération contenu, vidéos, publication sociale), voir [TASKS.md](TASKS.md) Phase B et au-delà.
