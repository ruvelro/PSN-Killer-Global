# 🎮 PSN Killer Global

Una aplicación de escritorio moderna desarrollada en **Python** con **CustomTkinter** diseñada para buscar, filtrar y descargar contenido oficial de PlayStation de forma masiva y a alta velocidad (juegos, actualizaciones, demos, temas, avatares, DLCs y licencias).

> **💡 Nota importante:** Ideal para respaldar y preservar todo tu contenido digital ante un hipotético cierre de los servidores oficiales de la tienda de PS3. ¡Guarda tus juegos antes de que sea tarde! Xd

---

## 🖼️ Vista Previa

![Captura de pantalla de la aplicación](screenshot.png)

---

## ✨ Características Principales

* **🚀 Motor de Descarga Turbo Multihilo:** Soporta hasta 16 hilos concurrentes con peticiones HTTP por rangos (`Range`) para exprimir al máximo tu conexión de fibra óptica.
* **🔍 Búsqueda y Filtros Avanzados:** Filtra por plataforma, nombre, Title ID o región (`US`, `EU`, `JP`, `ASIA`) al instante.
* **📚 Catálogos Multi-Plataforma:** Soporta PS3, PSP, PS Vita, PSX y PSM desde archivos TSV en la carpeta `data/`.
* **📂 Organización Automática:** Clasifica y guarda cada tipo de contenido en `Descargas/` por plataforma y tipo de contenido.
* **🔑 Soporte para Licencias:** Botón de acceso directo para descargar paquetes de licencias RAP universales.
* **🎨 Interfaz Oscura Minimalista:** Desarrollada con CustomTkinter para una experiencia visual limpia y moderna.
* **📦 Autoinstalación de Dependencias:** El script verifica e instala automáticamente las librerías necesarias (`customtkinter`, `requests`, `beautifulsoup4`) al primer inicio.

---

## 🛠️ Cómo Funciona en General

La aplicación opera mediante los siguientes componentes lógicos:

1. **Lectura de Bases de Datos Locales:** El script procesa archivos en formato TSV dentro de `data/` (`PS3_GAMES.tsv`, `PSP_GAMES.tsv`, `PSV_UPDATES.tsv`, etc.) que contienen los catálogos oficiales con los metadatos y las URLs directas de los servidores.
2. **Detección de Regiones:** Analiza automáticamente el prefijo del *Title ID* (por ejemplo, `BLUS`, `BLES`, `NPUB`) para clasificar la región del juego de forma inteligente.
3. **Segmentación de Archivos (Multihilo):** 
   * Primero realiza una petición HTTP `HEAD` para comprobar el tamaño exacto del archivo `.pkg` y si el servidor admite descargas por rangos (`Accept-Ranges`).
   * Si es compatible, divide el archivo en partes iguales y lanza múltiples hilos en paralelo que escriben de manera concurrente en el disco duro, acelerando drásticamente el proceso frente a una descarga lineal tradicional.

---

## ⚙️ Requisitos Previos

* En macOS, el lanzador usa **Homebrew** para instalar Python y evitar el Python de Xcode con Tk antiguo.
* En Linux, el lanzador usa `apt`, `dnf`, `pacman` o `zypper` si falta Python/Tkinter.
* En Windows, el lanzador usa `winget` si falta Python.

---

## 🚀 Instalación y Uso

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

Los catálogos TSV deben vivir en la carpeta `data/`. La raíz del proyecto queda reservada para la app, lanzadores, documentación y assets principales.

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

## 📜 Descargo de Responsabilidad (Disclaimer)
Este software se proporciona con fines educativos y de preservación digital de contenido adquirido legalmente. El desarrollador no se hace responsable del mal uso que se le pueda dar a esta herramienta.
