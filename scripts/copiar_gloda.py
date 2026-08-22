"""
Copia el gloda "en vivo" de Thunderbird (RUTA_GLODA_ORIGEN, dentro del
perfil -- bloqueado mientras Thunderbird esta abierto, y puede quedar a
medio escribir en cualquier momento) a una copia propia de solo lectura
(RUTA_GLODA) que es la que leen mapear_mbox.py e indexar_correo.py. Nunca
toca ni escribe el original.

Verificacion antes de sustituir la copia anterior: se copia primero a un
.tmp en el mismo directorio que el destino (mismo disco, para que la
sustitucion final con os.replace() sea atomica), y se comprueba que la
copia es utilizable (ver copia_valida()) antes de sustituir gloda.sqlite;
si no, se borra el .tmp y se registra el error sin tocar la copia anterior
-- asi un gloda a medio escribir nunca deja el destino en un estado peor
que el que ya tenia.

Sobre la comprobacion: el plan inicial era PRAGMA integrity_check, pero se
descarto tras comprobarlo contra datos reales -- falla SIEMPRE con
"unknown tokenizer: mozporter", incluso contra un gloda.sqlite bueno,
porque integrity_check (y quick_check) recorren tambien las tablas
virtuales FTS5 (messagesText/conversationsText), que usan el tokenizer
propio de Thunderbird, inexistente en el sqlite3 de Python. Con ese
PRAGMA, el script rechazaria toda copia, siempre. copia_valida() hace en
su lugar la comprobacion practica maxima posible desde Python con este
esquema: contar filas en las tablas que de verdad se leen despues
(folderLocations/messages), y ademas rechazar la copia si messages cayo
por debajo de UMBRAL_MENSAJES (90%) respecto a la copia anterior -- asi se
detecta tambien una copia que abre bien y no da 0 filas, pero llego
incompleta por pillar a Thunderbird a medio escribir.

No se copian eventuales -wal/-shm del origen (no los tiene en este
perfil, ver historial del repo): si Thunderbird pasara a usar WAL, la
copia seguiria siendo un snapshot estructuralmente valido (el ultimo
checkpoint), solo mas antiguo, no corrupto.

Uso:
    python copiar_gloda.py
"""

import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from config_rutas import BASE, CARPETA_DB, RUTA_GLODA, RUTA_GLODA_ORIGEN
from utils_comun import log
from utils_lock import adquirir_lock, liberar_lock

SCRIPTS = Path(__file__).resolve().parent   # antes: D:\paperless\scripts
LOG = SCRIPTS / "copiar_gloda.log"

# Lock de instancia unica, misma carpeta que usan los demas scripts del
# repo con lock (CARPETA_DB de config_rutas.py, el chroma/ compartido).
LOCK = Path(CARPETA_DB) / "copiar_gloda.lock"

# En el mismo directorio que el destino final: os.replace() solo es
# atomico dentro del mismo disco.
RUTA_TMP = RUTA_GLODA.with_name(RUTA_GLODA.name + ".tmp")


UMBRAL_MENSAJES = 0.9  # rechazar la copia si tiene menos del 90% de los mensajes que la anterior


def contar_mensajes(ruta: Path) -> int | None:
    """Cuenta filas de messages en `ruta`, o None si no existe o no se
    puede leer (no bloquea nada por si solo: solo sirve como referencia
    "de antes" para copia_valida())."""
    if not ruta.is_file():
        return None
    try:
        conexion = sqlite3.connect(f"file:/{ruta.resolve().as_posix()}?mode=ro", uri=True)
        try:
            return conexion.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        finally:
            conexion.close()
    except sqlite3.Error:
        return None


def copia_valida(ruta: Path, conteo_anterior: int | None) -> tuple[bool, str]:
    """Comprobacion practica de que la copia en `ruta` es utilizable: la
    abre en modo readonly, cuenta filas de folderLocations y messages --
    las tablas que de verdad leen mapear_mbox.py/indexar_correo.py -- y
    rechaza la copia si messages cayo por debajo de UMBRAL_MENSAJES
    respecto a `conteo_anterior` (el conteo de la copia que se iba a
    sustituir, o None si no habia copia previa que comparar).

    PRAGMA integrity_check/quick_check NO sirven aqui (ver docstring del
    modulo): fallan siempre con "unknown tokenizer: mozporter" en
    CUALQUIER gloda.sqlite, tambien en uno bueno. Contar filas en las
    tablas reales es lo maximo verificable desde Python con este esquema;
    detecta una copia truncada o a medio escribir por si sola (fallaria al
    abrir/consultar, o darian recuento 0), y la comparacion contra
    conteo_anterior detecta ademas una copia que abre bien pero llego
    incompleta (Thunderbird a medio escribir cuando se copio, sin que
    llegue a fallar la apertura ni a dar 0 filas).

    Devuelve (True, detalle) si la copia parece utilizable, o (False,
    detalle) si no -- detalle siempre listo para el log.
    """
    try:
        conexion = sqlite3.connect(f"file:/{ruta.resolve().as_posix()}?mode=ro", uri=True)
        try:
            n_carpetas = conexion.execute("SELECT COUNT(*) FROM folderLocations").fetchone()[0]
            n_mensajes = conexion.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        finally:
            conexion.close()
    except sqlite3.Error as e:
        return False, f"no se pudo abrir/consultar la copia: {e}"

    if n_carpetas == 0 or n_mensajes == 0:
        return False, f"folderLocations={n_carpetas} filas, messages={n_mensajes} filas (copia vacia o truncada)"

    if conteo_anterior is not None and n_mensajes < conteo_anterior * UMBRAL_MENSAJES:
        return False, (
            f"messages cayo de {conteo_anterior} a {n_mensajes} "
            f"({n_mensajes / conteo_anterior:.0%} de antes, umbral {UMBRAL_MENSAJES:.0%}) "
            f"-- probable copia a medio escribir"
        )

    detalle = f"{n_carpetas} carpetas, {n_mensajes} mensajes"
    if conteo_anterior is not None:
        detalle += f" (antes: {conteo_anterior})"
    return True, detalle


