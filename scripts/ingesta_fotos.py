"""
Ingiere fotos y videos desde el buzon "Solo recibir" de Syncthing hacia la
biblioteca definitiva, evitando duplicados por contenido (MD5). Se ejecuta
ANTES de organizar_fotos.py: este script solo coloca los ficheros nuevos en
FOTOS\\ / VIDEOS\\ (o sus subcarpetas WhatsApp); no los reordena por fecha,
de eso se encarga organizar_fotos.py despues (y solo para fotos).

Por defecto solo SIMULA e informa por consola. Para copiar/borrar de verdad:
    python ingesta_fotos.py --aplicar
"""
import hashlib
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from config_rutas import EXT_FOTO, EXT_VIDEO_MOVIL
from organizar_fotos import nombre_libre, CARPETA_FOTOS
from utils_comun import letra_disco

SCRIPTS = Path(__file__).resolve().parent   # D:\proyecto-repo\scripts (o D:\paperless\scripts en la copia viva)
DB = SCRIPTS / "ingesta_fotos.db"
LOG = SCRIPTS / "ingesta_fotos.log"

# "VIDEOS" coincide en los cuatro scripts del repo que lo usan
# (duplicados.py, indexar_videos.py, revisar.py, limpiar.py); se define
# aqui como constante local -- igual que organizar_fotos.py hace con
# CARPETA_FOTOS -- en vez de importarla de un script de indexado que
# arrastraria chromadb/requests solo por una cadena de texto.
CARPETA_VIDEOS = "VIDEOS"

# Buzones "Solo recibir" de Syncthing y su subcarpeta destino (misma para
# fotos y videos, cada una dentro de su raiz FOTOS/VIDEOS). La raiz completa
# (con la letra de disco) se resuelve en main().
BUZON_CAMARA = Path(r"D:\FOTOS\camara-movil")
BUZON_WHATSAPP = Path(r"D:\FOTOS\whatsapp-fotos")

TAM_CHUNK = 1024 * 1024   # 1 MB, para no cargar ficheros grandes enteros en memoria


def calcular_md5(ruta):
    """MD5 del contenido completo del fichero, leido a trozos."""
    h = hashlib.md5()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(TAM_CHUNK), b""):
            h.update(bloque)
    return h.hexdigest()


def abrir_bd():
    con = sqlite3.connect(str(DB))
    con.execute(
        "CREATE TABLE IF NOT EXISTS hashes ("
        "md5 TEXT PRIMARY KEY, ruta_destino TEXT, fecha_ingesta TEXT)"
    )
    con.commit()
    return con


def buscar_por_md5(con, md5):
    """Devuelve la ruta_destino ya registrada para ese MD5, o None."""
    fila = con.execute(
        "SELECT ruta_destino FROM hashes WHERE md5 = ?", (md5,)
    ).fetchone()
    return fila[0] if fila else None


def registrar_hash(con, md5, ruta_destino):
    con.execute(
        "INSERT OR REPLACE INTO hashes (md5, ruta_destino, fecha_ingesta) VALUES (?, ?, ?)",
        (md5, str(ruta_destino), datetime.now().isoformat(timespec="seconds")),
    )
    con.commit()


def resolver_destino(md5_origen, destino):
    """Decide donde debe copiarse el fichero, comparando contenido si el
    nombre ya existe en destino.

    Devuelve (ruta, ya_presente_con_ese_contenido):
    - destino libre                              -> (destino, False)
    - destino ocupado, mismo MD5 (mismo fichero)  -> (destino, True)
    - destino ocupado, MD5 distinto (colision de
      nombre real)                                -> (nombre_libre(destino), False)
    """
    if not destino.exists():
        return destino, False
    if calcular_md5(destino) == md5_origen:
        return destino, True
    return nombre_libre(destino), False


def ficheros_del_buzon(buzon):
    """Devuelve lista de (ruta, tipo) del buzon, tipo en {'foto', 'video'}.
    Cualquier otra extension se ignora."""
    if not buzon.exists():
        print(f"AVISO: no existe el buzon {buzon}")
        return []
    resultado = []
    for p in buzon.rglob("*"):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext in EXT_FOTO:
            resultado.append((p, "foto"))
        elif ext in EXT_VIDEO_MOVIL:
            resultado.append((p, "video"))
    return resultado


def escribir_log(lineas):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")


