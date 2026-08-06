"""
Mueve los duplicados confirmados a una carpeta de cuarentena.
NO borra definitivamente: si algo sale mal, los archivos siguen ahi.
Cuando pasen unas semanas y todo este bien, borras la carpeta a mano.
"""
import json
from datetime import datetime
from pathlib import Path
import shutil

BASE = Path(__file__).resolve().parent.parent      # antes: D:\paperless
SCRIPTS = Path(__file__).resolve().parent            # antes: D:\paperless\scripts

LISTA = SCRIPTS / "duplicados_confirmados.json"
CUARENTENA = BASE / "cuarentena_duplicados"
LOG = SCRIPTS / "borrado.log"


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

    rutas = [Path(r) for r in json.loads(LISTA.read_text(encoding="utf-8"))]
    if not rutas:
        print("La lista esta vacia. Nada que hacer.")
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