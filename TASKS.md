# TASKS — DailySmileCare

> Liste d'exécution pour **Claude Sonnet 4.6 depuis VS Code**.
> Lire [ARCHITECTURE.md](ARCHITECTURE.md) avant de commencer.
> Tâches ordonnées **MVP-first**. Respecter les dépendances (`Depends`).
> Chaque tâche se termine par un **DoD** (Definition of Done) vérifiable.

**Conventions**
- `Files` = fichiers du repo à toucher
- `External` = systèmes externes touchés (n8n, GitHub, Hostinger, Sheets, …)
- ✅ = case à cocher quand DoD validé

---

## T0 — Setup MCPs et accès (préalable, 30 min)

**Phase** : Préreq • **Depends** : —
**External** : VS Code Claude Code config

**Action**
1. Vérifier que les MCPs suivants sont accessibles dans la session Sonnet en VS Code : Gmail, Google Drive, GitHub. Sinon les ajouter via `claude mcp add` ou éditer `~/.claude.json`.
2. Pour n8n : **pas de MCP requis**, utilisation directe de l'API REST via Python `requests` (clé API en mémoire).
3. Stocker les variables sensibles dans `.env` à la racine (déjà gitignore) :
   - `N8N_API_KEY` (depuis mémoire `reference_n8n.md`)
   - `N8N_BASE_URL`
   - `GEMINI_API_KEY` (depuis mémoire — déjà connue)
   - `ANTHROPIC_API_KEY`
   - `HOSTINGER_FTP_HOST`, `HOSTINGER_FTP_USER`, `HOSTINGER_FTP_PASS` (depuis mémoire `reference_hostinger_github.md`)
   - `APPROVAL_HMAC_KEY` (à générer : `openssl rand -hex 32`)
4. Créer `requirements.txt` à la racine avec : `requests`, `python-dotenv`, `gspread`, `google-auth`.

**DoD**
- ✅ `.env` créé et **non commit** (vérifier `.gitignore`)
- ✅ `python -c "import requests, dotenv, gspread"` passe
- ✅ Un appel test `GET /api/v1/workflows` sur l'API n8n retourne la liste des workflows

---

# 🟢 PHASE A — Quiz personnalisé + déploiement auto (priorité 1)

## T1 — Refactor scoring quiz (personnalisation renforcée)

**Phase** : A • **Depends** : T0
**Files** : [blog/quiz.html](blog/quiz.html)

**Action**
1. Lire le scoring actuel du quiz (~470 lignes).
2. Remplacer le scoring linéaire par un système **multi-critères pondéré** : besoin médical, mode de vie, budget (sans afficher), tech-affinity, voyage, âge.
3. Le scoring doit générer une **étiquette de profil** lisible (ex: `"Sensitive teeth + travel-focused"`) à injecter dans le message du Top 3.
4. Conserver les 10 questions actuelles (intégrer Q4 tech Oui/Non, Q7 âge, budget flexible déjà présents — voir commit `865c080`).

**DoD**
- ✅ Pour 5 profils types distincts (testés manuellement), le Top 3 retourné est différent
- ✅ L'étiquette de profil s'affiche au-dessus du Top 3

---

## T2 — Supprimer prix / notation / comparaison

**Phase** : A • **Depends** : T1
**Files** : [blog/quiz.html](blog/quiz.html)

**Action**
- Retirer tous les `<div class="pick-price">$XX.XX</div>`
- Retirer toute étoile / note numérique
- Retirer toute comparaison de prix entre produits

**DoD**
- ✅ `grep -n '\$' blog/quiz.html` ne retourne plus de prix produits (sauf documentation)
- ✅ Aucun mot `rating`, `stars`, `★` dans la page de résultats

---

## T3 — CTA Amazon Affiliate distinct par produit du Top 3

**Phase** : A • **Depends** : T2
**Files** : [blog/quiz.html](blog/quiz.html), [data/data_products.csv](data/data_products.csv)

**Action**
1. Vérifier que chaque produit dans le scoring a son `url: "https://amzn.to/..."` individuel (déjà présent — voir lignes ~106-122 de quiz.html).
2. Le bouton "Get it on Amazon →" doit pointer sur l'URL **du produit affiché**, pas une URL générique.
3. Ajouter un `data-product-id` pour tracking ultérieur.

