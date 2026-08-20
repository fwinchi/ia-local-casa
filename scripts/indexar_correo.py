"""
Fase 1 (solo lectura) del MCP de correo: recorre los mbox de Thunderbird una
sola vez y vuelca asunto/cuerpo/remitente/metadatos a un FTS5 propio en
D:\\paperless\\correo\\correo.sqlite, para poder buscar sin depender del
tokenizer mozporter de gloda (ilegible desde Python).

De donde sale cada cosa
------------------------
- La LISTA de mensajes a procesar sale de gloda (messages JOIN
  folderLocations, deleted=0): gloda ya sabe que existe cada mensaje y en
  que carpeta esta, aunque no guarde asunto/cuerpo de forma accesible.
- El MBOX se usa solo para leer asunto/cuerpo/remitente de cada mensaje.
- La ruta del mbox de cada carpeta se resuelve reutilizando
  mapear_mbox.py (leer_prefs_servidores/resolver_ruta_mbox/usuario_y_host):
  ese mapeo ya esta hecho y probado alli, no se reimplementa aqui.

Localizacion del mensaje dentro del mbox
------------------------------------------
El plan original era usar messages.messageKey de gloda como offset de byte
directo (asi es como funciona nsIMsgDBHdr en un mbox local sin tocar). Se
comprobo contra los mbox reales de este perfil antes de darlo por bueno y
el resultado fue 0% de aciertos en las 30 carpetas con mbox.

Causa real (confirmada, NO reinvestigar): en carpetas IMAP -- que es el
caso de todas las carpetas de este perfil -- messageKey es el UID que
asigna el servidor IMAP, no un offset de byte en el fichero local; el
offset de byte solo es valido en carpetas mbox puramente locales (Local
Folders/Feeds). No tiene nada que ver con una restauracion de backup ni
con un desincronizado de gloda: es como funciona siempre nsIMsgDBHdr para
IMAP, y no cambia aunque se resincronice la cuenta.

Por eso aqui se localiza cada mensaje de otra forma, pero sigue siendo UNA
sola pasada por fichero: se recorre el mbox entero de principio a fin
partiendolo por las lineas "From " de cada mensaje, se le saca el
Message-ID real (barato, solo mirando las cabeceras) y se cruza contra el
conjunto de headerMessageID que gloda dice que hay en esa carpeta. Si al
terminar de recorrer el fichero queda algun headerMessageID de gloda sin
encontrar, se cuenta como "no resuelto" (mensaje que gloda cree que existe
pero ya no esta en el mbox tal cual) -- eso sustituye a la verificacion de
"empieza con From " del plan original, con el mismo espiritu: nunca
inventar un mensaje, contar y seguir cuando no se puede localizar.

Deduplicacion
-------------
El mismo mensaje puede estar en varias carpetas (Gmail: "Bandeja de
entrada", "Todos", "Importantes" son la misma copia via IMAP). Se
deduplica por header_message_id (columna UNIQUE): las carpetas se procesan
en orden de prioridad (Bandeja de entrada > Enviados > Todos > resto) y se
inserta con INSERT OR IGNORE, asi que la primera copia -- la de mayor
prioridad -- es la que queda, y las siguientes (incluidas las de pasadas
anteriores del script) se ignoran solas gracias al UNIQUE. Este mismo
mecanismo es lo que hace el reindexado incremental: si header_message_id
ya existe en la tabla, la segunda pasada no hace nada.

Privacidad de "cuenta"
----------------------
El campo cuenta NUNCA guarda el email de la cuenta -- es un id corto
("gmail-1", "outlook-2"...) asignado de forma deterministica a partir de
prefs.js, agrupando por proveedor (gmail/outlook/local/feeds) y numerando
las cuentas de cada proveedor por su directory-rel (orden estable, no
depende del email).

Solo stdlib: sqlite3, mailbox, email, html.parser, pathlib, argparse,
datetime (mas urllib.parse, ya usado por mapear_mbox.py, que se reutiliza).
"""