def main() -> bool:
    """Devuelve True si termina con una copia integra en destino (nueva),
    False si algo fallo -- en ese caso la copia anterior en RUTA_GLODA, si
    existia, se deja tal cual estaba."""
    try:
        origen_existe = RUTA_GLODA_ORIGEN.is_file()
    except OSError:
        origen_existe = False
    if not origen_existe:
        log(f"ERROR: no existe o no se puede acceder al gloda de origen: {RUTA_GLODA_ORIGEN}", LOG)
        return False

    RUTA_GLODA.parent.mkdir(parents=True, exist_ok=True)
    RUTA_TMP.unlink(missing_ok=True)  # restos de una ejecucion anterior interrumpida

    # Se cuenta ANTES de copiar: RUTA_GLODA todavia es la copia previa, sin
    # tocar (solo se sustituye al final, con os.replace(), y solo si la
    # copia nueva pasa copia_valida()).
    conteo_anterior = contar_mensajes(RUTA_GLODA)

    inicio = time.monotonic()
    try:
        shutil.copy2(RUTA_GLODA_ORIGEN, RUTA_TMP)
    except OSError as e:
        log(f"ERROR: no se pudo copiar el gloda de origen (¿Thunderbird lo tiene bloqueado?): {e}", LOG)
        RUTA_TMP.unlink(missing_ok=True)
        return False
    duracion = time.monotonic() - inicio

    tamano = RUTA_TMP.stat().st_size

    ok, detalle = copia_valida(RUTA_TMP, conteo_anterior)
    if not ok:
        log(
            f"ERROR: la copia no paso la comprobacion ({detalle}) -- copia a medio "
            f"escribir, truncada o corrupta. Se borra el .tmp, se conserva la copia "
            f"anterior en {RUTA_GLODA} (si existia).",
            LOG,
        )
        RUTA_TMP.unlink(missing_ok=True)
        return False

    os.replace(RUTA_TMP, RUTA_GLODA)

    log(
        f"OK. Copiados {tamano / (1024 * 1024):.1f} MB en {duracion:.1f}s "
        f"({tamano / max(duracion, 0.001) / (1024 * 1024):.1f} MB/s). "
        f"Comprobacion ok ({detalle}) -> {RUTA_GLODA}",
        LOG,
    )
    return True


if __name__ == "__main__":
    lock_f = adquirir_lock(LOCK)
    if lock_f is None:
        log("Ya hay otra instancia de copiar_gloda.py corriendo. Saliendo sin hacer nada.", LOG)
        sys.exit(0)
    codigo_salida = 0
    try:
        ok = main()
        if not ok:
            codigo_salida = 1
        else:
            # Copia validada: encadena mapear_mbox.py -> indexar_correo.py
            # para que correo.sqlite quede al dia con el gloda recien
            # copiado. Dentro del mismo try que main(), antes de liberar el
            # lock (ver finally), para que mapear_mbox.py no pueda
            # solaparse entre ejecuciones horarias de copiar_gloda.py.
            for script in ("mapear_mbox.py", "indexar_correo.py"):
                ruta_script = BASE / "scripts" / script
                try:
                    subprocess.run([sys.executable, str(ruta_script)], check=True, timeout=900)
                except subprocess.TimeoutExpired:
                    log(f"ERROR: {script} supero el timeout de 900s tras copiar gloda.", LOG)
                    codigo_salida = 1
                    break
                except subprocess.CalledProcessError as e:
                    log(f"ERROR: {script} termino con codigo {e.returncode} tras copiar gloda.", LOG)
                    codigo_salida = 1
                    break
                except OSError as e:
                    log(f"ERROR: no se pudo ejecutar {script} tras copiar gloda: {e}", LOG)
                    codigo_salida = 1
                    break
    finally:
        liberar_lock(lock_f)
    sys.exit(codigo_salida)
