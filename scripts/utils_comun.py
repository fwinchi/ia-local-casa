"""
Utilidades compartidas por los scripts que trabajan con el disco externo
"Multimedia IA": localizar su letra de unidad (letra_disco) y registrar
mensajes en el fichero de log propio de cada script (log).
"""
import os
import subprocess
from datetime import datetime

from config_rutas import ETIQUETA_DISCO

NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def letra_disco():
    ps = f'(Get-Volume | Where-Object FileSystemLabel -eq "{ETIQUETA_DISCO}").DriveLetter'
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    letra = r.stdout.strip()
    if not letra:
        raise SystemExit(f"Disco '{ETIQUETA_DISCO}' no conectado.")
    return letra


def log(msg, fichero, consola=True):
    linea = f"{datetime.now():%Y-%m-%d %H:%M} | {msg}"
    if consola:
        try:
            print(linea)
        except Exception:
            pass  # sin stdout (ejecucion oculta): no interrumpe el registro en fichero
    with open(fichero, "a", encoding="utf-8") as f:
        f.write(linea + "\n")
