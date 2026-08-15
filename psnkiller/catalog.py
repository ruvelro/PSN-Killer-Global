"""
Lectura y normalización de los catálogos TSV.

Sin estado ni interfaz: todo son funciones sobre filas y textos, para que se
pueda probar sin abrir una ventana ni tocar el disco.
"""
import os
import re
from difflib import SequenceMatcher

from .models import ContentItem
from .naming import item_filename

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
    "PSX": {"Juegos": "PSX_GAMES.tsv"},
    "PSM": {"Juegos": "PSM_GAMES.tsv"},
}

CONTENT_ORDER = ["Juegos", "Updates", "DLCs", "Temas", "Avatares", "Demos"]
RELATED_CATEGORIES = ["Juegos", "Updates", "DLCs", "Temas", "Avatares"]
GROUPED_DOWNLOAD_PLATFORMS = {"PS3", "PSP", "PSV"}
HEADER_FIRST_COLUMNS = ["title id", "id", "title_id"]

TITLE_STOPWORDS = {
    "the", "a", "an", "and", "of", "for", "to", "in", "on", "with", "edition",
    "game", "pack", "bundle", "level", "map", "skin", "costume", "theme", "avatar",
    "dlc", "update", "add", "content", "ps3", "psp", "psv", "vita", "psn"
}


# --------------------------------------------------------------------------
# Formato de tamaños y velocidades
# --------------------------------------------------------------------------

def format_bytes(bytes_num):
    """Convierte un número de bytes en formato MB/GB legible."""
    try:
        b = float(bytes_num)
        if b <= 0:
            return "N/A"
        if b >= 1024 ** 3:
            return f"{b / (1024 ** 3):.2f} GB"
        elif b >= 1024 ** 2:
            return f"{b / (1024 ** 2):.1f} MB"
        elif b >= 1024:
            return f"{b / 1024:.0f} KB"
        return f"{b:.0f} B"
    except (ValueError, TypeError):
        return "N/A"


def format_speed(bytes_per_sec):
    """Da formato a la velocidad en MB/s y Mbps."""
    if bytes_per_sec <= 0:
        return "0 KB/s"
    mb_s = bytes_per_sec / (1024 * 1024)
    mbps = (bytes_per_sec * 8) / (1024 * 1024)
    if mb_s >= 1:
        return f"{mb_s:.1f} MB/s | {mbps:.1f} Mbps"
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
    multipliers = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}
    return int(value * multipliers.get(unit, 1))


def format_total_size(bytes_num):
    return format_bytes(bytes_num) if bytes_num else "Sin tamaño"


# --------------------------------------------------------------------------
# Regiones, versiones y validaciones
# --------------------------------------------------------------------------

def auto_detect_region(tid):
    """Detecta la región del juego basándose en el prefijo del Title ID."""
    tid = (tid or "").upper()
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


def compatible_region(base_region, candidate_region):
    if not base_region or not candidate_region:
        return True
    return candidate_region in {base_region, "ALL", "FREE", "INT"}


def split_name_and_version(raw_name, default_ver="Base"):
    """Separa versiones adosadas al nombre."""
    if not raw_name:
        return "", default_ver

    match = re.search(r'(.*?)(?:\[?v?(\d{1,2}\.\d{2})\]?)$', raw_name.strip(), re.IGNORECASE)
    if match and match.group(2):
        return match.group(1).strip(), f"v{match.group(2)}"
    return raw_name.strip(), default_ver


def extract_version_from_text(text, default_ver="v01.00"):
    match = re.search(r'\bv[\s.]?(\d+(?:\.\d+)*)\b', text or "", re.IGNORECASE)
    return f"v{match.group(1)}" if match else default_ver


def version_tuple(version):
    numbers = re.findall(r"\d+", version or "")
    return tuple(int(n) for n in numbers) if numbers else (0,)


def is_valid_download_url(url):
    return (url or "").strip().lower().startswith(("http://", "https://"))


def is_missing_value(value):
    return not (value or "").strip() or (value or "").strip().upper() in {"MISSING", "N/A", "NA"}


def valid_sha256(value):
    return bool(value and re.fullmatch(r"[a-fA-F0-9]{64}", value.strip()))


# --------------------------------------------------------------------------
# Normalización y emparejado de títulos
# --------------------------------------------------------------------------

def normalize_title(text):
    text = (text or "").lower()
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


