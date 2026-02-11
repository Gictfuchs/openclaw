#!/usr/bin/env bash
# ==============================================================================
# Fochs Deployment Script
# Automatisiert die komplette Installation auf einem frischen Linux-Server.
#
# Verwendung:
#   curl -sSL https://raw.githubusercontent.com/Gictfuchs/openclaw/main/deploy/deploy.sh | sudo bash
#   # oder lokal:
#   sudo bash deploy/deploy.sh
#
# Was passiert:
#   1. System-Pakete installieren (Python 3.12, git, curl, nginx)
#   2. UV Package-Manager installieren
#   3. fochs-User erstellen
#   4. Repository klonen nach /opt/fochs
#   5. Dependencies installieren (uv sync)
#   6. .env aus .env.example erstellen
#   7. Systemd-Service installieren + aktivieren
#   8. Nginx Reverse-Proxy installieren (optional)
#   9. fochs doctor ausfuehren
# ==============================================================================

set -euo pipefail

# --- Farben ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

INSTALL_DIR="/opt/fochs"
FOCHS_USER="fochs"
REPO_URL="https://github.com/Gictfuchs/openclaw.git"
BRANCH="main"

# --- Hilfsfunktionen ---

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[FEHLER]${NC} $*" >&2; }

step() {
    echo ""
    echo -e "${BLUE}━━━ Schritt $1: $2 ━━━${NC}"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        err "Dieses Script muss als root ausgefuehrt werden (sudo)."
        exit 1
    fi
}

confirm() {
    local prompt="$1"
    local default="${2:-y}"
    local yn
    if [[ "$default" == "y" ]]; then
        read -r -p "$prompt [J/n] " yn
        yn="${yn:-y}"
    else
        read -r -p "$prompt [j/N] " yn
        yn="${yn:-n}"
    fi
    [[ "$yn" =~ ^[JjYy]$ ]]
}

# ==============================================================================
# Schritt 1: System-Pakete
# ==============================================================================

