"""Biblioteca: rutas de destino, deduplicación de descargas y persistencia."""
import json
import os
import sqlite3
import threading

import pytest

import app


def _item(**kwargs):
    base = dict(category="Juegos", title_id="BLES00483", region="EU", name="Killzone 2",
                version="Base", size="10 GB", url="http://x/y.pkg", platform="PS3")
    base.update(kwargs)
    return app.ContentItem(**base)


class TestOwningGameItem:
    def test_un_juego_es_su_propio_dueño(self, catalog_app):
        juego = catalog_app.add_content_item(
            platform="PS3", category="Juegos", title_id="BLES00483", region="EU",
            name="Killzone 2", version="Base", size="10 GB", url="http://x/base.pkg")
        assert catalog_app.owning_game_item(juego) is juego

    def test_una_update_se_resuelve_a_su_juego(self, catalog_app):
        juego = catalog_app.add_content_item(
            platform="PS3", category="Juegos", title_id="BLES00483", region="EU",
            name="Killzone 2", version="Base", size="10 GB", url="http://x/base.pkg")
        update = _item(category="Updates", version="v01.29", url="http://x/u.pkg")
        assert catalog_app.owning_game_item(update) is juego

    def test_sin_juego_en_el_catalogo_se_queda_como_esta(self, catalog_app):
        huerfano = _item(category="DLCs", title_id="ZZZZ99999")
        assert catalog_app.owning_game_item(huerfano) is huerfano

    def test_sin_title_id_se_queda_como_esta(self, catalog_app):
        suelto = _item(category="DLCs", title_id="")
        assert catalog_app.owning_game_item(suelto) is suelto


class TestTargetPath:
    def test_estructura_de_carpetas(self, catalog_app, downloads_dir):
        juego = _item()
        gk = app.game_key_for(juego)
        ruta = catalog_app.target_path_for(juego, juego, gk)
        assert os.path.relpath(ruta, str(downloads_dir)) == os.path.join(
            "PS3", "Killzone 2 [BLES00483]", "Base", "Killzone 2.pkg")

    def test_las_updates_van_a_la_carpeta_del_juego(self, catalog_app, downloads_dir):
        juego = _item()
        update = _item(category="Updates", version="v01.29", url="http://x/u.pkg")
        gk = app.game_key_for(juego)
        ruta = catalog_app.target_path_for(juego, update, gk)
        assert os.path.relpath(ruta, str(downloads_dir)) == os.path.join(
            "PS3", "Killzone 2 [BLES00483]", "Updates", "Killzone 2 v01.29.pkg")

    def test_reintento_reutiliza_la_ruta_del_manifest(self, catalog_app, downloads_dir, monkeypatch):
        monkeypatch.setattr(app, "MANIFEST_PATH", str(downloads_dir / "m.json"))
        juego = _item()
        gk = app.game_key_for(juego)
        primera = catalog_app.target_path_for(juego, juego, gk)
        os.makedirs(os.path.dirname(primera), exist_ok=True)
        open(primera, "w").close()
        catalog_app.register_manifest_entry(juego, juego, gk, primera, "error")
        # Sin esto se generaría "Killzone 2 (1).pkg" en cada reintento.
        assert catalog_app.target_path_for(juego, juego, gk) == primera


class TestItemAlreadyPresent:
    def test_detecta_por_url(self, catalog_app):
        entradas = [{"platform": "PS3", "status": "complete", "url": "http://x/y.pkg"}]
        assert catalog_app.item_already_present(_item(), entradas) is True

    def test_ignora_las_descargas_incompletas(self, catalog_app):
        entradas = [{"platform": "PS3", "status": "queued", "url": "http://x/y.pkg"}]
        assert catalog_app.item_already_present(_item(), entradas) is False

    def test_detecta_por_nombre_de_archivo(self, catalog_app):
        entradas = [{"platform": "PS3", "status": "complete", "url": "",
                     "path": "/d/Killzone 2.pkg"}]
        assert catalog_app.item_already_present(_item(), entradas) is True

    def test_no_confunde_juegos_distintos(self, catalog_app):
        entradas = [{"platform": "PS3", "status": "complete", "url": "http://x/otro.pkg",
                     "path": "/d/Otro.pkg", "category": "Juegos", "title_id": "BLUS1",
                     "name": "Otro", "version": "Base"}]
        assert catalog_app.item_already_present(_item(), entradas) is False


