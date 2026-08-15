"""
FileDownloader de extremo a extremo, contra un servidor HTTP local.

Levantar un servidor de verdad es la única forma de comprobar que el troceado
por rangos, la reanudación y la cancelación funcionan como se espera.
"""
import hashlib
import http.server
import os
import re
import threading

import pytest

from psnkiller.downloader import FileDownloader
from psnkiller.models import DownloadCancelled

MB = 1024 * 1024


class _RangeHandler(http.server.BaseHTTPRequestHandler):
    """Sirve `payload` con soporte de Range, o sin él si `accept_ranges` es False."""

    payload = b""
    accept_ranges = True

    def log_message(self, *args):
        pass

    def _headers_comunes(self, length, status=200, content_range=None):
        self.send_response(status)
        self.send_header("Content-Length", str(length))
        if self.accept_ranges:
            self.send_header("Accept-Ranges", "bytes")
        if content_range:
            self.send_header("Content-Range", content_range)
        self.end_headers()

    def do_HEAD(self):
        self._headers_comunes(len(self.payload))

    def do_GET(self):
        rango = self.headers.get("Range")
        if rango and self.accept_ranges:
            match = re.match(r"bytes=(\d+)-(\d*)", rango)
            inicio = int(match.group(1))
            fin = int(match.group(2)) if match.group(2) else len(self.payload) - 1
            trozo = self.payload[inicio:fin + 1]
            self._headers_comunes(len(trozo), 206,
                                  f"bytes {inicio}-{fin}/{len(self.payload)}")
            self.wfile.write(trozo)
        else:
            self._headers_comunes(len(self.payload))
            self.wfile.write(self.payload)


@pytest.fixture
def servidor():
    """Devuelve una función que arranca un servidor con el contenido dado."""
    servidores = []

    def arrancar(payload, accept_ranges=True):
        handler = type("Handler", (_RangeHandler,),
                       {"payload": payload, "accept_ranges": accept_ranges})
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        hilo = threading.Thread(target=httpd.serve_forever, daemon=True)
        hilo.start()
        servidores.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}/archivo.pkg"

    yield arrancar
    for httpd in servidores:
        httpd.shutdown()


def _contenido(n_bytes):
    return bytes((i * 7 + 13) % 256 for i in range(n_bytes))


class TestDescargaCompleta:
    def test_multihilo_reconstruye_el_archivo_intacto(self, servidor, tmp_path):
        datos = _contenido(8 * MB)
        url = servidor(datos)
        destino = str(tmp_path / "juego.pkg")

        d = FileDownloader(threads_per_download=8)
        d.download(url, destino)

        assert os.path.getsize(destino) == len(datos)
        assert hashlib.sha256(open(destino, "rb").read()).hexdigest() == \
               hashlib.sha256(datos).hexdigest()

    def test_archivo_pequeno_va_por_un_solo_hilo(self, servidor, tmp_path):
        """Antes se troceaba igualmente y salían rangos 'bytes=0--1'."""
        datos = _contenido(500)
        url = servidor(datos)
        destino = str(tmp_path / "avatar.pkg")

        hilos_vistos = []
        d = FileDownloader(threads_per_download=16,
                           on_progress=lambda f, s, h: hilos_vistos.append(h))
        d.download(url, destino)

        assert open(destino, "rb").read() == datos
        assert set(hilos_vistos) == {1}

    def test_servidor_sin_soporte_de_rangos(self, servidor, tmp_path):
        datos = _contenido(4 * MB)
        url = servidor(datos, accept_ranges=False)
        destino = str(tmp_path / "juego.pkg")

        FileDownloader(threads_per_download=8).download(url, destino)
        assert open(destino, "rb").read() == datos

    def test_no_queda_ningun_part(self, servidor, tmp_path):
        url = servidor(_contenido(4 * MB))
        FileDownloader(threads_per_download=4).download(url, str(tmp_path / "j.pkg"))
        assert [f for f in os.listdir(tmp_path) if f.endswith(".part")] == []

    def test_crea_las_carpetas_intermedias(self, servidor, tmp_path):
        url = servidor(_contenido(1024))
        destino = str(tmp_path / "PS3" / "Juego [BLES1]" / "Base" / "j.pkg")
        FileDownloader().download(url, destino)
        assert os.path.exists(destino)


class TestReanudacion:
    def test_continua_desde_un_part_existente(self, servidor, tmp_path):
        datos = _contenido(3 * MB)
        url = servidor(datos)
        destino = tmp_path / "juego.pkg"
        parcial = tmp_path / "juego.pkg.part"
        parcial.write_bytes(datos[:1 * MB])

        FileDownloader(threads_per_download=8).download(url, str(destino))
        assert destino.read_bytes() == datos

    def test_part_ya_completo_se_promociona(self, servidor, tmp_path):
        datos = _contenido(2 * MB)
        url = servidor(datos)
        destino = tmp_path / "juego.pkg"
        (tmp_path / "juego.pkg.part").write_bytes(datos)

        FileDownloader().download(url, str(destino))
        assert destino.read_bytes() == datos


