"""
Mueve los duplicados confirmados a una carpeta de cuarentena.
NO borra definitivamente: si algo sale mal, los archivos siguen ahi.
Cuando pasen unas semanas y todo este bien, borras la carpeta a mano.
"""
import json
import subprocess
from datetime import datetime
from pathlib import Path
import shutil

BASE = Path(__file__).resolve().parent.parent      # antes: D:\paperless
SCRIPTS = Path(__file__).resolve().parent            # antes: D:\paperless\scripts

LISTA = SCRIPTS / "duplicados_confirmados.json"
CUARENTENA = BASE / "cuarentena_duplicados"
LOG = SCRIPTS / "borrado.log"

ETIQUETA_DISCO_EXTERNO = "Multimedia IA"
CARPETA_FOTOS = "FOTOS"
CARPETA_VIDEOS = "VIDEOS"


def letra_disco_externo():
    ps = f'(Get-Volume | Where-Object FileSystemLabel -eq "{ETIQUETA_DISCO_EXTERNO}").DriveLetter'
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True)
    letra = r.stdout.strip()
    if not letra:
        raise SystemExit(f"No se encuentra el disco '{ETIQUETA_DISCO_EXTERNO}'. Conectalo.")
    return letra


def nombre_libre(ruta):
    if not ruta.exists():
        return ruta
    n = 1
    while True:
        nuevo = ruta.with_name(f"{ruta.stem} ({n}){ruta.suffix}")
        if not nuevo.exists():
            return nuevo
        n += 1


def main():
    if not LISTA.exists():
        raise SystemExit(f"No existe {LISTA}. Descarga la lista desde revision.html.")

    d = letra_disco_externo()
    permitidas = [(Path(f"{d}:\\") / CARPETA_FOTOS).resolve(),
                  (Path(f"{d}:\\") / CARPETA_VIDEOS).resolve()]

    # No confiar ciegamente en el JSON: solo se mueven rutas dentro de las
    # carpetas de fotos/vídeos del disco externo, nunca una ruta arbitraria
    # (por si el archivo se edita a mano o se corrompe).
    candidatas = [Path(r) for r in json.loads(LISTA.read_text(encoding="utf-8"))]
    rutas, rechazadas = [], []
    for p in candidatas:
        try:
            p_resuelta = p.resolve()
        except Exception:
            rechazadas.append(p)
            continue
        if any(p_resuelta.is_relative_to(c) for c in permitidas):
            rutas.append(p_resuelta)
        else:
            rechazadas.append(p)

    if rechazadas:
        print(f"AVISO: {len(rechazadas)} ruta(s) fuera de las carpetas permitidas, ignoradas:")
        for r in rechazadas:
            print(f"  RECHAZADA: {r}")

    if not rutas:
        print("La lista esta vacia (o todo fue rechazado). Nada que hacer.")
        return

    total_mb = sum(p.stat().st_size for p in rutas if p.exists()) / (1024 * 1024)
    print(f"Archivos a mover: {len(rutas)}  ({total_mb:.1f} MB)")
    print(f"Destino: {CUARENTENA}")
    if input("\nEscribe SI para continuar: ").strip().upper() != "SI":
        print("Cancelado.")
        return

    sesion = CUARENTENA / f"{datetime.now():%Y-%m-%d_%H%M}"
    sesion.mkdir(parents=True, exist_ok=True)

    movidos, fallos = 0, 0
    lineas = [f"--- {datetime.now():%Y-%m-%d %H:%M} ---"]

    for p in rutas:
        if not p.exists():
            lineas.append(f"NO EXISTE: {p}")
            continue
        try:
            # Conserva la estructura de carpetas dentro de la cuarentena
            rel = Path(p.drive.replace(":", "")) / p.relative_to(p.anchor)
            destino = nombre_libre(sesion / rel)
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(destino))
            lineas.append(f"MOVIDO: {p}  ->  {destino}")
            movidos += 1
        except Exception as e:
            lineas.append(f"ERROR: {p}  ({e})")
            fallos += 1

    lineas.append(f"Total movidos: {movidos} | Fallos: {fallos}")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")

    print(f"\nMovidos: {movidos} | Fallos: {fallos}")
    print(f"Cuarentena: {sesion}")
    print(f"Log: {LOG}")


if __name__ == "__main__":
    main()