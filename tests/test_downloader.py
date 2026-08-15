"""Motor de descarga: troceado por rangos y sesión HTTP."""
import pytest
import requests

import app

MB = 1024 * 1024


class TestPlanThreadCount:
    @pytest.mark.parametrize("total,pedidos,esperado", [
        (0, 16, 1),               # tamaño desconocido
        (100, 16, 1),             # más pequeño que el número de hilos
        (500 * 1024, 16, 1),      # menos de 1 MB
        (1 * MB, 16, 1),
        (7 * MB, 16, 7),
        (40 * 1024 * MB, 16, 16),  # tope en lo pedido
        (40 * 1024 * MB, 1, 1),
    ])
    def test_conteo(self, total, pedidos, esperado):
        assert app.plan_thread_count(total, pedidos) == esperado

    def test_nunca_devuelve_cero(self):
        for total in [0, 1, 10, 1000, MB - 1]:
            assert app.plan_thread_count(total, 16) >= 1

    @pytest.mark.parametrize("total", [10, 100, 1000, MB, 7 * MB, 40 * 1024 * MB])
    def test_los_rangos_generados_son_validos(self, total):
        """
        Replica el troceado real de _requests_fast_download.

        El fallo que esto cubre: con chunk_size 0 se emitían cabeceras
        'Range: bytes=0--1' que el servidor rechaza.
        """
        n = app.plan_thread_count(total, 16)
        chunk = total // n
        rangos = [
            (i * chunk, (total - 1) if i == n - 1 else (i * chunk + chunk - 1))
            for i in range(n)
        ]
        for inicio, fin in rangos:
            assert 0 <= inicio <= fin < total, f"rango inválido {inicio}-{fin} para total={total}"
        assert rangos[0][0] == 0
        assert rangos[-1][1] == total - 1
        # sin huecos ni solapamientos
        for (_, fin), (inicio, _) in zip(rangos, rangos[1:]):
            assert inicio == fin + 1


class TestDownloadSession:
    def test_el_pool_cubre_todos_los_hilos(self):
        """
        Con el HTTPAdapter por defecto (pool_maxsize=10) y 16 hilos, las
        conexiones sobrantes se descartaban y recreaban continuamente.
        """
        session = app.build_download_session(16)
        for esquema in ("https://", "http://"):
            adapter = session.get_adapter(f"{esquema}example.com")
            assert adapter._pool_maxsize == 16
            assert adapter._pool_connections == 16
        session.close()

    def test_cabeceras_de_navegador(self):
        session = app.build_download_session(4)
        assert "User-Agent" in session.headers
        # identity evita que el servidor comprima y desalinee los rangos
        assert session.headers["Accept-Encoding"] == "identity"
        session.close()

    def test_es_una_session_de_requests(self):
        session = app.build_download_session(4)
        assert isinstance(session, requests.Session)
        session.close()


class TestCategorias:
    @pytest.mark.parametrize("categoria,carpeta", [
        ("Juegos", "Base"), ("Updates", "Updates"), ("DLCs", "DLCs"),
        ("Temas", "Temas"), ("Avatares", "Avatares"), ("Demos", "Demos"),
    ])
    def test_carpeta_por_categoria(self, categoria, carpeta):
        assert app.category_folder(categoria) == carpeta

    def test_ida_y_vuelta_con_el_escaneo(self):
        """Las carpetas que crea la descarga deben ser las que reconoce el escaneo."""
        for categoria in ["Juegos", "Updates", "DLCs", "Temas", "Avatares", "Demos"]:
            carpeta = app.category_folder(categoria)
            assert app.DOWNLOAD_FOLDER_TO_CATEGORY[carpeta] == categoria


class TestSha256:
    def test_calculo(self, tmp_path):
        f = tmp_path / "x.bin"
        f.write_bytes(b"hola mundo")
        import hashlib
        assert app.calculate_sha256(str(f)) == hashlib.sha256(b"hola mundo").hexdigest()

    def test_archivo_grande_por_bloques(self, tmp_path):
        f = tmp_path / "grande.bin"
        datos = b"x" * (3 * MB + 7)
        f.write_bytes(datos)
        import hashlib
        assert app.calculate_sha256(str(f)) == hashlib.sha256(datos).hexdigest()
