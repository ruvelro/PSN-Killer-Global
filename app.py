import sys
import subprocess
import tkinter as tk
from tkinter import messagebox

# ==========================================
# 0. VERIFICACIÓN E INSTALACIÓN DE DEPENDENCIAS
# ==========================================
def verificar_e_instalar_dependencias():
    librerias_requeridas = {
        "customtkinter": "customtkinter",
        "bs4": "beautifulsoup4",
        "requests": "requests"
    }
    
    faltantes = []
    for mod, pip_name in librerias_requeridas.items():
        try:
            __import__(mod)
        except ImportError:
            faltantes.append(pip_name)

    if faltantes:
        root = tk.Tk()
        root.withdraw()
        
        mensaje = (
            f"Para ejecutar esta aplicación se necesitan las siguientes librerías:\n\n"
            f"• {', '.join(faltantes)}\n\n"
            f"¿Deseas instalarlas automáticamente ahora mismo?"
        )
        
        respuesta = messagebox.askyesno("Librerías Faltantes", mensaje)
        
        if respuesta:
            root.destroy()
            print("⏳ Instalando dependencias, por favor espera...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", *faltantes])
                messagebox.showinfo("Éxito", "¡Librerías instaladas correctamente! Iniciando la app...")
            except Exception as e:
                messagebox.showerror("Error", f"No se pudieron instalar las librerías automáticamente:\n{e}")
                sys.exit(1)
        else:
            messagebox.showwarning("Cancelado", "La aplicación no puede continuar sin estas librerías.")
            root.destroy()
            sys.exit(0)

verificar_e_instalar_dependencias()

# ==========================================
# IMPORTACIONES PRINCIPALES DE LA APLICACIÓN
# ==========================================
import os
import csv
import json
import re
import time
import requests
import threading
import hashlib
import shutil
import logging
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime
from difflib import SequenceMatcher
from tkinter import ttk, filedialog
import customtkinter as ctk

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DOWNLOADS_DIR = os.path.join(BASE_DIR, "Descargas")
MANIFEST_PATH = os.path.join(BASE_DIR, "downloads_manifest.json")
QUEUE_STATE_PATH = os.path.join(BASE_DIR, "download_queue.json")
APP_CONFIG_PATH = os.path.join(BASE_DIR, "app_config.json")
CATALOG_SOURCES_PATH = os.path.join(BASE_DIR, "catalog_sources.json")
CATALOG_STATE_PATH = os.path.join(DATA_DIR, "catalog_state.json")
CATALOG_BACKUP_DIR = os.path.join(DATA_DIR, "backups")
CATALOG_DB_PATH = os.path.join(DATA_DIR, "catalog.sqlite3")
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_PATH = os.path.join(LOG_DIR, "app.log")
APP_VERSION = "0.2.0"
CATALOG_STATE_META_KEY = "_meta"
DATABASE_TSV_BASE_URL = "https://raw.githubusercontent.com/ruvelro/PSN-Killer-Database/main/data"
NPS_TSV_BASE_URL = "https://nopaystation.com/tsv"
VITAWIKI_TSV_BASE_URL = "https://vitawiki.xyz/free"
CATALOG_PARSER_VERSION = "2"

# URL directa al pack de licencias
GITHUB_RAP_URL = "https://github.com/TheWizWikii/PS3-Stuff-Repository/releases/download/3/License_Pack_31.153.pkg"

CARPETAS = {
    "Juegos": os.path.join(DOWNLOADS_DIR, "Juegos"),
    "Updates": os.path.join(DOWNLOADS_DIR, "Updates"),
    "Demos": os.path.join(DOWNLOADS_DIR, "Demos"),
    "Temas": os.path.join(DOWNLOADS_DIR, "Temas"),
    "Avatares": os.path.join(DOWNLOADS_DIR, "Avatares"),
    "DLCs": os.path.join(DOWNLOADS_DIR, "DLCs"),
    "RAP": os.path.join(BASE_DIR, "Keys_RAP")
}

# Crear carpetas de destino automáticamente
for folder in CARPETAS.values():
    os.makedirs(folder, exist_ok=True)
os.makedirs(DOWNLOADS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CATALOG_BACKUP_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8"
)


@dataclass
class ContentItem:
    category: str
    title_id: str
    region: str
    name: str
    version: str
    size: str
    url: str
    content_id: str = ""
    match_type: str = ""
    platform: str = "PS3"
    license_value: str = ""
    sha256: str = ""
    required_fw: str = ""
    original_name: str = ""
    item_type: str = ""


@dataclass
class DownloadTask:
    task_id: int
    url: str
    dest_path: str
    title: str
    platform: str
    category: str
    base_item: ContentItem = None
    manifest_item: ContentItem = None
    game_key: str = ""
    status: str = "queued"
    progress: float = 0.0
    speed: str = ""
    error: str = ""
    created_at: str = ""
    completed_at: str = ""
    total_size: int = 0
    resume_path: str = ""


class DownloadCancelled(Exception):
    pass


def sanitize_filename(filename):
    r"""
    Limpia el nombre del archivo para que sea válido en Windows/Linux/macOS.
    Elimina caracteres no permitidos como : \ / * ? " < > |
    """
    filename = re.sub(r'[:\\/|]', ' -', filename)
    filename = re.sub(r'[?*"<>]', '', filename)
    filename = re.sub(r'\s+', ' ', filename).strip()
    return filename


def auto_detect_region(tid):
    """ Detecta la región del juego basándose en el prefijo del Title ID """
    tid = tid.upper()
    if len(tid) >= 4:
        code = tid[:4]
        if code.startswith(('BCUS', 'BLUS', 'NPUA', 'NPUB', 'NPUG', 'NPUZ', 'UP')):
            return 'US'
        elif code.startswith(('BCES', 'BLES', 'NPEA', 'NPEB', 'NPEG', 'NPEZ', 'EP')):
            return 'EU'
        elif code.startswith(('BCJS', 'BLJS', 'NPJA', 'NPJB', 'NPJH', 'JP')):
            return 'ASIA'
        elif code.startswith(('BCAS', 'BLAS', 'NPHA', 'NPHB', 'HP')):
            return 'ASIA'
    return 'ALL'


def split_name_and_version(raw_name, default_ver="Base"):
    """ Separa versiones adosadas al nombre """
    if not raw_name:
        return "", default_ver

    match = re.search(r'(.*?)(?:\[?v?(\d{1,2}\.\d{2})\]?)$', raw_name.strip(), re.IGNORECASE)
    if match and match.group(2):
        clean_name = match.group(1).strip()
        version_str = f"v{match.group(2)}"
        return clean_name, version_str

    return raw_name.strip(), default_ver


def extract_version_from_text(text, default_ver="v01.00"):
    match = re.search(r'\bv[\s.]?(\d+(?:\.\d+)*)\b', text or "", re.IGNORECASE)
    if match:
        return f"v{match.group(1)}"
    return default_ver


def format_bytes(bytes_num):
    """ Convierte un número de bytes en formato MB/GB legible """
    try:
        b = float(bytes_num)
        if b <= 0:
            return "N/A"
        if b >= 1024**3:
            return f"{b / (1024**3):.2f} GB"
        elif b >= 1024**2:
            return f"{b / (1024**2):.1f} MB"
        elif b >= 1024:
            return f"{b / 1024:.0f} KB"
        return f"{b:.0f} B"
    except (ValueError, TypeError):
        return "N/A"


def format_speed(bytes_per_sec):
    """ Da formato a la velocidad en MB/s y Mbps """
    if bytes_per_sec <= 0:
        return "0 KB/s"
    mb_s = bytes_per_sec / (1024 * 1024)
    mbps = (bytes_per_sec * 8) / (1024 * 1024)
    if mb_s >= 1:
        return f"{mb_s:.1f} MB/s | {mbps:.1f} Mbps"
    else:
        kb_s = bytes_per_sec / 1024
        return f"{kb_s:.0f} KB/s"


def parse_size_to_bytes(size_text):
    if not size_text or size_text in {"N/A", "Sin tamaño", "No disponible"}:
        return 0
    match = re.match(r"\s*([\d.]+)\s*([KMGT]?B)\s*$", size_text, re.IGNORECASE)
    if not match:
        return 0
    value = float(match.group(1))
    unit = match.group(2).upper()
    multipliers = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    return int(value * multipliers.get(unit, 1))


def format_total_size(bytes_num):
    return format_bytes(bytes_num) if bytes_num else "Sin tamaño"


BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    'Accept-Encoding': 'identity',
    'Connection': 'keep-alive',
    'Sec-Ch-Ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Upgrade-Insecure-Requests': '1',
    'Cache-Control': 'no-cache'
}

# Un hilo por debajo de este tamaño no compensa y, si el archivo es menor que el
# número de hilos, el troceado genera rangos vacíos que el servidor rechaza.
MIN_BYTES_PER_THREAD = 1024 * 1024


