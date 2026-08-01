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
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from tkinter import ttk
import customtkinter as ctk

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DOWNLOADS_DIR = os.path.join(BASE_DIR, "Descargas")
MANIFEST_PATH = os.path.join(BASE_DIR, "downloads_manifest.json")

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


def manifest_key(game_key, item):
    return f"{item.platform}|{game_key}|{item.category}|{item.title_id}|{item.version}|{item.url}"


class PSNDownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("PSN Killer Global")
        self.geometry("1180x740")

        self.setup_dark_theme()

        self.current_platform = "PS3"
        self.catalog = {
            platform: {category: [] for category in CONTENT_ORDER}
            for platform in PLATFORM_CATALOGS
        }
        self.data_store = self.catalog[self.current_platform]
        self.content_by_url = {}
        self.download_manifest = self.load_download_manifest()

        self.create_ui()
        self.load_all_data()
        self.refresh_downloads_view()

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

    def create_ui(self):
        top_frame = ctk.CTkFrame(self, height=50)
        top_frame.pack(fill="x", padx=10, pady=5)

        title_label = ctk.CTkLabel(
            top_frame, 
            text="🎮 PSN Killer Global (Downloader)",
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

        # Barra de estado inferior con la marca de agua integrada de forma sutil
        self.status_frame = ctk.CTkFrame(self, height=35)
        self.status_frame.pack(fill="x", side="bottom", padx=10, pady=5)

        self.status_label = ctk.CTkLabel(self.status_frame, text="Estado: Listo", font=ctk.CTkFont(size=12))
        self.status_label.pack(side="left", padx=10)

        # MARCA DE AGUA: Creado por TheWizWiki (Discreta a la derecha de la barra de estado)
        watermark_label = ctk.CTkLabel(
            self.status_frame, 
            text="✨ Creado por TheWizWiki", 
            font=ctk.CTkFont(size=11, slant="italic"),
            text_color="#888888"
        )
        watermark_label.pack(side="right", padx=15)

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

    def change_platform(self, platform):
        self.current_platform = platform
        self.data_store = self.catalog[self.current_platform]
        self.build_platform_tabs()
        self.populate_trees()
        self.refresh_downloads_view()

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
        columns = ("game", "base", "updates", "dlcs", "themes", "avatars", "folder")
        self.downloads_tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="browse")

        headings = {
            "game": "Juego",
            "base": "Base",
            "updates": "Última Update",
            "dlcs": "DLCs",
            "themes": "Temas",
            "avatars": "Avatares",
            "folder": "Carpeta",
        }
        widths = {
            "game": 280,
            "base": 90,
            "updates": 120,
            "dlcs": 100,
            "themes": 100,
            "avatars": 100,
            "folder": 320,
        }
        for col in columns:
            self.downloads_tree.heading(col, text=headings[col])
            self.downloads_tree.column(col, width=widths[col], anchor="w" if col in ["game", "folder"] else "center")

        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=self.downloads_tree.yview)
        self.downloads_tree.configure(yscrollcommand=scrollbar.set)
        self.downloads_tree.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scrollbar.pack(side="right", fill="y", pady=5)

        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_frame.pack(side="bottom", fill="x", padx=5, pady=5)

        refresh_btn = ctk.CTkButton(btn_frame, text="🔄 Actualizar descargas", command=self.refresh_downloads_view)
        refresh_btn.pack(side="left", fill="x", expand=True, padx=(0, 5))

        open_btn = ctk.CTkButton(btn_frame, text="📂 Abrir carpeta Descargas", command=self.open_downloads_folder)
        open_btn.pack(side="left", fill="x", expand=True, padx=(5, 0))

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
        self.catalog[platform][category].append(item)
        self.content_by_url[url] = item
        return item

    def header_value(self, row, header, *names):
        for name in names:
            index = header.get(name.lower())
            if index is not None and index < len(row):
                return row[index].strip()
        return ""

    def parse_catalog_row(self, platform, category, row, header=None):
        if not row:
            return None

        if header is None and row[0].strip().lower() in ["title id", "id", "title_id"]:
            return None

        url_index = next((i for i, col in enumerate(row) if col.strip().startswith("http")), None)
        if url_index is None:
            return None

        url = row[url_index].strip()
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

        size_str = format_bytes(file_size) if file_size.isdigit() else "N/A"
        if size_str == "N/A":
            size_match = re.search(r'\.pkg(\d+)$', url, re.IGNORECASE)
            size_str = format_bytes(size_match.group(1)) if size_match else "N/A"

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

    def load_all_data(self):
        for platform, files in PLATFORM_CATALOGS.items():
            for category, file_name in files.items():
                self.load_tsv_catalog(platform, category, file_name)

        self.data_store = self.catalog[self.current_platform]
        self.populate_trees()

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
                    tags=(item.url,)
                )
        
        self.update_summary_count()

    def filter_tables(self, event=None):
        query = self.search_entry.get().strip().lower()
        selected_region = self.region_combo.get()

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

                if match_text and match_region:
                    tree.insert(
                        "",
                        "end",
                        values=(item.title_id, item.region, item.name, item.version, item.size),
                        tags=(item.url,)
                    )

        self.update_summary_count()

    def tree_item_to_content(self, tree, item_id, category):
        values = tree.item(item_id)["values"]
        tags = tree.item(item_id)["tags"]
        url = tags[0] if tags else ""
        return self.content_by_url.get(
            url,
            ContentItem(category, values[0], values[1], values[2], values[3], values[4], url, platform=self.current_platform)
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
        if candidate.region != base_item.region:
            return False
        if has_number_conflict(base_item.name, candidate.name):
            return False

        base_tokens = title_tokens(base_item.name)
        candidate_tokens = title_tokens(candidate.name)
        if not base_tokens or not candidate_tokens:
            return False

        token_overlap = len(base_tokens & candidate_tokens) / len(base_tokens)
        return token_overlap >= 0.75 and title_similarity(base_item.name, candidate.name) >= 0.72

    def find_related_content(self, base_item):
        related = {"Juegos": [], "Updates": [], "DLCs": [], "Temas": [], "Avatares": []}
        base_copy = ContentItem(**{**base_item.__dict__, "match_type": "exact"})
        related["Juegos"].append(base_copy)

        for category in ["Updates", "DLCs", "Temas", "Avatares"]:
            for item in self.catalog[base_item.platform].get(category, []):
                if item.platform == base_item.platform and item.title_id == base_item.title_id:
                    match_type = "exact"
                elif self.is_suggested_match(base_item, item):
                    match_type = "suggested"
                else:
                    continue

                item_copy = ContentItem(**{**item.__dict__, "match_type": match_type})
                related[category].append(item_copy)

        return related

    def item_selected_by_default(self, item, category, related):
        if category == "Juegos":
            return True
        if item.match_type != "exact":
            return False
        if category == "Updates":
            return self.update_is_latest(item, related["Updates"])
        return True

    def start_complete_download_dialog(self, tree):
        selected_items = tree.selection()
        if len(selected_items) != 1:
            messagebox.showwarning("Atención", "Selecciona un único juego para descargarlo completo.")
            return

        base_item = self.tree_item_to_content(tree, selected_items[0], "Juegos")
        related = self.find_related_content(base_item)
        game_key = f"{sanitize_filename(base_item.name)} [{base_item.title_id}]"

        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Descargar completo - {base_item.name}")
        dialog.geometry("900x650")
        dialog.transient(self)
        dialog.grab_set()

        header = ctk.CTkLabel(
            dialog,
            text=f"Contenido relacionado para {base_item.name} [{base_item.title_id}]",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        header.pack(fill="x", padx=15, pady=(15, 5))

        hint = ctk.CTkLabel(
            dialog,
            text="Los exactos por Title ID se marcan automáticamente. Los sugeridos por nombre aparecen desmarcados.",
            text_color="#b0b0b0"
        )
        hint.pack(fill="x", padx=15, pady=(0, 10))

        scroll = ctk.CTkScrollableFrame(dialog)
        scroll.pack(fill="both", expand=True, padx=15, pady=5)

        checkbox_rows = []

        for category in ["Juegos", "Updates", "DLCs", "Temas", "Avatares"]:
            items = related[category]
            if not items:
                continue

            category_label = ctk.CTkLabel(
                scroll,
                text=f"{category} ({len(items)})",
                font=ctk.CTkFont(size=13, weight="bold")
            )
            category_label.pack(fill="x", anchor="w", padx=5, pady=(10, 2))

            for match_type in ["exact", "suggested"]:
                match_items = [item for item in items if item.match_type == match_type]
                if not match_items:
                    continue

                label_text = "Exactos" if match_type == "exact" else "Sugeridos"
                match_label = ctk.CTkLabel(scroll, text=label_text, text_color="#8fbce8" if match_type == "exact" else "#e0b15a")
                match_label.pack(fill="x", anchor="w", padx=18, pady=(4, 1))

                for item in match_items:
                    var = tk.BooleanVar(value=self.item_selected_by_default(item, category, related))
                    text = f"[{item.title_id} | {item.region}] {item.name} - {item.version} - {item.size}"
                    checkbox = ctk.CTkCheckBox(scroll, text=text, variable=var)
                    checkbox.pack(fill="x", anchor="w", padx=35, pady=2)
                    checkbox_rows.append((var, item))

        button_bar = ctk.CTkFrame(dialog)
        button_bar.pack(fill="x", padx=15, pady=15)

        def mark_exact():
            for var, item in checkbox_rows:
                var.set(item.match_type == "exact")

        def mark_all():
            for var, _item in checkbox_rows:
                var.set(True)

        def start_selected():
            selected = [item for var, item in checkbox_rows if var.get()]
            if not selected:
                messagebox.showwarning("Atención", "No hay contenido seleccionado para descargar.")
                return
            dialog.destroy()
            self.start_grouped_downloads(base_item, selected, game_key)

        ctk.CTkButton(button_bar, text="Marcar exactos", command=mark_exact).pack(side="left", padx=5)
        ctk.CTkButton(button_bar, text="Marcar todo visible", command=mark_all).pack(side="left", padx=5)
        ctk.CTkButton(button_bar, text="Descargar seleccionados", command=start_selected).pack(side="right", padx=5)
        ctk.CTkButton(button_bar, text="Cancelar", fg_color="#555555", command=dialog.destroy).pack(side="right", padx=5)

    def start_grouped_downloads(self, base_item, selected_items, game_key):
        game_dir = os.path.join(DOWNLOADS_DIR, base_item.platform, game_key)
        for folder in ["Base", "Updates", "DLCs", "Temas", "Avatares", "Demos"]:
            os.makedirs(os.path.join(game_dir, folder), exist_ok=True)

        for item in selected_items:
            dest_dir = os.path.join(game_dir, category_folder(item.category))
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = unique_path(os.path.join(dest_dir, item_filename(item)))
            clean_url = re.sub(r'(\.pkg)\d+$', r'\1', item.url, flags=re.IGNORECASE)

            self.register_manifest_entry(base_item, item, game_key, dest_path, "queued")
            threading.Thread(
                target=self._requests_fast_download,
                args=(clean_url, dest_path, item.name, base_item, item, game_key),
                daemon=True
            ).start()

        self.status_label.configure(text=f"Descargas agrupadas iniciadas: {len(selected_items)} elemento(s)")
        self.refresh_downloads_view()

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
            "path": path,
            "status": status,
            "downloaded_at": datetime.now().isoformat(timespec="seconds") if status == "complete" else "",
        }
        self.save_download_manifest()

    def scan_downloads_folder(self):
        scanned = {}
        if not os.path.exists(DOWNLOADS_DIR):
            return scanned

        for platform in os.listdir(DOWNLOADS_DIR):
            platform_dir = os.path.join(DOWNLOADS_DIR, platform)
            if not os.path.isdir(platform_dir):
                continue

            for game_key in os.listdir(platform_dir):
                game_dir = os.path.join(platform_dir, game_key)
                if not os.path.isdir(game_dir):
                    continue

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
                            "downloaded_at": "",
                        }
        return scanned

    def merged_download_entries(self):
        entries = dict(self.scan_downloads_folder())
        for key, entry in self.download_manifest.items():
            merged = dict(entry)
            merged.setdefault("platform", "PS3")
            if merged.get("path") and os.path.exists(merged["path"]):
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
            base_title_id = game_entries[0].get("base_title_id", "")
            base_item = next((item for item in self.catalog[platform]["Juegos"] if item.title_id == base_title_id), None)
            if not base_item:
                base_item = next((item for item in self.catalog[platform]["Juegos"] if item.name == game_name), None)
            available = self.find_related_content(base_item) if base_item else {}

            by_category = {}
            for entry in game_entries:
                by_category.setdefault(entry["category"], []).append(entry)

            base_status = "OK" if any(e["status"] == "complete" for e in by_category.get("Juegos", [])) else "Falta"
            update_status = "Falta"
            update_entries = by_category.get("Updates", [])
            if update_entries:
                latest = max(update_entries, key=lambda e: version_tuple(e.get("version", "")))
                update_status = f"OK {latest.get('version', '')}".strip() if latest.get("status") == "complete" else f"Pendiente {latest.get('version', '')}".strip()

            dlcs_done = sum(1 for e in by_category.get("DLCs", []) if e["status"] == "complete")
            themes_done = sum(1 for e in by_category.get("Temas", []) if e["status"] == "complete")
            avatars_done = sum(1 for e in by_category.get("Avatares", []) if e["status"] == "complete")

            dlcs_available = len(available.get("DLCs", [])) if available else len(by_category.get("DLCs", []))
            themes_available = len(available.get("Temas", [])) if available else len(by_category.get("Temas", []))
            avatars_available = len(available.get("Avatares", [])) if available else len(by_category.get("Avatares", []))

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
                    folder,
                )
            )

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

        for item_id in selected_items:
            item_values = tree.item(item_id)['values']
            tags = tree.item(item_id)['tags']
            raw_url = tags[0]
            item = self.content_by_url.get(raw_url)
            if not item:
                name = item_values[2]
                version = item_values[3]
                item = ContentItem(category, item_values[0], item_values[1], name, version, item_values[4], raw_url, platform=self.current_platform)

            clean_title = sanitize_filename(item.name)
            custom_filename = item_filename(item)

            dest_path = unique_path(os.path.join(target_dir, custom_filename))

            clean_url = re.sub(r'(\.pkg)\d+$', r'\1', item.url, flags=re.IGNORECASE)

            threading.Thread(
                target=self._requests_fast_download, 
                args=(clean_url, dest_path, clean_title), 
                daemon=True
            ).start()

    def download_rap(self):
        filename = os.path.join(CARPETAS["RAP"], "License_Pack_31.153.pkg")
        threading.Thread(
            target=self._requests_fast_download, 
            args=(GITHUB_RAP_URL, filename, "Licencias (31.153 .pkg)"), 
            daemon=True
        ).start()

    def _requests_fast_download(self, url, dest_path, title, base_item=None, manifest_item=None, game_key=None):
        """
        Motor de descarga Ultra-Turbo con 16 hilos simultáneos y huella de navegador web de alta gama.
        """
        try:
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            session = requests.Session()
            session.headers.update({
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
            })

            head_res = session.head(url, allow_redirects=True, timeout=10)
            total_size = int(head_res.headers.get('content-length', 0))
            accept_ranges = head_res.headers.get('accept-ranges', '').lower()

            if total_size <= 0 or 'bytes' not in accept_ranges:
                self._single_thread_download(session, url, dest_path, title, total_size)
                if base_item and manifest_item and game_key:
                    self.register_manifest_entry(base_item, manifest_item, game_key, dest_path, "complete")
                    self.refresh_downloads_view()
                return

            num_threads = 16
            chunk_size = total_size // num_threads
            lock = threading.Lock()
            downloaded_bytes = [0] * num_threads
            
            with open(dest_path, 'wb') as f:
                f.truncate(total_size)

            def download_part(thread_id, start, end):
                nonlocal downloaded_bytes
                headers = {'Range': f'bytes={start}-{end}'}
                try:
                    with session.get(url, headers=headers, stream=True, timeout=20) as r:
                        r.raise_for_status()
                        current_pos = start
                        with open(dest_path, 'r+b') as f:
                            f.seek(current_pos)
                            for chunk in r.iter_content(chunk_size=131072):
                                if chunk:
                                    f.write(chunk)
                                    current_pos += len(chunk)
                                    with lock:
                                        downloaded_bytes[thread_id] = current_pos - start
                except Exception as e:
                    print(f"Error en hilo {thread_id}: {e}")

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
                time.sleep(0.2)
                with lock:
                    current_total = sum(downloaded_bytes)
                
                now = time.time()
                elapsed = now - last_time
                if elapsed >= 0.2:
                    speed = (current_total - last_total_downloaded) / elapsed
                    speed_str = format_speed(speed)
                    percent = current_total / total_size if total_size > 0 else 0
                    
                    self.progress_bar.set(min(1.0, percent))
                    display_filename = os.path.basename(dest_path)
                    self.status_label.configure(
                        text=f"Descargando (Turbo 16H): {display_filename}... [{speed_str}]"
                    )

                    last_total_downloaded = current_total
                    last_time = now

            for t in threads:
                t.join()

            self.progress_bar.set(1.0)
            self.status_label.configure(text=f"✅ Finalizado: {os.path.basename(dest_path)}")
            if base_item and manifest_item and game_key:
                self.register_manifest_entry(base_item, manifest_item, game_key, dest_path, "complete")
                self.refresh_downloads_view()

        except Exception as e:
            self.status_label.configure(text="❌ Error en la descarga")
            if base_item and manifest_item and game_key:
                self.register_manifest_entry(base_item, manifest_item, game_key, dest_path, "error")
                self.refresh_downloads_view()
            messagebox.showerror("Error de Descarga", f"No se pudo descargar {title}:\n{e}")

    def _single_thread_download(self, session, url, dest_path, title, total_size):
        start_time = time.time()
        last_time = start_time
        downloaded_bytes = 0
        last_bytes = 0

        with session.get(url, stream=True, timeout=15) as response:
            response.raise_for_status()
            with open(dest_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        downloaded_bytes += len(chunk)

                        now = time.time()
                        elapsed = now - last_time
                        if elapsed >= 0.2:
                            speed = (downloaded_bytes - last_bytes) / elapsed
                            speed_str = format_speed(speed)
                            
                            if total_size > 0:
                                self.progress_bar.set(min(1.0, downloaded_bytes / total_size))

                            self.status_label.configure(
                                text=f"Descargando: {os.path.basename(dest_path)}... [{speed_str}]"
                            )
                            last_bytes = downloaded_bytes
                            last_time = now

        self.progress_bar.set(1.0)
        self.status_label.configure(text=f"✅ Finalizado: {os.path.basename(dest_path)}")


PS3DownloaderApp = PSNDownloaderApp


if __name__ == "__main__":
    app = PSNDownloaderApp()
    app.mainloop()
