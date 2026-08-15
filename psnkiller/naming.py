"""
Nombres de archivo y rutas de destino.

Todo lo de aquí tiene que producir rutas válidas a la vez en Windows, Linux y
macOS, que es el mínimo común denominador más restrictivo de los tres.
"""
import hashlib
import logging
import os
import re

# Nombres de dispositivo reservados en Windows: no se pueden usar como archivo
# ni como carpeta, ni siquiera con extensión (CON.pkg también falla).
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
MAX_NAME_LENGTH = 100
# Windows limita a 260 caracteres salvo que se active el soporte de rutas largas.
MAX_PATH_LENGTH = 240 if os.name == "nt" else 4096

CATEGORY_FOLDERS = {
    "Juegos": "Base",
    "Updates": "Updates",
    "DLCs": "DLCs",
    "Temas": "Temas",
    "Avatares": "Avatares",
    "Demos": "Demos",
}
DOWNLOAD_FOLDER_TO_CATEGORY = {folder: category for category, folder in CATEGORY_FOLDERS.items()}


def sanitize_filename(filename, max_length=MAX_NAME_LENGTH):
    r"""
    Limpia el nombre para que sea válido en Windows, Linux y macOS.

    Además de los caracteres prohibidos (: \ / | ? * " < >) elimina caracteres
    de control, recorta puntos y espacios finales (Windows los quita en silencio,
    dejando la ruta del manifest sin corresponder con la del disco) y escapa los
    nombres de dispositivo reservados.
    """
    filename = re.sub(r'[:\\/|]', ' -', filename or "")
    filename = re.sub(r'[?*"<>]', '', filename)
    filename = re.sub(r'[\x00-\x1f\x7f]', '', filename)
    filename = re.sub(r'\s+', ' ', filename).strip()
    filename = filename[:max_length].strip().rstrip(". ")
    if filename.split(".")[0].upper() in WINDOWS_RESERVED_NAMES:
        filename = f"_{filename}"
    return filename or "sin_nombre"


def clamp_path_length(dest_path, max_path_length=None):
    """
    Recorta el nombre del archivo si la ruta completa supera el límite del sistema.

    Se añade un hash corto del nombre original para que dos títulos largos que
    comparten prefijo no colapsen en la misma ruta.
    """
    limit = MAX_PATH_LENGTH if max_path_length is None else max_path_length
    if len(dest_path) <= limit:
        return dest_path

    directory, filename = os.path.split(dest_path)
    stem, ext = os.path.splitext(filename)
    digest = hashlib.sha256(filename.encode("utf-8")).hexdigest()[:8]
    available = limit - len(directory) - len(os.sep) - len(ext) - len(digest) - 1
    if available < 1:
        logging.warning("Ruta demasiado larga y no recortable: %s", dest_path)
        return dest_path
    return os.path.join(directory, f"{stem[:available].strip()}~{digest}{ext}")


def category_folder(category):
    return CATEGORY_FOLDERS.get(category, category)


def item_filename(item):
    clean_title = sanitize_filename(item.name)
    if item.version and item.version.lower() not in ["base", "n/a", "none"]:
        return f"{clean_title} {item.version}.pkg"
    return f"{clean_title}.pkg"


def game_key_for(item):
    """Identificador de carpeta de un juego. Debe ser estable: el manifest lo usa como clave."""
    name = sanitize_filename(item.name)
    return f"{name} [{item.title_id}]" if item.title_id else name


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
