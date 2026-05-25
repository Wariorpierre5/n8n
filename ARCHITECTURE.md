# ARCHITECTURE — DailySmileCare

> Document de référence stable. Décrit le **système cible**, pas la liste des choses à faire (voir [TASKS.md](TASKS.md)).
> Lecture obligatoire avant toute exécution.

---

## 1. Vision & contraintes

**Mission.** Générer du revenu via l'affiliation Amazon par production automatisée de contenu (site + réseaux sociaux), avec une architecture **dupliquable sur une autre niche en moins d'une semaine**.

**Contraintes dures :**
- **0 nouvel abonnement payant.** On utilise uniquement ce qui est déjà actif (voir §2).
- **Aucune publication sans approbation humaine.** Système d'approbation batch quotidien obligatoire (§6).
- **Hardcodé brosses à dents pour la V1**, refactor de paramétrage à la première duplication (décision validée).
- **MVP social = YouTube Shorts + X uniquement.** Instagram et TikTok arrivent après App Review / Audit. Snapchat reste manuel.

---

## 2. Stack technique

| Outil | Usage | Statut |
|---|---|---|
| n8n cloud | Orchestration tous pipelines | Actif |
| Claude Sonnet 4.6 (API Anthropic) | Génération texte, articles, scripts, scoring | Pay-per-use |
| Google AI Studio — Gemini, Imagen 3, Veo 2, TTS | Visuels, vidéos, voix off | Pay-per-use (clé en mémoire) |
| Google Sheets | Dashboard / planning / tracking | Gratuit |
| Google Drive | Stockage médias générés | Gratuit |
| Gmail | Notifications + approbations batch | Gratuit |
| GitHub (`Wariorpierre5/n8n`, branche `master`) | Versionning site | Gratuit |
| Hostinger FTP | Hébergement `dailysmilecare.com` | Actif |
| YouTube Data API v3 | Publication YouTube Shorts | Gratuit |
| X API v2 | Publication X (500 posts/mois) | Gratuit |
| Meta Graph API | Publication Instagram — **post App Review** | Gratuit (review ~2-6 sem) |
| TikTok Content Posting API | Publication TikTok — **post Audit** | Gratuit (audit requis) |
| Snapchat | **Publication manuelle**, hors automatisation | — |

---

## 3. Périmètre d'exécution Sonnet 4.6 depuis VS Code

Sonnet exécute **directement** :
- Lecture/écriture de tous les fichiers du repo (HTML, JS, Python, MD, JSON)
- Commits + push GitHub (branche `master`)
- Lancement de `blog/deploy_hostinger.py` pour déploiement FTP
- Appels REST à l'**API n8n** (clé en mémoire) — création, modification, activation de workflows
- Appels HTTP aux APIs Gemini, YouTube, X, Anthropic via scripts Python/Node
- Lecture/écriture Google Sheets via MCP Drive ou via service account
- Envoi d'emails Gmail via MCP Gmail ou SMTP service account