def main():
    aplicar = "--aplicar" in sys.argv

    letra = letra_disco()
    raiz_disco = Path(f"{letra}:\\")
    raiz_fotos = raiz_disco / CARPETA_FOTOS
    raiz_videos = raiz_disco / CARPETA_VIDEOS

    # Cada buzon aporta una subcarpeta (vacia = raiz directa) que se aplica
    # igual dentro de FOTOS y dentro de VIDEOS.
    buzones = [
        (BUZON_CAMARA, ""),
        (BUZON_WHATSAPP, "WhatsApp"),
    ]

    con = abrir_bd()
    registro = [f"--- {datetime.now():%Y-%m-%d %H:%M} ---"] if aplicar else None

    vistos = nuevos = duplicados = errores = 0

    for buzon, subcarpeta in buzones:
        ficheros = ficheros_del_buzon(buzon)
        n_fotos = sum(1 for _, tipo in ficheros if tipo == "foto")
        n_videos = sum(1 for _, tipo in ficheros if tipo == "video")
        print(f"{buzon.name}: {n_fotos} fotos, {n_videos} videos")

        for origen, tipo in ficheros:
            carpeta_destino = raiz_fotos if tipo == "foto" else raiz_videos
            if subcarpeta:
                carpeta_destino = carpeta_destino / subcarpeta

            vistos += 1
            try:
                md5_origen = calcular_md5(origen)
            except Exception as e:
                errores += 1
                print(f"  ERROR calculando MD5 de {origen.name}: {e}")
                if aplicar:
                    registro.append(f"ERROR MD5: {origen} ({e})")
                continue

            # 1. Ya ingerido antes (mismo contenido, ya registrado en la BD)
            ruta_previa = buscar_por_md5(con, md5_origen)
            if ruta_previa:
                duplicados += 1
                if aplicar:
                    try:
                        origen.unlink()
                        registro.append(
                            f"DUPLICADO (ya en BD, {ruta_previa}): {origen} - borrado del buzon"
                        )
                    except Exception as e:
                        errores += 1
                        registro.append(f"ERROR borrando duplicado {origen}: {e}")
                continue

            destino = carpeta_destino / origen.name
            destino_final, ya_en_sitio = resolver_destino(md5_origen, destino)

            # 2. Mismo contenido ya presente con ese nombre exacto, pero
            #    todavia no estaba en la BD (p.ej. copiado a mano antes de
            #    que existiera este script).
            if ya_en_sitio:
                duplicados += 1
                if aplicar:
                    try:
                        registrar_hash(con, md5_origen, destino_final)
                        origen.unlink()
                        registro.append(
                            f"DUPLICADO (ya en destino, no en BD): {origen} - "
                            f"registrado {destino_final} - borrado del buzon"
                        )
                    except Exception as e:
                        errores += 1
                        registro.append(f"ERROR registrando/borrando {origen}: {e}")
                continue

            # 3. Fichero nuevo de verdad.
            nuevos += 1
            if not aplicar:
                continue

            try:
                destino_final.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(origen), str(destino_final))

                # Orden critico: verificar antes de borrar nada del origen.
                if not destino_final.exists():
                    raise RuntimeError("el destino no existe tras la copia")
                md5_destino = calcular_md5(destino_final)
                if md5_destino != md5_origen:
                    raise RuntimeError(
                        f"MD5 no coincide tras copiar (origen {md5_origen}, destino {md5_destino})"
                    )

                registrar_hash(con, md5_origen, destino_final)

                # Solo se borra el original si la copia, la verificacion y el
                # registro en BD han ido bien.
                origen.unlink()
                registro.append(f"COPIADO: {origen} -> {destino_final}")
            except Exception as e:
                errores += 1
                registro.append(f"ERROR: {origen} ({e}) - origen NO borrado")
                print(f"  ERROR copiando {origen.name}: {e}")

    con.close()

    etiqueta_nuevos = "Nuevos copiados" if aplicar else "Nuevos (pendientes de copiar)"
    print(f"\nVistos: {vistos} | {etiqueta_nuevos}: {nuevos} | "
          f"Duplicados descartados: {duplicados} | Errores: {errores}")

    if not aplicar:
        print("\nMODO SIMULACION. No se ha copiado ni borrado nada.")
        print("Revisa el resumen y, si esta bien, ejecuta el script con  --aplicar")
        return

    escribir_log(registro)
    print(f"Log: {LOG}")


if __name__ == "__main__":
    main()
