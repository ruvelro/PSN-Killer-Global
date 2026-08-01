#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew no está instalado. Instalándolo..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
fi

BREW_PREFIX="$(brew --prefix)"
PYTHON_BIN="$BREW_PREFIX/bin/python3.13"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Instalando Python 3.13 y Tk desde Homebrew..."
  brew install python@3.13 python-tk@3.13
  PYTHON_BIN="$BREW_PREFIX/bin/python3.13"
fi

if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import tkinter
PY
then
  echo "Tkinter no está disponible. Instalando python-tk..."
  brew install python-tk@3.13
fi

if [[ ! -d ".venv" ]]; then
  echo "Creando entorno virtual..."
  "$PYTHON_BIN" -m venv .venv
fi

echo "Instalando dependencias..."
".venv/bin/python" -m pip install --upgrade pip
".venv/bin/python" -m pip install -r requirements.txt

echo "Lanzando PS3 PSN KILLER..."
exec ".venv/bin/python" app.py