import argparse
import mailbox
import sqlite3
import sys
from datetime import datetime
from email import message_from_bytes
from email.header import decode_header
from email.utils import parseaddr
from html.parser import HTMLParser
from pathlib import Path

from mapear_mbox import PERFIL_TB, RUTA_GLODA, leer_prefs_servidores, resolver_ruta_mbox, usuario_y_host
from utils_comun import log
from utils_lock import adquirir_lock, liberar_lock

# --- Rutas ---
RUTA_CORREO_DB = Path(r"D:\paperless\correo\correo.sqlite")
LOG = Path(r"D:\paperless\scripts\indexar_correo.log")
LOCK = RUTA_CORREO_DB.parent / "indexar_correo.lock"

# --- Limites de contenido ---
LIMITE_CUERPO = 20_000     # caracteres
PROGRESO_CADA = 500        # mensajes

# Carpetas que no se indexan nunca, comparacion case-insensitive por el
# nombre visible (folderLocations.name). Lista deliberadamente explicita y
# facil de editar -- en este perfil tambien existen "Deleted" y "Unwanted"
# (variantes en ingles de carpetas de cuentas que no usan nombres
# localizados) que NO estan aqui porque no se pidieron; si se quieren
# excluir tambien, añadir sus nombres en minuscula a este set.
EXCLUSIONES_CARPETA = {
    "spam", "correo no deseado", "junk", "papelera", "trash", "bin",
    "borradores", "drafts", "plantillas", "templates",
    "hugging face - blog",
}

# Prioridad de carpeta para la deduplicacion por header_message_id: menor
# numero = mayor prioridad. Todo lo que no aparezca aqui cae en el nivel 4.
PRIORIDAD_CARPETA = {
    "bandeja de entrada": 1,
    "enviados": 2,
    "todos": 3,
}


# --- Identificador de cuenta (nunca el email) ---

def proveedor_de_host(host: str) -> str:
    h = host.lower()
    if "gmail" in h:
        return "gmail"
    if "outlook" in h or "office365" in h:
        return "outlook"
    if h == "local folders":
        return "local"
    if h == "feeds":
        return "feeds"
    return h.split(".")[0] or "otro"


def construir_ids_cuenta(mapa_prefs: dict[tuple[str, str], str]) -> dict[tuple[str, str], str]:
    """{(host, usuario): "proveedor-N"}, numerado de forma estable por
    directory-rel dentro de cada proveedor (no por el email)."""
    por_proveedor: dict[str, list[tuple[tuple[str, str], str]]] = {}
    for clave, rel in mapa_prefs.items():
        host, _usuario = clave
        por_proveedor.setdefault(proveedor_de_host(host), []).append((clave, rel))

    ids: dict[tuple[str, str], str] = {}
    for proveedor, cuentas in por_proveedor.items():
        for i, (clave, _rel) in enumerate(sorted(cuentas, key=lambda x: x[1]), 1):
            ids[clave] = f"{proveedor}-{i}"
    return ids


# --- Escaneo del mbox (una sola pasada) ---

def escanear_mbox_abierto(f):
    """Generador de bloques de mensaje (bytes, sin la linea "From ..." del
    envoltorio mbox) leyendo `f` -- ya abierto en binario -- una sola vez
    de principio a fin."""
    bloque = None
    for linea in f:
        if linea.startswith(b"From "):
            if bloque is not None:
                yield bytes(bloque)
            bloque = bytearray()
            continue
        if bloque is None:
            continue  # basura antes del primer envoltorio (no deberia darse en un mbox valido)
        # Desescapado mboxrd: las lineas del cuerpo que empezaban por
        # "From " se guardaron con un ">" de mas para no confundirse con un
        # limite de mensaje real; se quita ese ">" al leer.
        sin_gt = linea.lstrip(b">")
        if linea.startswith(b">") and sin_gt.startswith(b"From "):
            linea = linea[1:]
        bloque.extend(linea)
    if bloque is not None:
        yield bytes(bloque)


