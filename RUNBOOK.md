# RUNBOOK — DailySmileCare

Doc de passation : comment opérer le pipeline au quotidien après le build initial.

> Pour la spec du système → [ARCHITECTURE.md](ARCHITECTURE.md).
> Pour l'historique des tâches → [TASKS.md](TASKS.md).

---

## 🎯 Vue d'ensemble

Le pipeline génère **5 contenus sociaux + 1 article persona/jour**, demande ton approbation par email, publie sur YouTube après ton OK, et tracke les revenus Amazon. Tout est automatisé via n8n cloud + Google Sheets + Gmail.

```
06h00 ET ─── (futur) génération article persona du jour
09h00 ET ─── ✉ Email approbation : 5 contenus prévus
            ↓ Tu cliques Approve/Reject/Edit dans Gmail
10h00 ET ─── (en place T7a) génération 5 textes sociaux du jour
            ↓ Webhook approve → status=approved → orchestrateur T9
            ↓ Veo → Drive → YouTube unlisted
23h00 ET ─── 🔁 Sync rapport Amazon (CSV → Affiliate_Tracking)

Lundi 08h ET ─ 📊 Email weekly récap
```

---

## 📍 Où se trouve quoi

| Service | URL / ID |
|---|---|
| Site live | https://dailysmilecare.com |
| GitHub repo | https://github.com/Wariorpierre5/n8n (branche `master`) |
| n8n cloud | https://n8n.srv1110969.hstgr.cloud |
| Sheets Dashboard | https://docs.google.com/spreadsheets/d/1OCfjGgVzflKfFjo2UpVHK5AeT4nDJXQeBtGU5Rw3UoM/ |
| Drive racine | `DailySmileCare/` dans ton Drive `affiliatetrentecinq@gmail.com` |
| YouTube channel | `@Dailysmilecare` |
| Gmail récap | `affiliatetrentecinq@gmail.com` |

**Credentials** : tous dans `.env` à la racine du projet (jamais commit). N8N stocke les OAuth des plateformes en sécurité dans son store interne.

---

## 🔄 Workflows n8n actifs

| Workflow | ID | Trigger | Quand ça tourne |
|---|---|---|---|
| `DailySmileCare-v2` | `0nhq9U9NKYbiGUH1` | Webhook `dsc-daily-content` | Manuel uniquement (T7 — génération contenu) |
| `DailySmileCare-v2-Approval-Mailer` | `Igdlp0ckWRvxqd9K` | Schedule + Webhook | **09h00 ET tous les jours** + webhook test |
| `DailySmileCare-v2-Approval-Webhooks` | `yEk6O2PMTNGGHohm` | Webhook `dsc-approval` | À chaque clic dans email |
| `DailySmileCare-v2-YouTube-Upload` | `ioUg7xUubnabNWGz` | Webhook `dsc-youtube-upload` | Appelé par T9 orchestrateur Python |
| `DailySmileCare-v2-Affiliate-Sync` | `OYbUy0G3D8bJfFRf` | Schedule + Webhook | **23h00 ET tous les jours** |
| `DailySmileCare-v2-Weekly-Report` | `gXLy8shscOrltnJm` | Schedule + Webhook | **Lundi 08h00 ET** |
| `DailySmileCare-Claude-Proxy` | persistent | Webhook | À chaque appel Claude depuis Python |

---

## 🧑‍💻 Opérations courantes

### Modifier le site (quiz, articles, index)
```bash
# Édite les fichiers dans blog/
./scripts/deploy.sh "ma modif"   # commit + push + FTP
```

### Générer un nouvel article persona
```bash
python3 scripts/t11_generate_article.py ashley   # ou n'importe quel persona
./scripts/deploy.sh "Régen Ashley"
```
Coût : ~$0.05 Claude.

### Régénérer les 10 articles
```bash
for p in ashley tyler priya dorothy linda jordan ethan sophia raymond marcus; do
  python3 scripts/t11_generate_article.py $p
done
./scripts/deploy.sh "Régen 10 articles"
```
Coût : ~$0.50 Claude.

### Trigger manuel : génération contenu social
```bash
curl -X POST https://n8n.srv1110969.hstgr.cloud/webhook/dailysmile-v2-daily
```
Crée 5 textes Drive + 5 lignes Cost_Tracker + 5 lignes Content_Calendar (status=pending_approval).
Coût : ~$0.008 Claude.

### Trigger manuel : mailer d'approbation
```bash
curl -X POST https://n8n.srv1110969.hstgr.cloud/webhook/dsc-mailer-run
```
Lit les rows `pending_approval` du jour → envoie email Gmail avec 3 tokens (approve/reject/edit) par row.

### Trigger manuel : publication YouTube Short
```bash
python3 scripts/t9_publish_youtube.py
```
Pour chaque row Content_Calendar `approved` + platform=`youtube_shorts` + permalink vide : génère Veo + upload Drive + upload YouTube + update Sheets.
Coût : ~$1.60 par vidéo (Veo 3.1 Lite 8s).

### Trigger manuel : vidéo quiz evergreen
```bash
python3 scripts/t15_quiz_video.py
# OU pour juste re-faire la voix-off sur le clip Veo existant :
python3 scripts/t15b_add_voiceover.py
```

### Trigger manuel : sync Amazon
```bash
curl -X POST https://n8n.srv1110969.hstgr.cloud/webhook/dsc-affiliate-sync
```
Lit le CSV le plus récent dans `DailySmileCare/amazon_reports/` Drive → append rows dans `Affiliate_Tracking`.

### Trigger manuel : weekly report
```bash
curl -X POST https://n8n.srv1110969.hstgr.cloud/webhook/dsc-weekly-report
```
Force l'email récap immédiat sans attendre lundi.

