"""
Detector de duplicados para fotos y videos del disco externo.
- Fotos: SHA-256 (exacto) + pHash (perceptual, detecta reescalados/recomprimidos)
- Videos: SHA-256 (exacto)
NO BORRA NADA. Genera informe + JSON para el paso de borrado posterior.
"""
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image
import imagehash

from config_rutas import CARPETA_DB
from utils_lock import adquirir_lock, liberar_lock

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass

# --- Configuracion ---
SCRIPTS = Path(__file__).resolve().parent   # antes: D:\paperless\scripts

ETIQUETA_DISCO = "Multimedia IA"
CARPETA_FOTOS = "FOTOS"
CARPETA_VIDEOS = "VIDEOS"
UMBRAL_PHASH = 5          # 0 = identicas; 5 = casi identicas; >10 empieza a dar falsos positivos
SALIDA = SCRIPTS

# Lock de instancia unica, en la misma carpeta que usan indexar_fotos.py /
# indexar_videos.py (CARPETA_DB de config_rutas.py, el chroma/ compartido).
LOCK = Path(CARPETA_DB) / "duplicados.lock"

EXT_FOTO = {".jpg", ".jpeg", ".png", ".heic", ".bmp", ".webp", ".tiff", ".gif"}
EXT_VIDEO = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v", ".mpg", ".mpeg", ".3gp"}


def letra_disco():
    ps = (
        f'(Get-Volume | Where-Object FileSystemLabel -eq "{ETIQUETA_DISCO}").DriveLetter'
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True
    )
    letra = r.stdout.strip()
    if not letra:
        raise SystemExit(f"No se encuentra el disco con etiqueta '{ETIQUETA_DISCO}'. Conectalo.")
    return letra


def sha256(ruta, bloque=1024 * 1024):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        while chunk := f.read(bloque):
            h.update(chunk)
    return h.hexdigest()


def phash(ruta):
    try:
        with Image.open(ruta) as im:
            im.draft("RGB", (512, 512))
            return imagehash.phash(im.convert("RGB"))
    except Exception:
        return None


def listar(carpeta, extensiones):
    if not carpeta.exists():
        print(f"AVISO: no existe {carpeta}")
        return []
    return [
        p for p in carpeta.rglob("*")
        if p.is_file() and p.suffix.lower() in extensiones
    ]


def resolucion(ruta):
    try:
        with Image.open(ruta) as im:
            return im.width * im.height
    except Exception:
        return 0


def mejor(grupo, es_foto):
    """Elige la copia a conservar: mayor resolucion, luego mayor tamano, luego mas antigua."""
    def clave(p):
        return (
            resolucion(p) if es_foto else 0,
            p.stat().st_size,
            -p.stat().st_mtime,
        )
    return max(grupo, key=clave)


def mb(ruta):
    return ruta.stat().st_size / (1024 * 1024)


def agrupar_exactos(archivos, etiqueta):
    print(f"\n[{etiqueta}] Calculando hash exacto de {len(archivos)} archivos...")
    mapa = {}
    for i, p in enumerate(archivos, 1):
        if i % 50 == 0:
            print(f"  {i}/{len(archivos)}")
        try:
            mapa.setdefault(sha256(p), []).append(p)
        except Exception as e:
            print(f"  ERROR {p.name}: {e}")
    return [g for g in mapa.values() if len(g) > 1]


def agrupar_perceptuales(archivos, ya_marcados):
    print(f"\n[FOTOS] Calculando hash perceptual...")
    hashes = []
    for i, p in enumerate(archivos, 1):
        if i % 50 == 0:
            print(f"  {i}/{len(archivos)}")
        if p in ya_marcados:
            continue
        h = phash(p)
        if h is not None:
            hashes.append((p, h))

    grupos, usados = [], set()
    for i, (p1, h1) in enumerate(hashes):
        if p1 in usados:
            continue
        grupo = [p1]
        for p2, h2 in hashes[i + 1:]:
            if p2 in usados:
                continue
            if (h1 - h2) <= UMBRAL_PHASH:
                grupo.append(p2)
                usados.add(p2)
        if len(grupo) > 1:
            usados.add(p1)
            grupos.append(grupo)
    return grupos


def escribir(grupos_fotos_exact, grupos_fotos_perc, grupos_videos):
    SALIDA.mkdir(parents=True, exist_ok=True)
    informe = SALIDA / "duplicados.txt"
    plan = SALIDA / "duplicados.json"

    lineas, borrables, espacio = [], [], 0.0
    lineas.append(f"INFORME DE DUPLICADOS - {datetime.now():%Y-%m-%d %H:%M}")
    lineas.append("=" * 70)

    bloques = [
        ("FOTOS - DUPLICADOS EXACTOS (byte a byte)", grupos_fotos_exact, True),
        (f"FOTOS - DUPLICADOS PERCEPTUALES (umbral {UMBRAL_PHASH}) - REVISAR", grupos_fotos_perc, True),
        ("VIDEOS - DUPLICADOS EXACTOS (byte a byte)", grupos_videos, False),
    ]

    for titulo, grupos, es_foto in bloques:
        lineas.append(f"\n\n### {titulo}")
        lineas.append(f"Grupos encontrados: {len(grupos)}")
        for n, g in enumerate(grupos, 1):
            conservar = mejor(g, es_foto)
            lineas.append(f"\n-- Grupo {n} --")
            for p in g:
                marca = "CONSERVAR" if p == conservar else "  borrar  "
                lineas.append(f"  [{marca}] {mb(p):8.2f} MB  {p}")
                if p != conservar:
                    borrables.append(str(p))
                    espacio += mb(p)

    lineas.append("\n\n" + "=" * 70)
    lineas.append(f"TOTAL archivos a borrar: {len(borrables)}")
    lineas.append(f"Espacio a liberar: {espacio:.1f} MB")

    informe.write_text("\n".join(lineas), encoding="utf-8")
    plan.write_text(json.dumps(borrables, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"Informe:  {informe}")
    print(f"Plan:     {plan}")
    print(f"A borrar: {len(borrables)} archivos ({espacio:.1f} MB)")
    print("=" * 60)


def main():
    d = letra_disco()
    print(f"Disco detectado en {d}:")
    raiz = Path(f"{d}:\\")

    fotos = listar(raiz / CARPETA_FOTOS, EXT_FOTO)
    videos = listar(raiz / CARPETA_VIDEOS, EXT_VIDEO)
    print(f"Fotos: {len(fotos)} | Videos: {len(videos)}")

    g_fotos_exact = agrupar_exactos(fotos, "FOTOS")
    marcados = {p for g in g_fotos_exact for p in g}
    g_fotos_perc = agrupar_perceptuales(fotos, marcados)
    g_videos = agrupar_exactos(videos, "VIDEOS")

    escribir(g_fotos_exact, g_fotos_perc, g_videos)


if __name__ == "__main__":
    lock_f = adquirir_lock(LOCK)
    if lock_f is None:
        print("Ya hay otra instancia de duplicados.py corriendo. Saliendo sin hacer nada.")
        sys.exit(0)
    try:
        main()
    finally:
        liberar_lock(lock_f)