Sonnet **ne fait pas** :
- Création des comptes developer Meta / TikTok / Snap (manuel, exige Pierre)
- App Review Meta / Audit TikTok (manuel, géré par Pierre)
- Validation des contenus avant publication (humain via emails d'approbation)
- Achat d'abonnements (interdit par contrainte)

---

## 4. Système personas — Architecture éditoriale centrale

**Règle.** 1 persona = 1 voix unique = 1 brosse attitrée = 1 audience régionale US ciblée.

| Persona | Brosse | Région US | Accent ton |
|---|---|---|---|
| Ashley | Aquasonic Black Series | Georgia | Southern mild |
| Tyler | Philips Sonicare 4100 | Ohio | General American |
| Priya | Oral-B Pro 1000 | New York | NYC neutral |
| Dorothy | Philips Sonicare 4100 | Iowa | Midwestern |
| Linda | Philips Sonicare 5300 | California | California neutral |
| Jordan | Philips Sonicare 7300 | Seattle | PNW neutral |
| Ethan | Ranvoo | Texas | Texas mild |
| Sophia | Oral-B iO Series 9 | Boston | New England |
| Raymond | Philips Sonicare 6500 | Floride | Florida neutral |
| Marcus | Philips Sonicare 9900 | LA | SoCal |

Voir [personas/](personas/) pour les fiches détaillées (10 fichiers `.md`).

### 4.1 Cohérence visuelle persona (sans HeyGen)

**Stratégie validée :** voix off + B-roll, **pas** de talking head.

1. **Reference image figée par persona** : 1 portrait Imagen 3 généré une fois, prompt verrouillé, seed mémorisée, stockée dans `personas/images/<persona>.png` et indexée dans Sheets `Personas`.
2. **Visuels secondaires** : Imagen 3 avec reference image en input + prompt scene-specific → cohérence du visage entre productions.
3. **Voix off** : Google TTS avec voice ID figée par persona (variante accent régional US), à stocker dans `personas/voices.json`.
4. **Vidéo** : Veo 2 produit le B-roll (objets, ambiance salle de bain, mains, brosse en action). La voix off est l'élément narratif. Aucun lip-sync requis.

---

## 5. Pipeline cible

```
SCHEDULER n8n
│
├── PIPELINE ARTICLE (Cron quotidien — 1 persona/jour × 10 = 10 articles/mois)
│   1. Analyse produit — Gemini (reviews Amazon + concurrence)
│   2. Alignement persona — Claude Sonnet (voix + accent régional)
│   3. Rédaction article — Claude Sonnet
│   4. SEO longue traîne US — Claude Sonnet (H1/H2, alt, méta)
│   5. Image hero — Imagen 3 (avec reference image persona)
│   6. QA Agent — Claude Sonnet (lisibilité + structure + densité mots-clés)
│   7. NOTIFICATION → entrée dans email batch quotidien
│   8. [Si approuvé] GitHub commit → FTP deploy → Hostinger live
│   9. Log → Sheets `Content_Calendar` + `Cost_Tracker`
│
├── PIPELINE VIDÉO QUIZ (one-shot evergreen, refresh trimestriel)
│   1. Script — Claude (hook / problème / solution / CTA)
│   2. Voix off — Google TTS (voix neutre US)
│   3. Vidéo — Veo 2 en 3 formats : 9:16 / 1:1 / 16:9
│   4. NOTIFICATION → email batch
│   5. [Si approuvé] Upload Drive + publication APIs natives
│
└── PIPELINE SOCIAL (Cron quotidien 10h00 ET — rotation 10 personas)
    1. Lecture planning — Sheets `Content_Calendar`
    2. Génération contenu — Claude Sonnet (voix + accent persona)
    3. Déclinaisons 5 formats (texte X / Shorts 9:16 / Reel IG / TikTok / Snap)
    4. Visuels — Imagen 3 + Veo 2 (avec reference image persona)
    5. NOTIFICATION → entrée dans email batch quotidien
    6. [Si approuvé]
       ├── YouTube Data API → Shorts (actif MVP)
       ├── X API v2 → X (actif MVP)
       ├── Meta Graph API → Instagram (en attente App Review)
       ├── TikTok Content Posting API → TikTok (en attente Audit)
       └── Snapchat : contenu stocké Drive pour publication manuelle
    7. Log → Sheets `Social_Performance`
```

---

## 6. Système d'approbation batch

**Décision :** 1 seul email récap par jour à 09h00 ET, contenant tous les contenus prévus pour les 24h suivantes.

### Format de l'email récap

```
Objet : [DAILY APPROVAL] 7 contenus prévus pour 2026-05-21

────────────────────────────
CARTE 1 — Ashley × Instagram Reel
  Aperçu : [thumbnail + 30 mots]
  💰 Coût généré : $0.04
  📈 Probabilité perf : 74%
  💵 Revenu estimé : $12-$28
  [✅ Approve]  [❌ Reject]  [✏️ Edit]
────────────────────────────
CARTE 2 — Marcus × YouTube Shorts
  ...
────────────────────────────

[✅ APPROVE ALL]   [❌ REJECT ALL]
```

### Mécanique technique

- 3 liens HTTPS uniques par carte, pointant vers 3 webhooks n8n distincts
- Chaque lien embarque un **token HMAC signé** (clé secrète stockée en variable n8n) lié au `content_id`, avec **TTL de 48h**
- Le webhook n8n :
  1. vérifie la signature HMAC
  2. vérifie que le token n'a pas déjà été consommé (Sheets `Approvals`)
  3. exécute l'action (publier / archiver / renvoyer en édition)
  4. répond une page HTML de confirmation
- Boutons globaux "Approve all" / "Reject all" : appellent un endpoint batch avec liste de tokens

### Auto-approbation conditionnelle

Hors scope V1 (validé : (a) batch uniquement). Réactivable plus tard via flag dans `Cost_Tracker`.

---

## 7. Modèle de données Google Sheets

Un seul classeur `DailySmileCare_Dashboard` (à créer), onglets :

| Onglet | Colonnes principales |
|---|---|
| `Personas` | id, name, brand_focus, region, accent, voice_id, image_ref_url, prompt_seed |
| `Products` | id, brand, model, asin, amazon_short_url, amazon_full_url, commission_rate, avg_price, target_persona_ids |
| `Themes` | id, theme_title, persona_ids[], related_product_ids[], status |
| `Content_Calendar` | content_id, date, persona_id, platform, type, status (draft/approved/published/rejected), permalink |
| `Approvals` | content_id, token_hash, action, timestamp, ip, user_agent |
| `Social_Performance` | content_id, platform, views, likes, saves, comments, clicks_amazon, conversions |
| `Cost_Tracker` | date, content_id, tokens_claude_in, tokens_claude_out, calls_gemini, cost_usd_total |
| `Affiliate_Tracking` | content_id, amazon_short_url, clicks, conversions, commission_usd, last_updated |
| `Weekly_Report` | week_iso, revenue_estimated, top_persona, top_article, top_platform, total_cost |

---

## 8. Calcul du revenu estimé

**Formule (par contenu, avant publication) :**
```
revenu_estimé_USD = trafic_projeté × CTR_affiliate × conv_amazon × commission_moyenne
```

**Constantes de bootstrap (décision validée — 60 premiers jours) :**

| Variable | Valeur par défaut | Source / hypothèse |
|---|---|---|
| `trafic_projeté` (Instagram post) | 80 vues | médiane comptes neufs niche health |
| `trafic_projeté` (YouTube Short) | 250 vues | médiane chaînes neuves |
| `trafic_projeté` (X post) | 30 vues | benchmark free tier |
| `trafic_projeté` (TikTok) | 200 vues | médiane comptes neufs |
| `CTR_affiliate` | 1.2 % | benchmark public health affiliate |
| `conv_amazon` | 2.5 % | médiane catégorie Health & Personal Care |
| `commission_moyenne` (brosses) | 3.0 % | observé dans `data/data_products.csv` |
| `panier_moyen` | $80 | médiane des 17 produits du CSV |

**Auto-calibrage :** à partir de 30 datapoints réels dans `Social_Performance`, chaque variable est recalculée comme moyenne mobile glissante sur les 90 derniers jours, par plateforme.

**Affichage dans l'email approbation :** intervalle `[revenu_estimé × 0.5, revenu_estimé × 2.3]` (bande de confiance large tant que < 30 datapoints).

---

## 9. Quiz personnalisé — spec produit

État source : [blog/quiz.html](blog/quiz.html) (10 questions, Top 3, ~470 lignes).

**Règles strictes V2 :**
- ✅ Nom du produit
- ✅ 1-2 phrases personnalisées **"why this matches your profile"**
- ✅ CTA Amazon distinct par produit du Top 3 (URL `amzn.to` individuelle)
- ✅ Message au-dessus du Top 3 : *"Based on your answers, here are the 3 best electric toothbrushes for you, [profil détecté]"*
- ✅ Badge "Best Match" sur le #1
- ❌ Aucun prix affiché
- ❌ Aucune notation / étoile
- ❌ Aucune comparaison de prix

**Scoring renforcé** : refactor à venir à l'exécution (décision : on verra à l'exécution).

