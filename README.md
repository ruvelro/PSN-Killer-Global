# 🎮 PSN Killer Global

Versión actual: **0.3.0**

Una aplicación de escritorio moderna desarrollada en **Python** con **CustomTkinter** diseñada para buscar, filtrar y descargar contenido oficial de PlayStation de forma masiva y a alta velocidad (juegos, actualizaciones, demos, temas, avatares, DLCs y licencias).

> **Nota importante:** herramienta orientada a preservación digital y respaldo de contenido adquirido legalmente en PS3, PSP, PS Vita, PSX y PSM.

---

## 🖼️ Vista Previa

![Captura de pantalla de la aplicación](screenshot.png)

---

## ✨ Características Principales

* **🚀 Motor de Descarga Turbo Multihilo:** Soporta hasta 16 hilos concurrentes con peticiones HTTP por rangos (`Range`) para exprimir al máximo tu conexión de fibra óptica.
* **🔍 Búsqueda y Filtros Avanzados:** Filtra por plataforma, nombre, Title ID o región (`US`, `EU`, `JP`, `ASIA`) al instante.
* **📚 Catálogos Multi-Plataforma:** Soporta PS3, PSP, PS Vita, PSX y PSM desde catálogos descargados en la carpeta `data/`.
* **📂 Organización Automática:** Clasifica y guarda cada tipo de contenido en `Descargas/` por plataforma y tipo de contenido.
* **📦 Descarga Completa Multi-Juego:** Permite seleccionar varios juegos y revisar, uno a uno, base, última update, DLCs, temas y avatares antes de añadirlos a la cola.
* **📚 Biblioteca de Descargas:** Muestra juegos descargados por plataforma, estado de base/update, contenido adicional presente y carpeta de destino.
* **⏯️ Cola de Descargas:** Lista tareas pendientes o activas con progreso, velocidad, pausa, reanudación, cancelación y reintento.
* **💿 Cola Persistente y Reanudación:** Guarda `download_queue.json` y usa archivos `.part` para continuar descargas parciales cuando el servidor admite rangos.
* **✅ Verificación SHA256:** Si el catálogo incluye hash, valida el archivo al terminar y lo marca como verificado o corrupto.
* **🔄 Actualizador de Catálogos:** Puede refrescar los TSV desde URLs configurables, guardando backup local y fecha de actualización.
* **🗄️ SQLite Local:** Indexa los catálogos en `data/catalog.sqlite3` y reconstruye la base cuando cambian los TSV.
* **🧩 Completar Biblioteca:** Analiza lo que ya hay en `Descargas/` y propone contenido relacionado pendiente.
* **📋 Faltantes Global:** Lista por plataforma todos los juegos con contenido pendiente y permite descargarlo en lote.
* **🔎 Detalles por Juego:** Doble clic en Biblioteca para ver archivos, rutas, estado, SHA256 y completar faltantes.
* **🧹 Limpieza Integrada:** Botones para limpiar historial, cola y descargas de la plataforma activa con confirmación.
* **🎚️ Filtros Avanzados:** Filtra por estado de descarga e integridad además de plataforma, nombre, Title ID y región.
* **⚙️ Configuración:** Ajusta carpeta de descargas, descargas simultáneas, hilos por archivo, perfil, auto-reanudar cola, auto-actualizar catálogos y accesos a fuentes/logs.
* **💾 Exportación:** Exporta biblioteca y cola a JSON, o la vista activa a CSV.
* **⚡ Arranque no Bloqueante:** La ventana aparece rápido y muestra una barra de progreso mientras carga o actualiza la base de datos local.
* **🔑 Soporte para Licencias:** Botón de acceso directo para descargar paquetes de licencias RAP universales.
* **🎨 Interfaz Oscura Minimalista:** Desarrollada con CustomTkinter para una experiencia visual limpia y moderna.
* **📦 Autoinstalación de Dependencias:** Los lanzadores verifican Python, crean `.venv` e instalan las librerías necesarias desde `requirements.txt`.

---

## 🛠️ Cómo Funciona en General

La aplicación opera mediante los siguientes componentes lógicos:

1. **Lectura de Bases de Datos Locales:** El script procesa archivos en formato TSV dentro de `data/` (`PS3_GAMES.tsv`, `PSP_GAMES.tsv`, `PSV_UPDATES.tsv`, etc.) que contienen los catálogos oficiales con los metadatos y las URLs directas de los servidores.
2. **Detección de Regiones:** Analiza automáticamente el prefijo del *Title ID* (por ejemplo, `BLUS`, `BLES`, `NPUB`) para clasificar la región del juego de forma inteligente.
3. **Matching de Contenido Relacionado:** Para descargas completas, marca automáticamente coincidencias exactas por Title ID o Content ID y deja como sugerencias no marcadas los contenidos relacionados por nombre y región compatible.
4. **Segmentación de Archivos (Multihilo):**
   * Primero realiza una petición HTTP `HEAD` para comprobar el tamaño exacto del archivo `.pkg` y si el servidor admite descargas por rangos (`Accept-Ranges`).
   * Si es compatible, divide el archivo en partes iguales y lanza múltiples hilos en paralelo que escriben de manera concurrente en el disco duro, acelerando drásticamente el proceso frente a una descarga lineal tradicional.

