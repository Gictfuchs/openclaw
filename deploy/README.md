# Fochs Deployment

## Schnellstart (Automatisch)

Das `deploy.sh`-Script automatisiert die komplette Installation:

```bash
# Auf dem Server als root:
git clone https://github.com/Gictfuchs/openclaw.git /tmp/openclaw-install
sudo bash /tmp/openclaw-install/deploy/deploy.sh
```

Das Script durchlaeuft alle Schritte: System-Pakete, UV, User, Repo, Dependencies,
Konfiguration, Systemd-Service und optional Nginx mit TLS.

---

## Bare-Metal (Manuell)

### 1. Voraussetzungen

```bash
# Python 3.12+, git, systemd
sudo apt update && sudo apt install -y python3.12 python3.12-venv git curl

# UV (schneller Package-Manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Installation

```bash
# User erstellen
sudo useradd -r -m -d /opt/fochs -s /bin/bash fochs
sudo su - fochs

# Repository klonen
git clone https://github.com/Gictfuchs/openclaw.git /opt/fochs
cd /opt/fochs

# Virtual Environment + Dependencies
uv sync

# Verzeichnisse erstellen
mkdir -p data data/chroma data/logs plugins /tmp/fochs
```

### 3. Konfiguration

```bash
cp .env.example .env
nano .env          # API Keys, Telegram Token, etc. eintragen
chmod 600 .env     # Nur Owner darf lesen
```

**Pflichtfelder:**

| Variable | Beschreibung | Bezugsquelle |
|----------|-------------|--------------|
| `FOCHS_ANTHROPIC_API_KEY` | Claude API Key | anthropic.com |
| `FOCHS_TELEGRAM_BOT_TOKEN` | Telegram Bot Token | @BotFather |
| `FOCHS_TELEGRAM_ALLOWED_USERS` | Erlaubte User IDs | Telegram |

**Empfohlen:**

| Variable | Beschreibung |
|----------|-------------|
| `FOCHS_BRAVE_API_KEY` | Web-Suche (2000 Queries/Monat gratis) |
| `FOCHS_SHELL_MODE` | restricted / standard / unrestricted |
| `FOCHS_WEB_SECRET_KEY` | Dashboard-Passwort (wird auto-generiert falls leer) |

Alternativ: Interaktiver Setup-Wizard:
```bash
uv run fochs setup
```

### 4. Systemd Service

```bash
# Service installieren
sudo cp deploy/fochs.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable fochs
sudo systemctl start fochs

# Status pruefen
sudo systemctl status fochs
sudo journalctl -u fochs -f
```

### 5. Shell-Modus aendern

```bash
# In .env aendern:
FOCHS_SHELL_MODE=standard

# Neustart:
sudo systemctl restart fochs
```

---

## Nginx Reverse-Proxy (HTTPS)

Das Web-Dashboard laeuft auf `127.0.0.1:8080` (nur lokal). Fuer externen
Zugriff wird ein Reverse-Proxy mit TLS empfohlen.

### Installation

```bash
sudo apt install -y nginx

# Config installieren
sudo cp deploy/nginx-fochs.conf /etc/nginx/sites-available/fochs

# Domain anpassen (fochs.example.com → deine Domain)
sudo sed -i 's/fochs.example.com/meine-domain.de/g' /etc/nginx/sites-available/fochs

# Aktivieren
sudo ln -s /etc/nginx/sites-available/fochs /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### TLS mit Let's Encrypt

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d meine-domain.de
```

### Ohne Nginx (SSH-Tunnel)

Falls kein externer Zugriff noetig ist:
```bash
# Von deinem Rechner:
ssh -L 8080:127.0.0.1:8080 user@server
# Dashboard unter http://localhost:8080 erreichbar
```

---

## Docker (Alternative)

```bash
# .env Datei erstellen
cp .env.example .env
nano .env

# Starten
docker compose up -d

# Logs
docker compose logs -f fochs
```

HINWEIS: Im Docker-Container sind Shell-Tools eingeschraenkt.
Self-Update und Software-Installation funktionieren nicht wie auf Bare-Metal.

---

## CLI-Befehle

| Befehl | Beschreibung |
|--------|-------------|
| `fochs` | Bot starten (Telegram + Dashboard) |
| `fochs setup` | Interaktiver Konfigurations-Wizard |
| `fochs doctor` | Health-Check und Diagnose |
| `fochs preflight` | Kompletter Bootstrap (Deps → Setup → Doctor) |
| `fochs update` | Update von Git + Neustart |
| `fochs update --dry-run` | Zeigt Updates ohne sie anzuwenden |

---

## Health Check

```bash
curl http://localhost:8080/api/health
```

---

## Backup

```bash
# Manuell
make backup

# Automatisch (Cronjob, taeglich 2 Uhr)
echo '0 2 * * * cd /opt/fochs && make backup' | sudo -u fochs crontab -
```

Gesichert werden: `data/` (DB, ChromaDB, Budget, Logs) und `.env`.

---

## Sicherheitsprofile

| Modus | Beschreibung |
|-------|-------------|
| restricted | Nur lesen: ls, cat, df, ps, git status |
| standard | Allgemein: pip install, git pull, Dateien schreiben |
| unrestricted | Volle Kontrolle (absolute Blocklist aktiv) |