def id_rapido_de_bloque(bloque: bytes) -> str | None:
    """Saca el valor de la cabecera Message-ID de un bloque SIN parsear el
    email entero -- solo se mira hasta la primera linea en blanco (fin de
    cabeceras). Se usa para decidir barato si un mensaje interesa antes de
    pagar el coste de un parseo MIME completo."""
    fin = bloque.find(b"\r\n\r\n")
    if fin == -1:
        fin = bloque.find(b"\n\n")
        if fin == -1:
            fin = len(bloque)
    cabeceras = bloque[:fin]
    idx = cabeceras.lower().find(b"\nmessage-id:")
    if idx == -1:
        # tambien puede ser la primera cabecera del bloque, sin \n delante
        if cabeceras.lower().startswith(b"message-id:"):
            idx = -1
            resto = cabeceras
        else:
            return None
    else:
        resto = cabeceras[idx + 1:]
    fin_linea = resto.find(b"\n")
    linea = resto[:fin_linea] if fin_linea != -1 else resto
    if b":" not in linea:
        return None
    valor = linea.split(b":", 1)[1].strip().strip(b"\r")
    return valor.decode("ascii", errors="replace").strip().strip("<>")


# --- Parseo completo de un mensaje ya localizado ---

def decodificar_cabecera(valor: str | None) -> str:
    if not valor:
        return ""
    try:
        trozos = decode_header(valor)
    except Exception:
        return valor
    partes = []
    for texto, codificacion in trozos:
        if isinstance(texto, bytes):
            try:
                partes.append(texto.decode(codificacion or "utf-8", errors="replace"))
            except (LookupError, TypeError):
                partes.append(texto.decode("utf-8", errors="replace"))
        else:
            partes.append(texto)
    return "".join(partes)


def destinatarios_de(mensaje) -> str:
    partes = []
    for campo in ("To", "Cc"):
        for valor in mensaje.get_all(campo) or []:
            texto = decodificar_cabecera(valor)
            if texto:
                partes.append(texto)
    return "; ".join(partes)


def decodificar_parte(parte) -> str:
    try:
        crudo = parte.get_payload(decode=True)
    except Exception:
        return ""
    if not crudo:
        return ""
    charset = parte.get_content_charset() or "utf-8"
    try:
        return crudo.decode(charset, errors="replace")
    except (LookupError, TypeError):
        return crudo.decode("utf-8", errors="replace")


class _ExtractorTextoHTML(HTMLParser):
    """Convierte HTML a texto plano quitando etiquetas, sin procesar
    script/style ni entrar en detalle de estructura (basta para busqueda)."""

    ETIQUETAS_BLOQUE = {"br", "p", "div", "tr", "li", "h1", "h2", "h3"}

    def __init__(self):
        super().__init__()
        self._trozos = []
        self._omitir = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._omitir += 1
        elif tag in self.ETIQUETAS_BLOQUE:
            self._trozos.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._omitir > 0:
            self._omitir -= 1

    def handle_data(self, data):
        if not self._omitir:
            self._trozos.append(data)

    def texto(self) -> str:
        lineas = [l.strip() for l in "".join(self._trozos).splitlines()]
        return "\n".join(l for l in lineas if l)


def html_a_texto(html: str) -> str:
    extractor = _ExtractorTextoHTML()
    try:
        extractor.feed(html)
        extractor.close()
    except Exception:
        pass
    return extractor.texto()


