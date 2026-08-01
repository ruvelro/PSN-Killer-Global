@echo off
setlocal

cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY_CMD=py -3"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "PY_CMD=python"
    ) else (
        echo Python no esta instalado. Intentando instalarlo con winget...
        where winget >nul 2>nul
        if not %errorlevel%==0 (
            echo No se encontro winget. Instala Python desde https://www.python.org/downloads/windows/ y vuelve a ejecutar este archivo.
            pause
            exit /b 1
        )
        winget install --id Python.Python.3.13 -e --source winget
        where py >nul 2>nul
        if %errorlevel%==0 (
            set "PY_CMD=py -3"
        ) else (
            where python >nul 2>nul
            if %errorlevel%==0 (
                set "PY_CMD=python"
            ) else (
                echo Python se instalo, pero esta consola aun no lo encuentra. Cierra esta ventana y ejecuta launch_windows.bat de nuevo.
                pause
                exit /b 1
            )
        )
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo Creando entorno virtual...
    %PY_CMD% -m venv .venv
    if not %errorlevel%==0 (
        echo No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
)

echo Instalando dependencias...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt

echo Lanzando PS3 PSN KILLER...
".venv\Scripts\python.exe" app.py

endlocal