**Tag Amazon Associates :** à confirmer par Pierre (provisoire `dailysmile-20`, format Amazon US standard). Les `amzn.to/...` existants dans le quiz embarquent déjà un tag — vérifier au moment de l'exécution. **Un seul tag global** pour tous les canaux en V1 (décision validée). Segmentation par canal post-MVP.

### Vidéo promotionnelle quiz (evergreen)

Voir §5 — Pipeline Vidéo Quiz. Structure 30-45s (hook / problème / solution / démo / CTA), 3 formats (9:16, 1:1, 16:9). Refresh trimestriel.

---

## 10. Sécurité

- **Tokens HMAC d'approbation** : clé secrète stockée dans variable d'environnement n8n `APPROVAL_HMAC_KEY` (rotation tous les 90 jours)
- **Clé API Gemini** : variable n8n `GEMINI_API_KEY` (déjà connue, voir mémoire)
- **Clé API n8n** : utilisée uniquement depuis VS Code via variable d'env locale, jamais commit
- **Tokens OAuth réseaux sociaux** : stockés dans n8n credentials, jamais en clair
- **FTP Hostinger** : credentials en variable d'env locale + lus par `deploy_hostinger.py`, jamais commit

---

## 11. Roadmap duplication niche

Quand la V1 brosses à dents tourne stable + génère du revenu :
1. Refactoriser le code en extrayant les constantes niche-spécifiques dans `config/niche.json`
2. Cloner le workflow n8n `DailySmileCare-v2` → `<NewNiche>-v1`
3. Remplacer le contenu de `data/data_products.csv` par les produits de la nouvelle niche
4. Régénérer 10 personas via Phase 1 du workflow (Claude Agent "PERSONAE")
5. Lancer les phases suivantes à l'identique

**Critères de sélection niche** (rappel) : commission Amazon > 4%, panier > $40, volume recherche US > 8k/mois, concurrence SEO modérée, produit physique, potentiel visuel élevé.

**Migration vers affiliations premium** (ShareASale, Impact, programmes directs) : 1 paramètre — le tag affiliation et l'URL de redirection — dans le générateur d'articles.