# --------------------------------------------------------------------------
# Identidad y calidad de un elemento del catálogo
# --------------------------------------------------------------------------

def catalog_item_key(item):
    """
    Identidad canónica de un elemento.

    Es también la clave con la que se guarda en SQLite: si las dos difieren, la
    base descarta elementos que en memoria son distintos.
    """
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


def catalog_item_tag(item):
    return "|".join(str(part) for part in catalog_item_key(item))


def catalog_item_score(item):
    """Cuánta información aporta un elemento; gana el mayor cuando dos comparten clave."""
    score = 0
    score += 100 if is_valid_download_url(item.url) else 0
    score += 30 if not is_missing_value(item.license_value) else 0
    score += 20 if not is_missing_value(item.sha256) else 0
    score += 10 if parse_size_to_bytes(item.size) else 0
    score += 5 if not is_missing_value(item.required_fw) else 0
    return score


def same_catalog_item(left, right):
    """¿El elemento de catálogo `left` se corresponde con la entrada descargada `right`?"""
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


# --------------------------------------------------------------------------
# Parseo de filas TSV
# --------------------------------------------------------------------------

def header_value(row, header, *names):
    for name in names:
        index = header.get(name.lower())
        if index is not None and index < len(row):
            return row[index].strip()
    return ""


def row_pkg_url(row, header):
    if header:
        for name in ("pkg direct link", "update url", "download url", "url"):
            value = header_value(row, header, name)
            if is_valid_download_url(value):
                return value
        return ""
    url_index = next((i for i, col in enumerate(row) if col.strip().startswith(("http://", "https://"))), None)
    return row[url_index].strip() if url_index is not None else ""


def is_header_row(row):
    return bool(row) and row[0].strip().lower() in HEADER_FIRST_COLUMNS


def build_header(row):
    return {name.strip().lower(): index for index, name in enumerate(row)}


def parse_catalog_row(platform, category, row, header=None):
    if not row:
        return None

    if header is None and is_header_row(row):
        return None

    url = row_pkg_url(row, header)
    title_id = header_value(row, header, "title id") if header else row[0].strip()
    region = header_value(row, header, "region") if header else ""
    name = header_value(row, header, "name") if header else ""
    version = "Base"
    content_id = header_value(row, header, "content id") if header else ""
    license_value = header_value(row, header, "zrif", "rap") if header else ""
    file_size = header_value(row, header, "file size") if header else ""
    sha256 = header_value(row, header, "sha256") if header else ""
    required_fw = header_value(row, header, "required fw", "required fw version") if header else ""
    original_name = header_value(row, header, "original name") if header else ""
    item_type = header_value(row, header, "type") if header else ""

    if platform == "PS3" and category == "Updates" and not header:
        # Formato heredado de clean_updates.py: id, nombre, versión, url.
        title_id = row[0].strip()
        name = row[1].strip() if len(row) > 1 else f"Actualización ({title_id})"
        version = row[2].strip() if len(row) > 2 else "v01.00"
    elif category == "Updates":
        version = header_value(row, header, "update version")
        if version:
            version = version if version.lower().startswith("v") else f"v{version}"
        else:
            version = extract_version_from_text(name, "v01.00")

    if platform == "PSP" and category == "Juegos" and header:
        name = header_value(row, header, "name")

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


class CatalogIndex:
    """
    Catálogo en memoria con índice por clave canónica.

    Sin el índice, insertar era O(n^2): con los 65.814 elementos de los TSV
    actuales la carga pasaba de 2 a 51 segundos.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.catalog = {
            platform: {category: [] for category in CONTENT_ORDER}
            for platform in PLATFORM_CATALOGS
        }
        self.index = {}
        self.by_url = {}
        self.by_tag = {}

    def __len__(self):
        return sum(len(items) for cats in self.catalog.values() for items in cats.values())

    def add(self, **fields):
        item = ContentItem(**fields)
        items = self.catalog[item.platform][item.category]
        key = catalog_item_key(item)
        position = self.index.get(key)

        if position is None:
            self.index[key] = len(items)
            items.append(item)
        else:
            existing = items[position]
            if catalog_item_score(item) <= catalog_item_score(existing):
                return existing
            items[position] = item

        if is_valid_download_url(item.url):
            self.by_url[item.url] = item
        self.by_tag[catalog_item_tag(item)] = item
        return item