def build_download_session(pool_size):
    """
    Crea una Session con el pool dimensionado al número de hilos.

    El HTTPAdapter por defecto trae pool_maxsize=10, así que con 16 hilos se
    descartaban y recreaban conexiones continuamente ("Connection pool is full").
    """
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=pool_size,
        pool_maxsize=pool_size,
        max_retries=0,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def plan_thread_count(total_size, requested):
    """Nunca más de un hilo por cada MIN_BYTES_PER_THREAD, para no generar rangos vacíos."""
    if total_size <= 0:
        return 1
    return max(1, min(requested, total_size // MIN_BYTES_PER_THREAD))


def calculate_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def valid_sha256(value):
    return bool(value and re.fullmatch(r"[a-fA-F0-9]{64}", value.strip()))


def data_path(filename):
    return os.path.join(DATA_DIR, os.path.basename(filename))


PLATFORM_CATALOGS = {
    "PS3": {
        "Juegos": "PS3_GAMES.tsv",
        "Updates": "PS3_UPDATES.tsv",
        "Demos": "PS3_DEMOS.tsv",
        "Temas": "PS3_THEMES.tsv",
        "Avatares": "PS3_AVATARS.tsv",
        "DLCs": "PS3_DLCS.tsv",
    },
    "PSP": {
        "Juegos": "PSP_GAMES.tsv",
        "Updates": "PSP_UPDATES.tsv",
        "Demos": "PSP_DEMOS.tsv",
        "Temas": "PSP_THEMES.tsv",
        "DLCs": "PSP_DLCS.tsv",
    },
    "PSV": {
        "Juegos": "PSV_GAMES.tsv",
        "Updates": "PSV_UPDATES.tsv",
        "Demos": "PSV_DEMOS.tsv",
        "Temas": "PSV_THEMES.tsv",
        "DLCs": "PSV_DLCS.tsv",
    },
    "PSX": {
        "Juegos": "PSX_GAMES.tsv",
    },
    "PSM": {
        "Juegos": "PSM_GAMES.tsv",
    },
}

CONTENT_ORDER = ["Juegos", "Updates", "DLCs", "Temas", "Avatares", "Demos"]
GROUPED_DOWNLOAD_PLATFORMS = {"PS3", "PSP", "PSV"}
RELATED_CATEGORIES = ["Juegos", "Updates", "DLCs", "Temas", "Avatares"]
DEFAULT_APP_CONFIG = {
    "downloads_dir": DOWNLOADS_DIR,
    "max_active_downloads": 2,
    "threads_per_download": 16,
    "auto_resume_queue": False,
    "catalog_primary_base_url": DATABASE_TSV_BASE_URL,
    "catalog_fallback_base_urls": [NPS_TSV_BASE_URL, VITAWIKI_TSV_BASE_URL],
    "catalog_update_interval_days": 7,
    "download_profile": "Completo seguro",
}
MAX_ACTIVE_DOWNLOADS = DEFAULT_APP_CONFIG["max_active_downloads"]
DOWNLOAD_FOLDER_TO_CATEGORY = {
    "Base": "Juegos",
    "Updates": "Updates",
    "DLCs": "DLCs",
    "Temas": "Temas",
    "Avatares": "Avatares",
    "Demos": "Demos",
}
TITLE_STOPWORDS = {
    "the", "a", "an", "and", "of", "for", "to", "in", "on", "with", "edition",
    "game", "pack", "bundle", "level", "map", "skin", "costume", "theme", "avatar",
    "dlc", "update", "add", "on", "content", "ps3", "psp", "psv", "vita", "psn"
}
DOWNLOAD_PROFILES = {
    "Base + última update": {"base": True, "latest_update": True, "exact_extras": False, "suggested": False},
    "Completo seguro": {"base": True, "latest_update": True, "exact_extras": True, "suggested": False},
    "Preservación completa": {"base": True, "latest_update": False, "exact_extras": True, "suggested": True},
    "Solo verificados": {"base": True, "latest_update": True, "exact_extras": True, "suggested": False, "require_sha256": True},
}


def normalize_title(text):
    text = text.lower()
    text = text.replace("™", "").replace("®", "")
    text = re.sub(r"\blittle\s+big\s+planet\b", "littlebigplanet", text)
    text = re.sub(r"\b(ps3|psn|demo|trial|trial to full|downloader|needs|free|space)\b", " ", text)
    text = re.sub(r"\b(goty|game of the year|ultimate|complete|edition|digital|stand alone)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def title_tokens(text):
    return set(normalize_title(text).split())


def meaningful_title_tokens(text):
    return {token for token in title_tokens(text) if token not in TITLE_STOPWORDS and len(token) > 1}


def title_numbers(text):
    return set(re.findall(r"\b\d+\b", normalize_title(text)))


def has_number_conflict(base_name, candidate_name):
    base_numbers = title_numbers(base_name)
    candidate_numbers = title_numbers(candidate_name)
    return bool(base_numbers or candidate_numbers) and base_numbers != candidate_numbers


def title_similarity(left, right):
    left_norm = normalize_title(left)
    right_norm = normalize_title(right)
    if not left_norm or not right_norm:
        return 0.0

    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    token_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens) if left_tokens and right_tokens else 0
    sequence_score = SequenceMatcher(None, left_norm, right_norm).ratio()

    if left_norm in right_norm or right_norm in left_norm:
        return max(token_score, sequence_score, 0.82)
    return max(token_score, sequence_score)


def version_tuple(version):
    numbers = re.findall(r"\d+", version or "")
    return tuple(int(n) for n in numbers) if numbers else (0,)


def category_folder(category):
    return {
        "Juegos": "Base",
        "Updates": "Updates",
        "DLCs": "DLCs",
        "Temas": "Temas",
        "Avatares": "Avatares",
        "Demos": "Demos",
    }.get(category, category)


def item_filename(item):
    clean_title = sanitize_filename(item.name)
    if item.version and item.version.lower() not in ["base", "n/a", "none"]:
        return f"{clean_title} {item.version}.pkg"
    return f"{clean_title}.pkg"


def unique_path(dest_path):
    counter = 1
    base_name, ext = os.path.splitext(dest_path)
    while os.path.exists(dest_path):
        dest_path = f"{base_name} ({counter}){ext}"
        counter += 1
    return dest_path


def partial_path(dest_path):
    return f"{dest_path}.part"


def manifest_key(game_key, item):
    return f"{item.platform}|{game_key}|{item.category}|{item.title_id}|{item.version}|{item.url}"


def compatible_region(base_region, candidate_region):
    if not base_region or not candidate_region:
        return True
    return candidate_region in {base_region, "ALL", "FREE", "INT"}


def same_catalog_item(left, right):
    if left.url and right.get("url") and left.url == right.get("url"):
        return True
    if right.get("path") and os.path.basename(right["path"]).lower() == item_filename(left).lower():
        return True
    return (
        left.category == right.get("category")
        and left.title_id == right.get("title_id")
        and left.name == right.get("name")
        and left.version == right.get("version")
    )


def is_valid_download_url(url):
    return (url or "").strip().lower().startswith(("http://", "https://"))


def is_missing_value(value):
    return not (value or "").strip() or (value or "").strip().upper() in {"MISSING", "N/A", "NA"}


def catalog_item_key(item):
    if item.content_id:
        return ("content_id", item.platform, item.category, item.content_id)
    if is_valid_download_url(item.url):
        return ("url", item.platform, item.category, item.url)
    return (
        "fallback",
        item.platform,
        item.category,
        item.title_id,
        item.region,
        normalize_title(item.name),
        item.version,
    )


def catalog_item_score(item):
    score = 0
    score += 100 if is_valid_download_url(item.url) else 0
    score += 30 if not is_missing_value(item.license_value) else 0
    score += 20 if not is_missing_value(item.sha256) else 0
    score += 10 if parse_size_to_bytes(item.size) else 0
    score += 5 if not is_missing_value(item.required_fw) else 0
    return score


class PSNDownloaderApp(ctk.CTk):
    def __init__(self):
        global DOWNLOADS_DIR
        super().__init__()

        self.title("PSN Killer Global")
        self.geometry("1400x780")

        self.setup_dark_theme()

        self.app_config = self.load_app_config()
        DOWNLOADS_DIR = self.app_config.get("downloads_dir", DOWNLOADS_DIR)
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        self.max_active_downloads = int(self.app_config.get("max_active_downloads", 2))
        self.threads_per_download = int(self.app_config.get("threads_per_download", 16))
        self.current_platform = "PS3"
        self.reset_catalog()
        self.download_manifest = self.load_download_manifest()
        self.download_tasks = {}
        self.download_order = []
        self.download_lock = threading.Lock()
        self.download_task_seq = 0
        self.active_downloads = 0
        self.running_task_ids = set()
        self.catalog_loading = False
        self.catalog_update_running = False
        self.ui_closed = False
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.create_ui()
        self.load_queue_state()
        self.refresh_downloads_view()
        self.refresh_queue_view()
        self.after(100, self.start_initial_catalog_load)

    def setup_dark_theme(self):
        """ Configura el estilo oscuro minimalista para los Treeview de Tkinter """
        style = ttk.Style()
        style.theme_use("default")

        bg_dark = "#1a1a1a"
        fg_white = "#e1e1e1"
        header_bg = "#2b2b2b"
        select_bg = "#1f6aa5"

        style.configure(
            "Treeview",
            background=bg_dark,
            foreground=fg_white,
            fieldbackground=bg_dark,
            rowheight=28,
            borderwidth=0,
            font=("Segoe UI", 10)
        )
        
        style.configure(
            "Treeview.Heading",
            background=header_bg,
            foreground=fg_white,
            relief="flat",
            font=("Segoe UI", 10, "bold")
        )

        style.map(
            "Treeview",
            background=[("selected", select_bg)],
            foreground=[("selected", "#ffffff")]
        )

        style.map(
            "Treeview.Heading",
            background=[("active", "#3a3a3a")]
        )

    def load_app_config(self):
        config = dict(DEFAULT_APP_CONFIG)
        if os.path.exists(APP_CONFIG_PATH):
            try:
                with open(APP_CONFIG_PATH, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                if isinstance(saved, dict):
                    config.update(saved)
                    old_primary = saved.get("catalog_primary_base_url")
                    old_fallbacks = saved.get("catalog_fallback_base_urls", [])
                    if old_primary == NPS_TSV_BASE_URL and not old_fallbacks:
                        config["catalog_primary_base_url"] = DATABASE_TSV_BASE_URL
                        config["catalog_fallback_base_urls"] = [NPS_TSV_BASE_URL, VITAWIKI_TSV_BASE_URL]
            except (json.JSONDecodeError, OSError) as e:
                logging.warning("No se pudo leer app_config.json: %s", e)
        return config

    def save_app_config(self):
        with open(APP_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self.app_config, f, indent=2, ensure_ascii=False)

    def content_item_to_dict(self, item):
        return asdict(item) if item else None

    def content_item_from_dict(self, data):
        if not isinstance(data, dict):
            return None
        fields = {field: data.get(field, "") for field in ContentItem.__dataclass_fields__}
        return ContentItem(**fields)

    def task_to_dict(self, task):
        data = asdict(task)
        data["base_item"] = self.content_item_to_dict(task.base_item)
        data["manifest_item"] = self.content_item_to_dict(task.manifest_item)
        return data

    def task_from_dict(self, data):
        fields = {}
        for field, definition in DownloadTask.__dataclass_fields__.items():
            value = data.get(field)
            fields[field] = definition.default if value is None else value
        fields["base_item"] = self.content_item_from_dict(data.get("base_item"))
        fields["manifest_item"] = self.content_item_from_dict(data.get("manifest_item"))
        task = DownloadTask(**fields)
        if task.status == "downloading":
            task.status = "paused"
        return task

    def save_queue_state(self):
        with self.download_lock:
            data = {
                "saved_at": datetime.now().isoformat(timespec="seconds"),
                "tasks": [self.task_to_dict(self.download_tasks[task_id]) for task_id in self.download_order],
            }
        with open(QUEUE_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load_queue_state(self):
        if not os.path.exists(QUEUE_STATE_PATH):
            return
        try:
            with open(QUEUE_STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for row in data.get("tasks", []):
                task = self.task_from_dict(row)
                self.download_tasks[task.task_id] = task
                self.download_order.append(task.task_id)
                self.download_task_seq = max(self.download_task_seq, task.task_id)
            logging.info("Cola restaurada: %d tarea(s)", len(self.download_order))
        except (json.JSONDecodeError, OSError, TypeError) as e:
            logging.exception("No se pudo restaurar la cola: %s", e)

    def on_close(self):
        try:
            self.save_queue_state()
        except OSError as e:
            logging.exception("No se pudo guardar la cola al cerrar: %s", e)
        # A partir de aquí los hilos de descarga ya no pueden tocar la interfaz.
        self.ui_closed = True
        self.destroy()

    def ui(self, func, *args, **kwargs):
        """
        Ejecuta una actualización de interfaz en el hilo principal de Tk.

        Tkinter no es thread-safe: llamar a un widget desde un hilo de descarga
        provoca 'main thread is not in main loop' o cierres inesperados. Todo el
        código que corre fuera del hilo principal debe pasar por aquí.
        """
        if self.ui_closed:
            return
        try:
            self.after(0, lambda: func(*args, **kwargs))
        except RuntimeError:
            # La ventana ya se está destruyendo; descartamos la actualización.
            self.ui_closed = True

    def set_status(self, message):
        self.status_label.configure(text=message)

    def set_progress(self, value):
        self.progress_bar.set(max(0.0, min(1.0, value)))

    def set_busy_state(self, message):
        self.status_label.configure(text=message)
        self.count_label.configure(text=message)
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()

    def clear_busy_state(self, message="Estado: Listo"):
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(0)
        self.status_label.configure(text=message)

    def start_initial_catalog_load(self):
        self.catalog_loading = True
        self.set_busy_state("Cargando base de datos local, espera...")
        threading.Thread(target=self._initial_catalog_load_worker, daemon=True).start()

    def _initial_catalog_load_worker(self):
        try:
            self.load_all_data(populate=False)
            self.after(0, self.finish_initial_catalog_load)
        except Exception as e:
            logging.exception("Error cargando catálogos al iniciar: %s", e)
            self.after(0, lambda: self.fail_initial_catalog_load(e))

    def finish_initial_catalog_load(self):
        self.catalog_loading = False
        self.data_store = self.catalog[self.current_platform]
        self.populate_trees()
        self.refresh_downloads_view()
        self.refresh_queue_view()
        self.clear_busy_state("Estado: Listo")
        if self.app_config.get("auto_resume_queue"):
            self.schedule_downloads()
        self.maybe_update_catalogs_on_start()

    def fail_initial_catalog_load(self, error):
        self.catalog_loading = False
        self.clear_busy_state("Error cargando catálogos")
        messagebox.showerror("Catálogos", f"No se pudo cargar la base de datos local:\n{error}")

    def create_ui(self):
        top_frame = ctk.CTkFrame(self, height=50)
        top_frame.pack(fill="x", padx=10, pady=5)

        title_label = ctk.CTkLabel(
            top_frame, 
            text=f"🎮 PSN Killer Global v{APP_VERSION}",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        title_label.pack(side="left", padx=15)

        rap_btn = ctk.CTkButton(
            top_frame, 
            text="🔑 Descargar Licencias (31.153)", 
            fg_color="#1f77b4", 
            hover_color="#135d96", 
            command=self.download_rap
        )
        rap_btn.pack(side="right", padx=15, pady=5)

        catalog_btn = ctk.CTkButton(
            top_frame,
            text="🔄 Actualizar Catálogos",
            fg_color="#4f6f8f",
            hover_color="#3d566f",
            command=self.update_catalogs_from_sources
        )
        catalog_btn.pack(side="right", padx=(0, 8), pady=5)

        export_btn = ctk.CTkButton(
            top_frame,
            text="💾 Exportar",
            fg_color="#5c5c5c",
            hover_color="#474747",
            command=self.export_current_report
        )
        export_btn.pack(side="right", padx=(0, 8), pady=5)

        settings_btn = ctk.CTkButton(
            top_frame,
            text="⚙️ Config",
            fg_color="#5c5c5c",
            hover_color="#474747",
            command=self.open_settings_dialog
        )
        settings_btn.pack(side="right", padx=(0, 8), pady=5)

        about_btn = ctk.CTkButton(
            top_frame,
            text="ℹ️ Acerca de",
            fg_color="#5c5c5c",
            hover_color="#474747",
            command=self.open_about_dialog
        )
        about_btn.pack(side="right", padx=(0, 8), pady=5)

        search_frame = ctk.CTkFrame(self)
        search_frame.pack(fill="x", padx=10, pady=5)

        search_label = ctk.CTkLabel(search_frame, text="🔍 Buscar:", font=ctk.CTkFont(weight="bold"))
        search_label.pack(side="left", padx=10)

        self.search_entry = ctk.CTkEntry(
            search_frame, 
            placeholder_text="Escribe el nombre del juego (ej: Call of Duty) o Title ID..."
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=5, pady=5)
        self.search_entry.bind("<KeyRelease>", self.filter_tables)

        region_label = ctk.CTkLabel(search_frame, text="🌍 Región:", font=ctk.CTkFont(weight="bold"))
        region_label.pack(side="left", padx=(15, 5))

        self.region_combo = ctk.CTkComboBox(
            search_frame,
            values=["TODAS", "EU", "US", "JP", "ASIA", "INT", "ALL", "FREE"],
            width=100,
            command=self.filter_tables
        )
        self.region_combo.set("TODAS")
        self.region_combo.pack(side="left", padx=10)

        status_label = ctk.CTkLabel(search_frame, text="📌 Estado:", font=ctk.CTkFont(weight="bold"))
        status_label.pack(side="left", padx=(5, 5))

        self.status_filter_combo = ctk.CTkComboBox(
            search_frame,
            values=["TODOS", "NO DESCARGADO", "DESCARGADO", "PENDIENTE", "ERROR", "CORRUPTO"],
            width=135,
            command=self.filter_tables
        )
        self.status_filter_combo.set("TODOS")
        self.status_filter_combo.pack(side="left", padx=(0, 8))

        integrity_label = ctk.CTkLabel(search_frame, text="✅ Hash:", font=ctk.CTkFont(weight="bold"))
        integrity_label.pack(side="left", padx=(0, 5))

        self.integrity_filter_combo = ctk.CTkComboBox(
            search_frame,
            values=["TODOS", "CON SHA256", "SIN SHA256", "VERIFICADO", "CORRUPTO"],
            width=120,
            command=self.filter_tables
        )
        self.integrity_filter_combo.set("TODOS")
        self.integrity_filter_combo.pack(side="left", padx=(0, 8))

        platform_label = ctk.CTkLabel(search_frame, text="🎛️ Plataforma:", font=ctk.CTkFont(weight="bold"))
        platform_label.pack(side="left", padx=(10, 5))

        self.platform_combo = ctk.CTkComboBox(
            search_frame,
            values=list(PLATFORM_CATALOGS.keys()),
            width=90,
            command=self.change_platform
        )
        self.platform_combo.set(self.current_platform)
        self.platform_combo.pack(side="left", padx=(0, 10))

        self.tabview = None
        self.tabs = {}
        self.trees = {}
        self.build_platform_tabs()

        self.count_frame = ctk.CTkFrame(self, height=30, fg_color="#1e1e1e")
        self.count_frame.pack(fill="x", padx=10, pady=(2, 2))

        self.count_label = ctk.CTkLabel(
            self.count_frame, 
            text="📊 Cargando resumen de contenido...", 
            font=ctk.CTkFont(size=11, weight="normal"),
            text_color="#b0b0b0"
        )
        self.count_label.pack(side="left", padx=15, pady=2)

        # Barra de estado inferior
        self.status_frame = ctk.CTkFrame(self, height=35)
        self.status_frame.pack(fill="x", side="bottom", padx=10, pady=5)

        self.status_label = ctk.CTkLabel(self.status_frame, text="Estado: Listo", font=ctk.CTkFont(size=12))
        self.status_label.pack(side="left", padx=10)

        self.progress_bar = ctk.CTkProgressBar(self.status_frame)
        self.progress_bar.pack(side="right", padx=10, pady=8)
        self.progress_bar.set(0)

    def active_categories(self):
        return [category for category in CONTENT_ORDER if category in PLATFORM_CATALOGS[self.current_platform]]

    def build_platform_tabs(self):
        if self.tabview is not None:
            self.tabview.destroy()

        self.tabview = ctk.CTkTabview(self)
        pack_options = {"fill": "both", "expand": True, "padx": 10, "pady": 5}
        if hasattr(self, "count_frame"):
            self.tabview.pack(before=self.count_frame, **pack_options)
        else:
            self.tabview.pack(**pack_options)

        self.tabs = {}
        self.trees = {}

        for cat in self.active_categories():
            tab = self.tabview.add(cat)
            self.tabs[cat] = tab
            self._build_tree_view(tab, cat)

        downloads_tab = self.tabview.add("Descargas")
        self.tabs["Descargas"] = downloads_tab
        self._build_downloads_view(downloads_tab)

        queue_tab = self.tabview.add("Cola")
        self.tabs["Cola"] = queue_tab
        self._build_queue_view(queue_tab)

        history_tab = self.tabview.add("Historial")
        self.tabs["Historial"] = history_tab
        self._build_history_view(history_tab)

    def change_platform(self, platform):
        self.current_platform = platform
        self.data_store = self.catalog[self.current_platform]
        self.build_platform_tabs()
        self.filter_tables()
        self.refresh_downloads_view()
        self.refresh_queue_view()

    def _build_tree_view(self, parent, category):
        columns = ("title_id", "region", "name", "version", "size")
        table_frame = ctk.CTkFrame(parent, fg_color="transparent")
        table_frame.pack(side="top", fill="both", expand=True, padx=5, pady=5)

        tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")

        tree.heading("title_id", text="ID / Código")
        tree.heading("region", text="Región")
        tree.heading("name", text="Nombre del Contenido / Juego")
        tree.heading("version", text="Versión")
        tree.heading("size", text="Tamaño")

        tree.column("title_id", width=110, anchor="center")
        tree.column("region", width=70, anchor="center")
        tree.column("name", width=550, anchor="w")
        tree.column("version", width=90, anchor="center")
        tree.column("size", width=100, anchor="center")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)

        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        tree.bind("<Double-1>", lambda event: self.start_download(tree, category))
        
        button_frame = ctk.CTkFrame(parent, fg_color="transparent")
        button_frame.pack(side="bottom", fill="x", padx=5, pady=(0, 5))

        btn = ctk.CTkButton(
            button_frame,
            text=f"⬇️ Descargar Elemento(s) Seleccionado(s) ({category})",
            command=lambda: self.start_download(tree, category)
        )
        btn.pack(side="left", fill="x", expand=True, padx=(0, 5))

        if category == "Juegos" and self.current_platform in GROUPED_DOWNLOAD_PLATFORMS:
            full_btn = ctk.CTkButton(
                button_frame,
                text="📦 Descargar juego completo",
                fg_color="#2d7d46",
                hover_color="#236638",
                command=lambda: self.start_complete_download_dialog(tree)
            )
            full_btn.pack(side="left", fill="x", expand=True, padx=(5, 0))

        self.trees[category] = tree

    def _build_downloads_view(self, parent):
        columns = ("game", "base", "updates", "dlcs", "themes", "avatars", "files", "status", "folder")
        table_frame = ctk.CTkFrame(parent, fg_color="transparent")
        table_frame.pack(side="top", fill="both", expand=True, padx=5, pady=5)

        self.downloads_tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")

        headings = {
            "game": "Juego",
            "base": "Base",
            "updates": "Última Update",
            "dlcs": "DLCs",
            "themes": "Temas",
            "avatars": "Avatares",
            "files": "Archivos",
            "status": "Estado",
            "folder": "Carpeta",
        }
        widths = {
            "game": 240,
            "base": 90,
            "updates": 120,
            "dlcs": 100,
            "themes": 100,
            "avatars": 100,
            "files": 80,
            "status": 110,
            "folder": 260,
        }
        for col in columns:
            self.downloads_tree.heading(col, text=headings[col])
            self.downloads_tree.column(col, width=widths[col], anchor="w" if col in ["game", "folder"] else "center")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.downloads_tree.yview)
        self.downloads_tree.configure(yscrollcommand=scrollbar.set)
        self.downloads_tree.bind("<Double-1>", lambda event: self.open_selected_library_details())
        self.downloads_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_frame.pack(side="bottom", fill="x", padx=5, pady=5)

        refresh_btn = ctk.CTkButton(btn_frame, text="🔄 Actualizar descargas", command=self.refresh_downloads_view)
        refresh_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        complete_btn = ctk.CTkButton(
            btn_frame,
            text="🧩 Completar biblioteca",
            fg_color="#2d7d46",
            hover_color="#236638",
            command=self.start_complete_library_dialog
        )
        complete_btn.pack(side="left", fill="x", expand=True, padx=4)

        details_btn = ctk.CTkButton(btn_frame, text="🔎 Detalles", command=self.open_selected_library_details)
        details_btn.pack(side="left", fill="x", expand=True, padx=4)

        missing_btn = ctk.CTkButton(btn_frame, text="📋 Faltantes", command=self.open_global_missing_dialog)
        missing_btn.pack(side="left", fill="x", expand=True, padx=4)

        verify_btn = ctk.CTkButton(btn_frame, text="✅ Verificar", command=self.verify_library_integrity)
        verify_btn.pack(side="left", fill="x", expand=True, padx=4)

        repair_btn = ctk.CTkButton(btn_frame, text="🛠️ Reparar corruptos", command=self.repair_corrupt_downloads)
        repair_btn.pack(side="left", fill="x", expand=True, padx=4)

        clear_btn = ctk.CTkButton(
            btn_frame,
            text="🧹 Limpiar descargas",
            fg_color="#7d2d2d",
            hover_color="#662323",
            command=self.clear_downloads_for_current_platform
        )
        clear_btn.pack(side="left", fill="x", expand=True, padx=4)

        open_btn = ctk.CTkButton(btn_frame, text="📂 Abrir carpeta Descargas", command=self.open_downloads_folder)
        open_btn.pack(side="left", fill="x", expand=True, padx=(4, 0))

    def _build_queue_view(self, parent):
        columns = ("id", "platform", "category", "title", "status", "progress", "speed", "folder")
        table_frame = ctk.CTkFrame(parent, fg_color="transparent")
        table_frame.pack(side="top", fill="both", expand=True, padx=5, pady=5)

        self.queue_tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")

        headings = {
            "id": "ID",
            "platform": "Plataforma",
            "category": "Tipo",
            "title": "Contenido",
            "status": "Estado",
            "progress": "Progreso",
            "speed": "Velocidad",
            "folder": "Destino",
        }
        widths = {
            "id": 55,
            "platform": 80,
            "category": 90,
            "title": 330,
            "status": 100,
            "progress": 90,
            "speed": 140,
            "folder": 300,
        }
        for col in columns:
            self.queue_tree.heading(col, text=headings[col])
            self.queue_tree.column(col, width=widths[col], anchor="w" if col in ["title", "folder"] else "center")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=scrollbar.set)
        self.queue_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_frame.pack(side="bottom", fill="x", padx=5, pady=5)

        ctk.CTkButton(btn_frame, text="⏸️ Pausar", command=self.pause_selected_tasks).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(btn_frame, text="▶️ Reanudar", command=self.resume_selected_tasks).pack(side="left", fill="x", expand=True, padx=4)
        ctk.CTkButton(btn_frame, text="🔁 Reintentar", command=self.retry_selected_tasks).pack(side="left", fill="x", expand=True, padx=4)
        ctk.CTkButton(btn_frame, text="✖️ Cancelar", fg_color="#7d2d2d", hover_color="#662323", command=self.cancel_selected_tasks).pack(side="left", fill="x", expand=True, padx=(4, 0))
        ctk.CTkButton(btn_frame, text="🧹 Limpiar cola", fg_color="#7d2d2d", hover_color="#662323", command=self.clear_queue).pack(side="left", fill="x", expand=True, padx=(4, 0))

        self.refresh_queue_view()

    def _build_history_view(self, parent):
        columns = ("created_at", "action", "platform", "name", "status", "details")
        table_frame = ctk.CTkFrame(parent, fg_color="transparent")
        table_frame.pack(side="top", fill="both", expand=True, padx=5, pady=5)

        self.history_tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "created_at": "Fecha",
            "action": "Acción",
            "platform": "Plataforma",
            "name": "Elemento",
            "status": "Estado",
            "details": "Detalles",
        }
        widths = {"created_at": 150, "action": 150, "platform": 90, "name": 300, "status": 100, "details": 520}
        for col in columns:
            self.history_tree.heading(col, text=headings[col])
            self.history_tree.column(col, width=widths[col], anchor="w" if col in {"name", "details"} else "center")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=scrollbar.set)
        self.history_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_frame.pack(side="bottom", fill="x", padx=5, pady=5)
        ctk.CTkButton(btn_frame, text="🔄 Actualizar historial", command=self.refresh_history_view).pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkButton(btn_frame, text="🧹 Limpiar historial", fg_color="#7d2d2d", hover_color="#662323", command=self.clear_history).pack(side="left", fill="x", expand=True, padx=(5, 0))
        self.refresh_history_view()

    def reset_catalog(self):
        """Vacía el catálogo en memoria y sus índices auxiliares."""
        self.catalog = {
            platform: {category: [] for category in CONTENT_ORDER}
            for platform in PLATFORM_CATALOGS
        }
        # catalog_item_key(item) -> posición dentro de self.catalog[platform][category].
        # La clave ya incluye plataforma y categoría, así que un único índice basta.
        self.catalog_index = {}
        self.content_by_url = {}
        self.content_by_tag = {}
        self.data_store = self.catalog[self.current_platform]

    def add_content_item(
        self,
        platform,
        category,
        title_id,
        region,
        name,
        version,
        size,
        url,
        content_id="",
        license_value="",
        sha256="",
        required_fw="",
        original_name="",
        item_type=""
    ):
        item = ContentItem(
            category=category,
            title_id=title_id,
            region=region,
            name=name,
            version=version,
            size=size,
            url=url,
            content_id=content_id,
            platform=platform,
            license_value=license_value,
            sha256=sha256,
            required_fw=required_fw,
            original_name=original_name,
            item_type=item_type
        )
        items = self.catalog[platform][category]
        key = catalog_item_key(item)
        index = self.catalog_index.get(key)

        if index is None:
            self.catalog_index[key] = len(items)
            items.append(item)
        else:
            existing = items[index]
            if catalog_item_score(item) <= catalog_item_score(existing):
                return existing
            items[index] = item

        if is_valid_download_url(item.url):
            self.content_by_url[item.url] = item
        self.content_by_tag[self.catalog_item_tag(item)] = item
        return item

    def catalog_item_tag(self, item):
        return "|".join(str(part) for part in catalog_item_key(item))

    def header_value(self, row, header, *names):
        for name in names:
            index = header.get(name.lower())
            if index is not None and index < len(row):
                return row[index].strip()
        return ""

    def row_pkg_url(self, row, header):
        if header:
            for name in ("pkg direct link", "update url", "download url", "url"):
                value = self.header_value(row, header, name)
                if is_valid_download_url(value):
                    return value
            return ""
        url_index = next((i for i, col in enumerate(row) if col.strip().startswith(("http://", "https://"))), None)
        return row[url_index].strip() if url_index is not None else ""

    def parse_catalog_row(self, platform, category, row, header=None):
        if not row:
            return None

        if header is None and row[0].strip().lower() in ["title id", "id", "title_id"]:
            return None

        url = self.row_pkg_url(row, header)
        title_id = self.header_value(row, header, "title id") if header else row[0].strip()
        region = self.header_value(row, header, "region") if header else ""
        name = self.header_value(row, header, "name") if header else ""
        version = "Base"
        content_id = self.header_value(row, header, "content id") if header else ""
        license_value = self.header_value(row, header, "zrif", "rap") if header else ""
        file_size = self.header_value(row, header, "file size") if header else ""
        sha256 = self.header_value(row, header, "sha256") if header else ""
        required_fw = self.header_value(row, header, "required fw", "required fw version") if header else ""
        original_name = self.header_value(row, header, "original name") if header else ""
        item_type = self.header_value(row, header, "type") if header else ""

        if platform == "PS3" and category == "Updates" and not header:
            title_id = row[0].strip()
            name = row[1].strip() if len(row) > 1 else f"Actualización ({title_id})"
            version = row[2].strip() if len(row) > 2 else "v01.00"
        elif category == "Updates":
            version = self.header_value(row, header, "update version")
            if version:
                version = version if version.lower().startswith("v") else f"v{version}"
            else:
                version = extract_version_from_text(name, "v01.00")

        if platform == "PSP" and category == "Juegos" and header:
            name = self.header_value(row, header, "name")

        if not name and len(row) > 1:
            name = row[1].strip()
        if not region:
            region = auto_detect_region(title_id)
        if not name or re.match(r'^[a-fA-F0-9]{15,}', name):
            name = f"Contenido ({title_id})"

        clean_name, name_version = split_name_and_version(name, version)
        if category != "Updates" or version == "Base":
            version = name_version

        size_str = format_bytes(file_size) if file_size.isdigit() else "Sin tamaño"
        if size_str == "Sin tamaño" and url:
            size_match = re.search(r'\.pkg(\d+)$', url, re.IGNORECASE)
            size_str = format_bytes(size_match.group(1)) if size_match else "Sin tamaño"
        if not url:
            size_str = "No disponible"

        return {
            "platform": platform,
            "category": category,
            "title_id": title_id,
            "region": region,
            "name": clean_name,
            "version": version,
            "size": size_str,
            "url": url,
            "content_id": content_id,
            "license_value": license_value,
            "sha256": sha256,
            "required_fw": required_fw,
            "original_name": original_name,
            "item_type": item_type,
        }

    def load_tsv_catalog(self, platform, category, file_name):
        file_path = data_path(file_name)
        if not os.path.exists(file_path):
            return

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f, delimiter="\t")
            first_row = next(reader, None)
            if not first_row:
                return

            has_header = first_row[0].strip().lower() in ["title id", "id", "title_id"]
            header = {name.strip().lower(): index for index, name in enumerate(first_row)} if has_header else None
            rows = reader if has_header else [first_row, *reader]

            for row in rows:
                parsed = self.parse_catalog_row(platform, category, row, header)
                if parsed:
                    self.add_content_item(**parsed)

    def catalog_files_metadata(self):
        metadata = {}
        for files in PLATFORM_CATALOGS.values():
            for file_name in files.values():
                path = data_path(file_name)
                metadata[file_name] = {
                    "mtime": os.path.getmtime(path) if os.path.exists(path) else 0,
                    "size": os.path.getsize(path) if os.path.exists(path) else 0,
                }
        return metadata

    def init_catalog_db(self):
        with sqlite3.connect(CATALOG_DB_PATH) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            user_version = conn.execute("PRAGMA user_version").fetchone()[0]
            if user_version > 1:
                logging.warning("SQLite schema más nuevo de lo esperado: %s", user_version)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS catalog_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title_id TEXT,
                    region TEXT,
                    name TEXT,
                    version TEXT,
                    size TEXT,
                    size_bytes INTEGER DEFAULT 0,
                    url TEXT,
                    content_id TEXT,
                    license_value TEXT,
                    sha256 TEXT,
                    required_fw TEXT,
                    original_name TEXT,
                    item_type TEXT,
                    normalized_name TEXT,
                    UNIQUE(platform, category, title_id, version, url)
                )
            """)
            conn.execute("PRAGMA user_version=1")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_platform_category ON catalog_items(platform, category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_title_id ON catalog_items(title_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_normalized_name ON catalog_items(normalized_name)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS catalog_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS action_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    action TEXT NOT NULL,
                    platform TEXT,
                    category TEXT,
                    name TEXT,
                    status TEXT,
                    details TEXT
                )
            """)

    def catalog_db_is_current(self):
        if not os.path.exists(CATALOG_DB_PATH):
            return False
        self.init_catalog_db()
        current = self.catalog_files_metadata()
        with sqlite3.connect(CATALOG_DB_PATH) as conn:
            row = conn.execute("SELECT value FROM catalog_meta WHERE key='tsv_metadata'").fetchone()
            parser_row = conn.execute("SELECT value FROM catalog_meta WHERE key='parser_version'").fetchone()
            count = conn.execute("SELECT COUNT(*) FROM catalog_items").fetchone()[0]
        if not row or not count:
            return False
        if not parser_row or parser_row[0] != CATALOG_PARSER_VERSION:
            return False
        try:
            return json.loads(row[0]) == current
        except json.JSONDecodeError:
            return False

    def save_catalog_to_db(self):
        self.init_catalog_db()
        metadata = self.catalog_files_metadata()
        with sqlite3.connect(CATALOG_DB_PATH) as conn:
            conn.execute("DELETE FROM catalog_items")
            rows = []
            for platform, categories in self.catalog.items():
                for category, items in categories.items():
                    for item in items:
                        rows.append((
                            platform, category, item.title_id, item.region, item.name, item.version,
                            item.size, parse_size_to_bytes(item.size), item.url, item.content_id,
                            item.license_value, item.sha256, item.required_fw, item.original_name,
                            item.item_type, normalize_title(item.name)
                        ))
            conn.executemany("""
                INSERT OR REPLACE INTO catalog_items (
                    platform, category, title_id, region, name, version, size, size_bytes,
                    url, content_id, license_value, sha256, required_fw, original_name,
                    item_type, normalized_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
            conn.execute(
                "INSERT OR REPLACE INTO catalog_meta(key, value) VALUES('tsv_metadata', ?)",
                (json.dumps(metadata, sort_keys=True),)
            )
            conn.execute(
                "INSERT OR REPLACE INTO catalog_meta(key, value) VALUES('rebuilt_at', ?)",
                (datetime.now().isoformat(timespec="seconds"),)
            )
            conn.execute(
                "INSERT OR REPLACE INTO catalog_meta(key, value) VALUES('parser_version', ?)",
                (CATALOG_PARSER_VERSION,)
            )
        logging.info("SQLite reconstruido: %d elemento(s)", len(rows))

    def load_catalog_from_db(self):
        self.init_catalog_db()
        self.reset_catalog()
        with sqlite3.connect(CATALOG_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT platform, category, title_id, region, name, version, size, url,
                       content_id, license_value, sha256, required_fw, original_name, item_type
                FROM catalog_items
                ORDER BY id
            """).fetchall()
        for row in rows:
            self.add_content_item(
                platform=row["platform"],
                category=row["category"],
                title_id=row["title_id"] or "",
                region=row["region"] or "",
                name=row["name"] or "",
                version=row["version"] or "",
                size=row["size"] or "",
                url=row["url"] or "",
                content_id=row["content_id"] or "",
                license_value=row["license_value"] or "",
                sha256=row["sha256"] or "",
                required_fw=row["required_fw"] or "",
                original_name=row["original_name"] or "",
                item_type=row["item_type"] or "",
            )

    def record_history(self, action, platform="", category="", name="", status="", details=None):
        self.init_catalog_db()
        with sqlite3.connect(CATALOG_DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO action_history(created_at, action, platform, category, name, status, details)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now().isoformat(timespec="seconds"),
                    action,
                    platform,
                    category,
                    name,
                    status,
                    json.dumps(details or {}, ensure_ascii=False),
                )
            )
        self.after(0, self.refresh_history_view)

    def history_report_rows(self, limit=500):
        self.init_catalog_db()
        with sqlite3.connect(CATALOG_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT created_at, action, platform, category, name, status, details
                FROM action_history
                ORDER BY id DESC
                LIMIT ?
            """, (limit,)).fetchall()
        return [dict(row) for row in rows]

    def refresh_history_view(self):
        if not hasattr(self, "history_tree"):
            return
        self.history_tree.delete(*self.history_tree.get_children())
        for row in self.history_report_rows():
            self.history_tree.insert(
                "",
                "end",
                values=(
                    row.get("created_at", ""),
                    row.get("action", ""),
                    row.get("platform", ""),
                    row.get("name", ""),
                    row.get("status", ""),
                    row.get("details", ""),
                )
            )

    def clear_history(self):
        if not messagebox.askyesno("Limpiar historial", "¿Quieres borrar todo el historial de acciones?"):
            return
        self.init_catalog_db()
        with sqlite3.connect(CATALOG_DB_PATH) as conn:
            conn.execute("DELETE FROM action_history")
        self.refresh_history_view()
        self.status_label.configure(text="Historial limpiado")

    def load_all_data(self, populate=True):
        if self.catalog_db_is_current():
            self.load_catalog_from_db()
        else:
            self.reset_catalog()
            for platform, files in PLATFORM_CATALOGS.items():
                for category, file_name in files.items():
                    self.load_tsv_catalog(platform, category, file_name)
            self.save_catalog_to_db()

        self.data_store = self.catalog[self.current_platform]
        if populate:
            self.populate_trees()

    def load_catalog_sources(self):
        def build_source_url(base_url, file_name):
            source_name = "PS1_GAMES.tsv" if "vitawiki.xyz" in base_url.lower() and file_name == "PSX_GAMES.tsv" else file_name
            return f"{base_url.rstrip('/')}/{source_name}"

        default_sources = {
            file_name: {
                "primary": build_source_url(
                    self.app_config.get("catalog_primary_base_url", DATABASE_TSV_BASE_URL),
                    file_name,
                ),
                "fallbacks": [
                    build_source_url(base, file_name)
                    for base in self.app_config.get("catalog_fallback_base_urls", [])
                    if isinstance(base, str) and base.strip()
                ],
            }
            for files in PLATFORM_CATALOGS.values()
            for file_name in files.values()
        }
        if not os.path.exists(CATALOG_SOURCES_PATH):
            return default_sources
        try:
            with open(CATALOG_SOURCES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return default_sources
            primary_base_url = data.get("primary_base_url")
            fallback_base_urls = data.get("fallback_base_urls")
            if isinstance(primary_base_url, str) and primary_base_url.strip():
                for file_name in default_sources:
                    default_sources[file_name]["primary"] = build_source_url(primary_base_url, file_name)
            if isinstance(fallback_base_urls, list):
                for file_name in default_sources:
                    default_sources[file_name]["fallbacks"] = [
                        build_source_url(base, file_name)
                        for base in fallback_base_urls
                        if isinstance(base, str) and base.strip()
                    ]
            raw_sources = data.get("sources", data)
            for file_name, config in raw_sources.items():
                safe_name = os.path.basename(file_name)
                if safe_name not in default_sources:
                    continue
                if isinstance(config, str):
                    default_sources[safe_name]["primary"] = config
                elif isinstance(config, dict):
                    if config.get("primary"):
                        default_sources[safe_name]["primary"] = config["primary"]
                    if isinstance(config.get("fallbacks"), list):
                        default_sources[safe_name]["fallbacks"] = config["fallbacks"]
            return default_sources
        except (json.JSONDecodeError, OSError):
            return default_sources

    def validate_catalog_file(self, file_path, platform, category, current_count=0):
        parsed = 0
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.reader(f, delimiter="\t")
                first_row = next(reader, None)
                if not first_row:
                    return False, 0, "catálogo vacío"
                has_header = first_row[0].strip().lower() in ["title id", "id", "title_id"]
                header = {name.strip().lower(): index for index, name in enumerate(first_row)} if has_header else None
                rows = reader if has_header else [first_row, *reader]
                for row in rows:
                    parsed_row = self.parse_catalog_row(platform, category, row, header)
                    if parsed_row and is_valid_download_url(parsed_row.get("url")):
                        parsed += 1
        except OSError as e:
            return False, 0, str(e)

        if parsed == 0:
            return False, parsed, "sin filas válidas con URL"
        if current_count >= 50 and parsed < max(10, int(current_count * 0.25)):
            return False, parsed, f"demasiado pequeño frente al catálogo actual ({parsed}/{current_count})"
        return True, parsed, ""

    def save_catalog_state(self, state):
        with open(CATALOG_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

    def load_catalog_state(self):
        if not os.path.exists(CATALOG_STATE_PATH):
            return {}
        try:
            with open(CATALOG_STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def update_catalogs_from_sources(self):
        if self.catalog_update_running:
            self.status_label.configure(text="Actualización de catálogos ya en curso...")
            return
        sources = self.load_catalog_sources()
        self.catalog_update_running = True
        self.set_busy_state("Actualizando catálogos desde las fuentes configuradas...")
        logging.info("Actualización de catálogos iniciada: %d fuente(s)", len(sources))
        threading.Thread(target=self._update_catalogs_worker, args=(sources,), daemon=True).start()

    def maybe_update_catalogs_on_start(self):
        days = int(self.app_config.get("catalog_update_interval_days", 0) or 0)
        if days <= 0:
            return
        state = self.load_catalog_state()
        meta = state.get(CATALOG_STATE_META_KEY, {}) if isinstance(state.get(CATALOG_STATE_META_KEY), dict) else {}
        last_check_value = meta.get("last_catalog_check_at")
        if last_check_value:
            try:
                last_check = datetime.fromisoformat(last_check_value)
                age_days = (datetime.now() - last_check).days
                if age_days < days:
                    logging.info("Auto-actualización omitida: última comprobación hace %d día(s)", age_days)
                    return
            except ValueError:
                logging.warning("Fecha last_catalog_check_at inválida: %s", last_check_value)

        last_values = [
            row.get("updated_at")
            for key, row in state.items()
            if key != CATALOG_STATE_META_KEY and isinstance(row, dict) and row.get("updated_at")
        ]
        if not last_values:
            self.update_catalogs_from_sources()
            return
        try:
            last_update = max(datetime.fromisoformat(value) for value in last_values)
        except ValueError:
            self.update_catalogs_from_sources()
            return
        age_days = (datetime.now() - last_update).days
        if age_days >= days:
            self.update_catalogs_from_sources()
        else:
            meta["last_catalog_check_at"] = last_update.isoformat(timespec="seconds")
            state[CATALOG_STATE_META_KEY] = meta
            self.save_catalog_state(state)

    def _update_catalogs_worker(self, sources):
        updated = []
        failed = []
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        state = self.load_catalog_state()

        known_files = {
            file_name: (platform, category)
            for platform, files in PLATFORM_CATALOGS.items()
            for category, file_name in files.items()
        }

        for file_name, source_config in sources.items():
            safe_name = os.path.basename(file_name)
            if safe_name not in known_files:
                failed.append(f"{safe_name}: archivo no reconocido")
                continue
            urls = []
            if isinstance(source_config, str):
                urls.append(source_config)
            elif isinstance(source_config, dict):
                urls.append(source_config.get("primary", ""))
                urls.extend(source_config.get("fallbacks", []))
            urls = list(dict.fromkeys(
                url for url in urls
                if isinstance(url, str) and url.startswith(("http://", "https://"))
            ))

            target_path = data_path(safe_name)
            backup_path = os.path.join(CATALOG_BACKUP_DIR, f"{timestamp}_{safe_name}")
            temp_path = target_path + ".tmp"
            platform, category = known_files[safe_name]
            current_count = len(self.catalog.get(platform, {}).get(category, []))
            last_error = "sin URLs válidas"

            for url in urls:
                try:
                    response = requests.get(url, timeout=30)
                    response.raise_for_status()
                    with open(temp_path, "wb") as f:
                        f.write(response.content)
                    valid, parsed, reason = self.validate_catalog_file(temp_path, platform, category, current_count)
                    if not valid:
                        last_error = f"{url}: {reason}"
                        os.remove(temp_path)
                        logging.warning("Catálogo rechazado %s desde %s: %s", safe_name, url, reason)
                        continue
                    if os.path.exists(target_path):
                        shutil.copy2(target_path, backup_path)
                    os.replace(temp_path, target_path)
                    state[safe_name] = {
                        "source": url,
                        "updated_at": datetime.now().isoformat(timespec="seconds"),
                        "backup": backup_path if os.path.exists(backup_path) else "",
                        "bytes": len(response.content),
                        "rows": parsed,
                    }
                    updated.append(safe_name)
                    self.record_history("catalog_update", platform, category, safe_name, "updated", {"source": url, "rows": parsed})
                    logging.info("Catálogo actualizado: %s desde %s", safe_name, url)
                    break
                except Exception as e:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    last_error = f"{url}: {e}"
                    logging.exception("Error actualizando catálogo %s: %s", safe_name, e)
            else:
                failed.append(f"{safe_name}: {last_error}")
                self.record_history("catalog_update", platform, category, safe_name, "failed", {"error": last_error})

        meta = state.get(CATALOG_STATE_META_KEY, {}) if isinstance(state.get(CATALOG_STATE_META_KEY), dict) else {}
        now_value = datetime.now().isoformat(timespec="seconds")
        meta["last_catalog_check_at"] = now_value
        if updated:
            meta["last_successful_catalog_update_at"] = now_value
        state[CATALOG_STATE_META_KEY] = meta
        self.save_catalog_state(state)
        self.load_all_data(populate=False)
        message = f"Actualizados: {len(updated)}"
        if failed:
            message += f"\nFallidos: {len(failed)}\n" + "\n".join(failed[:8])
        self.after(0, lambda: self.finish_catalog_update(message))

    def finish_catalog_update(self, message):
        self.catalog_update_running = False
        self.data_store = self.catalog[self.current_platform]
        self.populate_trees()
        self.refresh_downloads_view()
        self.refresh_queue_view()
        self.clear_busy_state("Estado: Listo")
        messagebox.showinfo("Actualizar catálogos", message)

    def catalog_source_summary(self):
        sources = self.load_catalog_sources()
        primary_values = [config.get("primary", "") for config in sources.values() if isinstance(config, dict)]
        primary = primary_values[0] if primary_values else self.app_config.get("catalog_primary_base_url", "")
        if "PSN-Killer-Database" in primary:
            source_name = "PSN-Killer-Database"
        elif "nopaystation.com" in primary:
            source_name = "NoPayStation"
        elif "vitawiki.xyz" in primary:
            source_name = "VitaWiki"
        else:
            source_name = primary or "Personalizada"
        return source_name, primary

    def open_about_dialog(self):
        source_name, source_url = self.catalog_source_summary()
        messagebox.showinfo(
            "Acerca de PSN Killer Global",
            (
                f"PSN Killer Global v{APP_VERSION}\n\n"
                "Herramienta de preservación y descarga de catálogos PSN para PS3, PSP, PS Vita, PSX y PSM.\n\n"
                "Repositorio principal:\n"
                "https://github.com/ruvelro/PSN-Killer-Global\n\n"
                "Catálogo activo:\n"
                f"{source_name}\n{source_url}\n\n"
                "Fuentes compatibles: PSN-Killer-Database, NoPayStation, VitaWiki y mirrors personalizados."
            )
        )

    def open_settings_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Configuración")
        dialog.geometry("680x500")
        dialog.transient(self)
        dialog.grab_set()

        frame = ctk.CTkFrame(dialog)
        frame.pack(fill="both", expand=True, padx=15, pady=15)

        ctk.CTkLabel(frame, text="Carpeta de descargas", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(10, 2))
        downloads_var = tk.StringVar(value=self.app_config.get("downloads_dir", DOWNLOADS_DIR))
        downloads_row = ctk.CTkFrame(frame, fg_color="transparent")
        downloads_row.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkEntry(downloads_row, textvariable=downloads_var).pack(side="left", fill="x", expand=True, padx=(0, 6))

        def choose_downloads_dir():
            selected = filedialog.askdirectory(initialdir=downloads_var.get() or BASE_DIR)
            if selected:
                downloads_var.set(selected)

        ctk.CTkButton(downloads_row, text="Elegir", width=90, command=choose_downloads_dir).pack(side="right")

        ctk.CTkLabel(frame, text="Descargas simultáneas", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(8, 2))
        active_var = tk.StringVar(value=str(self.max_active_downloads))
        ctk.CTkEntry(frame, textvariable=active_var).pack(fill="x", padx=10, pady=(0, 8))

        ctk.CTkLabel(frame, text="Hilos por archivo", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(8, 2))
        threads_var = tk.StringVar(value=str(self.threads_per_download))
        ctk.CTkEntry(frame, textvariable=threads_var).pack(fill="x", padx=10, pady=(0, 8))

        auto_resume_var = tk.BooleanVar(value=bool(self.app_config.get("auto_resume_queue")))
        ctk.CTkCheckBox(frame, text="Reanudar automáticamente la cola al abrir", variable=auto_resume_var).pack(anchor="w", padx=10, pady=(8, 8))

        ctk.CTkLabel(frame, text="Actualizar catálogos cada N días (0 = manual)", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(4, 2))
        update_days_var = tk.StringVar(value=str(self.app_config.get("catalog_update_interval_days", 0)))
        ctk.CTkEntry(frame, textvariable=update_days_var).pack(fill="x", padx=10, pady=(0, 8))

        source_name, source_url = self.catalog_source_summary()
        ctk.CTkLabel(frame, text=f"Fuente activa: {source_name}", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(4, 2))
        source_hint = ctk.CTkLabel(
            frame,
            text=f"{source_url}\nConfig editable: {CATALOG_SOURCES_PATH}",
            text_color="#b0b0b0",
            wraplength=620
        )
        source_hint.pack(fill="x", padx=10, pady=(4, 8))

        source_row = ctk.CTkFrame(frame, fg_color="transparent")
        source_row.pack(fill="x", padx=10, pady=(0, 8))

        def open_path(path):
            if sys.platform == "darwin":
                subprocess.Popen(["open", path])
            elif os.name == "nt":
                os.startfile(path)
            else:
                subprocess.Popen(["xdg-open", path])

        def open_sources_file():
            if not os.path.exists(CATALOG_SOURCES_PATH):
                shutil.copy2(os.path.join(BASE_DIR, "catalog_sources.example.json"), CATALOG_SOURCES_PATH)
            open_path(CATALOG_SOURCES_PATH)

        ctk.CTkButton(source_row, text="Abrir fuentes", command=open_sources_file).pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkButton(source_row, text="Abrir logs", command=lambda: open_path(LOG_DIR)).pack(side="left", fill="x", expand=True, padx=(5, 0))
        ctk.CTkButton(source_row, text="Importar PKGs", command=self.import_existing_folder).pack(side="left", fill="x", expand=True, padx=(5, 0))

        ctk.CTkLabel(frame, text="Perfil de descarga", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(4, 2))
        profile_var = tk.StringVar(value=self.app_config.get("download_profile", "Completo seguro"))
        ctk.CTkComboBox(frame, values=list(DOWNLOAD_PROFILES.keys()), variable=profile_var).pack(fill="x", padx=10, pady=(0, 8))

        button_bar = ctk.CTkFrame(dialog)
        button_bar.pack(fill="x", padx=15, pady=(0, 15))

        def save_settings():
            global DOWNLOADS_DIR
            try:
                max_active = max(1, min(8, int(active_var.get())))
                threads = max(1, min(32, int(threads_var.get())))
                update_days = max(0, int(update_days_var.get()))
            except ValueError:
                messagebox.showerror("Configuración", "Los valores numéricos no son válidos.")
                return

            downloads_dir = downloads_var.get().strip() or DOWNLOADS_DIR
            os.makedirs(downloads_dir, exist_ok=True)
            DOWNLOADS_DIR = downloads_dir
            self.app_config.update({
                "downloads_dir": downloads_dir,
                "max_active_downloads": max_active,
                "threads_per_download": threads,
                "auto_resume_queue": bool(auto_resume_var.get()),
                "catalog_update_interval_days": update_days,
                "download_profile": profile_var.get(),
            })
            self.max_active_downloads = max_active
            self.threads_per_download = threads
            self.save_app_config()
            self.refresh_downloads_view()
            self.schedule_downloads()
            dialog.destroy()

        ctk.CTkButton(button_bar, text="Guardar", command=save_settings).pack(side="right", padx=5)
        ctk.CTkButton(button_bar, text="Cancelar", fg_color="#555555", command=dialog.destroy).pack(side="right", padx=5)

    def update_summary_count(self):
        counts = {cat: len(self.trees[cat].get_children()) for cat in self.active_categories()}
        total = sum(counts.values())

        labels = {
            "Juegos": "🎮 Juegos",
            "Updates": "🔄 Updates",
            "DLCs": "📦 DLCs",
            "Temas": "🎨 Temas",
            "Avatares": "👤 Avatares",
            "Demos": "🎮 Demos",
        }
        parts = [f"{labels.get(cat, cat)}: {counts[cat]:,}" for cat in self.active_categories()]
        parts.append(f"🌐 TOTAL {self.current_platform}: {total:,} elementos")
        summary_text = "  |  ".join(parts).replace(",", ".")

        self.count_label.configure(text=summary_text)

    def populate_trees(self):
        for cat in self.active_categories():
            items = self.data_store[cat]
            tree = self.trees[cat]
            tree.delete(*tree.get_children())
            for item in items:
                tree.insert(
                    "",
                    "end",
                    values=(item.title_id, item.region, item.name, item.version, item.size),
                    tags=(self.catalog_item_tag(item),)
                )
        
        self.update_summary_count()

    def filter_tables(self, event=None):
        query = self.search_entry.get().strip().lower()
        selected_region = self.region_combo.get()
        selected_status = self.status_filter_combo.get()
        selected_integrity = self.integrity_filter_combo.get()
        entries = list(self.merged_download_entries().values())

        for cat in self.active_categories():
            items = self.data_store[cat]
            tree = self.trees[cat]
            tree.delete(*tree.get_children())
            
            for item in items:
                title_id = item.title_id.lower()
                region = item.region
                game_name = item.name.lower()

                match_text = (query in title_id) or (query in game_name)
                match_region = (selected_region == "TODAS") or (region == selected_region)
                match_status = self.item_matches_status_filter(item, entries, selected_status)
                match_integrity = self.item_matches_integrity_filter(item, entries, selected_integrity)

                if match_text and match_region and match_status and match_integrity:
                    tree.insert(
                        "",
                        "end",
                        values=(item.title_id, item.region, item.name, item.version, item.size),
                        tags=(self.catalog_item_tag(item),)
                    )

        self.update_summary_count()

    def matching_download_entries_for_item(self, item, entries):
        return [
            entry for entry in entries
            if entry.get("platform", "PS3") == item.platform and same_catalog_item(item, entry)
        ]

    def item_matches_status_filter(self, item, entries, selected_status):
        if selected_status == "TODOS":
            return True
        matches = self.matching_download_entries_for_item(item, entries)
        statuses = {entry.get("status", "") for entry in matches}
        if selected_status == "NO DESCARGADO":
            return not matches
        if selected_status == "DESCARGADO":
            return "complete" in statuses
        if selected_status == "PENDIENTE":
            return bool(statuses & {"queued", "downloading", "paused"})
        if selected_status == "ERROR":
            return bool(statuses & {"error", "cancelled"})
        if selected_status == "CORRUPTO":
            return "corrupt" in statuses or any(entry.get("integrity") == "corrupt" for entry in matches)
        return True

    def item_matches_integrity_filter(self, item, entries, selected_integrity):
        if selected_integrity == "TODOS":
            return True
        matches = self.matching_download_entries_for_item(item, entries)
        if selected_integrity == "CON SHA256":
            return valid_sha256(item.sha256)
        if selected_integrity == "SIN SHA256":
            return not valid_sha256(item.sha256)
        if selected_integrity == "VERIFICADO":
            return any(entry.get("integrity") == "verified" for entry in matches)
        if selected_integrity == "CORRUPTO":
            return any(entry.get("integrity") == "corrupt" for entry in matches)
        return True

    def tree_item_to_content(self, tree, item_id, category):
        values = tree.item(item_id)["values"]
        tags = tree.item(item_id)["tags"]
        item_tag = tags[0] if tags else ""
        return self.content_by_tag.get(
            item_tag,
            ContentItem(category, values[0], values[1], values[2], values[3], values[4], "", platform=self.current_platform)
        )

    def update_is_latest(self, item, candidates):
        same_title_updates = [
            candidate for candidate in candidates
            if candidate.category == "Updates" and candidate.title_id == item.title_id
        ]
        if not same_title_updates:
            return False
        return item == max(same_title_updates, key=lambda candidate: version_tuple(candidate.version))

    def is_suggested_match(self, base_item, candidate):
        if candidate.platform != base_item.platform:
            return False
        if candidate.title_id == base_item.title_id:
            return False
        if not compatible_region(base_item.region, candidate.region):
            return False
        if has_number_conflict(base_item.name, candidate.name):
            return False

        base_tokens = meaningful_title_tokens(base_item.name)
        candidate_tokens = meaningful_title_tokens(candidate.name)
        if not base_tokens or not candidate_tokens:
            return False

        token_overlap = len(base_tokens & candidate_tokens) / len(base_tokens)
        return token_overlap >= 0.75 and title_similarity(base_item.name, candidate.name) >= 0.72

    def is_exact_related_match(self, base_item, candidate):
        if candidate.platform != base_item.platform:
            return False
        if candidate.title_id and candidate.title_id == base_item.title_id:
            return True

        title_id = base_item.title_id.upper()
        technical_fields = " ".join([
            candidate.content_id,
            candidate.original_name,
            candidate.url,
            candidate.name,
        ]).upper()
        return bool(title_id and title_id in technical_fields)

    def find_related_content(self, base_item):
        related = {"Juegos": [], "Updates": [], "DLCs": [], "Temas": [], "Avatares": []}
        base_copy = ContentItem(**{**base_item.__dict__, "match_type": "exact"})
        related["Juegos"].append(base_copy)

        for category in ["Updates", "DLCs", "Temas", "Avatares"]:
            for item in self.catalog[base_item.platform].get(category, []):
                if self.is_exact_related_match(base_item, item):
                    match_type = "exact"
                elif self.is_suggested_match(base_item, item):
                    match_type = "suggested"
                else:
                    continue

                item_copy = ContentItem(**{**item.__dict__, "match_type": match_type})
                related[category].append(item_copy)

        return related

    def item_selected_by_default(self, item, category, related):
        profile = DOWNLOAD_PROFILES.get(self.app_config.get("download_profile", "Completo seguro"), DOWNLOAD_PROFILES["Completo seguro"])
        if profile.get("require_sha256") and not valid_sha256(item.sha256):
            return False
        if category == "Juegos":
            return profile.get("base", True)
        if item.match_type != "exact":
            return profile.get("suggested", False)
        if category == "Updates":
            return True if not profile.get("latest_update", True) else self.update_is_latest(item, related["Updates"])
        return profile.get("exact_extras", True)

    def item_already_present(self, item, entries):
        return any(
            entry.get("status") == "complete" and same_catalog_item(item, entry)
            for entry in entries
        )

    def downloaded_base_items_for_platform(self, platform):
        entries = self.merged_download_entries()
        grouped = {}
        for entry in entries.values():
            if entry.get("platform", "PS3") != platform:
                continue
            grouped.setdefault(entry.get("game_key", ""), []).append(entry)

        base_items = []
        seen = set()
        for game_key, game_entries in grouped.items():
            base_title_id = next((entry.get("base_title_id", "") for entry in game_entries if entry.get("base_title_id")), "")
            game_name = game_entries[0].get("game_name") or game_key
            base_item = None
            if base_title_id:
                base_item = next((item for item in self.catalog[platform]["Juegos"] if item.title_id == base_title_id), None)
            if not base_item:
                base_item = next((item for item in self.catalog[platform]["Juegos"] if item.name == game_name), None)
            if not base_item:
                normalized = normalize_title(game_name)
                base_item = next((item for item in self.catalog[platform]["Juegos"] if normalize_title(item.name) == normalized), None)
            if base_item and base_item.url not in seen:
                seen.add(base_item.url)
                base_items.append(base_item)
        return base_items

    def missing_related_content(self, base_item):
        game_key = f"{sanitize_filename(base_item.name)} [{base_item.title_id}]"
        existing_entries = [
            entry for entry in self.merged_download_entries().values()
            if entry.get("platform", "PS3") == base_item.platform and entry.get("game_key") == game_key
        ]
        related = self.find_related_content(base_item)
        missing = {category: [] for category in RELATED_CATEGORIES}
        for category, items in related.items():
            for item in items:
                if category == "Juegos":
                    continue
                if category == "Updates" and item.match_type == "exact" and not self.update_is_latest(item, related["Updates"]):
                    continue
                if not self.item_already_present(item, existing_entries):
                    missing[category].append(item)
        return game_key, missing

    def start_complete_library_dialog(self):
        if self.current_platform not in GROUPED_DOWNLOAD_PLATFORMS:
            messagebox.showinfo("Completar biblioteca", "Esta función está disponible para PS3, PSP y PS Vita.")
            return

        proposals = []
        for base_item in self.downloaded_base_items_for_platform(self.current_platform):
            game_key, missing = self.missing_related_content(base_item)
            if any(missing.values()):
                proposals.append((base_item, game_key, missing))

        if not proposals:
            messagebox.showinfo("Completar biblioteca", "No he encontrado contenido relacionado pendiente para esta plataforma.")
            return

        self.open_related_selection_dialog(
            proposals,
            title=f"Completar biblioteca - {self.current_platform}",
            header_text=f"Contenido pendiente para {len(proposals)} juego(s) de {self.current_platform}",
            include_base=False
        )

    def open_selected_library_details(self):
        if not hasattr(self, "downloads_tree"):
            return
        selected = self.downloads_tree.selection()
        if not selected:
            messagebox.showinfo("Detalles", "Selecciona un juego en Descargas.")
            return
        values = self.downloads_tree.item(selected[0])["values"]
        if not values:
            return
        game_name = values[0]
        folder = values[-1]
        entries = [
            entry for entry in self.merged_download_entries().values()
            if entry.get("platform", "PS3") == self.current_platform
            and (entry.get("game_name") == game_name or entry.get("game_key") == game_name or os.path.dirname(entry.get("path", "")) == folder)
        ]
        if not entries:
            messagebox.showinfo("Detalles", "No he encontrado entradas para ese juego.")
            return

        base_title_id = next((entry.get("base_title_id", "") for entry in entries if entry.get("base_title_id")), "")
        base_item = next((item for item in self.catalog[self.current_platform]["Juegos"] if item.title_id == base_title_id), None)
        if not base_item:
            base_item = next((item for item in self.catalog[self.current_platform]["Juegos"] if item.name == game_name), None)

        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Detalles - {game_name}")
        dialog.geometry("980x620")
        dialog.transient(self)

        title = ctk.CTkLabel(dialog, text=f"{game_name} ({self.current_platform})", font=ctk.CTkFont(size=16, weight="bold"))
        title.pack(fill="x", padx=15, pady=(15, 5))

        columns = ("category", "title_id", "name", "version", "status", "integrity", "path")
        detail_tree = ttk.Treeview(dialog, columns=columns, show="headings", selectmode="browse")
        headings = {
            "category": "Tipo",
            "title_id": "Title ID",
            "name": "Nombre",
            "version": "Versión",
            "status": "Estado",
            "integrity": "SHA256",
            "path": "Ruta",
        }
        widths = {"category": 90, "title_id": 100, "name": 280, "version": 90, "status": 95, "integrity": 95, "path": 300}
        for col in columns:
            detail_tree.heading(col, text=headings[col])
            detail_tree.column(col, width=widths[col], anchor="w" if col in {"name", "path"} else "center")
        detail_tree.pack(fill="both", expand=True, padx=15, pady=10)

        for entry in sorted(entries, key=lambda e: (e.get("category", ""), e.get("name", ""))):
            detail_tree.insert(
                "",
                "end",
                values=(
                    entry.get("category", ""),
                    entry.get("title_id", ""),
                    entry.get("name", ""),
                    entry.get("version", ""),
                    entry.get("status", ""),
                    entry.get("integrity", ""),
                    entry.get("path", ""),
                )
            )

        button_bar = ctk.CTkFrame(dialog)
        button_bar.pack(fill="x", padx=15, pady=(0, 15))

        def complete_missing():
            if not base_item:
                messagebox.showinfo("Completar", "No he podido relacionar este juego con el catálogo.")
                return
            game_key, missing = self.missing_related_content(base_item)
            if not any(missing.values()):
                messagebox.showinfo("Completar", "No hay contenido pendiente detectado.")
                return
            dialog.destroy()
            self.open_related_selection_dialog(
                [(base_item, game_key, missing)],
                title=f"Completar - {base_item.name}",
                header_text=f"Contenido pendiente para {base_item.name}",
                include_base=False
            )

        def open_folder():
            if folder and os.path.exists(folder):
                if sys.platform == "darwin":
                    subprocess.Popen(["open", folder])
                elif os.name == "nt":
                    os.startfile(folder)
                else:
                    subprocess.Popen(["xdg-open", folder])

        ctk.CTkButton(button_bar, text="🧩 Completar faltantes", command=complete_missing).pack(side="left", padx=5)
        ctk.CTkButton(button_bar, text="📂 Abrir carpeta", command=open_folder).pack(side="left", padx=5)
        ctk.CTkButton(button_bar, text="Cerrar", fg_color="#555555", command=dialog.destroy).pack(side="right", padx=5)

    def global_missing_groups(self):
        proposals = []
        for base_item in self.downloaded_base_items_for_platform(self.current_platform):
            game_key, missing = self.missing_related_content(base_item)
            if any(missing.values()):
                proposals.append((base_item, game_key, missing))
        return proposals

    def open_global_missing_dialog(self):
        proposals = self.global_missing_groups()
        if not proposals:
            messagebox.showinfo("Faltantes", "No hay contenido pendiente detectado en esta plataforma.")
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Faltantes - {self.current_platform}")
        dialog.geometry("920x560")
        dialog.transient(self)

        columns = ("game", "updates", "dlcs", "themes", "avatars")
        tree = ttk.Treeview(dialog, columns=columns, show="headings", selectmode="extended")
        headings = {"game": "Juego", "updates": "Updates", "dlcs": "DLCs", "themes": "Temas", "avatars": "Avatares"}
        widths = {"game": 360, "updates": 120, "dlcs": 120, "themes": 120, "avatars": 120}
        for col in columns:
            tree.heading(col, text=headings[col])
            tree.column(col, width=widths[col], anchor="w" if col == "game" else "center")
        tree.pack(fill="both", expand=True, padx=15, pady=15)

        proposal_by_iid = {}
        for index, (base_item, game_key, missing) in enumerate(proposals):
            iid = str(index)
            proposal_by_iid[iid] = (base_item, game_key, missing)
            tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    base_item.name,
                    len(missing.get("Updates", [])),
                    len(missing.get("DLCs", [])),
                    len(missing.get("Temas", [])),
                    len(missing.get("Avatares", [])),
                )
            )

        button_bar = ctk.CTkFrame(dialog)
        button_bar.pack(fill="x", padx=15, pady=(0, 15))

        def complete_selected():
            selected = tree.selection()
            chosen = [proposal_by_iid[iid] for iid in selected] if selected else proposals
            dialog.destroy()
            self.open_related_selection_dialog(
                chosen,
                title=f"Descargar faltantes - {self.current_platform}",
                header_text=f"Faltantes seleccionados: {len(chosen)} juego(s)",
                include_base=False
            )

        ctk.CTkButton(button_bar, text="Descargar seleccionados", command=complete_selected).pack(side="left", padx=5)
        ctk.CTkButton(button_bar, text="Cerrar", fg_color="#555555", command=dialog.destroy).pack(side="right", padx=5)

    def verify_library_integrity(self):
        threading.Thread(target=self._verify_library_integrity_worker, daemon=True).start()

    def _verify_library_integrity_worker(self):
        checked = 0
        corrupt = 0
        entries = self.merged_download_entries()
        for key, entry in entries.items():
            if entry.get("platform", "PS3") != self.current_platform:
                continue
            path = entry.get("path", "")
            sha = entry.get("sha256", "")
            if not path or not os.path.exists(path) or not valid_sha256(sha):
                continue
            checked += 1
            actual = calculate_sha256(path)
            manifest_entry = self.download_manifest.get(key)
            if actual.lower() == sha.lower():
                if manifest_entry:
                    manifest_entry.update({"status": "complete", "integrity": "verified", "actual_sha256": actual, "verified_at": datetime.now().isoformat(timespec="seconds")})
            else:
                corrupt += 1
                if manifest_entry:
                    manifest_entry.update({"status": "corrupt", "integrity": "corrupt", "actual_sha256": actual, "verified_at": datetime.now().isoformat(timespec="seconds")})
        self.save_download_manifest()
        self.record_history("verify_library", self.current_platform, "", "Biblioteca", "complete", {"checked": checked, "corrupt": corrupt})
        self.after(0, self.refresh_downloads_view)
        self.after(0, lambda: messagebox.showinfo("Verificar biblioteca", f"Comprobados: {checked}\nCorruptos: {corrupt}"))

    def repair_corrupt_downloads(self):
        repaired = 0
        entries = self.merged_download_entries()
        for key, entry in entries.items():
            if entry.get("platform", "PS3") != self.current_platform:
                continue
            if entry.get("status") != "corrupt" and entry.get("integrity") != "corrupt":
                continue
            item = self.content_by_url.get(entry.get("url", ""))
            if not item:
                continue
            base_item = next((game for game in self.catalog[self.current_platform]["Juegos"] if game.title_id == entry.get("base_title_id")), item)
            path = entry.get("path") or os.path.join(DOWNLOADS_DIR, item.platform, category_folder(item.category), item_filename(item))
            self.register_manifest_entry(base_item, item, entry.get("game_key", item.name), path, "queued")
            self.enqueue_download(item.url, path, item.name, item.category, item.platform, base_item, item, entry.get("game_key", item.name))
            repaired += 1
        messagebox.showinfo("Reparar corruptos", f"Reenviados a la cola: {repaired}")

    def import_existing_folder(self):
        folder = filedialog.askdirectory(title="Importar carpeta con PKGs")
        if not folder:
            return
        imported = 0
        unmatched = 0
        all_items = [
            item
            for categories in self.catalog[self.current_platform].values()
            for item in categories
        ]
        by_filename = {item_filename(item).lower(): item for item in all_items}
        for root_dir, _dirs, files in os.walk(folder):
            for filename in files:
                if not filename.lower().endswith(".pkg"):
                    continue
                item = by_filename.get(filename.lower())
                if not item:
                    unmatched += 1
                    continue
                game_key = f"{sanitize_filename(item.name)} [{item.title_id}]"
                dest_dir = os.path.join(DOWNLOADS_DIR, item.platform, game_key, category_folder(item.category))
                os.makedirs(dest_dir, exist_ok=True)
                src_path = os.path.join(root_dir, filename)
                dest_path = unique_path(os.path.join(dest_dir, filename))
                shutil.copy2(src_path, dest_path)
                self.register_manifest_entry(item, item, game_key, dest_path, "complete")
                imported += 1
        self.record_history("import_folder", self.current_platform, "", folder, "complete", {"imported": imported, "unmatched": unmatched})
        self.refresh_downloads_view()
        messagebox.showinfo("Importar carpeta", f"Importados: {imported}\nSin identificar: {unmatched}")

    def start_complete_download_dialog(self, tree):
        selected_items = tree.selection()
        if not selected_items:
            messagebox.showwarning("Atención", "Selecciona uno o varios juegos para descargarlos completos.")
            return

        base_items = [self.tree_item_to_content(tree, item_id, "Juegos") for item_id in selected_items]
        related_groups = []
        for base_item in base_items:
            game_key = f"{sanitize_filename(base_item.name)} [{base_item.title_id}]"
            related_groups.append((base_item, game_key, self.find_related_content(base_item)))

        plural = "juego" if len(base_items) == 1 else "juegos"
        self.open_related_selection_dialog(
            related_groups,
            title=f"Descargar completo - {len(base_items)} {plural}",
            header_text=f"Contenido relacionado para {len(base_items)} {plural} seleccionados",
            include_base=True
        )

    def open_related_selection_dialog(self, related_groups, title, header_text, include_base=True):
        dialog = ctk.CTkToplevel(self)
        dialog.title(title)
        dialog.geometry("980x720")
        dialog.transient(self)
        dialog.grab_set()

        header = ctk.CTkLabel(
            dialog,
            text=header_text,
            font=ctk.CTkFont(size=16, weight="bold")
        )
        header.pack(fill="x", padx=15, pady=(15, 5))

        hint = ctk.CTkLabel(
            dialog,
            text="Los exactos por Title ID se marcan automáticamente. Los sugeridos por nombre aparecen desmarcados.",
            text_color="#b0b0b0"
        )
        hint.pack(fill="x", padx=15, pady=(0, 10))

        summary_label = ctk.CTkLabel(dialog, text="", text_color="#d7d7d7", wraplength=930)
        summary_label.pack(fill="x", padx=15, pady=(0, 8))

        scroll = ctk.CTkScrollableFrame(dialog)
        scroll.pack(fill="both", expand=True, padx=15, pady=5)

        checkbox_rows = []

        for base_item, game_key, related in related_groups:
            game_label = ctk.CTkLabel(
                scroll,
                text=f"{base_item.name} [{base_item.title_id}]",
                font=ctk.CTkFont(size=15, weight="bold"),
                text_color="#ffffff"
            )
            game_label.pack(fill="x", anchor="w", padx=5, pady=(14, 4))

            for category in RELATED_CATEGORIES:
                if category == "Juegos" and not include_base:
                    continue
                items = related.get(category, [])
                if not items:
                    continue

                category_label = ctk.CTkLabel(
                    scroll,
                    text=f"{category} ({len(items)})",
                    font=ctk.CTkFont(size=13, weight="bold")
                )
                category_label.pack(fill="x", anchor="w", padx=18, pady=(8, 2))

                for match_type in ["exact", "suggested"]:
                    match_items = [item for item in items if item.match_type == match_type]
                    if not match_items:
                        continue

                    label_text = "Exactos" if match_type == "exact" else "Sugeridos"
                    match_label = ctk.CTkLabel(scroll, text=label_text, text_color="#8fbce8" if match_type == "exact" else "#e0b15a")
                    match_label.pack(fill="x", anchor="w", padx=32, pady=(4, 1))

                    for item in match_items:
                        downloadable = is_valid_download_url(item.url)
                        var = tk.BooleanVar(value=downloadable and self.item_selected_by_default(item, category, related))
                        suffix = "" if downloadable else " - No descargable"
                        text = f"[{item.title_id} | {item.region}] {item.name} - {item.version} - {item.size}{suffix}"
                        checkbox = ctk.CTkCheckBox(scroll, text=text, variable=var, command=lambda: update_selection_summary())
                        if not downloadable:
                            checkbox.configure(state="disabled")
                        checkbox.pack(fill="x", anchor="w", padx=48, pady=2)
                        checkbox_rows.append((var, base_item, game_key, related, item))

        button_bar = ctk.CTkFrame(dialog)
        button_bar.pack(fill="x", padx=15, pady=15)

        def update_selection_summary():
            selected = [item for var, _base_item, _game_key, _related, item in checkbox_rows if var.get()]
            total_size = sum(parse_size_to_bytes(item.size) for item in selected)
            updates = sum(1 for item in selected if item.category == "Updates")
            dlcs = sum(1 for item in selected if item.category == "DLCs")
            themes = sum(1 for item in selected if item.category == "Temas")
            avatars = sum(1 for item in selected if item.category == "Avatares")
            suggested = sum(1 for item in selected if item.match_type == "suggested")
            folders = len({os.path.join(DOWNLOADS_DIR, base_item.platform, game_key) for var, base_item, game_key, _related, _item in checkbox_rows if var.get()})
            summary_label.configure(
                text=(
                    f"Seleccionado: {len(selected)} archivo(s) | "
                    f"Tamaño estimado: {format_total_size(total_size)} | "
                    f"Updates: {updates} | DLCs: {dlcs} | Temas: {themes} | Avatares: {avatars} | "
                    f"Sugeridos: {suggested} | Carpetas destino: {folders}"
                )
            )

        def mark_exact():
            for var, _base_item, _game_key, _related, item in checkbox_rows:
                var.set(item.match_type == "exact")
            update_selection_summary()

        def mark_all():
            for var, _base_item, _game_key, _related, _item in checkbox_rows:
                var.set(is_valid_download_url(_item.url))
            update_selection_summary()

        def mark_latest_updates():
            for var, _base_item, _game_key, related, item in checkbox_rows:
                var.set(item.category == "Juegos" or self.item_selected_by_default(item, item.category, related))
            update_selection_summary()

        def unmark_suggested():
            for var, _base_item, _game_key, _related, item in checkbox_rows:
                if item.match_type == "suggested":
                    var.set(False)
            update_selection_summary()

        def start_selected():
            selected_by_game = {}
            for var, base_item, game_key, _related, item in checkbox_rows:
                if var.get():
                    selected_by_game.setdefault(game_key, {"base": base_item, "items": []})
                    if is_valid_download_url(item.url):
                        selected_by_game[game_key]["items"].append(item)

            if not selected_by_game:
                messagebox.showwarning("Atención", "No hay contenido seleccionado para descargar.")
                return
            dialog.destroy()
            total_items = 0
            for game_key, group in selected_by_game.items():
                total_items += len(group["items"])
                self.start_grouped_downloads(group["base"], group["items"], game_key, refresh=False)
            self.status_label.configure(text=f"Descargas agrupadas añadidas a la cola: {total_items} elemento(s)")
            self.refresh_downloads_view()
            self.refresh_queue_view()

        ctk.CTkButton(button_bar, text="Marcar exactos", command=mark_exact).pack(side="left", padx=5)
        ctk.CTkButton(button_bar, text="Marcar todo visible", command=mark_all).pack(side="left", padx=5)
        ctk.CTkButton(button_bar, text="Solo últimas updates", command=mark_latest_updates).pack(side="left", padx=5)
        ctk.CTkButton(button_bar, text="Desmarcar sugeridos", command=unmark_suggested).pack(side="left", padx=5)
        ctk.CTkButton(button_bar, text="Descargar seleccionados", command=start_selected).pack(side="right", padx=5)
        ctk.CTkButton(button_bar, text="Cancelar", fg_color="#555555", command=dialog.destroy).pack(side="right", padx=5)
        update_selection_summary()

    def start_grouped_downloads(self, base_item, selected_items, game_key, refresh=True):
        game_dir = os.path.join(DOWNLOADS_DIR, base_item.platform, game_key)
        for folder in ["Base", "Updates", "DLCs", "Temas", "Avatares", "Demos"]:
            os.makedirs(os.path.join(game_dir, folder), exist_ok=True)

        for item in selected_items:
            if not is_valid_download_url(item.url):
                continue
            dest_dir = os.path.join(game_dir, category_folder(item.category))
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = unique_path(os.path.join(dest_dir, item_filename(item)))
            clean_url = re.sub(r'(\.pkg)\d+$', r'\1', item.url, flags=re.IGNORECASE)

            self.register_manifest_entry(base_item, item, game_key, dest_path, "queued")
            self.enqueue_download(clean_url, dest_path, item.name, item.category, item.platform, base_item, item, game_key)

        if refresh:
            self.status_label.configure(text=f"Descargas agrupadas añadidas a la cola: {len(selected_items)} elemento(s)")
            self.refresh_downloads_view()
            self.refresh_queue_view()

    def enqueue_download(self, url, dest_path, title, category, platform, base_item=None, manifest_item=None, game_key=""):
        with self.download_lock:
            for existing in self.download_tasks.values():
                same_url = existing.url and existing.url == url
                same_path = os.path.abspath(existing.dest_path) == os.path.abspath(dest_path)
                if existing.status in {"queued", "downloading", "paused"} and (same_url or same_path):
                    self.status_label.configure(text=f"Ya estaba en cola: {title}")
                    logging.info("Descarga duplicada omitida: %s", title)
                    return existing

            self.download_task_seq += 1
            task = DownloadTask(
                task_id=self.download_task_seq,
                url=url,
                dest_path=dest_path,
                title=title,
                platform=platform,
                category=category,
                base_item=base_item,
                manifest_item=manifest_item,
                game_key=game_key,
                created_at=datetime.now().isoformat(timespec="seconds")
            )
            self.download_tasks[task.task_id] = task
            self.download_order.append(task.task_id)

        self.save_queue_state()
        self.refresh_queue_view()
        self.schedule_downloads()
        return task

    def schedule_downloads(self):
        with self.download_lock:
            while self.active_downloads < self.max_active_downloads:
                next_task = next(
                    (self.download_tasks[task_id] for task_id in self.download_order if self.download_tasks[task_id].status == "queued"),
                    None
                )
                if not next_task:
                    break
                next_task.status = "downloading"
                self.active_downloads += 1
                self.running_task_ids.add(next_task.task_id)
                threading.Thread(target=self.run_download_task, args=(next_task.task_id,), daemon=True).start()

        self.refresh_queue_view()
        self.save_queue_state()

    def run_download_task(self, task_id):
        task = self.download_tasks[task_id]
        try:
            self._requests_fast_download(
                task.url,
                task.dest_path,
                task.title,
                task.base_item,
                task.manifest_item,
                task.game_key,
                task
            )
        finally:
            with self.download_lock:
                self.active_downloads = max(0, self.active_downloads - 1)
                self.running_task_ids.discard(task_id)
            self.save_queue_state()
            self.after(0, self.schedule_downloads)

    def refresh_queue_view(self):
        if not hasattr(self, "queue_tree"):
            return

        selected_ids = set(self.queue_tree.selection())
        self.queue_tree.delete(*self.queue_tree.get_children())
        with self.download_lock:
            tasks = [self.download_tasks[task_id] for task_id in self.download_order]

        visible_ids = []
        for task in tasks:
            folder = os.path.dirname(task.dest_path)
            item_id = str(task.task_id)
            visible_ids.append(item_id)
            self.queue_tree.insert(
                "",
                "end",
                iid=item_id,
                values=(
                    task.task_id,
                    task.platform,
                    task.category,
                    task.title,
                    task.status,
                    f"{task.progress:.0%}",
                    task.speed,
                    folder,
                )
            )
        keep_selected = [item_id for item_id in visible_ids if item_id in selected_ids]
        if keep_selected:
            self.queue_tree.selection_set(keep_selected)

    def clear_queue(self):
        if not messagebox.askyesno("Limpiar cola", "¿Quieres borrar la cola? Las descargas en curso se conservarán."):
            return
        kept = []
        removed = 0
        with self.download_lock:
            for task_id in self.download_order:
                task = self.download_tasks.get(task_id)
                if not task:
                    continue
                if task.status == "downloading":
                    kept.append(task_id)
                    continue
                removed += 1
                self.download_tasks.pop(task_id, None)
                self.running_task_ids.discard(task_id)
            self.download_order = kept
        self.save_queue_state()
        self.refresh_queue_view()
        self.status_label.configure(text=f"Cola limpiada: {removed} tarea(s) eliminada(s)")

    def selected_queue_tasks(self):
        if not hasattr(self, "queue_tree"):
            return []
        selected = []
        with self.download_lock:
            for item_id in self.queue_tree.selection():
                task = self.download_tasks.get(int(item_id))
                if task:
                    selected.append(task)
        return selected

    def pause_selected_tasks(self):
        tasks = self.selected_queue_tasks()
        if not tasks:
            return
        for task in tasks:
            if task.status in {"queued", "downloading"}:
                task.status = "paused"
        self.status_label.configure(text="Descarga(s) pausada(s)")
        self.refresh_queue_view()
        self.save_queue_state()

    def resume_selected_tasks(self):
        tasks = self.selected_queue_tasks()
        if not tasks:
            return
        for task in tasks:
            if task.status == "paused":
                task.status = "downloading" if task.task_id in self.running_task_ids else "queued"
        self.status_label.configure(text="Descarga(s) reanudada(s)")
        self.refresh_queue_view()
        self.save_queue_state()
        self.schedule_downloads()

    def cancel_selected_tasks(self):
        tasks = self.selected_queue_tasks()
        if not tasks:
            return
        for task in tasks:
            if task.status in {"queued", "paused", "downloading", "error", "corrupt"}:
                task.status = "cancelled"
        self.status_label.configure(text="Descarga(s) cancelada(s)")
        self.refresh_queue_view()
        self.save_queue_state()
        self.schedule_downloads()

    def retry_selected_tasks(self):
        tasks = self.selected_queue_tasks()
        if not tasks:
            return
        for task in tasks:
            if task.status in {"error", "cancelled", "complete", "corrupt"}:
                task.status = "queued"
                task.progress = 0.0
                task.speed = ""
                task.error = ""
                task.completed_at = ""
                if task.base_item and task.manifest_item and task.game_key:
                    self.register_manifest_entry(task.base_item, task.manifest_item, task.game_key, task.dest_path, "queued")
        self.status_label.configure(text="Descarga(s) reenviada(s) a la cola")
        self.refresh_queue_view()
        self.save_queue_state()
        self.schedule_downloads()

    def wait_if_task_paused(self, task):
        if not task:
            return
        while task.status == "paused":
            time.sleep(0.2)
        if task.status == "cancelled":
            raise DownloadCancelled()

    def update_task_progress(self, task, progress=None, speed=""):
        if not task:
            return
        if progress is not None:
            task.progress = max(0.0, min(1.0, progress))
        if speed:
            task.speed = speed
        self.save_queue_state()
        self.after(0, self.refresh_queue_view)

    def complete_task(self, task):
        if not task:
            return
        task.status = "complete"
        task.progress = 1.0
        task.completed_at = datetime.now().isoformat(timespec="seconds")
        self.save_queue_state()
        self.after(0, self.refresh_queue_view)

    def fail_task(self, task, error):
        if not task:
            return
        task.error = str(error)
        task.status = "cancelled" if isinstance(error, DownloadCancelled) else "error"
        self.save_queue_state()
        self.after(0, self.refresh_queue_view)

    def queue_report_rows(self):
        with self.download_lock:
            tasks = [self.download_tasks[task_id] for task_id in self.download_order]
        return [
            {
                "id": task.task_id,
                "platform": task.platform,
                "category": task.category,
                "title": task.title,
                "status": task.status,
                "progress": f"{task.progress:.0%}",
                "speed": task.speed,
                "path": task.dest_path,
                "error": task.error,
                "created_at": task.created_at,
                "completed_at": task.completed_at,
            }
            for task in tasks
        ]

    def library_report_rows(self):
        entries = self.merged_download_entries()
        rows = []
        for entry in entries.values():
            if entry.get("platform", "PS3") != self.current_platform:
                continue
            rows.append({
                "platform": entry.get("platform", "PS3"),
                "game_key": entry.get("game_key", ""),
                "game_name": entry.get("game_name", ""),
                "base_title_id": entry.get("base_title_id", ""),
                "category": entry.get("category", ""),
                "title_id": entry.get("title_id", ""),
                "name": entry.get("name", ""),
                "version": entry.get("version", ""),
                "status": entry.get("status", ""),
                "integrity": entry.get("integrity", ""),
                "sha256": entry.get("sha256", ""),
                "path": entry.get("path", ""),
                "downloaded_at": entry.get("downloaded_at", ""),
                "verified_at": entry.get("verified_at", ""),
            })
        return rows

    def export_current_report(self):
        active_tab = self.tabview.get() if self.tabview else "Descargas"
        default_name = "psn_killer_export.json" if active_tab not in {"Descargas", "Cola"} else f"psn_killer_{active_tab.lower()}.json"
        path = filedialog.asksaveasfilename(
            title="Exportar informe",
            defaultextension=".json",
            initialfile=default_name,
            filetypes=[("JSON", "*.json"), ("CSV", "*.csv")]
        )
        if not path:
            return

        data = {
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "platform": self.current_platform,
            "library": self.library_report_rows(),
            "queue": self.queue_report_rows(),
            "history": self.history_report_rows(),
        }

        try:
            if path.lower().endswith(".csv"):
                section = "queue" if active_tab == "Cola" else "history" if active_tab == "Historial" else "library"
                rows = data[section]
                with open(path, "w", newline="", encoding="utf-8") as f:
                    if rows:
                        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                        writer.writeheader()
                        writer.writerows(rows)
                    else:
                        f.write("")
            else:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            messagebox.showinfo("Exportar", f"Informe exportado:\n{path}")
        except OSError as e:
            messagebox.showerror("Exportar", f"No se pudo exportar el informe:\n{e}")

    def load_download_manifest(self):
        if not os.path.exists(MANIFEST_PATH):
            return {}
        try:
            with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
        return {}

    def save_download_manifest(self):
        with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(self.download_manifest, f, indent=2, ensure_ascii=False)

    def register_manifest_entry(self, base_item, item, game_key, path, status):
        key = manifest_key(game_key, item)
        logging.info("Manifest %s: %s [%s]", status, item.name, item.platform)
        self.download_manifest[key] = {
            "platform": base_item.platform,
            "game_key": game_key,
            "game_name": base_item.name,
            "base_title_id": base_item.title_id,
            "category": item.category,
            "title_id": item.title_id,
            "name": item.name,
            "version": item.version,
            "url": item.url,
            "sha256": item.sha256,
            "path": path,
            "status": status,
            "integrity": "",
            "verified_at": "",
            "downloaded_at": datetime.now().isoformat(timespec="seconds") if status == "complete" else "",
        }
        self.save_download_manifest()

    def update_manifest_integrity(self, base_item, item, game_key, path, status, integrity, actual_sha256=""):
        key = manifest_key(game_key, item)
        entry = self.download_manifest.get(key)
        if not entry:
            self.register_manifest_entry(base_item, item, game_key, path, status)
            entry = self.download_manifest[key]
        entry.update({
            "status": status,
            "path": path,
            "sha256": item.sha256,
            "actual_sha256": actual_sha256,
            "integrity": integrity,
            "verified_at": datetime.now().isoformat(timespec="seconds"),
            "downloaded_at": datetime.now().isoformat(timespec="seconds") if status == "complete" else entry.get("downloaded_at", ""),
        })
        self.save_download_manifest()

    def verify_download_integrity(self, base_item, item, game_key, path):
        if not valid_sha256(item.sha256):
            self.register_manifest_entry(base_item, item, game_key, path, "complete")
            self.download_manifest[manifest_key(game_key, item)]["integrity"] = "no-sha256"
            self.save_download_manifest()
            return "complete"

        actual_sha256 = calculate_sha256(path)
        if actual_sha256.lower() == item.sha256.lower():
            logging.info("SHA256 verificado: %s", path)
            self.update_manifest_integrity(base_item, item, game_key, path, "complete", "verified", actual_sha256)
            self.record_history("verify_file", item.platform, item.category, item.name, "verified", {"path": path})
            return "complete"

        logging.warning("SHA256 corrupto: %s esperado=%s real=%s", path, item.sha256, actual_sha256)
        self.update_manifest_integrity(base_item, item, game_key, path, "corrupt", "corrupt", actual_sha256)
        self.record_history("verify_file", item.platform, item.category, item.name, "corrupt", {"path": path})
        return "corrupt"

    def scan_downloads_folder(self):
        scanned = {}
        if not os.path.exists(DOWNLOADS_DIR):
            return scanned

        for platform in os.listdir(DOWNLOADS_DIR):
            if platform not in PLATFORM_CATALOGS:
                continue
            platform_dir = os.path.join(DOWNLOADS_DIR, platform)
            if not os.path.isdir(platform_dir):
                continue

            for folder_name in os.listdir(platform_dir):
                folder_path = os.path.join(platform_dir, folder_name)
                if not os.path.isdir(folder_path):
                    continue

                if folder_name in DOWNLOAD_FOLDER_TO_CATEGORY:
                    category = DOWNLOAD_FOLDER_TO_CATEGORY[folder_name]
                    for filename in os.listdir(folder_path):
                        if not filename.lower().endswith(".pkg"):
                            continue
                        path = os.path.join(folder_path, filename)
                        game_name = os.path.splitext(filename)[0]
                        game_key = game_name
                        key = f"scan|{platform}|simple|{category}|{filename}"
                        scanned[key] = {
                            "platform": platform,
                            "game_key": game_key,
                            "game_name": game_name,
                            "base_title_id": "",
                            "category": category,
                            "title_id": "",
                            "name": game_name,
                            "version": "",
                            "url": "",
                            "path": path,
                            "status": "complete",
                            "integrity": "scanned",
                            "downloaded_at": "",
                        }
                    continue

                game_key = folder_name
                game_dir = folder_path
                for category, folder in [
                    ("Juegos", "Base"),
                    ("Updates", "Updates"),
                    ("DLCs", "DLCs"),
                    ("Temas", "Temas"),
                    ("Avatares", "Avatares"),
                    ("Demos", "Demos"),
                ]:
                    folder_path = os.path.join(game_dir, folder)
                    if not os.path.isdir(folder_path):
                        continue
                    for filename in os.listdir(folder_path):
                        if not filename.lower().endswith(".pkg"):
                            continue
                        path = os.path.join(folder_path, filename)
                        key = f"scan|{platform}|{game_key}|{category}|{filename}"
                        scanned[key] = {
                            "platform": platform,
                            "game_key": game_key,
                            "game_name": re.sub(r"\s+\[[^\]]+\]$", "", game_key),
                            "base_title_id": "",
                            "category": category,
                            "title_id": "",
                            "name": os.path.splitext(filename)[0],
                            "version": "",
                            "url": "",
                            "path": path,
                            "status": "complete",
                            "integrity": "scanned",
                            "downloaded_at": "",
                        }
        return scanned

    def merged_download_entries(self):
        entries = dict(self.scan_downloads_folder())
        for key, entry in self.download_manifest.items():
            merged = dict(entry)
            merged.setdefault("platform", "PS3")
            if merged.get("path") and os.path.exists(merged["path"]):
                if merged.get("status") not in {"corrupt", "error", "cancelled"}:
                    merged["status"] = "complete"
                entries = {
                    scan_key: scan_entry for scan_key, scan_entry in entries.items()
                    if os.path.abspath(scan_entry.get("path", "")) != os.path.abspath(merged["path"])
                }
            entries[key] = merged
        return entries

    def refresh_downloads_view(self):
        if not hasattr(self, "downloads_tree"):
            return

        entries = self.merged_download_entries()
        self.downloads_tree.delete(*self.downloads_tree.get_children())

        grouped = {}
        for entry in entries.values():
            if entry.get("platform", "PS3") != self.current_platform:
                continue
            grouped.setdefault(entry["game_key"], []).append(entry)

        for game_key, game_entries in sorted(grouped.items()):
            game_name = game_entries[0].get("game_name") or game_key
            platform = game_entries[0].get("platform", "PS3")
            folder = os.path.join(DOWNLOADS_DIR, platform, game_key)
            if not os.path.isdir(folder):
                existing_paths = [entry.get("path", "") for entry in game_entries if entry.get("path")]
                if existing_paths:
                    folder = os.path.dirname(existing_paths[0])
            base_title_id = game_entries[0].get("base_title_id", "")
            base_item = next((item for item in self.catalog[platform]["Juegos"] if item.title_id == base_title_id), None)
            if not base_item:
                base_item = next((item for item in self.catalog[platform]["Juegos"] if item.name == game_name), None)
            available = self.find_related_content(base_item) if base_item else {}

            by_category = {}
            for entry in game_entries:
                by_category.setdefault(entry["category"], []).append(entry)

            base_entries = by_category.get("Juegos", [])
            if any(e["status"] == "complete" for e in base_entries):
                base_status = "OK"
            elif any(e["status"] in {"queued", "downloading", "paused"} for e in base_entries):
                base_status = "Pendiente"
            elif any(e["status"] in {"error", "cancelled", "corrupt"} for e in base_entries):
                base_status = "Revisar"
            else:
                base_status = "Falta"
            update_status = "Falta"
            update_entries = by_category.get("Updates", [])
            if update_entries:
                latest = max(update_entries, key=lambda e: version_tuple(e.get("version", "")))
                update_status = f"OK {latest.get('version', '')}".strip() if latest.get("status") == "complete" else f"{latest.get('status', 'Pendiente')} {latest.get('version', '')}".strip()

            dlcs_done = sum(1 for e in by_category.get("DLCs", []) if e["status"] == "complete")
            themes_done = sum(1 for e in by_category.get("Temas", []) if e["status"] == "complete")
            avatars_done = sum(1 for e in by_category.get("Avatares", []) if e["status"] == "complete")
            completed_files = sum(1 for e in game_entries if e.get("status") == "complete")
            total_files = len(game_entries)
            problem_files = sum(1 for e in game_entries if e.get("status") in {"error", "cancelled", "corrupt"} or e.get("integrity") == "corrupt")
            pending_files = sum(1 for e in game_entries if e.get("status") in {"queued", "downloading", "paused"})
            verified_files = sum(1 for e in game_entries if e.get("integrity") == "verified")

            dlcs_available = len(available.get("DLCs", [])) if available else len(by_category.get("DLCs", []))
            themes_available = len(available.get("Temas", [])) if available else len(by_category.get("Temas", []))
            avatars_available = len(available.get("Avatares", [])) if available else len(by_category.get("Avatares", []))
            overall_status = "OK"
            if problem_files:
                overall_status = "Revisar"
            elif pending_files:
                overall_status = "Pendiente"
            elif verified_files and verified_files == completed_files:
                overall_status = "Verificado"

            self.downloads_tree.insert(
                "",
                "end",
                values=(
                    game_name,
                    base_status,
                    update_status,
                    f"{dlcs_done}/{dlcs_available}",
                    f"{themes_done}/{themes_available}",
                    f"{avatars_done}/{avatars_available}",
                    f"{completed_files}/{total_files}",
                    overall_status,
                    folder,
                )
            )

    def clear_downloads_for_current_platform(self):
        platform = self.current_platform
        blocking_statuses = {"queued", "downloading", "paused"}
        with self.download_lock:
            blocking = [
                task for task in self.download_tasks.values()
                if task.platform == platform and task.status in blocking_statuses
            ]
        if blocking:
            messagebox.showwarning(
                "Limpiar descargas",
                f"Hay {len(blocking)} tarea(s) pendientes o activas de {platform}. Limpia o cancela la cola antes de borrar descargas."
            )
            return

        platform_dir = os.path.join(DOWNLOADS_DIR, platform)
        if not messagebox.askyesno(
            "Limpiar descargas",
            f"Esto borrará los archivos descargados de {platform} en:\n{platform_dir}\n\n¿Continuar?"
        ):
            return

        removed_manifest = 0
        for key, entry in list(self.download_manifest.items()):
            if entry.get("platform", "PS3") == platform:
                self.download_manifest.pop(key, None)
                removed_manifest += 1
        self.save_download_manifest()

        if os.path.isdir(platform_dir):
            shutil.rmtree(platform_dir)
        os.makedirs(platform_dir, exist_ok=True)

        with self.download_lock:
            kept_order = []
            for task_id in self.download_order:
                task = self.download_tasks.get(task_id)
                if task and task.platform == platform:
                    self.download_tasks.pop(task_id, None)
                    continue
                kept_order.append(task_id)
            self.download_order = kept_order
        self.save_queue_state()

        self.refresh_downloads_view()
        self.refresh_queue_view()
        self.record_history("clear_downloads", platform, "", f"Descargas {platform}", "cleared", {"manifest_entries": removed_manifest, "path": platform_dir})
        self.status_label.configure(text=f"Descargas de {platform} limpiadas")

    def open_downloads_folder(self):
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", DOWNLOADS_DIR])
            elif os.name == "nt":
                os.startfile(DOWNLOADS_DIR)
            else:
                subprocess.Popen(["xdg-open", DOWNLOADS_DIR])
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo abrir la carpeta de descargas:\n{e}")

    def start_download(self, tree, category):
        selected_items = tree.selection()
        if not selected_items:
            messagebox.showwarning("Atención", "Por favor selecciona uno o varios elementos para descargar.")
            return

        target_dir = os.path.join(DOWNLOADS_DIR, self.current_platform, category_folder(category))
        queued_count = 0
        skipped_count = 0

        for item_id in selected_items:
            item_values = tree.item(item_id)['values']
            tags = tree.item(item_id)['tags']
            item_tag = tags[0] if tags else ""
            item = self.content_by_tag.get(item_tag)
            if not item:
                name = item_values[2]
                version = item_values[3]
                item = ContentItem(category, item_values[0], item_values[1], name, version, item_values[4], "", platform=self.current_platform)
            if not is_valid_download_url(item.url):
                skipped_count += 1
                continue

            clean_title = sanitize_filename(item.name)
            custom_filename = item_filename(item)

            dest_path = unique_path(os.path.join(target_dir, custom_filename))

            clean_url = re.sub(r'(\.pkg)\d+$', r'\1', item.url, flags=re.IGNORECASE)

            game_key = f"{sanitize_filename(item.name)} [{item.title_id}]"
            self.register_manifest_entry(item, item, game_key, dest_path, "queued")
            self.enqueue_download(clean_url, dest_path, clean_title, item.category, item.platform, item, item, game_key)
            queued_count += 1

        if skipped_count and not queued_count:
            messagebox.showwarning("No disponible", "Los elementos seleccionados no tienen PKG descargable en el catálogo.")
        elif skipped_count:
            messagebox.showinfo("Descargas", f"Añadidos: {queued_count}\nNo disponibles omitidos: {skipped_count}")
        self.status_label.configure(text=f"Elemento(s) añadido(s) a la cola: {queued_count}")

    def download_rap(self):
        filename = os.path.join(CARPETAS["RAP"], "License_Pack_31.153.pkg")
        self.enqueue_download(GITHUB_RAP_URL, filename, "Licencias (31.153 .pkg)", "RAP", "PS3")
        self.status_label.configure(text="Licencias añadidas a la cola")

    def _requests_fast_download(self, url, dest_path, title, base_item=None, manifest_item=None, game_key=None, task=None):
        """
        Motor de descarga Ultra-Turbo con 16 hilos simultáneos y huella de navegador web de alta gama.
        """
        try:
            logging.info("Descarga iniciada: %s -> %s", title, dest_path)
            self.wait_if_task_paused(task)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            temp_path = partial_path(dest_path)
            if task:
                task.resume_path = temp_path
            requested_threads = max(1, self.threads_per_download)
            session = build_download_session(requested_threads)

            head_res = session.head(url, allow_redirects=True, timeout=10)
            total_size = int(head_res.headers.get('content-length', 0))
            accept_ranges = head_res.headers.get('accept-ranges', '').lower()
            if task:
                task.total_size = total_size

            num_threads = plan_thread_count(total_size, requested_threads)
            existing_partial = os.path.getsize(temp_path) if os.path.exists(temp_path) else 0
            if total_size <= 0 or 'bytes' not in accept_ranges or existing_partial or num_threads < 2:
                self._single_thread_download(session, url, dest_path, title, total_size, task)
                if base_item and manifest_item and game_key:
                    final_status = self.verify_download_integrity(base_item, manifest_item, game_key, dest_path)
                    self.ui(self.refresh_downloads_view)
                    if final_status == "corrupt":
                        if task:
                            task.status = "corrupt"
                            task.progress = 1.0
                            task.error = "SHA256 no coincide"
                            self.ui(self.refresh_queue_view)
                        self.ui(self.set_status, f"Corrupto: {os.path.basename(dest_path)}")
                        return
                self.complete_task(task)
                return

            chunk_size = total_size // num_threads
            lock = threading.Lock()
            downloaded_bytes = [0] * num_threads
            part_errors = []
            
            with open(temp_path, 'wb') as f:
                f.truncate(total_size)

            def download_part(thread_id, start, end):
                nonlocal downloaded_bytes
                headers = {'Range': f'bytes={start}-{end}'}
                try:
                    with session.get(url, headers=headers, stream=True, timeout=20) as r:
                        r.raise_for_status()
                        current_pos = start
                        with open(temp_path, 'r+b') as f:
                            f.seek(current_pos)
                            for chunk in r.iter_content(chunk_size=131072):
                                self.wait_if_task_paused(task)
                                if chunk:
                                    f.write(chunk)
                                    current_pos += len(chunk)
                                    with lock:
                                        downloaded_bytes[thread_id] = current_pos - start
                except Exception as e:
                    with lock:
                        part_errors.append(e)

            start_time = time.time()
            last_time = start_time
            last_total_downloaded = 0

            threads = []
            for i in range(num_threads):
                start = i * chunk_size
                end = (total_size - 1) if i == num_threads - 1 else (start + chunk_size - 1)
                t = threading.Thread(target=download_part, args=(i, start, end), daemon=True)
                threads.append(t)
                t.start()

            while any(t.is_alive() for t in threads):
                self.wait_if_task_paused(task)
                time.sleep(0.2)
                with lock:
                    current_total = sum(downloaded_bytes)
                
                now = time.time()
                elapsed = now - last_time
                if elapsed >= 0.2:
                    speed = (current_total - last_total_downloaded) / elapsed
                    speed_str = format_speed(speed)
                    percent = current_total / total_size if total_size > 0 else 0
                    
                    self.ui(self.set_progress, percent)
                    self.update_task_progress(task, percent, speed_str)
                    display_filename = os.path.basename(dest_path)
                    self.ui(
                        self.set_status,
                        f"Descargando ({num_threads} hilos): {display_filename}... [{speed_str}]"
                    )

                    last_total_downloaded = current_total
                    last_time = now

            for t in threads:
                t.join()

            if part_errors:
                raise part_errors[0]

            os.replace(temp_path, dest_path)
            self.ui(self.set_progress, 1.0)
            self.ui(self.set_status, f"✅ Finalizado: {os.path.basename(dest_path)}")
            if base_item and manifest_item and game_key:
                final_status = self.verify_download_integrity(base_item, manifest_item, game_key, dest_path)
                self.ui(self.refresh_downloads_view)
                if final_status == "corrupt":
                    if task:
                        task.status = "corrupt"
                        task.progress = 1.0
                        task.error = "SHA256 no coincide"
                        self.ui(self.refresh_queue_view)
                    self.ui(self.set_status, f"Corrupto: {os.path.basename(dest_path)}")
                    return
            self.complete_task(task)
            logging.info("Descarga completada: %s", dest_path)
            self.record_history("download", task.platform if task else "", task.category if task else "", title, "complete", {"path": dest_path})

        except DownloadCancelled as e:
            self.fail_task(task, e)
            logging.info("Descarga cancelada: %s", dest_path)
            self.record_history("download", task.platform if task else "", task.category if task else "", title, "cancelled", {"path": dest_path})
            self.ui(self.set_status, f"Cancelado: {os.path.basename(dest_path)}")
            if base_item and manifest_item and game_key:
                self.register_manifest_entry(base_item, manifest_item, game_key, dest_path, "cancelled")
                self.ui(self.refresh_downloads_view)
        except Exception as e:
            self.ui(self.set_status, "❌ Error en la descarga")
            self.fail_task(task, e)
            logging.exception("Error descargando %s: %s", title, e)
            self.record_history("download", task.platform if task else "", task.category if task else "", title, "error", {"path": dest_path, "error": str(e)})
            if base_item and manifest_item and game_key:
                self.register_manifest_entry(base_item, manifest_item, game_key, dest_path, "error")
                self.ui(self.refresh_downloads_view)
            # El diálogo se abre en el hilo principal: si no, bloquea la descarga y rompe Tk.
            self.ui(messagebox.showerror, "Error de Descarga", f"No se pudo descargar {title}:\n{e}")

    def _single_thread_download(self, session, url, dest_path, title, total_size, task=None):
        start_time = time.time()
        last_time = start_time
        temp_path = partial_path(dest_path)
        resume_from = os.path.getsize(temp_path) if os.path.exists(temp_path) else 0
        downloaded_bytes = resume_from
        last_bytes = resume_from
        headers = {}
        mode = "ab" if resume_from else "wb"
        if resume_from and total_size and resume_from < total_size:
            headers["Range"] = f"bytes={resume_from}-"
        elif resume_from and total_size and resume_from >= total_size:
            os.replace(temp_path, dest_path)
            self.ui(self.set_progress, 1.0)
            self.update_task_progress(task, 1.0, "")
            return

        with session.get(url, headers=headers, stream=True, timeout=15) as response:
            response.raise_for_status()
            if resume_from and headers and response.status_code != 206:
                mode = "wb"
                downloaded_bytes = 0
                last_bytes = 0
            with open(temp_path, mode) as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    self.wait_if_task_paused(task)
                    if chunk:
                        f.write(chunk)
                        downloaded_bytes += len(chunk)

                        now = time.time()
                        elapsed = now - last_time
                        if elapsed >= 0.2:
                            speed = (downloaded_bytes - last_bytes) / elapsed
                            speed_str = format_speed(speed)
                            
                            if total_size > 0:
                                progress = min(1.0, downloaded_bytes / total_size)
                                self.ui(self.set_progress, progress)
                                self.update_task_progress(task, progress, speed_str)

                            self.ui(
                                self.set_status,
                                f"Descargando: {os.path.basename(dest_path)}... [{speed_str}]"
                            )
                            last_bytes = downloaded_bytes
                            last_time = now

        os.replace(temp_path, dest_path)
        self.ui(self.set_progress, 1.0)
        self.update_task_progress(task, 1.0, "")
        self.ui(self.set_status, f"✅ Finalizado: {os.path.basename(dest_path)}")


PS3DownloaderApp = PSNDownloaderApp


if __name__ == "__main__":
    app = PSNDownloaderApp()
    app.mainloop()
