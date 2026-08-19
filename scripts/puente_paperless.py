"""
Puente manual entre la carpeta de documentos a indexar y la carpeta de
consumo de Paperless (D:\\paperless\\consume).

Flujo: cualquier documento que se deje a mano en a_paperless/ (subcarpeta
de la carpeta local "Documentos para indexar", CARPETAS_PDFS[1] de
config_rutas.py) se copia a CARPETA_CONSUME para que Paperless lo procese.
Solo si la copia verifica bien (mismo tamano que el original), el original
se mueve a enviado/ -- asi queda rastro de que ya se envio, sin borrar nada
nunca.

NO hace nada automatico: hay que dejar los archivos en a_paperless/ a mano
y ejecutar este script (o su lanzador puente-paperless.bat).

Uso:
    python puente_paperless.py             # copia y mueve de verdad
    python puente_paperless.py --simular   # solo dice que haria, no toca nada
"""
import shutil
import sys
import time
from pathlib import Path

from config_rutas import (
    CARPETA_A_PAPERLESS,
    CARPETA_ENVIADO,
    CARPETA_CONSUME,
    CARPETA_DB,
)
from utils_comun import log
from utils_lock import adquirir_lock, liberar_lock

SCRIPTS = Path(__file__).resolve().parent   # antes: D:\paperless\scripts
LOG = SCRIPTS / "puente_paperless.log"

# Lock de instancia unica, misma carpeta que usan los demas scripts del
# repo con lock (CARPETA_DB de config_rutas.py, el chroma/ compartido).
LOCK = Path(CARPETA_DB) / "puente_paperless.lock"

# Extensiones que puede consumir Paperless via esta carpeta de entrada.
# Conjunto propio de este script: no coincide con EXTENSIONES (documentos,
# sin imagenes) ni con EXT_FOTO (fotos, con mas formatos de imagen que
# jpg/png) de config_rutas.py -- aqui es deliberadamente ese subconjunto.
EXTENSIONES_PUENTE = {".pdf", ".docx", ".odt", ".txt", ".jpg", ".png"}

SEGUNDOS_MIN_QUIETO = 30   # si se modifico hace menos, se asume copia en curso


def nombre_libre(carpeta, nombre):
    """Path libre en `carpeta` para `nombre`: si ya existe, prueba con
    sufijos _1, _2... antes de la extension, hasta encontrar uno libre."""
    candidato = carpeta / nombre
    if not candidato.exists():
        return candidato
    stem, suffix = candidato.stem, candidato.suffix
    n = 1
    while True:
        candidato = carpeta / f"{stem}_{n}{suffix}"
        if not candidato.exists():
            return candidato
        n += 1


def procesar(origen, simular):
    """Copia `origen` a consume/ y, si la copia verifica bien, mueve el
    original a enviado/. Devuelve (resultado, mensaje) con resultado en
    {"copiado", "error"}."""
    destino_consume = nombre_libre(CARPETA_CONSUME, origen.name)

    if simular:
        return "copiado", f"[SIMULACION] {origen.name} -> {destino_consume}"

    shutil.copy2(str(origen), str(destino_consume))

    tam_origen = origen.stat().st_size
    tam_destino = destino_consume.stat().st_size
    if tam_destino != tam_origen:
        destino_consume.unlink(missing_ok=True)
        return "error", (
            f"{origen.name}: tamano no coincide tras copiar "
            f"(origen {tam_origen} bytes, destino {tam_destino} bytes) -- "
            f"destino borrado, original conservado en a_paperless/"
        )

    destino_enviado = nombre_libre(CARPETA_ENVIADO, origen.name)
    shutil.move(str(origen), str(destino_enviado))
    return "copiado", (
        f"{origen.name} -> {destino_consume.name} "
        f"(original movido a enviado/{destino_enviado.name})"
    )


def main():
    simular = "--simular" in sys.argv
    modo = " (SIMULACION)" if simular else ""

    CARPETA_A_PAPERLESS.mkdir(parents=True, exist_ok=True)
    CARPETA_ENVIADO.mkdir(parents=True, exist_ok=True)

    archivos = sorted(
        p for p in CARPETA_A_PAPERLESS.iterdir()
        if p.is_file() and p.suffix.lower() in EXTENSIONES_PUENTE
    )
    log(f"Encontrados {len(archivos)} archivos en a_paperless/{modo}", LOG)

    copiados = omitidos = errores = 0
    ahora = time.time()

    for p in archivos:
        try:
            edad = ahora - p.stat().st_mtime
            if edad < SEGUNDOS_MIN_QUIETO:
                omitidos += 1
                log(f"OMITIDO (copia en curso, modificado hace {edad:.0f}s): {p.name}", LOG)
                continue

            resultado, mensaje = procesar(p, simular)
            if resultado == "error":
                errores += 1
                log(f"ERROR {mensaje}", LOG)
            else:
                copiados += 1
                log(mensaje, LOG)
        except Exception as e:
            errores += 1
            log(f"ERROR procesando {p.name}: {e}", LOG)

    log(
        f"TERMINADO{modo}. Copiados: {copiados} | Omitidos: {omitidos} | "
        f"Errores: {errores} | Total: {len(archivos)}",
        LOG,
    )


if __name__ == "__main__":
    lock_f = adquirir_lock(LOCK)
    if lock_f is None:
        log("Ya hay otra instancia de puente_paperless.py corriendo. Saliendo sin hacer nada.", LOG)
        sys.exit(0)
    try:
        main()
    finally:
        liberar_lock(lock_f)