def cuerpo_de(mensaje) -> str:
    texto_plano = texto_html = None
    if mensaje.is_multipart():
        for parte in mensaje.walk():
            disp = str(parte.get("Content-Disposition", "")).lower()
            if disp.startswith("attachment"):
                continue
            tipo = parte.get_content_type()
            if tipo == "text/plain" and texto_plano is None:
                texto_plano = decodificar_parte(parte)
            elif tipo == "text/html" and texto_html is None:
                texto_html = decodificar_parte(parte)
    else:
        tipo = mensaje.get_content_type()
        if tipo == "text/plain":
            texto_plano = decodificar_parte(mensaje)
        elif tipo == "text/html":
            texto_html = decodificar_parte(mensaje)

    cuerpo = texto_plano if texto_plano else (html_a_texto(texto_html) if texto_html else "")
    return cuerpo[:LIMITE_CUERPO]


def tiene_adjuntos(mensaje) -> bool:
    if not mensaje.is_multipart():
        return False
    for parte in mensaje.walk():
        disp = str(parte.get("Content-Disposition", "")).lower()
        if disp.startswith("attachment"):
            return True
        if parte.get_filename():
            return True
    return False


def parsear_mensaje(bloque: bytes, header_id: str, fecha_us, carpeta: str, cuenta: str) -> dict:
    mensaje = message_from_bytes(bloque, _class=mailbox.mboxMessage)
    nombre_crudo, direccion = parseaddr(mensaje.get("From", ""))
    return {
        "header_message_id": header_id,
        "fecha": (fecha_us or 0) // 1_000_000,
        "remitente": direccion,
        "remitente_nombre": decodificar_cabecera(nombre_crudo),
        "destinatarios": destinatarios_de(mensaje),
        "asunto": decodificar_cabecera(mensaje.get("Subject", "")),
        "carpeta": carpeta,
        "cuenta": cuenta,
        "tiene_adjuntos": 1 if tiene_adjuntos(mensaje) else 0,
        "tamano": len(bloque),
        "cuerpo": cuerpo_de(mensaje),
    }


# --- Base de datos destino ---