class TestDownloadEntryIndex:
    def _entradas(self):
        return {
            "a": {"platform": "PS3", "url": "http://x/y.pkg", "path": "/d/Killzone 2.pkg",
                  "category": "Juegos", "title_id": "BLES00483", "name": "Killzone 2",
                  "version": "Base", "status": "complete"},
            "b": {"platform": "PSV", "url": "http://x/otro.pkg", "path": "/d/Otro.pkg",
                  "category": "Juegos", "title_id": "PCSB1", "name": "Otro",
                  "version": "Base", "status": "complete"},
        }

    def test_encuentra_lo_mismo_que_la_busqueda_lineal(self, catalog_app, monkeypatch):
        entradas = self._entradas()
        monkeypatch.setattr(catalog_app, "merged_download_entries", lambda: entradas)
        index = catalog_app.download_entry_index()

        item = _item()
        lineal = [e for e in entradas.values()
                  if e.get("platform", "PS3") == item.platform and app.same_catalog_item(item, e)]
        indexado = catalog_app.matching_download_entries_for_item(item, index)
        assert sorted(map(id, lineal)) == sorted(map(id, indexado))

    def test_no_cruza_plataformas(self, catalog_app, monkeypatch):
        entradas = self._entradas()
        monkeypatch.setattr(catalog_app, "merged_download_entries", lambda: entradas)
        index = catalog_app.download_entry_index()
        assert catalog_app.matching_download_entries_for_item(_item(), index) == [entradas["a"]]

    def test_sin_duplicados_cuando_coinciden_varios_criterios(self, catalog_app, monkeypatch):
        entradas = self._entradas()
        monkeypatch.setattr(catalog_app, "merged_download_entries", lambda: entradas)
        index = catalog_app.download_entry_index()
        # El item coincide por url, por nombre de archivo y por campos a la vez.
        assert len(catalog_app.matching_download_entries_for_item(_item(), index)) == 1


class TestCacheDeDescargas:
    def test_se_reutiliza(self, catalog_app, downloads_dir):
        primera = catalog_app.merged_download_entries()
        assert catalog_app.merged_download_entries() is primera

    def test_se_invalida(self, catalog_app, downloads_dir):
        primera = catalog_app.merged_download_entries()
        catalog_app.invalidate_download_entries()
        assert catalog_app.merged_download_entries() is not primera

    def test_guardar_el_manifest_invalida(self, catalog_app, downloads_dir, monkeypatch):
        monkeypatch.setattr(app, "MANIFEST_PATH", str(downloads_dir / "m.json"))
        primera = catalog_app.merged_download_entries()
        catalog_app.save_download_manifest()
        assert catalog_app.merged_download_entries() is not primera


class TestQueueState:
    @pytest.fixture
    def queue_app(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app, "QUEUE_STATE_PATH", str(tmp_path / "download_queue.json"))

        class QueueApp(app.PSNDownloaderApp):
            def __init__(self):
                self.download_tasks = {}
                self.download_order = []
                self.download_task_seq = 0
                self.download_lock = threading.Lock()
                self.queue_state_saved_at = 0.0
                self.queue_refresh_pending = False
                self.ui_closed = True

        a = QueueApp()
        tarea = app.DownloadTask(task_id=1, url="http://x/y.pkg", dest_path="/d/y.pkg",
                                 title="Juego", platform="PS3", category="Juegos")
        a.download_tasks[1] = tarea
        a.download_order.append(1)
        return a, tarea

    def _en_disco(self):
        with open(app.QUEUE_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)["tasks"][0]

    def test_completar_persiste_al_momento(self, queue_app):
        a, tarea = queue_app
        a.complete_task(tarea)
        assert self._en_disco()["status"] == "complete"

    def test_fallar_persiste_al_momento(self, queue_app):
        a, tarea = queue_app
        a.fail_task(tarea, RuntimeError("sin red"))
        d = self._en_disco()
        assert d["status"] == "error"
        assert "sin red" in d["error"]

    def test_cancelar_se_distingue_de_error(self, queue_app):
        a, tarea = queue_app
        a.fail_task(tarea, app.DownloadCancelled())
        assert self._en_disco()["status"] == "cancelled"

    def test_el_progreso_no_escribe_en_cada_tick(self, queue_app, monkeypatch):
        a, tarea = queue_app
        a.save_queue_state()
        escrituras = []
        monkeypatch.setattr(a, "save_queue_state", lambda: escrituras.append(1))
        for i in range(100):
            a.update_task_progress(tarea, i / 100, "10 MB/s")
        assert escrituras == []

    def test_el_progreso_acaba_escribiendo(self, queue_app, monkeypatch):
        a, tarea = queue_app
        a.save_queue_state()
        a.queue_state_saved_at -= app.QUEUE_SAVE_INTERVAL_SECONDS + 1
        a.update_task_progress(tarea, 0.5, "10 MB/s")
        assert self._en_disco()["progress"] == 0.5

    def test_escritura_atomica_sin_restos(self, queue_app):
        a, _ = queue_app
        a.save_queue_state()
        directorio = os.path.dirname(app.QUEUE_STATE_PATH)
        assert [f for f in os.listdir(directorio) if f.endswith(".tmp")] == []

    def test_ida_y_vuelta(self, queue_app):
        a, tarea = queue_app
        tarea.status = "paused"
        a.save_queue_state()
        a.download_tasks.clear()
        a.download_order.clear()
        a.load_queue_state()
        assert a.download_tasks[1].title == "Juego"

    def test_al_restaurar_lo_que_bajaba_queda_en_pausa(self, queue_app):
        a, tarea = queue_app
        tarea.status = "downloading"
        a.save_queue_state()
        a.download_tasks.clear()
        a.download_order.clear()
        a.load_queue_state()
        assert a.download_tasks[1].status == "paused"


