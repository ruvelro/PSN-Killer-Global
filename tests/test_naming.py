"""Nombres de archivo y rutas: deben ser válidos en Windows, Linux y macOS."""
import os

import pytest

import app


class TestSanitizeFilename:
    @pytest.mark.parametrize("entrada,esperado", [
        ("Ratchet: Size Matters", "Ratchet - Size Matters"),
        ("God of War / Ascension", "God of War - Ascension"),
        (r"Test\Path|Name", "Test -Path -Name"),
        ('Que? "Raro" <esto>', "Que Raro esto"),
        ("  espacios   colapsados  ", "espacios colapsados"),
    ])
    def test_caracteres_prohibidos(self, entrada, esperado):
        assert app.sanitize_filename(entrada) == esperado

    @pytest.mark.parametrize("reservado", ["CON", "PRN", "AUX", "NUL", "COM1", "LPT9"])
    def test_nombres_reservados_de_windows(self, reservado):
        """Windows no deja crear estos archivos ni con extensión."""
        assert app.sanitize_filename(reservado) == f"_{reservado}"
        assert app.sanitize_filename(f"{reservado}.pkg") == f"_{reservado}.pkg"

    def test_nombre_reservado_como_prefijo_es_valido(self):
        assert app.sanitize_filename("CONTRA") == "CONTRA"

    @pytest.mark.parametrize("entrada", ["Final Fantasy...", "Final Fantasy   ", "Final Fantasy. . "])
    def test_puntos_y_espacios_finales(self, entrada):
        """Windows los recorta en silencio, dejando el manifest sin corresponder con el disco."""
        assert app.sanitize_filename(entrada) == "Final Fantasy"

    def test_caracteres_de_control(self):
        assert app.sanitize_filename("Gran\x00\x07 Turismo\x1f") == "Gran Turismo"

    def test_nunca_devuelve_cadena_vacia(self):
        assert app.sanitize_filename("???") == "sin_nombre"
        assert app.sanitize_filename("") == "sin_nombre"
        assert app.sanitize_filename(None) == "sin_nombre"

    def test_longitud_maxima(self):
        assert len(app.sanitize_filename("A" * 300)) == app.MAX_NAME_LENGTH

    def test_conserva_caracteres_no_ascii(self):
        assert app.sanitize_filename("オリジナル衣装") == "オリジナル衣装"


class TestClampPathLength:
    def test_ruta_corta_intacta(self):
        ruta = os.path.join("dir", "archivo.pkg")
        assert app.clamp_path_length(ruta) == ruta

    def test_recorta_por_encima_del_limite(self, monkeypatch):
        monkeypatch.setattr(app, "MAX_PATH_LENGTH", 120)
        ruta = os.path.join("carpeta", "N" * 300 + ".pkg")
        recortada = app.clamp_path_length(ruta)
        assert len(recortada) <= 120
        assert recortada.endswith(".pkg")

    def test_no_colisionan_titulos_con_prefijo_comun(self, monkeypatch):
        monkeypatch.setattr(app, "MAX_PATH_LENGTH", 120)
        a = app.clamp_path_length(os.path.join("d", "X" * 200 + "Alpha.pkg"))
        b = app.clamp_path_length(os.path.join("d", "X" * 200 + "Beta.pkg"))
        assert a != b


class TestItemFilename:
    def _item(self, **kwargs):
        base = dict(category="Juegos", title_id="BLES00483", region="EU",
                    name="Killzone 2", version="Base", size="10 GB", url="http://x/y.pkg")
        base.update(kwargs)
        return app.ContentItem(**base)

    def test_version_base_no_aparece(self):
        assert app.item_filename(self._item()) == "Killzone 2.pkg"

    def test_version_real_si_aparece(self):
        assert app.item_filename(self._item(version="v01.29")) == "Killzone 2 v01.29.pkg"

    @pytest.mark.parametrize("version", ["Base", "N/A", "none", "BASE"])
    def test_versiones_vacias_equivalentes(self, version):
        assert app.item_filename(self._item(version=version)) == "Killzone 2.pkg"


class TestGameKey:
    def test_incluye_title_id(self):
        item = app.ContentItem("Juegos", "BLES00483", "EU", "Killzone 2", "Base", "10 GB", "u")
        assert app.game_key_for(item) == "Killzone 2 [BLES00483]"

    def test_sin_title_id(self):
        item = app.ContentItem("Juegos", "", "EU", "Suelto", "Base", "1 GB", "u")
        assert app.game_key_for(item) == "Suelto"

    def test_saneado(self):
        item = app.ContentItem("Juegos", "BLES1", "EU", "Ratchet: Size", "Base", "1 GB", "u")
        assert app.game_key_for(item) == "Ratchet - Size [BLES1]"


class TestUniquePath:
    def test_devuelve_la_misma_si_no_existe(self, tmp_path):
        ruta = str(tmp_path / "juego.pkg")
        assert app.unique_path(ruta) == ruta

    def test_evita_pisar_un_archivo_existente(self, tmp_path):
        ruta = tmp_path / "juego.pkg"
        ruta.touch()
        assert app.unique_path(str(ruta)) == str(tmp_path / "juego (1).pkg")

    def test_partial_path(self):
        assert app.partial_path("/d/j.pkg") == "/d/j.pkg.part"