**DoD**
- ✅ Cliquer sur le CTA du produit #1 ouvre l'URL Amazon du #1, idem #2 et #3
- ✅ Les trois URLs sont distinctes

---

## T4 — Message personnalisé "Best Match" + profil

**Phase** : A • **Depends** : T1, T2
**Files** : [blog/quiz.html](blog/quiz.html)

**Action**
1. Au-dessus du Top 3, afficher : *"Based on your answers, here are the 3 best electric toothbrushes for you, **[profil détecté]**"*
2. Sur le #1, ajouter un badge visible "🏆 Best Match" (CSS distinct, déjà à demi-existant via `.pick-top`)
3. Sous chaque produit, 1-2 phrases **"Why this matches you"** générées dynamiquement à partir des réponses (template + variables : sensibilité, budget bracket, usage).

**DoD**
- ✅ Le badge "Best Match" est visible et stylé sur le #1 uniquement
- ✅ Pour 3 profils testés, les 1-2 phrases "Why" diffèrent et sont cohérentes avec les réponses

---

## T5 — Déploiement automatique GitHub + FTP depuis VS Code

**Phase** : A • **Depends** : T4
**Files** : [blog/deploy_hostinger.py](blog/deploy_hostinger.py), nouveau `scripts/deploy.sh`
**External** : GitHub `Wariorpierre5/n8n`, FTP Hostinger

**Action**
1. Lire `blog/deploy_hostinger.py` (117 lignes) pour comprendre la mécanique FTP actuelle.
2. Créer un script `scripts/deploy.sh` qui enchaîne :
   ```
   git add blog/ && git commit -m "$1" && git push origin master
   python blog/deploy_hostinger.py
   ```
3. Documenter dans `README.md` (si absent) : `./scripts/deploy.sh "message de commit"`.

**DoD**
- ✅ `./scripts/deploy.sh "test quiz V2"` push sur GitHub **et** déploie sur Hostinger
- ✅ `https://dailysmilecare.com/blog/quiz.html` montre la V2 du quiz dans les 2 minutes

---

# 🟡 PHASE B — Pipeline social MVP (YouTube Shorts + X)

## T6 — Créer workflow n8n "DailySmileCare-v2"

**Phase** : B • **Depends** : T0
**External** : n8n cloud

**Action**
1. Via API n8n, créer un nouveau workflow vide nommé `DailySmileCare-v2`.
2. Récupérer son `workflowId` et le stocker dans `.env` (`N8N_WORKFLOW_ID_V2`).
3. Ne **pas** modifier l'ancien workflow "Essai Affiliate" (référence figée).

**DoD**
- ✅ Le workflow `DailySmileCare-v2` existe et est visible dans n8n UI
- ✅ `N8N_WORKFLOW_ID_V2` est dans `.env`

---

## T7 — Pipeline génération contenu social (5 déclinaisons)

**Phase** : B • **Depends** : T6
**External** : n8n, Claude API, Gemini API

**Action**
Ajouter au workflow `DailySmileCare-v2` les nœuds suivants en série :
1. **Schedule Trigger** — Cron daily 10h00 ET
2. **Sheets — Read Calendar** — lit la ligne du jour dans `Content_Calendar` (persona du jour)
3. **Claude — Generate Content** — produit 5 déclinaisons (voir [ARCHITECTURE.md §5](ARCHITECTURE.md)) :
   - X : texte ≤ 280 char + 1 image
   - YouTube Shorts : script 30s + voix off + 9:16
   - Instagram Reel : script 20s + 9:16 (stocké, pas publié)
   - TikTok : script 20s + 9:16 (stocké, pas publié)
   - Snapchat : 1 image + caption (stocké pour publication manuelle)
4. **Imagen 3** — image cohérente avec `image_ref_url` du persona (cf. T13)
5. **Veo 2** — vidéo 9:16 (pour YT Shorts, IG, TikTok) ; réutilisée tel quel
6. **Google TTS** — voix off avec voice ID persona
7. **Calc Metrics** — Function node : coût (tokens × prix), proba perf, revenu estimé (formule [ARCHITECTURE.md §8](ARCHITECTURE.md))
8. **Sheets — Append `Cost_Tracker`**
9. **Sheets — Update `Content_Calendar` status=`pending_approval`**

