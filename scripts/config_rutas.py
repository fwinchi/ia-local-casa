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

BASE y CARPETA_DB son comunes a los dos circuitos: mismo `chroma/`,
colecciones distintas ("documentos" en uno, "fotos"/"videos" en otro).
"""

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
