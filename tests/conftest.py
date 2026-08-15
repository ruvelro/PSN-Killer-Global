import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402


@pytest.fixture
def catalog_app():
    """
    Instancia sin ventana, sólo con el estado que necesita la lógica de catálogo.

    Evita ctk.CTk.__init__ a propósito: los tests no deben depender de que haya
    un servidor gráfico disponible.
    """

    class HeadlessApp(app.PSNDownloaderApp):
        def __init__(self):
            self.current_platform = "PS3"
            self.reset_catalog()
            self.download_manifest = {}
            self.download_entries_cache = None
            self.catalog_db_ready = False
            self.ui_closed = True

    return HeadlessApp()


@pytest.fixture
def downloads_dir(tmp_path, monkeypatch):
    """Redirige DOWNLOADS_DIR a un directorio temporal."""
    target = tmp_path / "Descargas"
    target.mkdir()
    monkeypatch.setattr(app, "DOWNLOADS_DIR", str(target))
    return target
