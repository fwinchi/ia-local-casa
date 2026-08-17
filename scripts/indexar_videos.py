"""
Indexa los videos del disco externo en ChromaDB:
  1. ffmpeg extrae 3 fotogramas repartidos por el video
  2. vl3-paperless describe cada fotograma
  3. Se resume en una descripcion unica y se vectoriza con nomic-embed-text
  4. Se guarda en ChromaDB con ruta, duracion, resolucion y fecha

Es incremental. NO modifica ni mueve ningun archivo.
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import chromadb
import requests

from config_rutas import (
    CARPETA_DB as CHROMA_PATH,   # mismo chroma/ que documentos, otra coleccion
    OLLAMA_BASE as OLLAMA,
    MODELO_VISION,
    MODELO_EMBED_FOTOS as MODELO_EMBED,
)
from utils_lock import adquirir_lock, liberar_lock

SCRIPTS = Path(__file__).resolve().parent         # antes: D:\paperless\scripts

ETIQUETA_DISCO = "Multimedia IA"
CARPETA_VIDEOS = "VIDEOS"
COLECCION = "videos"
FOTOGRAMAS = 3
ANCHO_MAX = 896
LOG = SCRIPTS / "indexar_videos.log"

# Lock de instancia unica, en la misma carpeta donde el script guarda sus
# datos (CARPETA_DB de config_rutas.py, el chroma/ compartido).
# adquirir_lock()/liberar_lock() viven en utils_lock.py, compartidas con
# indexar_documentos.py e indexar_fotos.py.
LOCK = Path(CHROMA_PATH) / "indexar_videos.lock"

EXT_VIDEO = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v", ".mpg", ".mpeg", ".3gp", ".webm"}

PROMPT = """Describe este fotograma de un video en espanol, en 1 o 2 frases.
Indica que o quien aparece, el lugar o tipo de escena, y si hay texto visible
transcribelo. Se concreto y factual. No inventes nombres de personas ni lugares.
Responde solo con la descripcion."""

FFMPEG = shutil.which("ffmpeg") or str(Path.home() / "AppData/Local/Microsoft/WinGet/Links/ffmpeg.exe")
FFPROBE = shutil.which("ffprobe") or str(Path.home() / "AppData/Local/Microsoft/WinGet/Links/ffprobe.exe")

NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def log(msg):
    linea = f"{datetime.now():%Y-%m-%d %H:%M} | {msg}"
    print(linea)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(linea + "\n")


def letra_disco():
    ps = f'(Get-Volume | Where-Object FileSystemLabel -eq "{ETIQUETA_DISCO}").DriveLetter'
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    letra = r.stdout.strip()
    if not letra:
        raise SystemExit(f"Disco '{ETIQUETA_DISCO}' no conectado.")
    return letra


def info_video(ruta):
    """Devuelve (duracion_segundos, resolucion) usando ffprobe."""
    r = subprocess.run(
        [FFPROBE, "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", str(ruta)],
        capture_output=True, text=True, creationflags=NO_WINDOW,
    )
    try:
        datos = json.loads(r.stdout)
        dur = float(datos.get("format", {}).get("duration", 0))
        res = "?"
        for s in datos.get("streams", []):
            if s.get("codec_type") == "video":
                res = f"{s.get('width')}x{s.get('height')}"
                break
        return dur, res
    except Exception:
        return 0.0, "?"


def extraer_fotogramas(ruta, duracion, carpeta):
    """Saca FOTOGRAMAS repartidos evitando el principio y el final."""
    salidas = []
    if duracion <= 0:
        instantes = [1]
    else:
        instantes = [duracion * f for f in (0.15, 0.5, 0.85)][:FOTOGRAMAS]

    for i, t in enumerate(instantes):
        destino = carpeta / f"f{i}.jpg"
        subprocess.run(
            [FFMPEG, "-y", "-ss", f"{t:.2f}", "-i", str(ruta),
             "-frames:v", "1", "-vf", f"scale='min({ANCHO_MAX},iw)':-2",
             "-q:v", "4", str(destino)],
            capture_output=True, creationflags=NO_WINDOW,
        )
        if destino.exists() and destino.stat().st_size > 0:
            salidas.append(destino)
    return salidas


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


def describir(imagen):
    with open(imagen, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    datos = _post_ollama(
        f"{OLLAMA}/api/generate",
        {"model": MODELO_VISION, "prompt": PROMPT, "images": [b64],
         "stream": False, "options": {"temperature": 0.1}},
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
    if not Path(FFMPEG).exists() and not shutil.which("ffmpeg"):
        raise SystemExit("No se encuentra ffmpeg.")

    d = letra_disco()
    raiz = Path(f"{d}:\\") / CARPETA_VIDEOS
    videos = sorted(p for p in raiz.rglob("*")
                    if p.is_file() and p.suffix.lower() in EXT_VIDEO)
    log(f"Disco {d}: | {len(videos)} videos encontrados")

    cli = chromadb.PersistentClient(path=CHROMA_PATH)
    col = cli.get_or_create_collection(name=COLECCION, metadata={"hnsw:space": "cosine"})
    ya = set(col.get(include=[])["ids"])
    log(f"Ya indexados: {len(ya)}")

    nuevos, errores = 0, 0
    for i, p in enumerate(videos, 1):
        idf = f"{p.relative_to(raiz)}|{p.stat().st_size}"
        if idf in ya:
            continue
        try:
            dur, res = info_video(p)
            with tempfile.TemporaryDirectory() as tmp:
                frames = extraer_fotogramas(p, dur, Path(tmp))
                if not frames:
                    raise RuntimeError("no se pudo extraer ningun fotograma")
                partes = [describir(f) for f in frames]

            desc = " ".join(f"[{n*100//len(partes)}%] {t}" for n, t in enumerate(partes))
            col.upsert(
                ids=[idf],
                embeddings=[embed(desc)],
                documents=[desc],
                metadatas=[{
                    "ruta": str(p),
                    "nombre": p.name,
                    "carpeta": str(p.parent.relative_to(raiz)) or ".",
                    "duracion": f"{int(dur//60)}:{int(dur%60):02d}",
                    "resolucion": res,
                    "fecha": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d"),
                }],
            )
            nuevos += 1
            log(f"[{i}/{len(videos)}] {p.name} ({int(dur)}s) -> {desc[:70]}...")
        except Exception as e:
            errores += 1
            log(f"[{i}/{len(videos)}] ERROR {p.name}: {e}")

    log(f"TERMINADO. Nuevos: {nuevos} | Errores: {errores} | Total: {col.count()}")


if __name__ == "__main__":
    lock_f = adquirir_lock(LOCK)
    if lock_f is None:
        log("Ya hay otra instancia de indexar_videos.py corriendo. Saliendo sin hacer nada.")
        sys.exit(0)
    try:
        main()
    finally:
        liberar_lock(lock_f)