class TestControl:
    def test_la_cancelacion_aborta(self, servidor, tmp_path):
        url = servidor(_contenido(8 * MB))

        llamadas = []

        def cancelar_pronto():
            llamadas.append(1)
            if len(llamadas) > 3:
                raise DownloadCancelled()

        d = FileDownloader(threads_per_download=4, check_control=cancelar_pronto)
        with pytest.raises(DownloadCancelled):
            d.download(url, str(tmp_path / "juego.pkg"))
        assert not os.path.exists(tmp_path / "juego.pkg")

    def test_se_reporta_progreso_y_estado(self, servidor, tmp_path):
        url = servidor(_contenido(6 * MB))
        progreso, estados = [], []

        d = FileDownloader(threads_per_download=6,
                           on_progress=lambda f, s, h: progreso.append(f),
                           on_status=estados.append)
        d.download(url, str(tmp_path / "juego.pkg"))

        assert progreso and progreso[-1] == 1.0
        assert all(0.0 <= f <= 1.0 for f in progreso)
        assert any("Finalizado" in e for e in estados)


class TestAislamientoDeLaInterfaz:
    def test_el_motor_no_arrastra_tkinter(self):
        """
        La razón de existir de psnkiller.downloader: si vuelve a depender de Tk,
        vuelve a ser posible tocar widgets desde un hilo de descarga.
        """
        import subprocess
        import sys

        codigo = (
            "import sys; import psnkiller.downloader; "
            "modulos = [m for m in sys.modules if m == 'tkinter' or m.startswith('tkinter.') "
            "or m == 'customtkinter']; "
            "print(','.join(modulos))"
        )
        salida = subprocess.run(
            [sys.executable, "-c", codigo],
            capture_output=True, text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        assert salida.returncode == 0, salida.stderr
        assert salida.stdout.strip() == "", f"el motor importa {salida.stdout.strip()}"

    @pytest.mark.parametrize("modulo", ["psnkiller.catalog", "psnkiller.naming", "psnkiller.models"])
    def test_los_modulos_de_logica_tampoco(self, modulo):
        import subprocess
        import sys

        codigo = (
            f"import sys; import {modulo}; "
            "print(','.join(m for m in sys.modules if m == 'tkinter' or m == 'customtkinter'))"
        )
        salida = subprocess.run(
            [sys.executable, "-c", codigo],
            capture_output=True, text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        assert salida.stdout.strip() == ""


class TestReanudacionMultihilo:
    """
    Pausar una descarga multihilo tiraba el .part entero: en un .pkg de 40 GB
    se perdia todo lo bajado y el reintento caia a monohilo.
    """

    def test_lo_ya_descargado_no_se_vuelve_a_pedir(self, servidor, tmp_path):
        datos = _contenido(8 * MB)
        url = servidor(datos)
        destino = str(tmp_path / "juego.pkg")
        parcial = tmp_path / "juego.pkg.part"

        # Simula una descarga interrumpida a mitad: .part preasignado con la
        # primera mitad de cada rango escrita.
        from psnkiller.downloader import save_part_state, split_ranges
        rangos = split_ranges(len(datos), 4)
        parcial.write_bytes(bytearray(len(datos)))
        con_datos = bytearray(parcial.read_bytes())
        hechos = []
        for inicio, fin in rangos:
            mitad = (fin - inicio + 1) // 2
            con_datos[inicio:inicio + mitad] = datos[inicio:inicio + mitad]
            hechos.append(mitad)
        parcial.write_bytes(bytes(con_datos))
        save_part_state(str(parcial), url, len(datos), rangos, hechos)

        FileDownloader(threads_per_download=4).download(url, destino)

        assert open(destino, "rb").read() == datos, "el archivo reanudado no coincide"
        assert not parcial.exists()
        assert not os.path.exists(str(parcial) + ".json")

    def test_al_cancelar_se_guarda_el_estado(self, servidor, tmp_path):
        url = servidor(_contenido(12 * MB))
        destino = str(tmp_path / "juego.pkg")
        parcial = str(tmp_path / "juego.pkg.part")

        llamadas = []

        def cancelar_a_medias():
            llamadas.append(1)
            if len(llamadas) > 60:
                raise DownloadCancelled()

        d = FileDownloader(threads_per_download=4, check_control=cancelar_a_medias)
        with pytest.raises(DownloadCancelled):
            d.download(url, destino)

        assert os.path.exists(parcial), "el .part debe conservarse para reanudar"
        assert os.path.exists(parcial + ".json"), "debe quedar el estado por rangos"

    def test_cancelar_y_reanudar_produce_el_archivo_correcto(self, servidor, tmp_path):
        datos = _contenido(12 * MB)
        url = servidor(datos)
        destino = str(tmp_path / "juego.pkg")

        llamadas = []

        def cancelar_a_medias():
            llamadas.append(1)
            if len(llamadas) > 60:
                raise DownloadCancelled()

        with pytest.raises(DownloadCancelled):
            FileDownloader(threads_per_download=4, check_control=cancelar_a_medias).download(url, destino)

        # Segunda pasada sin interrupciones: debe completar y coincidir byte a byte.
        FileDownloader(threads_per_download=4).download(url, destino)
        assert open(destino, "rb").read() == datos

    def test_cambiar_el_numero_de_hilos_no_rompe_la_reanudacion(self, servidor, tmp_path):
        """Los rangos guardados mandan sobre los que tocarian con la config nueva."""
        datos = _contenido(12 * MB)
        url = servidor(datos)
        destino = str(tmp_path / "juego.pkg")

        llamadas = []

        def cancelar(*_):
            llamadas.append(1)
            if len(llamadas) > 60:
                raise DownloadCancelled()

        with pytest.raises(DownloadCancelled):
            FileDownloader(threads_per_download=8, check_control=cancelar).download(url, destino)

        FileDownloader(threads_per_download=3).download(url, destino)   # otro numero de hilos
        assert open(destino, "rb").read() == datos


class TestEstadoDelPart:
    """load_part_state debe rechazar todo estado del que no pueda fiarse."""

    def _preparar(self, tmp_path, total=1024):
        from psnkiller.downloader import save_part_state
        parcial = tmp_path / "x.pkg.part"
        parcial.write_bytes(bytearray(total))
        rangos = [(0, 511), (512, 1023)]
        save_part_state(str(parcial), "http://a/b.pkg", total, rangos, [100, 200])
        return str(parcial), total

    def test_estado_valido_se_acepta(self, tmp_path):
        from psnkiller.downloader import load_part_state
        parcial, total = self._preparar(tmp_path)
        assert load_part_state(parcial, "http://a/b.pkg", total) == [(0, 511, 100), (512, 1023, 200)]

    def test_url_distinta_se_rechaza(self, tmp_path):
        from psnkiller.downloader import load_part_state
        parcial, total = self._preparar(tmp_path)
        assert load_part_state(parcial, "http://otro/b.pkg", total) is None

    def test_tamano_distinto_se_rechaza(self, tmp_path):
        from psnkiller.downloader import load_part_state
        parcial, _ = self._preparar(tmp_path)
        assert load_part_state(parcial, "http://a/b.pkg", 2048) is None

    def test_part_no_preasignado_se_rechaza(self, tmp_path):
        from psnkiller.downloader import load_part_state
        parcial, total = self._preparar(tmp_path)
        with open(parcial, "wb") as f:
            f.write(b"corto")
        assert load_part_state(parcial, "http://a/b.pkg", total) is None

    def test_sin_part_se_rechaza(self, tmp_path):
        from psnkiller.downloader import load_part_state
        parcial, total = self._preparar(tmp_path)
        os.remove(parcial)
        assert load_part_state(parcial, "http://a/b.pkg", total) is None

    def test_json_corrupto_se_rechaza(self, tmp_path):
        from psnkiller.downloader import load_part_state, part_state_path
        parcial, total = self._preparar(tmp_path)
        with open(part_state_path(parcial), "w") as f:
            f.write("{roto")
        assert load_part_state(parcial, "http://a/b.pkg", total) is None

    def test_contador_imposible_se_rechaza(self, tmp_path):
        from psnkiller.downloader import load_part_state, part_state_path, save_part_state
        parcial, total = self._preparar(tmp_path)
        save_part_state(parcial, "http://a/b.pkg", total, [(0, 511), (512, 1023)], [999999, 0])
        assert load_part_state(parcial, "http://a/b.pkg", total) is None
        assert os.path.exists(part_state_path(parcial))

    def test_rangos_con_hueco_se_rechazan(self, tmp_path):
        from psnkiller.downloader import load_part_state, save_part_state
        parcial = tmp_path / "y.pkg.part"
        parcial.write_bytes(bytearray(1024))
        save_part_state(str(parcial), "http://a/b.pkg", 1024, [(0, 100), (512, 1023)], [0, 0])
        assert load_part_state(str(parcial), "http://a/b.pkg", 1024) is None

    def test_clear_part_state_borra_todo(self, tmp_path):
        from psnkiller.downloader import clear_part_state, part_state_path
        parcial, _ = self._preparar(tmp_path)
        clear_part_state(parcial)
        assert not os.path.exists(part_state_path(parcial))
        clear_part_state(parcial)   # idempotente
