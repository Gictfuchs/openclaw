# Fochs Deployment

## Bare-Metal (Empfohlen)

### 1. Voraussetzungen

```bash
# Python 3.12+, git, systemd
sudo apt update && sudo apt install -y python3.12 python3.12-venv git

# UV (schneller Package-Manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Installation

```bash
# User erstellen
sudo useradd -r -m -d /opt/fochs -s /bin/bash fochs
sudo su - fochs

# Repository klonen
git clone https://github.com/your-org/openclaw.git /opt/fochs
cd /opt/fochs

# Virtual Environment + Dependencies
uv sync

# Verzeichnisse erstellen
mkdir -p data plugins /tmp/fochs
```

### 3. Konfiguration

```bash
cp .env.example .env
# .env bearbeiten: API Keys, Telegram Token, etc.
nano .env
```

Wichtige Variablen:
- `FOCHS_ANTHROPIC_API_KEY` - Claude API Key
- `FOCHS_TELEGRAM_BOT_TOKEN` - Telegram Bot Token
- `FOCHS_TELEGRAM_ALLOWED_USERS` - Erlaubte Telegram User IDs
- `FOCHS_SHELL_MODE` - restricted/standard/unrestricted
- `FOCHS_WEB_SECRET_KEY` - Dashboard-Passwort

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

## Health Check

```bash
curl http://localhost:8080/api/health
```

## Sicherheitsprofile

| Modus | Beschreibung |
|-------|-------------|
| restricted | Nur lesen: ls, cat, df, ps, git status |
| standard | Allgemein: pip install, git pull, Dateien schreiben |
| unrestricted | Volle Kontrolle (absolute Blocklist aktiv) |