class TestCatalogDb:
    @pytest.fixture
    def db_app(self, catalog_app, tmp_path, monkeypatch):
        monkeypatch.setattr(app, "CATALOG_DB_PATH", str(tmp_path / "c.sqlite3"))
        return catalog_app

    def test_las_conexiones_se_cierran(self, db_app, monkeypatch):
        abiertas = []
        original = sqlite3.connect
        monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: abiertas.append(original(*a, **k)) or abiertas[-1])
        db_app.init_catalog_db()
        db_app.record_history("test", "PS3", "Juegos", "x", "ok")
        for conn in abiertas:
            with pytest.raises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")

    def test_el_ddl_se_ejecuta_una_sola_vez(self, db_app, monkeypatch):
        db_app.init_catalog_db()
        llamadas = []
        monkeypatch.setattr(app, "catalog_db", lambda: llamadas.append(1))
        db_app.init_catalog_db()
        assert llamadas == []

    def test_esquema_actual(self, db_app):
        db_app.init_catalog_db()
        with sqlite3.connect(app.CATALOG_DB_PATH) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == app.CATALOG_DB_SCHEMA_VERSION
            columnas = [r[1] for r in conn.execute("PRAGMA table_info(catalog_items)")]
        assert "item_key" in columnas

    def test_el_catalogo_sobrevive_al_viaje_a_sqlite(self, db_app):
        """
        La UNIQUE antigua no coincidía con catalog_item_key y descartaba
        elementos: 451 DLCs de un mismo title_id se guardaban como 1.
        """
        for i in range(50):
            db_app.add_content_item(
                platform="PSV", category="DLCs", title_id="PCSG00251", region="ASIA",
                name=f"Traje {i}", version="Base", size="", url="",
                content_id=f"JP0001-PCSG00251_00-DLC{i:04d}")
        antes = len(db_app.catalog["PSV"]["DLCs"])
        assert antes == 50

        db_app.save_catalog_to_db()
        db_app.reset_catalog()
        db_app.load_catalog_from_db()
        assert len(db_app.catalog["PSV"]["DLCs"]) == antes

    def test_migracion_desde_el_esquema_1(self, db_app):
        """Una base v1 debe reconstruirse conservando el historial."""
        with sqlite3.connect(app.CATALOG_DB_PATH) as conn:
            conn.execute("CREATE TABLE catalog_items (id INTEGER PRIMARY KEY, platform TEXT)")
            conn.execute("CREATE TABLE action_history (id INTEGER PRIMARY KEY, created_at TEXT, "
                         "action TEXT, platform TEXT, category TEXT, name TEXT, status TEXT, details TEXT)")
            conn.execute("INSERT INTO action_history(created_at, action) VALUES ('2026-01-01', 'x')")
            conn.execute("PRAGMA user_version=1")

        db_app.init_catalog_db()

        with sqlite3.connect(app.CATALOG_DB_PATH) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == app.CATALOG_DB_SCHEMA_VERSION
            assert conn.execute("SELECT COUNT(*) FROM action_history").fetchone()[0] == 1
            columnas = [r[1] for r in conn.execute("PRAGMA table_info(catalog_items)")]
        assert "item_key" in columnas
        assert db_app.catalog_db_is_current() is False  # fuerza reconstruir desde los TSV