---

## ⚙️ Requisitos Previos

* En macOS, el lanzador usa **Homebrew** para instalar Python y evitar el Python de Xcode con Tk antiguo.
* En Linux, el lanzador usa `apt`, `dnf`, `pacman` o `zypper` si falta Python/Tkinter.
* En Windows, el lanzador usa `winget` si falta Python.

---

## 🚀 Instalación y Uso

### Descarga directa (recomendado)

Descarga el paquete de tu sistema desde la
**[última release](https://github.com/ruvelro/PSN-Killer-Global/releases/latest)**,
descomprímelo y ejecuta el lanzador. No hace falta cuenta de GitHub ni `git`.

| Sistema | Archivo | Lanzador |
|---|---|---|
| Windows | `PSN-Killer-Global-<versión>-windows.zip` | `launch_windows.bat` |
| macOS | `PSN-Killer-Global-<versión>-macos.zip` | `./launch_macos.sh` |
| Linux | `PSN-Killer-Global-<versión>-linux.zip` | `./launch_linux.sh` |

Cada release incluye `SHA256SUMS.txt` para comprobar la descarga:

```bash
sha256sum -c SHA256SUMS.txt
```

En macOS y Linux, si el lanzador no tiene permiso de ejecución:

```bash
chmod +x launch_macos.sh
```

### Desde el código fuente

1. Clona este repositorio o descarga los archivos fuente.
2. Ejecuta el lanzador de tu sistema:

   **macOS**
   ```bash
   ./launch_macos.sh
   ```

   **Linux**
   ```bash
   ./launch_linux.sh
   ```

   **Windows**
   ```bat
   launch_windows.bat
   ```

Los lanzadores comprueban Python, crean `.venv`, instalan `requirements.txt` y arrancan `app.py`.

Los catálogos TSV se guardan en la carpeta `data/` como caché local y ya no se versionan en este repo. La raíz del proyecto queda reservada para la app, lanzadores, documentación y assets principales.

Por defecto, el actualizador usa como fuente primaria `https://raw.githubusercontent.com/ruvelro/PSN-Killer-Database/main/data/<nombre.tsv>`, con NoPayStation como secundaria y VitaWiki como mirror adicional. Este orden protege catálogos curados como `PS3_UPDATES.tsv`, que actualmente es mucho más completo en la base propia que en la fuente pública de NoPayStation.

Para cambiar la fuente global o añadir mirrors, copia `catalog_sources.example.json` a `catalog_sources.json` y ajusta `primary_base_url`, `fallback_base_urls` o las fuentes por archivo. Cada actualización valida que el TSV tenga filas útiles antes de reemplazar el anterior; si la fuente nueva viene vacía o rota, conserva el catálogo local y prueba los fallbacks configurados. Los backups se guardan en `data/backups/` y el estado en `data/catalog_state.json`.

La configuración local se guarda en `app_config.json`, la cola en `download_queue.json`, la caché SQLite en `data/catalog.sqlite3` y los logs técnicos en `logs/app.log`. Estos archivos no se versionan.

### Uso manual

Si prefieres hacerlo a mano:

1. Crea y activa un entorno virtual:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```
3. Arranca la app:
   ```bash
   python app.py
   ```

---

## 🧱 Estructura del Proyecto

```
app.py                    Interfaz de escritorio (CustomTkinter)
psnkiller/
  models.py               ContentItem, DownloadTask, DownloadCancelled
  naming.py               Nombres y rutas válidas en Windows, Linux y macOS
  catalog.py              Parseo de TSV, normalización de títulos, CatalogIndex
  downloader.py           Motor HTTP multihilo
tests/                    Suite de pytest
clean_updates.py          Herramienta para convertir volcados HTML a TSV
```

El paquete `psnkiller` no depende de Tkinter. El motor de descarga se comunica
con la interfaz mediante callbacks, y es la interfaz quien lleva cada
actualización al hilo principal de Tk. Hay un test que falla si `downloader.py`
vuelve a arrastrar Tkinter, para que esa separación no se pierda.

---

## 🧪 Desarrollo

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
```

La suite no necesita servidor gráfico más allá de importar CustomTkinter: usa
fixtures sin ventana y, para el motor de descarga, un servidor HTTP local con
soporte de `Range`. En CI se ejecuta bajo `xvfb` en Python 3.9 y 3.13.

---

## 📄 Licencia

Distribuido bajo licencia [MIT](LICENSE).

---

## 📜 Descargo de Responsabilidad (Disclaimer)
Este software se proporciona con fines educativos y de preservación digital de contenido adquirido legalmente. El desarrollador no se hace responsable del mal uso que se le pueda dar a esta herramienta.
