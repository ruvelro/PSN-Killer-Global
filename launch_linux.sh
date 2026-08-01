#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

install_python() {
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv python3-tk python3-pip
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3 python3-tkinter python3-pip
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -Sy --needed python tk
  elif command -v zypper >/dev/null 2>&1; then
    sudo zypper install -y python3 python3-tk python3-pip
  else
    echo "No se encontró un gestor soportado (apt, dnf, pacman, zypper). Instala Python 3 con Tkinter manualmente."
    exit 1
  fi
}

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 no está instalado. Instalándolo..."
  install_python
fi

if ! python3 - <<'PY' >/dev/null 2>&1
import tkinter
PY
then
  echo "Tkinter no está disponible. Instalando soporte Tk..."
  install_python
fi

if [[ ! -d ".venv" ]]; then
  echo "Creando entorno virtual..."
  python3 -m venv .venv
fi

echo "Instalando dependencias..."
".venv/bin/python" -m pip install --upgrade pip
".venv/bin/python" -m pip install -r requirements.txt

echo "Lanzando PS3 PSN KILLER..."
exec ".venv/bin/python" app.py
