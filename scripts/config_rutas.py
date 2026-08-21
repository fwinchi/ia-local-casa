"""
Constantes de rutas y configuracion compartidas por varios scripts del
repo. Un solo sitio para no tener que mantener sincronizadas varias
copias cada vez que cambia una carpeta, un modelo o los formatos
soportados. Dos circuitos, cada uno con sus propias constantes:

- Documentos (indexar_documentos.py, mcp_documentos.py, buscar.py; también salud.py):
  CARPETAS_PDFS, OLLAMA (URL completa del endpoint de embeddings),
  MODELO (bge-m3), EXTENSIONES.
- Fotos/vídeos (indexar_fotos.py, indexar_videos.py, mcp_fotos.py):
  OLLAMA_BASE (URL base de Ollama, sin ruta de endpoint — estos scripts
  la usan tanto para /api/generate como para /api/embeddings),
  MODELO_VISION (vl3-paperless), MODELO_EMBED_FOTOS (nomic-embed-text),
  IMMICH_BASE_URL (solo mcp_fotos.py, para listar_personas).
- Correo (copiar_gloda.py, mapear_mbox.py, indexar_correo.py, mcp_correo.py):
  PERFIL_TB (perfil de Thunderbird), RUTA_GLODA_ORIGEN (gloda real, en el
  perfil), RUTA_GLODA (copia de solo lectura que generan y leen los demas).

BASE y CARPETA_DB son comunes a los dos primeros circuitos: mismo `chroma/`,
colecciones distintas ("documentos" en uno, "fotos"/"videos" en otro).
"""

import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent   # antes: D:\paperless

# Carpetas indexadas por indexar_documentos.py y validadas por abrir_documento en
# mcp_documentos.py (ninguna ruta fuera de ellas se puede abrir). Ambas con el
# mismo nombre de subcarpeta a proposito: antes se indexaba
# OneDrive\Documentos entero y arrastraba basura (configs y logs de
# videojuegos, cachés de DaVinci).
CARPETAS_PDFS = [
    (Path.home() / "OneDrive" / "Documentos" / "Documentos para indexar").resolve(),
    (Path.home() / "Documents" / "Documentos para indexar").resolve(),
]

# ADVERTENCIA (GHSA-f4j7-r4q5-qw2c / CVE-2026-45829, ver
# docs/vulnerabilidades-conocidas.md): chromadb 1.5.9 tiene un RCE en
# CollectionCommon._embed() que se dispara cuando se llama a
# .add()/.upsert()/.query()/.get() con documents=/query_texts= SIN pasar
# tambien embeddings=/query_embeddings= ya calculados -- Chroma entonces
# calcula el embedding el mismo, y si la coleccion tiene una
# embedding_function maliciosa en su configuracion, se ejecuta. Todos los
# scripts de este repo pasan siempre el embedding ya calculado (via
# Ollama) en cada .add()/.upsert()/.query(); NUNCA anadir una llamada
# nueva a Chroma sin hacer lo mismo.
CARPETA_DB = str(BASE / "chroma")

# --- Documentos ---
OLLAMA = "http://localhost:11434/api/embeddings"
MODELO = "bge-m3"

# Formatos que indexa indexar_documentos.py y que abrir_documento puede abrir.
EXTENSIONES = [".pdf", ".docx", ".txt", ".odt"]

# --- Fotos / vídeos ---
OLLAMA_BASE = "http://localhost:11434"
MODELO_VISION = "vl3-paperless"
MODELO_EMBED_FOTOS = "nomic-embed-text"

# Immich corre en el host, igual que mcp_fotos.py (no es un contenedor desde
# el punto de vista de este script), asi que localhost va bien.
IMMICH_BASE_URL = "http://localhost:2283"

# --- Disco externo ---
ETIQUETA_DISCO = "Multimedia IA"

# --- Extensiones multimedia ---
# .gif excluido a proposito (decision del usuario).
EXT_FOTO = {".jpg", ".jpeg", ".png", ".heic", ".bmp", ".webp", ".tiff"}
EXT_VIDEO = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v", ".mpg", ".mpeg", ".3gp", ".webm"}

# Subconjunto para el buzon de Syncthing (ingesta_fotos.py): solo formatos
# que genera un movil. Se excluyen .wmv/.mpg/.mpeg a proposito -- son
# formatos heredados de PC que no deben entrar por esa via.
EXT_VIDEO_MOVIL = {".mp4", ".mov", ".avi", ".mkv", ".3gp", ".m4v", ".webm"}

# --- Puente manual a Paperless (puente_paperless.py) ---
# Derivadas de CARPETAS_PDFS[1] (la carpeta local, NO la de OneDrive): asi
# a_paperless/ y enviado/ no se sincronizan de mas a la nube por error.
CARPETA_A_PAPERLESS = CARPETAS_PDFS[1] / "a_paperless"
CARPETA_ENVIADO = CARPETAS_PDFS[1] / "enviado"
CARPETA_CONSUME = Path(r"D:\paperless\consume")

# --- Correo (mapear_mbox.py, indexar_correo.py, mcp_correo.py, copiar_gloda.py) ---
# Perfil de Thunderbird de donde salen tanto el gloda "en vivo" (RUTA_GLODA_ORIGEN,
# bloqueado mientras Thunderbird esta abierto) como prefs.js y los mbox en disco
# (leidos por mapear_mbox.py). Un solo perfil: "6g35p5va.default-release".
#
# perfil_tb() hace la resolucion (APPDATA, o TB_APPDATA bajo LocalSystem, que
# no tiene perfil de usuario) y solo deben llamarla los scripts de correo.
# PERFIL_TB y RUTA_GLODA_ORIGEN se mantienen disponibles para compatibilidad
# pero calculados de forma perezosa (module __getattr__, PEP 562): no se
# resuelven al importar config_rutas, solo al acceder a esos nombres, para
# que los circuitos de documentos/fotos no se rompan si no hay perfil de
# Thunderbird (p.ej. bajo LocalSystem sin TB_APPDATA).


def perfil_tb() -> Path:
    appdata = Path(os.environ.get("APPDATA", ""))
    if not (appdata / "Thunderbird").is_dir():
        appdata = Path(os.environ.get("TB_APPDATA", appdata))
    if not (appdata / "Thunderbird").is_dir():
        raise RuntimeError(
            "No se encontro la carpeta Thunderbird en APPDATA "
            f"({appdata!s}). Bajo LocalSystem (sin perfil de usuario), "
            "define la variable de entorno TB_APPDATA apuntando al AppData "
            "del usuario cuyo perfil de Thunderbird se quiere usar."
        )
    return appdata / "Thunderbird" / "Profiles" / "6g35p5va.default-release"


def __getattr__(name):
    if name == "PERFIL_TB":
        return perfil_tb()
    if name == "RUTA_GLODA_ORIGEN":
        # gloda "en vivo" de Thunderbird: se copia (copiar_gloda.py) a
        # RUTA_GLODA para poder leerlo sin pelearse con el lock de
        # Thunderbird ni arriesgarse a leerlo a medio escribir.
        return perfil_tb() / "global-messages-db.sqlite"
    raise AttributeError(f"module {__name__!r} no tiene el atributo {name!r}")


# Copia de solo lectura de gloda que usan mapear_mbox.py e indexar_correo.py.
# La genera copiar_gloda.py; no es el gloda real de Thunderbird.
RUTA_GLODA = Path(r"D:\paperless\correo\gloda.sqlite")
