# FÚTBOL LIVE PRO 2026 — edición nativa Windows

**Código 100 % Python/PySide6 para las ventanas.** No utiliza Flask, HTTP local, navegador, HTML, JavaScript, WebView ni Electron.

## Lo que incluye

- Panel Windows con 20 clubes del ZIP original y edición de nombre, puntos, regalo, valor, escudo y estado.
- Temporizador, iniciar, pausar, reiniciar, eliminación automática y campeón.
- Ventanas independientes nativas de estadio 9:16, tabla tradicional y tabla estadio.
- Fondo estadio, transparente o verde chroma en la ventana principal de estadio.
- Conector experimental TikTokLive dentro del programa y en hilo aparte. Regalos de racha al finalizar; solo se aceptan regalos asignados a exactamente un club activo.
- API-Football para consultar ligas colombianas y tablas de posiciones, con actualización cada 15, 30 o 60 minutos.
- Persistencia en `%APPDATA%\FutbolLivePro\datos.json` (la primera ejecución puede importar un `datos.json` junto al ejecutable).

## Compilar EXE automáticamente en GitHub (no hace falta Python en tu PC)

1. Abre GitHub, inicia sesión y pulsa **New repository**.
2. Escribe un nombre, por ejemplo `FutbolLivePro`, y crea el repositorio **privado**.
3. Pulsa **Add file > Upload files** y sube los archivos de este proyecto. **Atención:** GitHub no conserva carpetas vacías; para conservar `.github/workflows/windows-exe.yml`, puedes crear ese archivo directamente desde **Add file > Create new file**, pegando la ruta `.github/workflows/windows-exe.yml` como nombre y el contenido del archivo incluido.
4. Sube `main.py`, `requirements.txt`, `datos.json` y `README.md` en la raíz.
5. En la pestaña **Actions**, abre **Compilar FutbolLivePro.exe** y pulsa **Run workflow**. Si se ejecutó automáticamente al subir archivos, también puedes abrir esa ejecución.
6. Espera a que aparezca una marca verde. En el detalle de la ejecución, abajo en **Artifacts**, descarga `FutbolLivePro-Windows-x64`.
7. Descomprime el artefacto: dentro encontrarás **FutbolLivePro.exe**. Ábrelo con doble clic en Windows 11 de 64 bits. No necesitas instalar Python.

**Importante:** el ZIP de este proyecto es código fuente; el EXE final solo aparece tras compilar en un runner Windows de GitHub Actions. En este entorno Linux no puedo compilar ni probar un ejecutable nativo de Windows.

## Captura en TikTok LIVE Studio

1. Abre `FutbolLivePro.exe`.
2. En la pestaña **Ventanas para LIVE Studio**, abre **Estadio legendario**.
3. En TikTok LIVE Studio agrega una fuente **Captura de ventana** y selecciona **Estadio Legendario**.
4. Ajusta la fuente al lienzo vertical. El tamaño inicial de la ventana es **540×960 (9:16)**; si tu monitor permite, agrándala a 1080×1920 o ajusta la captura al tamaño que necesites.
5. Elige fondo de estadio, transparencia o verde chroma. La captura de ventana de TikTok LIVE Studio puede **no preservar transparencia alfa**: usa verde chroma y la herramienta de clave de color del programa de transmisión si ocurre.
6. Las ventanas **Tabla tradicional** y **Tabla estadio** también pueden capturarse por separado.

## API-Football

En **Configuración**, escribe la clave, pulsa **Buscar ligas de Colombia**, selecciona la competición y temporada, guarda y luego pulsa **Actualizar clasificación ahora**. Los datos y escudos dependen de la cobertura del proveedor. Comprueba que la clasificación corresponde a **Finalización 2026** y no a otra fase; la aplicación no puede verificarlo por sí sola. La tabla de la Liga no se altera por regalos.

## TikTok LIVE

Escribe tu usuario en Configuración y pulsa **Conectar a TikTok LIVE**. El conector usa una biblioteca no oficial; no garantiza acceso ni continuidad. Debes tener el LIVE activo. La detección y nombres de regalos pueden variar según la versión de TikTokLive. Si dos equipos tienen asignado «Rosa», el regalo Rosa **no** sumará a ninguno: asigna regalos únicos.

## Limitaciones importantes

- **No hay EXE precompilado en esta entrega.** El workflow genera uno en Windows.
- **No he probado** este proyecto en Windows 11, TikTok LIVE Studio, con una cuenta LIVE real ni con una API key real. Se validó sintaxis Python, pero no se puede garantizar su funcionamiento final sin esas pruebas.
- La estética del estadio está recreada con **QPainter**, no es una copia píxel a píxel del HTML anterior; no se usa ningún archivo web en la interfaz.
- Los escudos de la batalla se cargan de URL o de un archivo local configurado. Los escudos de la liga provienen del proveedor deportivo.
- El botón de simulación y el botón de regalo manual hacen lo mismo: suman un regalo al equipo seleccionado.
- No hay APK Android: la petición actual es exclusivamente para Windows 11.
- En caso de antivirus/SmartScreen, un EXE sin firma digital puede requerir confirmación del usuario. No desactives la protección de tu equipo; revisa el origen del archivo.
- API key y configuración se guardan en JSON sin cifrar dentro del perfil de Windows. No publiques ese archivo en GitHub.

## Estructura

```text
FutbolLivePro_Nativo/
  main.py
  requirements.txt
  datos.json
  README.md
  .github/
    workflows/
      windows-exe.yml
```

## Compilación manual opcional en Windows

```powershell
py -3.11 -m pip install -r requirements.txt
py -3.11 -m PyInstaller --noconfirm --clean --onefile --windowed --name FutbolLivePro --collect-all TikTokLive main.py
```

El resultado es `dist\FutbolLivePro.exe`.
