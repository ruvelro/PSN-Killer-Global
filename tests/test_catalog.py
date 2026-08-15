"""Parseo, normalización y deduplicación del catálogo."""
import pytest

from psnkiller import catalog as app


class TestRegion:
    @pytest.mark.parametrize("title_id,region", [
        ("BLUS30109", "US"), ("BCUS98111", "US"), ("NPUB30740", "US"),
        ("BLES00483", "EU"), ("BCES00065", "EU"), ("NPEB00219", "EU"),
        ("BLJS10001", "JP"), ("NPJB00123", "JP"), ("BCJS30001", "JP"),
        ("BCAS20001", "ASIA"), ("NPHA80001", "ASIA"), ("BLAS50001", "ASIA"),
    ])
    def test_prefijos_conocidos(self, title_id, region):
        assert app.auto_detect_region(title_id) == region

    def test_japones_y_asiatico_se_distinguen(self):
        """Los catalogos usan JP para los japoneses; antes ambos daban ASIA."""
        assert app.auto_detect_region("BLJS10001") == "JP"
        assert app.auto_detect_region("NPHA80001") == "ASIA"

    @pytest.mark.parametrize("title_id", ["XXXX00000", "", "AB"])
    def test_desconocido_es_all(self, title_id):
        assert app.auto_detect_region(title_id) == "ALL"

    def test_no_distingue_mayusculas(self):
        assert app.auto_detect_region("blus30109") == "US"

    @pytest.mark.parametrize("base,candidato,compatible", [
        ("EU", "EU", True), ("EU", "ALL", True), ("EU", "FREE", True),
        ("EU", "INT", True), ("EU", "US", False), ("", "US", True),
        # Los catalogos etiquetan el mismo contenido japones como JP o ASIA.
        ("JP", "ASIA", True), ("ASIA", "JP", True),
        ("JP", "US", False), ("ASIA", "EU", False),
    ])
    def test_compatibilidad(self, base, candidato, compatible):
        assert app.compatible_region(base, candidato) is compatible


class TestTamanos:
    @pytest.mark.parametrize("texto,esperado", [
        ("1.5 GB", 1610612736), ("100 MB", 104857600), ("512 KB", 524288), ("2 TB", 2199023255552),
    ])
    def test_parseo(self, texto, esperado):
        assert app.parse_size_to_bytes(texto) == esperado

    @pytest.mark.parametrize("texto", ["N/A", "Sin tamaño", "No disponible", "", "cinco", None])
    def test_valores_no_numericos_son_cero(self, texto):
        assert app.parse_size_to_bytes(texto) == 0

    @pytest.mark.parametrize("valor,esperado", [
        (0, "N/A"), (-5, "N/A"), (512, "512 B"), (1536, "2 KB"),
        (5 * 1024 ** 2, "5.0 MB"), (5 * 1024 ** 3, "5.00 GB"),
    ])
    def test_formato(self, valor, esperado):
        assert app.format_bytes(valor) == esperado

    def test_formato_tolera_basura(self):
        assert app.format_bytes("no-es-un-numero") == "N/A"

    def test_ida_y_vuelta(self):
        assert app.parse_size_to_bytes(app.format_bytes(5 * 1024 ** 3)) == 5 * 1024 ** 3

    def test_velocidad_cero(self):
        assert app.format_speed(0) == "0 KB/s"

    def test_velocidad_alta_incluye_mbps(self):
        assert "Mbps" in app.format_speed(10 * 1024 ** 2)


class TestVersiones:
    def test_separa_version_pegada_al_nombre(self):
        assert app.split_name_and_version("Killzone 2 v01.29") == ("Killzone 2", "v01.29")

    def test_sin_version_usa_el_valor_por_defecto(self):
        assert app.split_name_and_version("Killzone 2") == ("Killzone 2", "Base")

    def test_extrae_version_de_un_texto(self):
        assert app.extract_version_from_text("Update v1.05") == "v1.05"

    def test_sin_version_devuelve_el_defecto(self):
        assert app.extract_version_from_text("sin nada") == "v01.00"

    @pytest.mark.parametrize("version,esperado", [
        ("v01.29", (1, 29)), ("v1.5", (1, 5)), ("", (0,)), (None, (0,)),
    ])
    def test_tupla_comparable(self, version, esperado):
        assert app.version_tuple(version) == esperado

    def test_ordena_correctamente(self):
        versiones = ["v01.02", "v01.10", "v01.09", "v02.00"]
        ordenadas = sorted(versiones, key=app.version_tuple)
        assert ordenadas[-1] == "v02.00"
        # v01.10 es posterior a v01.09 aunque sea "menor" alfabéticamente
        assert ordenadas.index("v01.10") > ordenadas.index("v01.09")


class TestNormalizacionDeTitulos:
    def test_quita_marcas_y_ediciones(self):
        assert app.normalize_title("LittleBigPlanet™ GOTY Edition") == "littlebigplanet"

    def test_unifica_little_big_planet(self):
        assert app.normalize_title("Little Big Planet") == app.normalize_title("LittleBigPlanet")

    def test_conflicto_de_numeros(self):
        assert app.has_number_conflict("Uncharted 2", "Uncharted 3") is True
        assert app.has_number_conflict("Uncharted 2", "Uncharted 2 Among Thieves") is False

    def test_similitud_alta_en_subcadena(self):
        assert app.title_similarity("Uncharted 2", "Uncharted 2 Among Thieves") >= 0.82

    def test_similitud_baja_entre_titulos_distintos(self):
        assert app.title_similarity("Killzone 2", "Gran Turismo 5") < 0.5

    def test_similitud_con_vacios(self):
        assert app.title_similarity("", "algo") == 0.0