**DoD**
- ✅ Lancement manuel du workflow produit 5 fichiers/textes dans Drive `/DailySmileCare/staging/<date>/<persona>/`
- ✅ Une nouvelle ligne apparaît dans `Cost_Tracker`

---

## T8 — Système d'approbation batch (email + webhooks)

**Phase** : B • **Depends** : T7
**External** : n8n, Gmail, Sheets

**Action**
1. **Nouveau workflow n8n** `DailySmileCare-v2-Approval-Mailer` :
   - Schedule Trigger 09h00 ET
   - Lit toutes les lignes `pending_approval` de `Content_Calendar`
   - Pour chaque ligne : génère 3 tokens HMAC (approve / reject / edit) via Function node (clé `APPROVAL_HMAC_KEY` en variable n8n)
   - Construit un email HTML avec carte par contenu (preview, coût, proba, revenu) + boutons globaux Approve All / Reject All
   - Envoie via Gmail
2. **Webhooks d'approbation** (3 endpoints n8n) :
   - `POST /webhook/approve` — vérifie HMAC, marque `approved`, déclenche publication
   - `POST /webhook/reject` — vérifie HMAC, marque `rejected`, log dans `Approvals`
   - `POST /webhook/edit` — vérifie HMAC, marque `needs_edit`, envoie un email avec lien d'édition
3. Endpoint batch `POST /webhook/approve-all` accepte un array de tokens.
4. TTL token = 48h. Stockage des `token_hash` consommés dans `Approvals`.

**DoD**
- ✅ À 09h05, un email arrive dans la boîte du compte Gmail configuré
- ✅ Cliquer "Approve" sur une carte modifie le statut Sheets en `approved`
- ✅ Un token consommé ne peut pas être réutilisé (test : double-clic → erreur 409)
- ✅ Un token expiré (TTL > 48h) est rejeté

---

## T9 — Publication automatique YouTube Shorts + X

**Phase** : B • **Depends** : T8
**External** : n8n, YouTube Data API v3, X API v2

**Action**
1. Configurer credentials OAuth YouTube + X dans n8n (manuel — Pierre fournit les comptes developer).
2. Ajouter au workflow `DailySmileCare-v2` un trigger sur changement de statut Sheets `Content_Calendar` → `approved` :
   - Si platform = `youtube_shorts` → YouTube Data API upload
   - Si platform = `x` → X API v2 post
   - Si platform ∈ `{instagram, tiktok, snapchat}` → log "scheduled, awaiting platform activation"
3. Après publication : mettre à jour `Content_Calendar.permalink` + `status = published`.

**DoD**
- ✅ Un contenu approuvé pour YouTube Shorts apparaît sur la chaîne `Dailysmilecare` dans les 5 min
- ✅ Un contenu approuvé pour X apparaît sur le compte `Dailysmilecare` dans les 5 min
- ✅ Le `permalink` est bien enregistré dans Sheets

---

# 🟠 PHASE C — Articles 10 personas (régénération mensuelle)

## T10 — Archiver les 10 articles existants

**Phase** : C • **Depends** : T5
**Files** : [blog/posts/](blog/posts/) → nouveau `blog/posts/_archive/2026-05/`

