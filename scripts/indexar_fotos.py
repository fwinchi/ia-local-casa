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
import msvcrt
import subprocess
import sys
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


def adquirir_lock():
    """Lock de instancia unica via msvcrt.locking sobre un fichero abierto,
    no por comprobacion de existencia: si el proceso anterior crasheo,
    Windows libera el lock del descriptor solo, sin dejar candados
    huerfanos que haya que borrar a mano.

    Devuelve el file object con el lock activo, o None si ya hay otra
    instancia corriendo.
    """
    f = open(LOCK, "a+b")
    try:
        if f.tell() == 0:
            f.write(b"0")
            f.flush()
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        return None
    return f


def liberar_lock(f):
    if f is None:
        return
    try:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    f.close()


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


def describir(ruta):
    r = requests.post(
        f"{OLLAMA}/api/generate",
        json={
            "model": MODELO_VISION,
            "prompt": PROMPT,
            "images": [imagen_b64(ruta)],
            "stream": False,
            "options": {"temperature": 0.1},
        },
        timeout=300,
    )
    r.raise_for_status()
    return r.json()["response"].strip()


def embed(texto):
    r = requests.post(
        f"{OLLAMA}/api/embeddings",
        json={"model": MODELO_EMBED, "prompt": f"search_document: {texto}"},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["embedding"]


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
    lock_f = adquirir_lock()
    if lock_f is None:
        log("Ya hay otra instancia de indexar_fotos.py corriendo. Saliendo sin hacer nada.")
        sys.exit(0)
    try:
        main()
    finally:
        liberar_lock(lock_f)