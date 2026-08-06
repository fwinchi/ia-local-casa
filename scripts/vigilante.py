"""
Vigilante de duplicados.
- Si el disco no esta conectado: sale al instante y borra el estado.
- Si esta conectado: ejecuta revisar.py y abre revision.html SOLO si los
  duplicados detectados han cambiado desde la ultima vez que se mostro.
"""
import hashlib
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ETIQUETA_DISCO = "OrangePi Externo"
SCRIPTS = Path(__file__).resolve().parent   # antes: D:\paperless\scripts
PYTHON = str(Path.home() / "AppData/Local/Python/bin/python.exe")
REVISAR = SCRIPTS / "revisar.py"
HTML = SCRIPTS / "revision.html"
ESTADO = SCRIPTS / ".estado_duplicados"
LOG = SCRIPTS / "vigilante.log"


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M} | {msg}\n")


def disco_conectado():
    ps = f'(Get-Volume | Where-Object FileSystemLabel -eq "{ETIQUETA_DISCO}").DriveLetter'
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return bool(r.stdout.strip())


def firma_html():
    """Huella del conjunto de archivos duplicados (ignora la fecha del informe)."""
    if not HTML.exists():
        return None
    texto = HTML.read_text(encoding="utf-8", errors="ignore")
    rutas = sorted(set(re.findall(r'data-ruta="([^"]+)"', texto)))
    if not rutas:
        return "vacio"
    return hashlib.sha256("\n".join(rutas).encode("utf-8")).hexdigest()


def main():
    if not disco_conectado():
        if ESTADO.exists():
            ESTADO.unlink()
            log("Disco desconectado. Estado reiniciado.")
        return

    r = subprocess.run(
        [PYTHON, str(REVISAR)],
        capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if r.returncode != 0:
        log(f"ERROR en revisar.py: {r.stderr.strip()[:300]}")
        return

    firma = firma_html()
    if firma in (None, "vacio"):
        log("Sin duplicados.")
        ESTADO.write_text("vacio", encoding="utf-8")
        return

    anterior = ESTADO.read_text(encoding="utf-8").strip() if ESTADO.exists() else ""
    if firma == anterior:
        log("Sin cambios. No se abre el HTML.")
        return

    ESTADO.write_text(firma, encoding="utf-8")
    log("Duplicados nuevos. Abriendo revision.html")
    os.startfile(str(HTML))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"EXCEPCION: {e}")
        sys.exit(1)