"""Biblioteca: rutas de destino, deduplicación de descargas y persistencia."""
import json
import os
import sqlite3
import threading
import time

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
                self.running_task_ids = set()
                self.queue_state_saved_at = 0.0
                self.queue_refresh_pending = False
                self.shutdown_event = threading.Event()
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


class TestContenidoRelacionado:
    """
    La Biblioteca pedía find_related_content por juego en cada refresco, y el
    refresco salta al terminar cada descarga: 162 ms por juego, 16 s con 100.
    """

    def _catalogo(self, catalog_app, n_dlcs=200):
        juego = catalog_app.add_content_item(
            platform="PS3", category="Juegos", title_id="BLES00483", region="EU",
            name="Killzone 2", version="Base", size="10 GB", url="http://x/base.pkg")
        for i in range(n_dlcs):
            catalog_app.add_content_item(
                platform="PS3", category="DLCs", title_id="BLES00483" if i < 5 else f"BLES{i:05d}",
                region="EU", name=f"Killzone 2 Mapa {i}", version="Base", size="100 MB",
                url=f"http://x/dlc{i}.pkg", content_id=f"EP0001-BLES00483_00-DLC{i:04d}")
        return juego

    def test_la_cache_devuelve_lo_mismo(self, catalog_app):
        juego = self._catalogo(catalog_app)
        primera = catalog_app.find_related_content(juego)
        catalog_app.related_content_cache = {}
        segunda = catalog_app.find_related_content(juego)
        assert primera == segunda

    def test_la_segunda_llamada_usa_la_cache(self, catalog_app):
        juego = self._catalogo(catalog_app)
        assert catalog_app.find_related_content(juego) is catalog_app.find_related_content(juego)

    def test_reset_catalog_vacia_las_caches(self, catalog_app):
        juego = self._catalogo(catalog_app)
        catalog_app.find_related_content(juego)
        assert catalog_app.related_content_cache
        catalog_app.reset_catalog()
        assert catalog_app.related_content_cache == {}
        assert catalog_app.technical_fields_cache == {}

    def test_hoisting_no_cambia_el_resultado(self, catalog_app):
        """Pasar los invariantes del juego base debe dar exactamente lo mismo."""
        juego = self._catalogo(catalog_app, n_dlcs=50)
        base_title_id = juego.title_id.upper()
        base_tokens = app.meaningful_title_tokens(juego.name)
        for item in catalog_app.catalog["PS3"]["DLCs"]:
            assert (catalog_app.is_exact_related_match(juego, item)
                    == catalog_app.is_exact_related_match(juego, item, base_title_id))
            assert (catalog_app.is_suggested_match(juego, item)
                    == catalog_app.is_suggested_match(juego, item, base_tokens))

    def test_campos_tecnicos_memorizados(self, catalog_app):
        self._catalogo(catalog_app, n_dlcs=10)
        item = catalog_app.catalog["PS3"]["DLCs"][0]
        esperado = " ".join([item.content_id, item.original_name, item.url, item.name]).upper()
        assert catalog_app.candidate_technical_fields(item) == esperado
        # la segunda llamada sale de la caché
        assert catalog_app.candidate_technical_fields(item) is catalog_app.technical_fields_cache[id(item)]

    def test_encuentra_los_dlcs_del_mismo_title_id(self, catalog_app):
        juego = self._catalogo(catalog_app, n_dlcs=20)
        related = catalog_app.find_related_content(juego)
        exactos = [i for i in related["DLCs"] if i.match_type == "exact"]
        assert len(exactos) >= 5


class TestCachesDeTitulos:
    def test_devuelven_frozenset_para_no_corromper_la_cache(self):
        assert isinstance(app.meaningful_title_tokens("Killzone 2"), frozenset)

    def test_normalize_title_memorizado(self):
        from psnkiller.catalog import normalize_title
        normalize_title.cache_clear()
        normalize_title("LittleBigPlanet GOTY")
        antes = normalize_title.cache_info().hits
        normalize_title("LittleBigPlanet GOTY")
        assert normalize_title.cache_info().hits == antes + 1

    def test_clear_title_caches_las_vacia(self):
        from psnkiller.catalog import clear_title_caches, normalize_title
        normalize_title("algo")
        clear_title_caches()
        assert normalize_title.cache_info().currsize == 0


class TestCierreLimpio:
    """
    Los hilos de descarga son daemon: sin coordinacion, destroy() los mata a
    media escritura y el .part queda con bytes a medias, que en la siguiente
    sesion se toman por progreso valido y dan un .pkg corrupto.
    """

    @pytest.fixture
    def app_cierre(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app, "QUEUE_STATE_PATH", str(tmp_path / "q.json"))

        class ShutdownApp(app.PSNDownloaderApp):
            def __init__(self):
                self.download_tasks = {}
                self.download_order = []
                self.download_task_seq = 0
                self.download_lock = threading.Lock()
                self.running_task_ids = set()
                self.active_downloads = 0
                self.queue_state_saved_at = 0.0
                self.queue_refresh_pending = False
                self.shutdown_event = threading.Event()
                self.ui_closed = True
                self.max_active_downloads = 2

        return ShutdownApp()

    def _tarea(self, a, task_id=1, status="downloading"):
        t = app.DownloadTask(task_id=task_id, url="http://x/y.pkg", dest_path="/d/y.pkg",
                             title="Juego", platform="PS3", category="Juegos", status=status)
        a.download_tasks[task_id] = t
        a.download_order.append(task_id)
        return t

    def test_sin_descargas_activas_no_espera(self, app_cierre):
        assert app_cierre.stop_active_downloads(timeout=0.2) == []

    def test_el_hilo_de_descarga_recibe_la_senal(self, app_cierre):
        tarea = self._tarea(app_cierre)
        app_cierre.running_task_ids.add(1)

        parado = threading.Event()

        def worker():
            try:
                while True:
                    app_cierre.wait_if_task_paused(tarea)
                    time.sleep(0.01)
            except app.DownloadCancelled:
                with app_cierre.download_lock:
                    app_cierre.running_task_ids.discard(1)
                parado.set()

        threading.Thread(target=worker, daemon=True).start()
        rezagadas = app_cierre.stop_active_downloads(timeout=3)

        assert parado.wait(1), "el hilo no atendio la senal de cierre"
        assert rezagadas == []

    def test_una_descarga_atascada_se_reporta(self, app_cierre):
        self._tarea(app_cierre)
        app_cierre.running_task_ids.add(1)   # nadie la va a liberar
        rezagadas = app_cierre.stop_active_downloads(timeout=0.3)
        assert len(rezagadas) == 1

    def test_al_cerrar_queda_en_pausa_no_cancelada(self, app_cierre):
        """Cerrar la app no es cancelar: al volver debe poder reanudarse."""
        tarea = self._tarea(app_cierre)
        app_cierre.shutdown_event.set()
        app_cierre.fail_task(tarea, app.DownloadCancelled())
        assert tarea.status == "paused"
        assert tarea.error == ""

    def test_cancelar_de_verdad_sigue_siendo_cancelado(self, app_cierre):
        tarea = self._tarea(app_cierre)
        app_cierre.fail_task(tarea, app.DownloadCancelled())
        assert tarea.status == "cancelled"

    def test_no_se_arrancan_descargas_nuevas_al_cerrar(self, app_cierre):
        self._tarea(app_cierre, status="queued")
        app_cierre.shutdown_event.set()
        app_cierre.schedule_downloads()
        assert app_cierre.running_task_ids == set()
        assert app_cierre.download_tasks[1].status == "queued"