class TestValidaciones:
    @pytest.mark.parametrize("url,valida", [
        ("http://a/b.pkg", True), ("https://a/b.pkg", True),
        ("ftp://a/b.pkg", False), ("MISSING", False), ("", False), (None, False),
    ])
    def test_url_descargable(self, url, valida):
        assert app.is_valid_download_url(url) is valida

    @pytest.mark.parametrize("valor", ["MISSING", "N/A", "NA", "", "   ", None])
    def test_valores_ausentes(self, valor):
        assert app.is_missing_value(valor) is True

    def test_sha256_valido(self):
        assert app.valid_sha256("a" * 64) is True

    @pytest.mark.parametrize("valor", ["a" * 63, "z" * 64, "", None, "MISSING"])
    def test_sha256_invalido(self, valor):
        assert app.valid_sha256(valor) is False


class TestDeduplicacion:
    """add_content_item usa un índice; debe conservar el elemento de mayor calidad."""

    def _añadir(self, catalog_app, **kwargs):
        base = dict(platform="PS3", category="Juegos", title_id="BLES00483", region="EU",
                    name="Killzone 2", version="Base", size="10 GB", url="http://x/y.pkg")
        base.update(kwargs)
        return catalog_app.add_content_item(**base)

    def test_elemento_nuevo_se_añade(self, catalog_app):
        self._añadir(catalog_app)
        assert len(catalog_app.catalog["PS3"]["Juegos"]) == 1

    def test_duplicado_exacto_no_crece(self, catalog_app):
        self._añadir(catalog_app)
        self._añadir(catalog_app)
        assert len(catalog_app.catalog["PS3"]["Juegos"]) == 1

    def test_gana_el_que_tiene_sha256(self, catalog_app):
        self._añadir(catalog_app)
        self._añadir(catalog_app, sha256="a" * 64)
        items = catalog_app.catalog["PS3"]["Juegos"]
        assert len(items) == 1
        assert items[0].sha256 == "a" * 64

    def test_no_degrada_un_elemento_mejor(self, catalog_app):
        self._añadir(catalog_app, sha256="a" * 64)
        self._añadir(catalog_app)
        assert catalog_app.catalog["PS3"]["Juegos"][0].sha256 == "a" * 64

    def test_content_id_distingue_elementos(self, catalog_app):
        self._añadir(catalog_app, category="DLCs", content_id="UP0001-X_00-DLC001", url="")
        self._añadir(catalog_app, category="DLCs", content_id="UP0001-X_00-DLC002", url="")
        assert len(catalog_app.catalog["PS3"]["DLCs"]) == 2

    def test_el_indice_sigue_a_la_lista(self, catalog_app):
        self._añadir(catalog_app)
        self._añadir(catalog_app, title_id="BLUS30109", name="Otro")
        items = catalog_app.catalog["PS3"]["Juegos"]
        for item in items:
            indice = catalog_app.catalog_index[app.catalog_item_key(item)]
            assert items[indice] is item

    def test_reset_limpia_los_indices(self, catalog_app):
        self._añadir(catalog_app)
        catalog_app.reset_catalog()
        assert catalog_app.catalog_index == {}
        assert catalog_app.content_by_url == {}
        assert catalog_app.catalog["PS3"]["Juegos"] == []


class TestParseoDeFilas:
    def test_fila_con_cabecera(self, catalog_app):
        cabecera = {"title id": 0, "region": 1, "name": 2, "pkg direct link": 3, "file size": 4}
        fila = ["BLES00483", "EU", "Killzone 2", "http://x/y.pkg", "10737418240"]
        r = catalog_app.parse_catalog_row("PS3", "Juegos", fila, cabecera)
        assert r["title_id"] == "BLES00483"
        assert r["name"] == "Killzone 2"
        assert r["url"] == "http://x/y.pkg"
        assert r["size"] == "10.00 GB"

    def test_la_fila_de_cabecera_se_descarta(self, catalog_app):
        assert catalog_app.parse_catalog_row("PS3", "Juegos", ["Title ID", "Region"], None) is None

    def test_fila_vacia(self, catalog_app):
        assert catalog_app.parse_catalog_row("PS3", "Juegos", [], None) is None

    def test_region_deducida_si_falta(self, catalog_app):
        cabecera = {"title id": 0, "name": 1, "pkg direct link": 2}
        r = catalog_app.parse_catalog_row("PS3", "Juegos", ["BLUS30109", "Juego", "http://x/y.pkg"], cabecera)
        assert r["region"] == "US"

    def test_sin_url_marca_no_disponible(self, catalog_app):
        cabecera = {"title id": 0, "name": 1, "pkg direct link": 2}
        r = catalog_app.parse_catalog_row("PS3", "Juegos", ["BLES1", "Juego", "MISSING"], cabecera)
        assert r["url"] == ""
        assert r["size"] == "No disponible"

    def test_updates_ps3_sin_cabecera(self, catalog_app):
        """Formato heredado de clean_updates.py: id, nombre, versión, url."""
        fila = ["BLES00483", "Killzone 2", "v01.29", "http://x/y.pkg"]
        r = catalog_app.parse_catalog_row("PS3", "Updates", fila, None)
        assert r["version"] == "v01.29"
        assert r["name"] == "Killzone 2"

    def test_nombre_hexadecimal_se_sustituye(self, catalog_app):
        cabecera = {"title id": 0, "name": 1, "pkg direct link": 2}
        r = catalog_app.parse_catalog_row("PS3", "DLCs", ["BLES1", "a" * 20, "http://x/y.pkg"], cabecera)
        assert r["name"] == "Contenido (BLES1)"