def preparar_db(ruta: Path) -> sqlite3.Connection:
    """correos_fts se declara content='correos' (contenido externo, no
    contentless): se probo con content='' primero -- que es mas compacto,
    ya que no duplica el texto dentro del indice FTS -- pero en ese modo
    SELECT y snippet() sobre columnas de la FTS devuelven NULL siempre (no
    hay texto real que devolver, solo el indice invertido para MATCH). El
    MCP de correo (mcp_correo.py) necesita snippet() en las busquedas y el
    cuerpo completo en leer_correo, asi que cuerpo pasa a vivir en
    correos.cuerpo (la tabla de contenido) y la FTS solo indexa sobre ella;
    content_rowid='id' porque el alias de rowid de correos es "id", no
    "rowid"."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(str(ruta))
    conexion.execute("PRAGMA journal_mode=WAL")
    conexion.executescript("""
        CREATE TABLE IF NOT EXISTS correos (
            id INTEGER PRIMARY KEY,
            header_message_id TEXT UNIQUE,
            fecha INTEGER,
            remitente TEXT,
            remitente_nombre TEXT,
            destinatarios TEXT,
            asunto TEXT,
            cuerpo TEXT,
            carpeta TEXT,
            cuenta TEXT,
            tiene_adjuntos INTEGER,
            tamano INTEGER
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS correos_fts USING fts5(
            asunto, cuerpo, remitente, content='correos', content_rowid='id'
        );
        CREATE TABLE IF NOT EXISTS meta (
            clave TEXT PRIMARY KEY,
            valor TEXT
        );
    """)
    conexion.commit()
    return conexion


def guardar_mensaje(conexion: sqlite3.Connection, registro: dict) -> bool:
    """Inserta el mensaje si su header_message_id es nuevo. Devuelve True si
    se inserto, False si ya existia (dedup / reindexado incremental)."""
    cur = conexion.execute(
        "INSERT OR IGNORE INTO correos "
        "(header_message_id, fecha, remitente, remitente_nombre, destinatarios, "
        " asunto, cuerpo, carpeta, cuenta, tiene_adjuntos, tamano) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            registro["header_message_id"], registro["fecha"], registro["remitente"],
            registro["remitente_nombre"], registro["destinatarios"], registro["asunto"],
            registro["cuerpo"], registro["carpeta"], registro["cuenta"],
            registro["tiene_adjuntos"], registro["tamano"],
        ),
    )
    if cur.rowcount == 0:
        return False
    conexion.execute(
        "INSERT INTO correos_fts (rowid, asunto, cuerpo, remitente) VALUES (?,?,?,?)",
        (cur.lastrowid, registro["asunto"], registro["cuerpo"], registro["remitente"]),
    )
    return True


# --- Seleccion de carpetas ---

def carpetas_a_procesar(conexion_gloda, mapa_prefs, ids_cuenta) -> tuple[dict, dict]:
    """Devuelve (carpetas_validas, contadores) donde carpetas_validas es
    {folder_id: {"ruta", "nombre", "cuenta", "prioridad"}}."""
    contadores = {"excluidas": 0, "sin_cuenta": 0, "sin_mbox": 0}
    validas = {}

    filas = conexion_gloda.execute("SELECT id, folderURI, name FROM folderLocations").fetchall()
    for folder_id, folder_uri, nombre in filas:
        usuario, host = usuario_y_host(folder_uri)
        if usuario is None:
            contadores["sin_cuenta"] += 1
            continue
        if host.lower() == "feeds":
            contadores["excluidas"] += 1
            continue
        if nombre.strip().lower() in EXCLUSIONES_CARPETA:
            contadores["excluidas"] += 1
            continue

        ruta_mbox = resolver_ruta_mbox(folder_uri, mapa_prefs, PERFIL_TB)
        if ruta_mbox is None:
            contadores["sin_cuenta"] += 1
            continue
        if not ruta_mbox.is_file():
            contadores["sin_mbox"] += 1
            continue

        validas[folder_id] = {
            "ruta": ruta_mbox,
            "nombre": nombre,
            "cuenta": ids_cuenta.get((host, usuario), "desconocida"),
            "prioridad": PRIORIDAD_CARPETA.get(nombre.strip().lower(), 4),
        }

    return validas, contadores


def mensajes_esperados(conexion_gloda, folder_id: int) -> tuple[dict, int]:
    """{header_message_id limpio: fecha_us} para una carpeta, segun gloda.
    Devuelve tambien cuantas filas de esa carpeta no tienen headerMessageID
    (no se pueden localizar por este metodo)."""
    esperados = {}
    sin_id = 0
    for header_id, fecha_us in conexion_gloda.execute(
        "SELECT headerMessageID, date FROM messages WHERE folderID = ? AND deleted = 0", (folder_id,)
    ):
        limpio = (header_id or "").strip().strip("<>")
        if not limpio:
            sin_id += 1
            continue
        esperados[limpio] = fecha_us
    return esperados, sin_id


def parsear_args():
    parser = argparse.ArgumentParser(
        description="Indexa asunto/cuerpo/remitente de los mbox de Thunderbird "
                     "en un FTS5 propio (correo.sqlite), usando gloda como fuente "
                     "de la lista de mensajes."
    )
    parser.add_argument(
        "--limite", type=int, default=None,
        help="Procesar como mucho N mensajes en total (para probar antes de la pasada completa).",
    )
    return parser.parse_args()


def main():
    args = parsear_args()

    mapa_prefs = leer_prefs_servidores(PERFIL_TB)
    ids_cuenta = construir_ids_cuenta(mapa_prefs)

    conexion_gloda = sqlite3.connect(f"file:/{RUTA_GLODA.resolve().as_posix()}?mode=ro", uri=True)
    carpetas_validas, contadores = carpetas_a_procesar(conexion_gloda, mapa_prefs, ids_cuenta)
    log(
        f"Carpetas: {len(carpetas_validas)} validas | {contadores['excluidas']} excluidas | "
        f"{contadores['sin_mbox']} sin mbox en disco | {contadores['sin_cuenta']} sin cuenta reconocida",
        LOG,
    )

    orden_carpetas = sorted(carpetas_validas.items(), key=lambda kv: kv[1]["prioridad"])

    # Total esperado para el "[n/total]" del progreso (cuenta lo que gloda
    # dice que hay, con headerMessageID, en las carpetas validas).
    ids_validas = tuple(carpetas_validas.keys())
    total = 0
    sin_id_gloda_total = 0
    if ids_validas:
        marcadores = ",".join("?" * len(ids_validas))
        for header_id, in conexion_gloda.execute(
            f"SELECT headerMessageID FROM messages WHERE deleted=0 AND folderID IN ({marcadores})",
            ids_validas,
        ):
            if (header_id or "").strip().strip("<>"):
                total += 1
            else:
                sin_id_gloda_total += 1
    if args.limite is not None:
        total = min(total, args.limite)
    log(
        f"Mensajes a procesar: {total}" + (f" (limitado con --limite {args.limite})" if args.limite else "")
        + (f" | {sin_id_gloda_total} sin Message-ID en gloda, no localizables" if sin_id_gloda_total else ""),
        LOG,
    )

    conexion_destino = preparar_db(RUTA_CORREO_DB)

    insertados = ya_existian = no_resueltos = fallos = 0
    procesados = 0
    parar = False

    for folder_id, info in orden_carpetas:
        if parar:
            break

        esperados, _sin_id = mensajes_esperados(conexion_gloda, folder_id)
        if not esperados:
            continue

        completo = True
        try:
            with open(info["ruta"], "rb") as f:
                for bloque in escanear_mbox_abierto(f):
                    hid = id_rapido_de_bloque(bloque)
                    if hid is None or hid not in esperados:
                        continue
                    fecha_us = esperados.pop(hid)

                    procesados += 1
                    asunto_mostrado = "(error)"
                    try:
                        registro = parsear_mensaje(bloque, hid, fecha_us, info["nombre"], info["cuenta"])
                        asunto_mostrado = registro["asunto"]
                        if guardar_mensaje(conexion_destino, registro):
                            insertados += 1
                        else:
                            ya_existian += 1
                    except Exception as e:
                        fallos += 1
                        log(f"ERROR mensaje {hid!r} carpeta={info['nombre']!r} cuenta={info['cuenta']}: {e}", LOG)

                    if procesados % PROGRESO_CADA == 0:
                        conexion_destino.commit()
                        log(f"[{procesados}/{total}] {asunto_mostrado[:60]}", LOG)

                    if args.limite is not None and procesados >= args.limite:
                        parar = True
                        completo = False
                        break
        except OSError as e:
            completo = False
            log(f"ERROR abriendo mbox de {info['nombre']!r} ({info['cuenta']}): {e}", LOG)

        if completo:
            # Lo que gloda esperaba en esta carpeta y no aparecio en el
            # recorrido completo del fichero: mensaje que gloda cree que
            # existe pero ya no esta en el mbox tal cual.
            no_resueltos += len(esperados)

    conexion_gloda.close()

    conexion_destino.execute(
        "INSERT OR REPLACE INTO meta (clave, valor) VALUES ('ultima_indexacion', ?)",
        (datetime.now().isoformat(timespec="seconds"),),
    )
    conexion_destino.commit()
    conexion_destino.close()

    log(
        f"TERMINADO. Procesados: {procesados} | Insertados: {insertados} | "
        f"Ya existian (dedup/incremental): {ya_existian} | No resueltos: {no_resueltos} | Fallos: {fallos}",
        LOG,
    )


if __name__ == "__main__":
    lock_f = adquirir_lock(LOCK)
    if lock_f is None:
        log("Ya hay otra instancia de indexar_correo.py corriendo. Saliendo sin hacer nada.", LOG)
        sys.exit(0)
    try:
        main()
    finally:
        liberar_lock(lock_f)
