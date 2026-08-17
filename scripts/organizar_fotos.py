"""
Organiza las fotos del disco externo en carpetas AAAA\\MM segun la fecha EXIF.
Las fotos sin fecha EXIF fiable van a la carpeta "Sin fecha".

Por defecto solo SIMULA y genera un informe. Para mover de verdad:
    python organizar_fotos.py --aplicar
"""
import re
import sys
from datetime import datetime
from pathlib import Path
import shutil

from PIL import Image, ExifTags

from config_rutas import EXT_FOTO
from utils_comun import letra_disco

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass

SCRIPTS = Path(__file__).resolve().parent   # antes: D:\paperless\scripts

CARPETA_FOTOS = "FOTOS"
SIN_FECHA = "Sin fecha"
INFORME = SCRIPTS / "organizacion_fotos.txt"
LOG = SCRIPTS / "organizar_fotos.log"

# Subcarpetas de primer nivel bajo la raiz que el recorrido ignora por
# completo (no se cuentan, no aparecen en el informe). Se puede reordenar
# ese subarbol aparte con --raiz, que desactiva esta exclusion.
EXCLUIR = {"WhatsApp"}

MESES = {
    "01": "01-Enero", "02": "02-Febrero", "03": "03-Marzo", "04": "04-Abril",
    "05": "05-Mayo", "06": "06-Junio", "07": "07-Julio", "08": "08-Agosto",
    "09": "09-Septiembre", "10": "10-Octubre", "11": "11-Noviembre", "12": "12-Diciembre",
}


def fecha_exif(ruta):
    """Solo DateTimeOriginal. Si no existe, devuelve None (no inventamos fecha)."""
    try:
        with Image.open(ruta) as im:
            exif = im._getexif() or {}
            for tag, valor in exif.items():
                if ExifTags.TAGS.get(tag) == "DateTimeOriginal":
                    texto = str(valor).strip()
                    if len(texto) >= 7 and texto[:4].isdigit():
                        anio, mes = texto[:4], texto[5:7]
                        if anio > "1990" and mes in MESES:
                            return anio, mes
    except Exception:
        pass
    return None


FECHA_MIN, FECHA_MAX = 1995, datetime.now().year


def _valida(anio, mes):
    if mes not in MESES:
        return None
    if not (FECHA_MIN <= int(anio) <= FECHA_MAX):
        return None
    return anio, mes


def fecha_nombre(p):
    n = p.name
    m = re.search(r"(?<!\d)(19[9]\d|20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)", n)
    if m:
        r = _valida(m.group(1), m.group(2))
        if r:
            return r
    m = re.search(r"(?<!\d)(19[9]\d|20\d{2})[-_.](0[1-9]|1[0-2])[-_.](0[1-9]|[12]\d|3[01])(?!\d)", n)
    if m:
        r = _valida(m.group(1), m.group(2))
        if r:
            return r
    m = re.search(r"(?<!\d)(1[0-9]{12})(?!\d)", n)
    if m:
        try:
            f = datetime.fromtimestamp(int(m.group(1)) / 1000)
            r = _valida(f"{f.year}", f"{f.month:02d}")
            if r:
                return r
        except Exception:
            pass
    return None


def destino_de(p, raiz):
    f = fecha_exif(p) or fecha_nombre(p)
    if f is None:
        return raiz / SIN_FECHA / p.name
    anio, mes = f
    return raiz / anio / MESES[mes] / p.name


def nombre_libre(ruta):
    if not ruta.exists():
        return ruta
    n = 1
    while True:
        nuevo = ruta.with_name(f"{ruta.stem} ({n}){ruta.suffix}")
        if not nuevo.exists():
            return nuevo
        n += 1


def dentro_de_excluida(p, raiz):
    """True si el primer nivel de carpeta de p bajo raiz esta en EXCLUIR."""
    rel = p.relative_to(raiz).parts
    return len(rel) > 1 and rel[0] in EXCLUIR


def main():
    aplicar = "--aplicar" in sys.argv

    if "--raiz" in sys.argv:
        i = sys.argv.index("--raiz")
        if i + 1 >= len(sys.argv):
            raise SystemExit("--raiz necesita una ruta: --raiz <ruta>")
        raiz = Path(sys.argv[i + 1])
        excluir_activo = False   # --raiz permite ordenar precisamente el subarbol excluido
    else:
        d = letra_disco()
        raiz = Path(f"{d}:\\") / CARPETA_FOTOS
        excluir_activo = True

    fotos = [p for p in raiz.rglob("*")
             if p.is_file() and p.suffix.lower() in EXT_FOTO]
    if excluir_activo:
        fotos = [p for p in fotos if not dentro_de_excluida(p, raiz)]
    print(f"Raiz {raiz}: {len(fotos)} fotos")

    movimientos, ya_ok, resumen = [], 0, {}
    for i, p in enumerate(fotos, 1):
        if i % 100 == 0:
            print(f"  analizando {i}/{len(fotos)}")
        destino = destino_de(p, raiz)
        clave = str(destino.parent.relative_to(raiz))
        resumen[clave] = resumen.get(clave, 0) + 1
        if destino.parent == p.parent:
            ya_ok += 1
            continue
        movimientos.append((p, destino))

    lineas = [f"ORGANIZACION DE FOTOS - {datetime.now():%Y-%m-%d %H:%M}",
              "=" * 70,
              f"Fotos totales: {len(fotos)}",
              f"Ya en su sitio: {ya_ok}",
              f"A mover: {len(movimientos)}",
              "", "### CARPETAS RESULTANTES"]
    for k in sorted(resumen):
        lineas.append(f"  {k}  ->  {resumen[k]} fotos")
    lineas += ["", "### MOVIMIENTOS"]
    for origen, destino in movimientos:
        lineas.append(f"  {origen.relative_to(raiz)}  ->  {destino.relative_to(raiz)}")

    INFORME.write_text("\n".join(lineas), encoding="utf-8")
    print(f"\nInforme: {INFORME}")
    print(f"Ya en su sitio: {ya_ok} | A mover: {len(movimientos)}")

    if not aplicar:
        print("\nMODO SIMULACION. No se ha movido nada.")
        print("Revisa el informe y, si esta bien, ejecuta el script con  --aplicar")
        return

    if not movimientos:
        print("Nada que mover.")
        return

    if input(f"\nMover {len(movimientos)} fotos. Escribe SI para continuar: ").strip().upper() != "SI":
        print("Cancelado.")
        return

    movidos, fallos = 0, 0
    registro = [f"--- {datetime.now():%Y-%m-%d %H:%M} ---"]
    for origen, destino in movimientos:
        try:
            destino = nombre_libre(destino)
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(origen), str(destino))
            registro.append(f"MOVIDO: {origen} -> {destino}")
            movidos += 1
        except Exception as e:
            registro.append(f"ERROR: {origen} ({e})")
            fallos += 1

    # Limpia carpetas que hayan quedado vacias
    for carpeta in sorted(raiz.rglob("*"), key=lambda x: -len(x.parts)):
        if carpeta.is_dir():
            try:
                next(carpeta.iterdir())
            except StopIteration:
                carpeta.rmdir()
                registro.append(f"CARPETA VACIA ELIMINADA: {carpeta}")
            except Exception:
                pass

    with open(LOG, "a", encoding="utf-8") as f:
        f.write("\n".join(registro) + "\n")

    print(f"\nMovidos: {movidos} | Fallos: {fallos}")
    print(f"Log: {LOG}")
    print("\nIMPORTANTE: ejecuta ahora indexar_fotos.py para actualizar las rutas del indice.")


if __name__ == "__main__":
    main()