install_system_packages() {
    step 1 "System-Pakete installieren"

    apt-get update -qq

    local packages=(git curl)

    # Python 3.12 — pruefen ob verfuegbar
    if command -v python3.12 &>/dev/null; then
        ok "Python 3.12 bereits installiert: $(python3.12 --version)"
    elif apt-cache show python3.12 &>/dev/null 2>&1; then
        packages+=(python3.12 python3.12-venv)
    else
        # Fallback: System-Python pruefen
        local py_version
        py_version=$(python3 --version 2>/dev/null | grep -oP '\d+\.\d+' || echo "0.0")
        if [[ "$(echo "$py_version >= 3.12" | bc -l 2>/dev/null || echo 0)" == "1" ]]; then
            ok "Python $py_version genuegt (>= 3.12)"
        else
            err "Python 3.12+ nicht verfuegbar. Bitte manuell installieren:"
            err "  sudo add-apt-repository ppa:deadsnakes/ppa"
            err "  sudo apt install python3.12 python3.12-venv"
            exit 1
        fi
    fi

    if [[ ${#packages[@]} -gt 0 ]]; then
        info "Installiere: ${packages[*]}"
        apt-get install -y -qq "${packages[@]}"
    fi

    ok "System-Pakete bereit"
}

# ==============================================================================
# Schritt 2: UV installieren
# ==============================================================================

install_uv() {
    step 2 "UV Package-Manager installieren"

    if command -v uv &>/dev/null; then
        ok "UV bereits installiert: $(uv --version)"
        return
    fi

    info "Installiere UV..."
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh 2>/dev/null

    if command -v uv &>/dev/null; then
        ok "UV installiert: $(uv --version)"
    else
        # Fallback: vielleicht in ~/.local/bin
        export PATH="$HOME/.local/bin:$PATH"
        if command -v uv &>/dev/null; then
            ok "UV installiert (in ~/.local/bin): $(uv --version)"
        else
            err "UV-Installation fehlgeschlagen. Bitte manuell: https://docs.astral.sh/uv/"
            exit 1
        fi
    fi
}

# ==============================================================================
# Schritt 3: fochs-User erstellen
# ==============================================================================

create_user() {
    step 3 "Fochs-User erstellen"

    if id "$FOCHS_USER" &>/dev/null; then
        ok "User '$FOCHS_USER' existiert bereits"
    else
        info "Erstelle System-User '$FOCHS_USER'..."
        useradd -r -m -d "$INSTALL_DIR" -s /bin/bash "$FOCHS_USER"
        ok "User '$FOCHS_USER' erstellt (Home: $INSTALL_DIR)"
    fi
}

# ==============================================================================
# Schritt 4: Repository klonen
# ==============================================================================

clone_repo() {
    step 4 "Repository klonen"

    if [[ -d "$INSTALL_DIR/.git" ]]; then
        ok "Repository bereits vorhanden in $INSTALL_DIR"
        info "Aktualisiere auf neuesten Stand..."
        sudo -u "$FOCHS_USER" git -C "$INSTALL_DIR" pull origin "$BRANCH" --ff-only || {
            warn "git pull fehlgeschlagen — ueberspringe"
        }
    else
        info "Klone $REPO_URL nach $INSTALL_DIR..."
        # Falls /opt/fochs existiert aber kein Git-Repo ist
        if [[ -d "$INSTALL_DIR" ]]; then
            warn "$INSTALL_DIR existiert bereits (kein Git-Repo). Klone in temp..."
            local tmpdir
            tmpdir=$(mktemp -d)
            git clone --branch "$BRANCH" "$REPO_URL" "$tmpdir/openclaw"
            cp -a "$tmpdir/openclaw/." "$INSTALL_DIR/"
            rm -rf "$tmpdir"
        else
            git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
        fi
        chown -R "$FOCHS_USER:$FOCHS_USER" "$INSTALL_DIR"
        ok "Repository geklont"
    fi
}

# ==============================================================================
# Schritt 5: Dependencies installieren
# ==============================================================================

install_deps() {
    step 5 "Python-Dependencies installieren"

    info "Fuehre 'uv sync' aus..."
    sudo -u "$FOCHS_USER" bash -c "cd $INSTALL_DIR && uv sync --frozen 2>&1" || {
        warn "'uv sync --frozen' fehlgeschlagen, versuche ohne --frozen..."
        sudo -u "$FOCHS_USER" bash -c "cd $INSTALL_DIR && uv sync 2>&1"
    }

    ok "Dependencies installiert"
}

# ==============================================================================
# Schritt 6: Konfiguration
# ==============================================================================

setup_config() {
    step 6 "Konfiguration"

    local env_file="$INSTALL_DIR/.env"

    if [[ -f "$env_file" ]]; then
        ok ".env existiert bereits"
        warn "Bitte manuell pruefen: $env_file"
    else
        info "Erstelle .env aus .env.example..."
        sudo -u "$FOCHS_USER" cp "$INSTALL_DIR/.env.example" "$env_file"
        ok ".env erstellt"
    fi

    # Verzeichnisse erstellen
    local dirs=("$INSTALL_DIR/data" "$INSTALL_DIR/data/chroma" "$INSTALL_DIR/data/logs" "$INSTALL_DIR/plugins" "/tmp/fochs")
    for dir in "${dirs[@]}"; do
        mkdir -p "$dir"
        chown "$FOCHS_USER:$FOCHS_USER" "$dir"
    done
    ok "Verzeichnisse erstellt (data, chroma, logs, plugins)"

    # Permissions
    chmod 600 "$env_file"
    chown "$FOCHS_USER:$FOCHS_USER" "$env_file"
    ok ".env Permissions gesetzt (600)"

    echo ""
    warn "╔══════════════════════════════════════════════════════════╗"
    warn "║  WICHTIG: .env muss noch mit echten API-Keys gefuellt  ║"
    warn "║  werden bevor der Service gestartet wird!              ║"
    warn "║                                                        ║"
    warn "║  Mindestens benoetigt:                                 ║"
    warn "║    - FOCHS_ANTHROPIC_API_KEY                           ║"
    warn "║    - FOCHS_TELEGRAM_BOT_TOKEN                          ║"
    warn "║    - FOCHS_TELEGRAM_ALLOWED_USERS                      ║"
    warn "║                                                        ║"
    warn "║  Bearbeiten: sudo -u fochs nano $env_file    ║"
    warn "╚══════════════════════════════════════════════════════════╝"
}

# ==============================================================================
# Schritt 7: Systemd-Service
# ==============================================================================

install_service() {
    step 7 "Systemd-Service installieren"

    local service_src="$INSTALL_DIR/deploy/fochs.service"
    local service_dst="/etc/systemd/system/fochs.service"

    if [[ ! -f "$service_src" ]]; then
        err "Service-Datei nicht gefunden: $service_src"
        return 1
    fi

    cp "$service_src" "$service_dst"
    systemctl daemon-reload
    systemctl enable fochs
    ok "Service installiert und aktiviert (fochs.service)"

    info "Service wird NICHT automatisch gestartet — erst .env konfigurieren!"
    info "Danach starten mit: sudo systemctl start fochs"
}

# ==============================================================================
# Schritt 8: Nginx (optional)
# ==============================================================================

install_nginx() {
    step 8 "Nginx Reverse-Proxy (optional)"

    if ! confirm "Nginx Reverse-Proxy einrichten?" "y"; then
        info "Nginx uebersprungen"
        info "Dashboard ist ueber SSH-Tunnel erreichbar:"
        info "  ssh -L 8080:127.0.0.1:8080 user@server"
        return
    fi

    # Nginx installieren falls noetig
    if ! command -v nginx &>/dev/null; then
        info "Installiere Nginx..."
        apt-get install -y -qq nginx
    fi
    ok "Nginx verfuegbar: $(nginx -v 2>&1)"

    local nginx_src="$INSTALL_DIR/deploy/nginx-fochs.conf"
    local nginx_dst="/etc/nginx/sites-available/fochs"

    if [[ ! -f "$nginx_src" ]]; then
        err "Nginx-Config nicht gefunden: $nginx_src"
        return 1
    fi

    # Domain abfragen
    local domain
    read -r -p "Domain fuer Fochs Dashboard (z.B. fochs.deinserver.de): " domain
    if [[ -z "$domain" ]]; then
        warn "Keine Domain angegeben — verwende 'localhost'"
        domain="localhost"
    fi

    # Config kopieren und Domain ersetzen
    sed "s/fochs.example.com/$domain/g" "$nginx_src" > "$nginx_dst"

    # Symlink erstellen
    ln -sf "$nginx_dst" /etc/nginx/sites-enabled/fochs

    # Default-Site deaktivieren (optional)
    if [[ -L /etc/nginx/sites-enabled/default ]]; then
        if confirm "Default Nginx-Site deaktivieren?" "n"; then
            rm /etc/nginx/sites-enabled/default
        fi
    fi

    # Config testen
    if nginx -t 2>/dev/null; then
        systemctl reload nginx
        ok "Nginx konfiguriert fuer: $domain"
    else
        err "Nginx-Config fehlerhaft! Bitte manuell pruefen: $nginx_dst"
        nginx -t
        return 1
    fi

    # Let's Encrypt
    if [[ "$domain" != "localhost" ]]; then
        echo ""
        if confirm "TLS-Zertifikat mit Let's Encrypt einrichten?" "y"; then
            if ! command -v certbot &>/dev/null; then
                apt-get install -y -qq certbot python3-certbot-nginx
            fi
            certbot --nginx -d "$domain" --non-interactive --agree-tos --redirect \
                --email "admin@$domain" || {
                warn "Certbot fehlgeschlagen — bitte manuell ausfuehren:"
                warn "  sudo certbot --nginx -d $domain"
            }
        else
            warn "TLS nicht eingerichtet. Spaeter: sudo certbot --nginx -d $domain"
        fi
    fi
}

# ==============================================================================
# Schritt 9: Verifikation
# ==============================================================================

verify() {
    step 9 "Verifikation"

    echo ""
    info "Fuehre 'fochs doctor' aus..."
    echo ""
    sudo -u "$FOCHS_USER" bash -c "cd $INSTALL_DIR && uv run fochs doctor" || {
        warn "Doctor hat Warnungen/Fehler gemeldet — bitte oben pruefen"
    }
}

# ==============================================================================
# Zusammenfassung
# ==============================================================================

summary() {
    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}  Installation abgeschlossen!${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "  Naechste Schritte:"
    echo ""
    echo "  1. API-Keys konfigurieren:"
    echo "     sudo -u fochs nano /opt/fochs/.env"
    echo ""
    echo "  2. Interaktiver Setup-Wizard (optional):"
    echo "     sudo -u fochs bash -c 'cd /opt/fochs && uv run fochs setup'"
    echo ""
    echo "  3. Service starten:"
    echo "     sudo systemctl start fochs"
    echo ""
    echo "  4. Status pruefen:"
    echo "     sudo systemctl status fochs"
    echo "     sudo journalctl -u fochs -f"
    echo ""
    echo "  5. Health Check:"
    echo "     curl http://localhost:8080/api/health"
    echo ""
}

# ==============================================================================
# Main
# ==============================================================================

main() {
    echo ""
    echo -e "${BLUE}╔══════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║     Fochs Deployment Script v1.0     ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════╝${NC}"
    echo ""

    check_root

    install_system_packages
    install_uv
    create_user
    clone_repo
    install_deps
    setup_config
    install_service
    install_nginx
    verify
    summary
}

main "$@"
