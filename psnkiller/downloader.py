"""
Motor de descarga HTTP.

Este módulo NO importa tkinter a propósito. Se comunica con quien lo use
mediante callbacks, y quien los recibe es responsable de llevarlos al hilo de
interfaz que corresponda. Esa separación es la que evita que se repita el fallo
de tocar widgets desde un hilo de descarga.
"""
import hashlib
import json
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
# Cada cuántos bytes se vacía el buffer al disco. Marca el máximo que se puede
# perder al reanudar: lo no volcado se vuelve a descargar.
FLUSH_INTERVAL_BYTES = 4 * 1024 * 1024
PART_STATE_INTERVAL_SECONDS = 2.0
PART_JOIN_TIMEOUT_SECONDS = 10.0


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


# --------------------------------------------------------------------------
# Estado de una descarga multihilo interrumpida
# --------------------------------------------------------------------------
# Sin esto, pausar o cerrar durante una descarga multihilo tiraba el .part
# entero: en un .pkg de 40 GB se perdía todo lo bajado. El sidecar guarda
# cuánto lleva escrito cada rango para poder retomarlos donde iban.

def part_state_path(temp_path):
    return f"{temp_path}.json"


def save_part_state(temp_path, url, total_size, ranges, done):
    """Guarda el progreso por rango. Escritura atómica: un corte aquí no debe cegar el .part."""
    state = {
        "version": 1,
        "url": url,
        "total_size": total_size,
        "ranges": [[start, end, int(done[i])] for i, (start, end) in enumerate(ranges)],
    }
    path = part_state_path(temp_path)
    temp = f"{path}.tmp"
    try:
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(temp, path)
    except OSError as e:
        logging.warning("No se pudo guardar el estado de %s: %s", temp_path, e)


