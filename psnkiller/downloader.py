"""
Motor de descarga HTTP.

Este módulo NO importa tkinter a propósito. Se comunica con quien lo use
mediante callbacks, y quien los recibe es responsable de llevarlos al hilo de
interfaz que corresponda. Esa separación es la que evita que se repita el fallo
de tocar widgets desde un hilo de descarga.
"""
import hashlib
import logging
import os
import threading
import time

import requests

from .catalog import format_speed
from .models import DownloadCancelled
from .naming import partial_path

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    # identity evita que el servidor comprima y desalinee los rangos por bytes.
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
PROGRESS_INTERVAL_SECONDS = 0.2


def calculate_sha256(path, block_size=1024 * 1024):
    """SHA256 leyendo por bloques, para no cargar un .pkg de 40 GB en memoria."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(block_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def split_ranges(total_size, num_threads):
    """Reparte [0, total_size) en num_threads rangos contiguos y no vacíos."""
    chunk = total_size // num_threads
    return [
        (i * chunk, (total_size - 1) if i == num_threads - 1 else (i * chunk + chunk - 1))
        for i in range(num_threads)
    ]


class FileDownloader:
    """
    Descarga un archivo, en varios hilos si el servidor admite rangos.

    Los callbacks son opcionales:
      on_progress(fraccion, texto_velocidad, hilos)
      on_status(texto)
      check_control()  se llama a menudo; debe bloquear mientras esté en pausa
                       y lanzar DownloadCancelled si se ha cancelado.
    """

    def __init__(self, threads_per_download=16, on_progress=None, on_status=None, check_control=None):
        self.threads_per_download = max(1, threads_per_download)
        self.on_progress = on_progress or (lambda *a: None)
        self.on_status = on_status or (lambda *a: None)
        self.check_control = check_control or (lambda: None)

    # -- utilidades internas ------------------------------------------------

    def _probe(self, session, url):
        """Devuelve (tamaño_total, admite_rangos)."""
        response = session.head(url, allow_redirects=True, timeout=10)
        total_size = int(response.headers.get('content-length', 0))
        accept_ranges = response.headers.get('accept-ranges', '').lower()
        return total_size, 'bytes' in accept_ranges

    def _report(self, downloaded, total_size, speed_bytes, threads, filename):
        speed_text = format_speed(speed_bytes)
        fraction = min(1.0, downloaded / total_size) if total_size > 0 else 0.0
        self.on_progress(fraction, speed_text, threads)
        etiqueta = f"Descargando ({threads} hilos)" if threads > 1 else "Descargando"
        self.on_status(f"{etiqueta}: {filename}... [{speed_text}]")

    # -- API pública --------------------------------------------------------

    def download(self, url, dest_path):
        """
        Descarga url en dest_path y devuelve el tamaño final en bytes.

        Escribe primero en un .part y renombra al terminar, así un corte no deja
        un .pkg incompleto que parezca válido.
        """
        self.check_control()
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        temp_path = partial_path(dest_path)

        requested = self.threads_per_download
        session = build_download_session(requested)
        try:
            total_size, accepts_ranges = self._probe(session, url)
            num_threads = plan_thread_count(total_size, requested)
            existing_partial = os.path.getsize(temp_path) if os.path.exists(temp_path) else 0

            if total_size <= 0 or not accepts_ranges or existing_partial or num_threads < 2:
                self._single_thread(session, url, dest_path, temp_path, total_size)
            else:
                self._multi_thread(session, url, dest_path, temp_path, total_size, num_threads)
        finally:
            session.close()

        logging.info("Descarga completada: %s", dest_path)
        return os.path.getsize(dest_path) if os.path.exists(dest_path) else 0

    # -- estrategias --------------------------------------------------------

    def _multi_thread(self, session, url, dest_path, temp_path, total_size, num_threads):
        lock = threading.Lock()
        downloaded_bytes = [0] * num_threads
        part_errors = []

        with open(temp_path, 'wb') as f:
            f.truncate(total_size)

        def download_part(thread_id, start, end):
            headers = {'Range': f'bytes={start}-{end}'}
            try:
                with session.get(url, headers=headers, stream=True, timeout=20) as r:
                    r.raise_for_status()
                    current_pos = start
                    with open(temp_path, 'r+b') as f:
                        f.seek(current_pos)
                        for chunk in r.iter_content(chunk_size=131072):
                            self.check_control()
                            if chunk:
                                f.write(chunk)
                                current_pos += len(chunk)
                                with lock:
                                    downloaded_bytes[thread_id] = current_pos - start
            except Exception as e:
                with lock:
                    part_errors.append(e)

        threads = []
        for i, (start, end) in enumerate(split_ranges(total_size, num_threads)):
            t = threading.Thread(target=download_part, args=(i, start, end), daemon=True)
            threads.append(t)
            t.start()

        filename = os.path.basename(dest_path)
        last_time = time.time()
        last_total = 0
        while any(t.is_alive() for t in threads):
            self.check_control()
            time.sleep(PROGRESS_INTERVAL_SECONDS)
            with lock:
                current_total = sum(downloaded_bytes)

            now = time.time()
            elapsed = now - last_time
            if elapsed >= PROGRESS_INTERVAL_SECONDS:
                self._report(current_total, total_size,
                             (current_total - last_total) / elapsed, num_threads, filename)
                last_total = current_total
                last_time = now

        for t in threads:
            t.join()

        if part_errors:
            raise part_errors[0]

        os.replace(temp_path, dest_path)
        self.on_progress(1.0, "", num_threads)
        self.on_status(f"✅ Finalizado: {filename}")

    def _single_thread(self, session, url, dest_path, temp_path, total_size):
        resume_from = os.path.getsize(temp_path) if os.path.exists(temp_path) else 0
        downloaded_bytes = resume_from
        last_bytes = resume_from
        headers = {}
        mode = "ab" if resume_from else "wb"

        if resume_from and total_size and resume_from >= total_size:
            os.replace(temp_path, dest_path)
            self.on_progress(1.0, "", 1)
            return
        if resume_from and total_size:
            headers["Range"] = f"bytes={resume_from}-"

        filename = os.path.basename(dest_path)
        last_time = time.time()

        with session.get(url, headers=headers, stream=True, timeout=15) as response:
            response.raise_for_status()
            if resume_from and headers and response.status_code != 206:
                # El servidor ignoró el Range y manda el archivo entero.
                mode = "wb"
                downloaded_bytes = 0
                last_bytes = 0
            with open(temp_path, mode) as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    self.check_control()
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded_bytes += len(chunk)

                    now = time.time()
                    elapsed = now - last_time
                    if elapsed >= PROGRESS_INTERVAL_SECONDS:
                        self._report(downloaded_bytes, total_size,
                                     (downloaded_bytes - last_bytes) / elapsed, 1, filename)
                        last_bytes = downloaded_bytes
                        last_time = now

        os.replace(temp_path, dest_path)
        self.on_progress(1.0, "", 1)
        self.on_status(f"✅ Finalizado: {filename}")


__all__ = [
    "BROWSER_HEADERS",
    "DownloadCancelled",
    "FileDownloader",
    "MIN_BYTES_PER_THREAD",
    "build_download_session",
    "calculate_sha256",
    "plan_thread_count",
    "split_ranges",
]
