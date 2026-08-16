"""
Indexa las fotos del disco externo en ChromaDB:
  1. vl3-paperless (vision) describe cada foto en espanol
  2. nomic-embed-text vectoriza la descripcion
  3. Se guarda en ChromaDB con ruta, fecha EXIF y carpeta

Es incremental: si la foto ya esta indexada y no ha cambiado, la salta.
NO modifica ni mueve ningun archivo.
"""
import base64
import io
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import chromadb
import requests
from PIL import Image, ExifTags

from config_rutas import (
    CARPETA_DB as CHROMA_PATH,   # mismo chroma/ que documentos, otra coleccion
    OLLAMA_BASE as OLLAMA,
    MODELO_VISION,
    MODELO_EMBED_FOTOS as MODELO_EMBED,
)
from utils_lock import adquirir_lock, liberar_lock

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass

# --- Configuracion ---
SCRIPTS = Path(__file__).resolve().parent         # antes: D:\paperless\scripts

ETIQUETA_DISCO = "Multimedia IA"
CARPETA_FOTOS = "FOTOS"
COLECCION = "fotos"
LADO_MAX = 896          # se reescala antes de mandar al modelo (mas rapido)
LOG = SCRIPTS / "indexar_fotos.log"

# Lock de instancia unica, en la misma carpeta donde el script guarda sus
# datos (CARPETA_DB de config_rutas.py, el chroma/ compartido).
# adquirir_lock()/liberar_lock() viven en utils_lock.py, compartidas con
# indexar_documentos.py.
LOCK = Path(CHROMA_PATH) / "indexar_fotos.lock"

EXT_FOTO = {".jpg", ".jpeg", ".png", ".heic", ".bmp", ".webp", ".tiff"}

PROMPT = """Describe esta fotografia en espanol, en 2 o 3 frases.
Incluye: que o quien aparece, el lugar o tipo de escena (playa, montana, interior,
ciudad, restaurante, celebracion...), objetos destacados, y si hay texto visible
transcribelo. Se concreto y factual. No inventes nombres de personas ni lugares.
Responde solo con la descripcion, sin preambulos."""


def log(msg):
    linea = f"{datetime.now():%Y-%m-%d %H:%M} | {msg}"
    print(linea)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(linea + "\n")


def letra_disco():
    ps = f'(Get-Volume | Where-Object FileSystemLabel -eq "{ETIQUETA_DISCO}").DriveLetter'
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True)
    letra = r.stdout.strip()
    if not letra:
        raise SystemExit(f"Disco '{ETIQUETA_DISCO}' no conectado.")
    return letra


def fecha_exif(ruta):
    try:
        with Image.open(ruta) as im:
            exif = im._getexif() or {}
            for tag, valor in exif.items():
                if ExifTags.TAGS.get(tag) in ("DateTimeOriginal", "DateTime"):
                    return str(valor)[:10].replace(":", "-")
    except Exception:
        pass
    # Sin EXIF: usa la fecha de modificacion del archivo
    return datetime.fromtimestamp(ruta.stat().st_mtime).strftime("%Y-%m-%d")


def imagen_b64(ruta):
    with Image.open(ruta) as im:
        im = im.convert("RGB")
        im.thumbnail((LADO_MAX, LADO_MAX))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=88)
        return base64.b64encode(buf.getvalue()).decode()


def _post_ollama(url, payload, timeout):
    """POST a Ollama con reintentos y backoff exponencial: mismo patron que
    embedding() en indexar_documentos.py (3 intentos, esperas de 2 y 4
    segundos). Reintenta ante fallos de conexion, timeout y errores 5xx del
    servidor; un error 4xx (peticion invalida) se propaga de inmediato."""
    esperas = (2, 4)
    for intento in range(3):
        try:
            r = requests.post(url, json=payload, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except (ConnectionResetError, requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            if intento == 2:
                raise
            log(f"  Reintento Ollama ({intento + 1}/3) tras {type(e).__name__}: {e}. Espero {esperas[intento]}s.")
            time.sleep(esperas[intento])
        except requests.exceptions.HTTPError as e:
            if e.response is None or e.response.status_code < 500 or intento == 2:
                raise
            log(f"  Reintento Ollama ({intento + 1}/3) tras HTTP {e.response.status_code}. Espero {esperas[intento]}s.")
            time.sleep(esperas[intento])


def describir(ruta):
    datos = _post_ollama(
        f"{OLLAMA}/api/generate",
        {
            "model": MODELO_VISION,
            "prompt": PROMPT,
            "images": [imagen_b64(ruta)],
            "stream": False,
            "options": {"temperature": 0.1},
        },
        timeout=300,
    )
    return datos["response"].strip()


def embed(texto):
    datos = _post_ollama(
        f"{OLLAMA}/api/embeddings",
        {"model": MODELO_EMBED, "prompt": f"search_document: {texto}"},
        timeout=120,
    )
    return datos["embedding"]


def main():
    d = letra_disco()
    raiz = Path(f"{d}:\\") / CARPETA_FOTOS
    fotos = sorted(p for p in raiz.rglob("*")
                   if p.is_file() and p.suffix.lower() in EXT_FOTO)
    log(f"Disco {d}: | {len(fotos)} fotos encontradas")

    cliente = chromadb.PersistentClient(path=CHROMA_PATH)
    col = cliente.get_or_create_collection(
        name=COLECCION, metadata={"hnsw:space": "cosine"}
    )

    ya = set(col.get(include=[])["ids"])
    log(f"Ya indexadas: {len(ya)}")

    nuevas, errores = 0, 0
    for i, p in enumerate(fotos, 1):
        # ID estable: ruta relativa + tamano (cambia si la foto cambia)
        idf = f"{p.relative_to(raiz)}|{p.stat().st_size}"
        if idf in ya:
            continue
        try:
            desc = describir(p)
            vec = embed(desc)
            col.upsert(
                ids=[idf],
                embeddings=[vec],
                documents=[desc],
                metadatas=[{
                    "ruta": str(p),
                    "nombre": p.name,
                    "carpeta": str(p.parent.relative_to(raiz)) or ".",
                    "fecha": fecha_exif(p),
                }],
            )
            nuevas += 1
            log(f"[{i}/{len(fotos)}] {p.name} -> {desc[:70]}...")
        except Exception as e:
            errores += 1
            log(f"[{i}/{len(fotos)}] ERROR {p.name}: {e}")

    # Purga entradas cuyas fotos ya no existen (movidas o borradas)
    datos = col.get(include=["metadatas"])
    huerfanas = [i for i, m in zip(datos["ids"], datos["metadatas"])
                 if not Path(m.get("ruta", "")).exists()]
    if huerfanas:
        col.delete(ids=huerfanas)
        log(f"Purgadas {len(huerfanas)} entradas obsoletas")

    log(f"TERMINADO. Nuevas: {nuevas} | Errores: {errores} | Total: {col.count()}")


if __name__ == "__main__":
    lock_f = adquirir_lock(LOCK)
    if lock_f is None:
        log("Ya hay otra instancia de indexar_fotos.py corriendo. Saliendo sin hacer nada.")
        sys.exit(0)
    try:
        main()
    finally:
        liberar_lock(lock_f)