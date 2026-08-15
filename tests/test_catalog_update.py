"""Actualización de catálogos: verificación de integridad contra el manifiesto."""
import hashlib
import json

import pytest

import app


class _RespuestaFalsa:
    def __init__(self, content=b"", payload=None, status_ok=True):
        self.content = content
        self._payload = payload
        self._ok = status_ok

    def raise_for_status(self):
        if not self._ok:
            raise app.requests.RequestException("500")

    def json(self):
        if self._payload is None:
            raise ValueError("no es JSON")
        return self._payload


@pytest.fixture
def update_app(catalog_app):
    catalog_app.app_config = dict(app.DEFAULT_APP_CONFIG)
    return catalog_app


class TestFetchCatalogManifest:
    def test_extrae_los_hashes(self, update_app, monkeypatch):
        payload = {"catalogs": {
            "PS3_GAMES.tsv": {"sha256": "a" * 64, "rows": 10},
            "PS3_DLCS.tsv": {"sha256": "b" * 64},
        }}
        monkeypatch.setattr(app.requests, "get", lambda *a, **k: _RespuestaFalsa(payload=payload))
        assert update_app.fetch_catalog_manifest() == {"PS3_GAMES.tsv": "a" * 64, "PS3_DLCS.tsv": "b" * 64}

    def test_descarta_hashes_invalidos(self, update_app, monkeypatch):
        payload = {"catalogs": {
            "PS3_GAMES.tsv": {"sha256": "no-es-un-hash"},
            "PS3_DLCS.tsv": {"sha256": "b" * 64},
        }}
        monkeypatch.setattr(app.requests, "get", lambda *a, **k: _RespuestaFalsa(payload=payload))
        assert update_app.fetch_catalog_manifest() == {"PS3_DLCS.tsv": "b" * 64}

    def test_fuente_sin_manifiesto_no_es_un_error(self, update_app, monkeypatch):
        """Sólo PSN-Killer-Database lo publica; con NoPayStation se sigue igual."""
        def falla(*a, **k):
            raise app.requests.RequestException("404")
        monkeypatch.setattr(app.requests, "get", falla)
        assert update_app.fetch_catalog_manifest() == {}

    def test_respuesta_que_no_es_json(self, update_app, monkeypatch):
        monkeypatch.setattr(app.requests, "get", lambda *a, **k: _RespuestaFalsa(payload=None))
        assert update_app.fetch_catalog_manifest() == {}

    def test_json_sin_la_clave_catalogs(self, update_app, monkeypatch):
        monkeypatch.setattr(app.requests, "get", lambda *a, **k: _RespuestaFalsa(payload={"otra": 1}))
        assert update_app.fetch_catalog_manifest() == {}


class TestVerificacionAlActualizar:
    """
    Un TSV truncado a mitad de descarga puede seguir pareciendo válido: tiene
    filas con URL y quizá supera el umbral de tamaño. Sólo el hash lo detecta.
    """

    TSV = (
        b"Title ID\tRegion\tName\tPKG direct link\n"
        b"BLES00483\tEU\tKillzone 2\thttp://x/y.pkg\n"
        b"BLUS30109\tUS\tOtro Juego\thttp://x/z.pkg\n"
    )

    @pytest.fixture
    def entorno(self, update_app, tmp_path, monkeypatch):
        monkeypatch.setattr(app, "DATA_DIR", str(tmp_path))
        monkeypatch.setattr(app, "CATALOG_BACKUP_DIR", str(tmp_path / "backups"))
        monkeypatch.setattr(app, "CATALOG_STATE_PATH", str(tmp_path / "state.json"))
        monkeypatch.setattr(app, "CATALOG_DB_PATH", str(tmp_path / "c.sqlite3"))
        (tmp_path / "backups").mkdir()
        monkeypatch.setattr(update_app, "load_all_data", lambda populate=True: None)
        monkeypatch.setattr(update_app, "ui", lambda *a, **k: None)
        monkeypatch.setattr(update_app, "record_history", lambda *a, **k: None)
        return update_app, tmp_path

    def _ejecutar(self, a, tmp_path, monkeypatch, contenido, manifiesto):
        monkeypatch.setattr(a, "fetch_catalog_manifest", lambda: manifiesto)
        monkeypatch.setattr(app.requests, "get", lambda *ar, **k: _RespuestaFalsa(content=contenido))
        a._update_catalogs_worker({"PS3_GAMES.tsv": {"primary": "http://x/PS3_GAMES.tsv", "fallbacks": []}})
        destino = tmp_path / "PS3_GAMES.tsv"
        estado = json.loads((tmp_path / "state.json").read_text()) if (tmp_path / "state.json").exists() else {}
        return destino, estado

    def test_hash_correcto_se_acepta(self, entorno, monkeypatch):
        a, tmp_path = entorno
        bueno = hashlib.sha256(self.TSV).hexdigest()
        destino, estado = self._ejecutar(a, tmp_path, monkeypatch, self.TSV, {"PS3_GAMES.tsv": bueno})
        assert destino.exists()
        assert estado["PS3_GAMES.tsv"]["sha256_verified"] is True
        assert estado["PS3_GAMES.tsv"]["sha256"] == bueno

    def test_hash_incorrecto_se_rechaza(self, entorno, monkeypatch):
        a, tmp_path = entorno
        destino, estado = self._ejecutar(a, tmp_path, monkeypatch, self.TSV, {"PS3_GAMES.tsv": "c" * 64})
        assert not destino.exists(), "un TSV con hash que no cuadra no debe instalarse"
        assert "PS3_GAMES.tsv" not in estado

    def test_no_deja_el_temporal_al_rechazar(self, entorno, monkeypatch):
        a, tmp_path = entorno
        self._ejecutar(a, tmp_path, monkeypatch, self.TSV, {"PS3_GAMES.tsv": "c" * 64})
        assert not (tmp_path / "PS3_GAMES.tsv.tmp").exists()

    def test_sin_manifiesto_sigue_la_validacion_normal(self, entorno, monkeypatch):
        a, tmp_path = entorno
        destino, estado = self._ejecutar(a, tmp_path, monkeypatch, self.TSV, {})
        assert destino.exists()
        assert estado["PS3_GAMES.tsv"]["sha256_verified"] is False

    def test_un_tsv_truncado_pasa_la_heuristica_pero_no_el_hash(self, entorno, monkeypatch):
        """Justificación de todo esto: la validación por filas no lo detectaba."""
        a, tmp_path = entorno
        truncado = self.TSV[:-15]
        # Sin hash: la heurística lo da por bueno.
        destino, _ = self._ejecutar(a, tmp_path, monkeypatch, truncado, {})
        assert destino.exists()
        destino.unlink()
        # Con hash del archivo completo: se rechaza.
        completo = hashlib.sha256(self.TSV).hexdigest()
        destino, _ = self._ejecutar(a, tmp_path, monkeypatch, truncado, {"PS3_GAMES.tsv": completo})
        assert not destino.exists()