**Action**
- Créer `blog/posts/_archive/2026-05/`
- Copier tous les fichiers HTML actuels de `blog/posts/` vers cet archive (préserver structure)
- Commit + push (mais **ne pas redéployer** pour préserver les URLs publiques actuelles jusqu'à la régénération)

**DoD**
- ✅ Les 10 articles existent en double : version live (inchangée) + version archive

---

## T11 — Pipeline article complet (n8n)

**Phase** : C • **Depends** : T6, T10
**External** : n8n, Gemini, Claude, Imagen 3, GitHub, Hostinger

**Action**
Ajouter au workflow `DailySmileCare-v2` un sous-pipeline Article :
1. **Schedule Trigger** — Cron daily 06h00 ET
2. **Sheets — Read Calendar** — récupère persona du jour (rotation 30j → ~3 articles/persona/mois)
3. **Gemini — Product Analysis** — reviews Amazon + concurrence
4. **Claude — Article Draft** — voix persona + accent régional (5000-8000 mots)
5. **Claude — SEO Pass** — H1/H2/H3, alt, méta-description, slug
6. **Imagen 3 — Hero** — avec reference image persona
7. **Claude — QA Agent** — lisibilité (Flesch ≥ 60), densité mots-clés (1-2%), structure HTML
8. **HTML Render** — template Jinja → fichier `blog/posts/<slug>.html`
9. **Entry Approval Queue** — passe par T8 batch mailer
10. **[After Approval] GitHub commit + FTP deploy + Sheets log**

**DoD**
- ✅ Lancement manuel produit un fichier HTML valide dans le repo
- ✅ Après approbation, l'article est live sur `dailysmilecare.com/blog/posts/<slug>.html`
- ✅ `Content_Calendar` log la production

---

## T12 — Régénération des 10 articles existants

**Phase** : C • **Depends** : T11
**External** : n8n, GitHub, Hostinger

**Action**
- Lancer manuellement T11 dix fois (une par persona)
- Approuver via email batch
- Les nouveaux articles **écrasent les URLs publiques** (perte SEO temporaire acceptée, décision validée)

**DoD**
- ✅ Les 10 URLs publiques renvoient les nouvelles versions
- ✅ Les versions archivées restent dans `blog/posts/_archive/2026-05/`

---

# 🔵 PHASE D — Cohérence visuelle persona + vidéos

## T13 — Générer 10 reference images persona figées

**Phase** : D • **Depends** : T0
**Files** : nouveau `personas/images/<persona>.png` × 10, mise à jour Sheets `Personas`
**External** : Imagen 3 (Google AI Studio)

**Action**
1. Pour chaque persona dans [personas/](personas/), rédiger un prompt Imagen 3 verrouillé (visage, âge, ambiance, style) qui matche la fiche `.md`.
2. Générer 4 variations par persona, sélectionner la meilleure manuellement.
3. Stocker dans `personas/images/<persona>.png`.
4. Indexer dans Sheets `Personas` : `image_ref_url` + `prompt_seed` (le prompt exact utilisé).

**DoD**
- ✅ 10 fichiers PNG existent dans `personas/images/`
- ✅ La colonne `image_ref_url` de `Personas` est remplie pour les 10

---

## T14 — Configurer voix TTS par persona

**Phase** : D • **Depends** : T0
**Files** : nouveau `personas/voices.json`
**External** : Google Cloud TTS

**Action**
1. Sélectionner pour chaque persona une voix Google TTS US qui colle à la région/accent.
2. Stocker `{persona_id: {voice_name, speaking_rate, pitch}}` dans `personas/voices.json`.
3. Référencer ce fichier dans le pipeline social (T7) et vidéo persona (T15).

**DoD**
- ✅ Un appel test TTS par persona produit un MP3 dans le bon ton

---

## T15 — Vidéo quiz evergreen (3 formats)

**Phase** : D • **Depends** : T6, T8
**External** : Veo 2, Google TTS, n8n

**Action**
1. Script 30-45s : hook / problème / solution / démo / CTA (cf. [ARCHITECTURE.md §5](ARCHITECTURE.md))
2. Génération Veo 2 en 3 formats : 9:16 (30s), 1:1 (30s), 16:9 (45s)
3. Voix off TTS neutre US
4. Passage par approbation batch (T8)
5. Publication YouTube Shorts + X (autres plateformes : stocké Drive)
6. Refresh trimestriel (Cron 1er janvier/avril/juillet/octobre)

**DoD**
- ✅ 3 fichiers MP4 dans Drive `/DailySmileCare/quiz_video/<date>/`
- ✅ Publication live sur YouTube + X après approbation

---

# ⚪ PHASE E — Dashboard tracking & analytics

## T16 — Initialiser le classeur Sheets `DailySmileCare_Dashboard`

**Phase** : E • **Depends** : T0
**External** : Google Sheets

**Action**
- Créer le classeur, ajouter les 9 onglets listés en [ARCHITECTURE.md §7](ARCHITECTURE.md) avec leurs colonnes.
- Pré-remplir `Personas` (depuis [personas/](personas/) + T13/T14) et `Products` (depuis [data/data_products.csv](data/data_products.csv)).
- Donner l'ID du classeur à n8n via variable `SHEETS_DASHBOARD_ID`.

**DoD**
- ✅ Le classeur existe, 9 onglets visibles, `Personas` et `Products` remplis

---

## T17 — Tracking affiliate (mise à jour quotidienne)

**Phase** : E • **Depends** : T16
**External** : n8n, Amazon Associates report (manuel ou scrape)

**Action**
1. Sous-workflow n8n `Affiliate_Sync` (Cron daily 23h ET) :
   - Lit le rapport Amazon Associates (méthode : Pierre fournit un export CSV quotidien dans Drive, OU scrape de la page rapport — à décider à l'exécution)
   - Met à jour `Affiliate_Tracking` : clicks, conversions, commission_usd

**DoD**
- ✅ La table `Affiliate_Tracking` se met à jour quotidiennement avec les chiffres Amazon

---

## T18 — Weekly Report Gmail

**Phase** : E • **Depends** : T16, T17
**External** : n8n, Gmail, Sheets

**Action**
- Workflow `Weekly_Report` — Cron lundi 08h ET
- Agrège `Cost_Tracker`, `Social_Performance`, `Affiliate_Tracking` sur les 7 derniers jours
- Email Gmail avec : revenu estimé, revenu réel, top persona, top article, top plateforme, coût total IA, ROI brut
- Append ligne dans `Weekly_Report`

**DoD**
- ✅ Le lundi suivant T18-deploy, un email récap arrive à 08h05

---

# 🟣 PHASE F — Extensions post-MVP

## T19 — Activation Instagram (après App Review Meta)

**Phase** : F • **Depends** : T9 + App Review approuvée
**Action** : Activer le nœud Meta Graph API dans T9, basculer le statut `instagram` de `awaiting platform activation` à `auto`.
**DoD** : ✅ 1 post test apparaît sur Instagram via API.

## T20 — Activation TikTok (après Content Posting Audit)

**Phase** : F • **Depends** : T9 + Audit approuvé
**Action** : Activer le nœud TikTok Content Posting API dans T9.
**DoD** : ✅ 1 post test apparaît sur TikTok en public.

## T21 — Snapchat manuel — process de publication

**Phase** : F • **Depends** : T7
**Action** : Documenter dans `README.md` le process manuel quotidien (5 min) : download depuis Drive → upload manuel via app Snapchat.
**DoD** : ✅ Process documenté et testé une fois.

---

# 🔴 PHASE G — Préparer la duplication niche (post-revenu validé)

## T22 — Extraire constantes niche dans `config/niche.json`

**Phase** : G • **Depends** : MVP validé + revenu mesurable
**Files** : nouveau `config/niche.json`, refactor tous fichiers hardcodés
**Action** : Identifier toutes les mentions hardcodées (brand names, mots-clés SEO, prompts persona, branding visuel) et les externaliser dans `config/niche.json`.
**DoD** : ✅ Changer 1 valeur dans `config/niche.json` permet un dry-run d'une autre niche sans casser le code.

---

# 📊 Vue d'ensemble — ordre d'exécution

```
T0 (setup)
 ├─→ A : T1 → T2 → T3 → T4 → T5   [Quiz V2 live]
 ├─→ B : T6 → T7 → T8 → T9         [Pipeline social MVP YT+X]
 ├─→ D : T13 + T14 (parallèles à C)
 ├─→ C : T10 → T11 → T12           [10 articles régénérés]
 ├─→ D : T15                       [Vidéo quiz]
 ├─→ E : T16 → T17 → T18           [Dashboard]
 ├─→ F : T19 / T20 / T21           [Quand reviews approuvées]
 └─→ G : T22                       [Quand prêt à dupliquer]
```

**Critère de succès MVP** : à la fin de Phase A + B, le quiz V2 est live, 1 contenu/jour est publié sur YouTube + X après approbation batch quotidienne, et `Cost_Tracker` enregistre chaque génération.
