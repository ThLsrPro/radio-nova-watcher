# Radio Nova Watcher

### Projet
Écoute Radio Nova live → transcription Groq whisper-large-v3 → détection regex locale → push ntfy.sh. GitHub Actions dimanche 18h Paris. Flux : `http://radionova.ice.infomaniak.ch/radionova-256.aac`

### Stack
- Python 3.11+, FFmpeg, Groq API, ntfy.sh, GitHub Actions
- Détection : regex/mots-clés locaux (pas d'API Claude/OpenAI/Anthropic)

### Fichiers clés
| Fichier | Rôle |
|---|---|
| `main.py` | boucle principale + health checks |
| `audio_capture.py` | FFmpeg + watchdog reconnexion |
| `transcriber.py` | Groq whisper-large-v3 |
| `detector.py` | regex 3 niveaux + contexte multi-chunks |
| `notifier.py` | ntfy.sh HTTP POST |
| `archiver.py` | sessions → GitHub Gist privé |
| `quota_monitor.py` | quotas Groq jour/mois |
| `healthcheck.py` | check autonome samedi |
| `config.py` | chargement .env |
| `docs/index.html` | dashboard GitHub Pages (HTML/CSS/JS inline) |
| `docs/generate_dashboard.py` | injecte URL Gist dans index.html |
| `scripts/optimize_context.py` | analyse CLAUDE.md + optimisation tokens |

### Variables d'environnement
- `GROQ_API_KEY` — clé Groq
- `NTFY_TOPIC` — nom topic ntfy
- `NTFY_SERVER` — URL serveur (défaut : https://ntfy.sh)
- `GIST_TOKEN` — token GitHub scope:gist uniquement
- `GIST_ENABLED` — true/false
- `RADIO_STREAM_URL` — URL flux AAC
- `CHUNK_DURATION_SECONDS` — durée chunk (défaut : 15)
- `DETECTION_COOLDOWN_MINUTES` — cooldown notifs (défaut : 30)

### Pièges connus
- **ntfy headers** : pas d'emoji dans `Title`/`Tags` (latin-1 → UnicodeEncodeError) — emoji uniquement dans body
- **Flux radio** : `GET stream=True` obligatoire, pas `HEAD` (streams AAC refusent HEAD → HTTP 400)
- **archiver** : logique fetch-merge-push — toujours recharger le Gist avant d'écrire (évite l'écrasement)
- **detector** : `add_transcript()` appelé APRÈS `analyze()` (chunk courant → buffer itération suivante)
- **CI** : `CI=true` → `quota_monitor` skip I/O fichier (filesystem éphémère Actions)
- **Gist** : `MAX_SESSIONS=10` — les 10 sessions les plus récentes conservées

### Comportements clés
- Watchdog : alerte ntfy si aucun chunk depuis 120s, backoff exponentiel 10/20/40/80/160s
- Detector : buffer `deque(3)`, mode alerte partielle si confidence 50-84 (seuil → 60 sur 3 chunks suivants)
- Archiver : sauvegarde périodique 2min, `start_session()` reprend session du jour si elle existe
- `healthcheck.py` : exit(0) OK / exit(1) erreur — workflow samedi 16h00 UTC

### Conventions
- Code commenté en français, type hints partout
- Secrets GitHub : `GIST_TOKEN` / `GIST_ENABLED` (pas de préfixe supplémentaire)
- Logs : `logs/app.log` + `logs/transcriptions.log`

### Commandes utiles
```
source venv/bin/activate
python main.py
python main.py --test-notification
python healthcheck.py
python scripts/optimize_context.py
python -c "from archiver import test_accumulation; test_accumulation()"
```

### Maintenance CLAUDE.md
- Mettre à jour après chaque nouvelle fonctionnalité (mode compact)
- Pas d'exemples de code dans ce fichier
- Garder < 150 lignes, supprimer sections obsolètes
- Relancer `scripts/optimize_context.py` avant commit important