def load_part_state(temp_path, url, total_size):
    """
    Devuelve los rangos reanudables, o None si no se puede confiar en el estado.

    Se descarta en cuanto algo no cuadre (otra URL, otro tamaño, el .part no
    está preasignado, contadores imposibles): reanudar mal produce un .pkg
    corrupto que además pasaría por completo.
    """
    path = part_state_path(temp_path)
    if not os.path.exists(path) or not os.path.exists(temp_path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    if state.get("version") != 1 or state.get("url") != url or state.get("total_size") != total_size:
        return None
    # El .part se preasigna al tamaño final; si no lo está, no vale para escribir por offsets.
    if os.path.getsize(temp_path) != total_size:
        return None

    ranges = []
    for entry in state.get("ranges", []):
        if not isinstance(entry, list) or len(entry) != 3:
            return None
        start, end, done = entry
        if not all(isinstance(v, int) for v in (start, end, done)):
            return None
        if not (0 <= start <= end < total_size) or not (0 <= done <= end - start + 1):
            return None
        ranges.append((start, end, done))

    if not ranges or ranges[0][0] != 0 or ranges[-1][1] != total_size - 1:
        return None
    for (_, fin, _), (inicio, _, _) in zip(ranges, ranges[1:]):
        if inicio != fin + 1:
            return None
    return ranges


def clear_part_state(temp_path):
    for path in (part_state_path(temp_path), f"{part_state_path(temp_path)}.tmp"):
        try:
            os.remove(path)
        except OSError:
            pass


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
            resumable = load_part_state(temp_path, url, total_size) if accepts_ranges else None
            existing_partial = os.path.getsize(temp_path) if os.path.exists(temp_path) else 0

            if total_size <= 0 or not accepts_ranges or num_threads < 2:
                clear_part_state(temp_path)
                self._single_thread(session, url, dest_path, temp_path, total_size)
            elif resumable:
                # Se retoman los rangos guardados, no los que tocarían ahora: el
                # usuario puede haber cambiado el número de hilos entre sesiones.
                logging.info("Reanudando descarga multihilo: %s", dest_path)
                self._multi_thread(session, url, dest_path, temp_path, total_size, resumable)
            elif existing_partial:
                # .part de una descarga monohilo previa, o estado no fiable.
                clear_part_state(temp_path)
                self._single_thread(session, url, dest_path, temp_path, total_size)
            else:
                ranges = [(start, end, 0) for start, end in split_ranges(total_size, num_threads)]
                self._multi_thread(session, url, dest_path, temp_path, total_size, ranges)
        finally:
            session.close()

        logging.info("Descarga completada: %s", dest_path)
        return os.path.getsize(dest_path) if os.path.exists(dest_path) else 0

    # -- estrategias --------------------------------------------------------

    def _multi_thread(self, session, url, dest_path, temp_path, total_size, ranges):
        """
        Descarga por rangos. `ranges` es [(inicio, fin, ya_descargado)].

        Se persiste `flushed`, no `downloaded`: sólo los bytes que ya han salido
        del buffer de Python cuentan como recuperables. Guardar de más haría que
        al reanudar se saltaran bytes nunca escritos, y el .pkg resultante sería
        corrupto pasando por completo.
        """
        num_threads = len(ranges)
        lock = threading.Lock()
        downloaded_bytes = [done for _, _, done in ranges]
        flushed_bytes = [done for _, _, done in ranges]
        plain_ranges = [(start, end) for start, end, _ in ranges]
        part_errors = []
        stop = threading.Event()

        if not os.path.exists(temp_path) or os.path.getsize(temp_path) != total_size:
            with open(temp_path, 'wb') as f:
                f.truncate(total_size)

        def download_part(thread_id, start, end, already):
            begin = start + already
            if begin > end:
                return  # este rango ya estaba completo
            headers = {'Range': f'bytes={begin}-{end}'}
            try:
                with session.get(url, headers=headers, stream=True, timeout=20) as r:
                    r.raise_for_status()
                    current_pos = begin
                    last_flush = begin
                    with open(temp_path, 'r+b') as f:
                        f.seek(current_pos)
                        for chunk in r.iter_content(chunk_size=131072):
                            if stop.is_set():
                                break
                            self.check_control()
                            if not chunk:
                                continue
                            f.write(chunk)
                            current_pos += len(chunk)
                            with lock:
                                downloaded_bytes[thread_id] = current_pos - start
                            if current_pos - last_flush >= FLUSH_INTERVAL_BYTES:
                                f.flush()
                                last_flush = current_pos
                                with lock:
                                    flushed_bytes[thread_id] = current_pos - start
                        f.flush()
                        with lock:
                            flushed_bytes[thread_id] = current_pos - start
            except Exception as e:
                with lock:
                    part_errors.append(e)

        threads = []
        for i, (start, end, already) in enumerate(ranges):
            t = threading.Thread(target=download_part, args=(i, start, end, already), daemon=True)
            threads.append(t)
            t.start()

        filename = os.path.basename(dest_path)
        last_time = time.time()
        last_total = sum(downloaded_bytes)
        last_state_save = time.time()

        def persistir():
            with lock:
                instantanea = list(flushed_bytes)
            save_part_state(temp_path, url, total_size, plain_ranges, instantanea)

        try:
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
                if now - last_state_save >= PART_STATE_INTERVAL_SECONDS:
                    persistir()
                    last_state_save = now
        except BaseException:
            # Pausa, cancelación o cierre: hay que parar a los hilos y dejar
            # constancia de por dónde iban antes de soltar el control.
            stop.set()
            for t in threads:
                t.join(timeout=PART_JOIN_TIMEOUT_SECONDS)
            persistir()
            raise

        for t in threads:
            t.join()

        if part_errors:
            persistir()
            raise part_errors[0]

        if sum(flushed_bytes) < total_size:
            persistir()
            raise OSError(
                f"Descarga incompleta: {sum(flushed_bytes)} de {total_size} bytes"
            )

        clear_part_state(temp_path)
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
    "clear_part_state",
    "load_part_state",
    "part_state_path",
    "save_part_state",
    "plan_thread_count",
    "split_ranges",
]
