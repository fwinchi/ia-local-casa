"""
Constantes de rutas y configuracion compartidas por varios scripts del
repo. Un solo sitio para no tener que mantener sincronizadas varias
copias cada vez que cambia una carpeta, un modelo o los formatos
soportados. Dos circuitos, cada uno con sus propias constantes:

- Documentos (indexar_pdfs.py, mcp_pdfs.py, buscar.py; también salud.py):
  CARPETAS_PDFS, OLLAMA (URL completa del endpoint de embeddings),
  MODELO (bge-m3), EXTENSIONES.
- Fotos/vídeos (indexar_fotos.py, indexar_videos.py, mcp_fotos.py):
  OLLAMA_BASE (URL base de Ollama, sin ruta de endpoint — estos scripts
  la usan tanto para /api/generate como para /api/embeddings),
  MODELO_VISION (vl-paperless), MODELO_EMBED_FOTOS (nomic-embed-text).

BASE y CARPETA_DB son comunes a los dos circuitos: mismo `chroma/`,
colecciones distintas ("documentos" en uno, "fotos"/"videos" en otro).
"""

from pathlib import Path

BASE = Path(__file__).resolve().parent.parent   # antes: D:\paperless

# Carpetas indexadas por indexar_pdfs.py y validadas por abrir_pdf en
# mcp_pdfs.py (ninguna ruta fuera de ellas se puede abrir). Ambas con el
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

# Formatos que indexa indexar_pdfs.py y que abrir_pdf puede abrir.
EXTENSIONES = [".pdf", ".docx", ".txt", ".odt"]

# --- Fotos / vídeos ---
OLLAMA_BASE = "http://localhost:11434"
MODELO_VISION = "vl-paperless"
MODELO_EMBED_FOTOS = "nomic-embed-text"