### Approuver / rejeter un contenu sans email
Si tu veux modifier directement le statut sans cliquer sur Gmail :
1. Ouvre `Content_Calendar` dans Sheets
2. Change la colonne F `status` de `pending_approval` → `approved` / `rejected`
3. Si tu mets `approved` et plateforme = `youtube_shorts`, run `python3 scripts/t9_publish_youtube.py`

---

## 🪟 Onglets Google Sheets

| Onglet | Contenu |
|---|---|
| `Personas` | 10 personas avec brand, region, accent, voice_id, image_ref_url, prompt_seed |
| `Products` | 17 produits brosses à dents avec amazon_short_url + target_persona_ids |
| `Themes` | Vide pour l'instant — thèmes communs cross-personas (T12+) |
| `Content_Calendar` | Toutes les pieces de contenu générées (status + permalink) |
| `Approvals` | Log des tokens utilisés pour approve/reject (avec consumed_at, ip, ua) |
| `Social_Performance` | Vide — sera peuplé par metric sync (futur) |
| `Cost_Tracker` | Tous les appels Claude/Gemini avec coût USD |
| `Affiliate_Tracking` | Rows quotidiennes depuis Amazon CSV (clicks, conversions, commission) |
| `Weekly_Report` | 1 row par semaine ISO avec totaux |

---

## 📥 Mettre à jour le rapport Amazon (quotidien)

1. Va sur ton dashboard **Amazon Associates** → Reports → Earnings Report
2. Filtre sur les 24 dernières heures
3. Exporte en CSV
4. **Upload dans Drive** `DailySmileCare/amazon_reports/`
5. Le sync s'exécutera automatiquement à 23h00 ET (ou trigger manuel via webhook)

**Format CSV attendu** (flexible) :
```csv
date,amazon_short_url,clicks,conversions,commission_usd
2026-05-25,https://amzn.to/3PFV8Tm,42,3,3.60
```

Le parser reconnaît aussi : `asin`, `earnings`, `items_ordered`, `items_shipped` etc.

---

## 🚨 Troubleshooting

### Un workflow échoue
1. Ouvre n8n → Workflows → click sur le workflow → onglet **Executions**
2. Click sur la dernière exécution rouge → voit quel node a planté
3. Le message d'erreur est en bas

### Le mailer n'envoie pas
Vérifier que :
- Le credential `Gmail account` n'a pas expiré (Settings → Credentials)
- Le workflow `DailySmileCare-v2-Approval-Mailer` est **activé**
- Il y a des rows `pending_approval` dans `Content_Calendar` (sinon le workflow skip)

### Un email d'approbation reste "Lien invalide" quand je clique
Le token est expiré (TTL 48h) ou déjà utilisé. Approuve directement dans Sheets (colonne F → `approved`).

### Veo échoue avec "internal server issue"
Erreur transitoire Google. Re-trigger plus tard. Si ça persiste plusieurs heures, baisser à `veo-2.0-generate-001` (modèle plus stable).

### YouTube upload retourne `uploadId` sans permalink
C'est en fait OK — l'`uploadId` EST le video ID final. Vérifier sur YouTube Studio que la vidéo apparaît. (Bug dans la response n8n YouTube node, patché dans T9.)

### Anthropic API : "Bad request"
Probablement le model ID a changé. Vérifier dans `scripts/t11_generate_article.py` que le model est `claude-sonnet-4-6` ou la version la plus récente.

---

## 💰 Coûts

| Service | Plan | Coût mensuel estimé |
|---|---|---|
| n8n cloud (Hostinger) | Existant | — |
| Hostinger hébergement | Existant | — |
| Google AI Studio | **Pay-as-you-go** | ~$10-30 (selon usage) |
| Anthropic Claude | Pay-as-you-go | ~$5-15 (selon nombre d'articles) |
| Amazon Associates | Gratuit | — |
| YouTube + Gmail + Drive + Sheets | Gratuit | — |

**Drivers principaux** :
- Veo 3.1 Lite : $1.60 par vidéo (limiter à ~5-10/mois pour test, puis scaler avec ROI)
- Imagen 4 : $0.04 par image (rarement utilisé une fois personas générés)
- Claude Sonnet 4.6 : ~$0.05 par article, ~$0.008 par génération sociale
- Gemini TTS : Gratuit jusqu'à plusieurs centaines de calls/jour

---

## 🚀 Quand revenir

**Quand tu reviens dans X semaines/mois**, vérifie dans cet ordre :
1. **Gmail** : reçus les emails d'approbation quotidiens ?
2. **YouTube Studio** : combien de vidéos publiées ? Performance ?
3. **Affiliate_Tracking** : revenus quotidiens ?
4. **Weekly_Report email** : ROI ?

Si tout marche → laisse tourner.
Si problème → cf. Troubleshooting ci-dessus.

**Pour activer les plateformes deferred** :
- **Instagram** : finir Meta App Review (peut prendre 2-6 semaines)
- **TikTok** : finir Content Posting Audit
- **X (Twitter)** : créer X Developer account + obtenir API keys
- **Snapchat** : reste manuel (publication via app)

**Pour dupliquer sur autre niche** (T22, post-MVP) : extraire les constantes hardcodées (brosses à dents, persona names, Amazon URLs) dans `config/niche.json`, puis cloner les workflows.

---

## 📞 En cas de gros bug

1. **Revenir en arrière** : `git log` → identifier le bon commit → `git reset --hard <hash>` → `./scripts/deploy.sh "rollback"`
2. **Désactiver tous les schedules** : ouvre n8n → désactive `DailySmileCare-v2-*` un par un
3. **Articles archivés** : `blog/posts/_archive/2026-05/` contient la V1 originale, restaurable manuellement

---

Bon vol. 🦷
