"""
Servidor MCP de correo (fase 1, solo lectura): busqueda y consulta sobre el
indice generado por indexar_correo.py (D:\\paperless\\correo\\correo.sqlite).
Se sirve via mcpo para Open WebUI, igual que mcp_documentos.py / mcp_fotos.py.

Este servidor NUNCA escribe, mueve ni borra nada -- ni en correo.sqlite ni
en los mbox de Thunderbird. Toda conexion se abre en modo readonly
(file:...?mode=ro); si esa apertura fallase por cualquier motivo, sqlite3
lanza un error en vez de dejar escribir, asi que no hace falta ninguna
comprobacion adicional para garantizarlo.

Dos formas de buscar, que no hay que confundir (los docstrings de cada
tool lo repiten porque el modelo los lee para elegir cual usar):
- buscar_correos: BUSQUEDA DE TEXTO libre (FTS5) en asunto+cuerpo+remitente,
  ordenada por relevancia. Para "busca correos que hablen de...".
- listar_correos: FILTRADO EXACTO (remitente/cuenta/fechas), sin buscar
  texto, ordenado por fecha. Para "correos de fulano" o "correos de marzo".

contar_correos existe aparte de listar_correos porque los modelos locales
cuentan mal filas de una lista larga que se les pasa como contexto; aqui el
numero lo calcula SQL con COUNT(*), no el modelo.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from indexar_correo import construir_ids_cuenta
from mapear_mbox import PERFIL_TB, leer_prefs_servidores

# --- Rutas ---
RUTA_CORREO_DB = Path(r"D:\paperless\correo\correo.sqlite")

# --- Limites ---
LIMITE_MAX = 100              # tope duro, aunque el modelo pida mas
LARGO_SNIPPET = 200            # caracteres del fragmento de buscar_correos
TOKENS_SNIPPET_FTS = 40        # snippet() de FTS5 cuenta en "tokens", no caracteres; se recorta a LARGO_SNIPPET despues

mcp = FastMCP("Correo")


# --- Conexion ---

def _abrir_indice():
    """Abre correo.sqlite en modo readonly y comprueba que tiene datos.

    Devuelve (conexion, None) si esta listo para consultar, o (None,
    {"error": ...}) si no -- nunca hay que dejar que un tool siga adelante
    y devuelva una lista vacia en ese caso: el modelo la leeria como "no
    hay correos que cumplan el filtro" en vez de "el indice no existe",
    e inventaria una respuesta a partir de ahi.
    """
    if not RUTA_CORREO_DB.is_file():
        return None, {"error": "Indice de correo no generado. Ejecuta scripts/indexar_correo.py primero."}

    conexion = sqlite3.connect(f"file:/{RUTA_CORREO_DB.resolve().as_posix()}?mode=ro", uri=True)
    conexion.row_factory = sqlite3.Row
    try:
        total = conexion.execute("SELECT COUNT(*) FROM correos").fetchone()[0]
    except sqlite3.OperationalError:
        conexion.close()
        return None, {"error": "correo.sqlite existe pero no tiene la tabla 'correos'. Indice corrupto o incompleto -- reejecuta scripts/indexar_correo.py."}

    if total == 0:
        conexion.close()
        return None, {"error": "El indice de correo esta vacio (0 correos). Ejecuta scripts/indexar_correo.py."}

    return conexion, None


def _tope(limite: int) -> int:
    return max(1, min(limite, LIMITE_MAX))


def _fecha_iso(epoch_segundos) -> str:
    if not epoch_segundos:
        return ""
    return datetime.fromtimestamp(epoch_segundos).isoformat(timespec="seconds")


def _con_enlace(resultado: dict, header_message_id: str | None) -> dict:
    """Anade 'enlace': '[abrir](mid:<header_message_id>)' a resultado si
    header_message_id no es None ni cadena vacia; si lo es, deja resultado
    sin ese campo."""
    if header_message_id:
        resultado["enlace"] = f"[abrir](mid:{header_message_id})"
    return resultado


def _rango_fechas(desde: str | None, hasta: str | None):
    """(epoch_desde, epoch_hasta, error). error es un str si el formato de
    alguna fecha no es YYYY-MM-DD; en ese caso los otros dos son None."""
    epoch_desde = epoch_hasta = None
    try:
        if desde:
            epoch_desde = int(datetime.strptime(desde, "%Y-%m-%d").timestamp())
        if hasta:
            fin = datetime.strptime(hasta, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            epoch_hasta = int(fin.timestamp())
    except ValueError:
        return None, None, "Formato de fecha invalido. Usa YYYY-MM-DD tanto en 'desde' como en 'hasta'."
    return epoch_desde, epoch_hasta, None


def _consulta_fts(texto: str) -> str:
    """Convierte el texto libre del modelo en una consulta FTS5 segura: cada
    palabra se envuelve en comillas dobles (escapando antes las comillas
    dobles que el propio texto pudiera traer, doblandolas, que es como FTS5
    escapa comillas dentro de una cadena entre comillas) para que se busque
    como texto literal palabra a palabra en vez de interpretar caracteres
    como -, * o : como operadores de FTS5. Varias palabras se buscan en AND
    (comportamiento por defecto de FTS5 al poner terminos seguidos)."""
    terminos = texto.split()
    if not terminos:
        return '""'
    return " ".join('"' + t.replace('"', '""') + '"' for t in terminos)


# --- Tools ---

@mcp.tool()
def buscar_correos(
    texto: str,
    limite: int = 20,
    cuenta: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
) -> dict:
    """BUSQUEDA DE TEXTO libre en el contenido de los correos (asunto, cuerpo
    y remitente), usando el indice de texto completo (FTS5). Los resultados
    se ordenan por relevancia, no por fecha.

    Usa esta herramienta cuando el usuario pregunte por el CONTENIDO de sus
    correos ("busca correos que hablen de...", "¿tengo algun correo sobre
    la reserva del hotel?"). Si en cambio quiere correos de una persona o
    cuenta concreta, o de un rango de fechas, sin buscar texto, usa
    listar_correos en su lugar -- es mas precisa para eso y no depende de
    que la palabra exacta aparezca en el correo.

    Args:
        texto: palabras a buscar (se buscan todas, en cualquier orden, en
            asunto+cuerpo+remitente).
        limite: maximo de resultados (por defecto 20, tope 100).
        cuenta: si se indica, limita la busqueda a esa cuenta (ver
            listar_cuentas para los ids disponibles, p.ej. "gmail-1").
        desde: no devolver correos anteriores a esta fecha (YYYY-MM-DD).
        hasta: no devolver correos posteriores a esta fecha (YYYY-MM-DD).
    """
    conexion, error = _abrir_indice()
    if error:
        return error

    try:
        epoch_desde, epoch_hasta, error_fecha = _rango_fechas(desde, hasta)
        if error_fecha:
            return {"error": error_fecha}

        sql = (
            "SELECT c.id, c.header_message_id, c.fecha, c.remitente, c.remitente_nombre, c.asunto, c.carpeta, c.cuenta, "
            f"snippet(correos_fts, 1, '»', '«', ' … ', {TOKENS_SNIPPET_FTS}) AS fragmento "
            "FROM correos_fts JOIN correos c ON c.id = correos_fts.rowid "
            "WHERE correos_fts MATCH ?"
        )
        parametros = [_consulta_fts(texto)]
        if cuenta:
            sql += " AND c.cuenta = ?"
            parametros.append(cuenta)
        if epoch_desde is not None:
            sql += " AND c.fecha >= ?"
            parametros.append(epoch_desde)
        if epoch_hasta is not None:
            sql += " AND c.fecha <= ?"
            parametros.append(epoch_hasta)
        sql += " ORDER BY rank LIMIT ?"
        parametros.append(_tope(limite))

        filas = conexion.execute(sql, parametros).fetchall()
    except sqlite3.OperationalError as e:
        return {"error": f"Consulta de busqueda invalida: {e}"}
    finally:
        conexion.close()

    resultados = []
    for f in filas:
        fragmento = f["fragmento"] or ""
        if len(fragmento) > LARGO_SNIPPET:
            fragmento = fragmento[:LARGO_SNIPPET] + "…"
        resultados.append(_con_enlace({
            "id": f["id"],
            "fecha": _fecha_iso(f["fecha"]),
            "remitente": f["remitente"],
            "remitente_nombre": f["remitente_nombre"],
            "asunto": f["asunto"],
            "carpeta": f["carpeta"],
            "cuenta": f["cuenta"],
            "fragmento": fragmento,
        }, f["header_message_id"]))
    return {"resultados": resultados, "total_devueltos": len(resultados)}


@mcp.tool()
def listar_correos(
    remitente: str | None = None,
    cuenta: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    limite: int = 50,
) -> dict:
    """FILTRADO EXACTO de correos por remitente/cuenta/fechas, SIN buscar
    texto -- no usa el indice de busqueda, es una consulta directa y
    deterministica sobre los metadatos. Ordenado por fecha, del mas
    reciente al mas antiguo.

    Usa esta herramienta cuando el usuario pida correos de una persona o
    cuenta concreta, o de un periodo, SIN mencionar un tema o palabra a
    buscar ("correos de Maria", "que me llego de outlook-2 en marzo"). Si
    en cambio quiere correos que traten sobre algo, usa buscar_correos.

    Args:
        remitente: texto a buscar dentro del remitente (email o nombre
            mostrado) -- coincidencia parcial, no hace falta el email
            completo (p.ej. "mercadona" encuentra "info@mercadona.es").
        cuenta: limita a esa cuenta (ver listar_cuentas para los ids
            disponibles, p.ej. "gmail-1").
        desde: no devolver correos anteriores a esta fecha (YYYY-MM-DD).
        hasta: no devolver correos posteriores a esta fecha (YYYY-MM-DD).
        limite: maximo de resultados (por defecto 50, tope 100).
    """
    conexion, error = _abrir_indice()
    if error:
        return error

    try:
        epoch_desde, epoch_hasta, error_fecha = _rango_fechas(desde, hasta)
        if error_fecha:
            return {"error": error_fecha}

        sql = (
            "SELECT id, header_message_id, fecha, remitente, remitente_nombre, asunto, carpeta, cuenta, tiene_adjuntos "
            "FROM correos WHERE 1=1"
        )
        parametros = []
        if remitente:
            sql += " AND (remitente LIKE ? OR remitente_nombre LIKE ?)"
            comodin = f"%{remitente}%"
            parametros += [comodin, comodin]
        if cuenta:
            sql += " AND cuenta = ?"
            parametros.append(cuenta)
        if epoch_desde is not None:
            sql += " AND fecha >= ?"
            parametros.append(epoch_desde)
        if epoch_hasta is not None:
            sql += " AND fecha <= ?"
            parametros.append(epoch_hasta)
        sql += " ORDER BY fecha DESC LIMIT ?"
        parametros.append(_tope(limite))

        filas = conexion.execute(sql, parametros).fetchall()
    finally:
        conexion.close()

    resultados = [
        _con_enlace(
            {
                "id": f["id"],
                "fecha": _fecha_iso(f["fecha"]),
                "remitente": f["remitente"],
                "remitente_nombre": f["remitente_nombre"],
                "asunto": f["asunto"],
                "carpeta": f["carpeta"],
                "cuenta": f["cuenta"],
                "tiene_adjuntos": bool(f["tiene_adjuntos"]),
            },
            f["header_message_id"],
        )
        for f in filas
    ]
    return {"resultados": resultados, "total_devueltos": len(resultados)}


@mcp.tool()
def leer_correo(id: int) -> dict:
    """Devuelve un correo completo: todos sus metadatos y el cuerpo entero
    en texto plano (no solo un fragmento). Usa el id que devuelven
    buscar_correos o listar_correos.

    Args:
        id: id del correo (campo "id" de buscar_correos/listar_correos).
    """
    conexion, error = _abrir_indice()
    if error:
        return error

    try:
        f = conexion.execute(
            "SELECT id, header_message_id, fecha, remitente, remitente_nombre, destinatarios, "
            "asunto, cuerpo, carpeta, cuenta, tiene_adjuntos, tamano FROM correos WHERE id = ?",
            (id,),
        ).fetchone()
    finally:
        conexion.close()

    if f is None:
        return {"error": f"No existe ningun correo con id {id}."}

    return _con_enlace(
        {
            "id": f["id"],
            "header_message_id": f["header_message_id"],
            "fecha": _fecha_iso(f["fecha"]),
            "remitente": f["remitente"],
            "remitente_nombre": f["remitente_nombre"],
            "destinatarios": f["destinatarios"],
            "asunto": f["asunto"],
            "cuerpo": f["cuerpo"],
            "carpeta": f["carpeta"],
            "cuenta": f["cuenta"],
            "tiene_adjuntos": bool(f["tiene_adjuntos"]),
            "tamano": f["tamano"],
        },
        f["header_message_id"],
    )


@mcp.tool()
def contar_correos(
    remitente: str | None = None,
    cuenta: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
) -> dict:
    """Cuenta cuantos correos cumplen un filtro, SIN devolver la lista --
    solo el numero, calculado con COUNT(*) en SQL. Usa esta herramienta
    para preguntas tipo "¿cuantos correos tengo de fulano?" o "¿cuantos
    correos me llegaron en 2023?" en vez de listar_correos + contar a mano:
    los modelos cuentan mal las filas de una lista larga que se les pasa
    como contexto, esto es siempre exacto.

    Los mismos filtros que listar_correos (remitente/cuenta/fechas), sin
    busqueda de texto.

    Args:
        remitente: texto a buscar dentro del remitente (email o nombre
            mostrado) -- coincidencia parcial.
        cuenta: limita a esa cuenta (ver listar_cuentas).
        desde: no contar correos anteriores a esta fecha (YYYY-MM-DD).
        hasta: no contar correos posteriores a esta fecha (YYYY-MM-DD).
    """
    conexion, error = _abrir_indice()
    if error:
        return error

    try:
        epoch_desde, epoch_hasta, error_fecha = _rango_fechas(desde, hasta)
        if error_fecha:
            return {"error": error_fecha}

        sql = "SELECT COUNT(*) FROM correos WHERE 1=1"
        parametros = []
        if remitente:
            sql += " AND (remitente LIKE ? OR remitente_nombre LIKE ?)"
            comodin = f"%{remitente}%"
            parametros += [comodin, comodin]
        if cuenta:
            sql += " AND cuenta = ?"
            parametros.append(cuenta)
        if epoch_desde is not None:
            sql += " AND fecha >= ?"
            parametros.append(epoch_desde)
        if epoch_hasta is not None:
            sql += " AND fecha <= ?"
            parametros.append(epoch_hasta)

        total = conexion.execute(sql, parametros).fetchone()[0]
    finally:
        conexion.close()

    return {"total": total}


@mcp.tool()
def listar_cuentas() -> dict:
    """Lista las cuentas de correo indexadas (ids como "gmail-1",
    "outlook-2"...), con cuantos correos tiene cada una y el rango de
    fechas que cubre. Nunca incluye el email real de la cuenta, solo el id
    corto. Deterministico (agregado SQL, no estimado).

    Usa esta herramienta para saber que cuentas hay disponibles antes de
    filtrar por "cuenta" en buscar_correos/listar_correos/contar_correos.
    """
    conexion, error = _abrir_indice()
    if error:
        return error

    try:
        filas = conexion.execute(
            "SELECT cuenta, COUNT(*) AS n, MIN(fecha) AS desde, MAX(fecha) AS hasta "
            "FROM correos GROUP BY cuenta ORDER BY n DESC"
        ).fetchall()
    finally:
        conexion.close()

    cuentas = [
        {
            "cuenta": f["cuenta"],
            "correos": f["n"],
            "desde": _fecha_iso(f["desde"]),
            "hasta": _fecha_iso(f["hasta"]),
        }
        for f in filas
    ]
    return {"cuentas": cuentas}


def _enmascarar_direccion(valor: str | None) -> str | None:
    """Enmascara la parte local de una direccion de correo, dejando el
    dominio integro: "xavier@gmail.com" -> "xa***r@gmail.com". Partes
    locales de 1-2 caracteres se devuelven tal cual (sin asteriscos); de
    3 caracteres se devuelven como 2 primeras + 1 asterisco (la ultima no
    cabe). Devuelve None si `valor` no tiene forma de direccion de correo
    -- p.ej. las cuentas locales/feeds, cuyo "usuario" en prefs.js es
    literalmente "nobody", no un email."""
    if not valor or "@" not in valor:
        return None
    local, _, dominio = valor.partition("@")
    if not local or not dominio:
        return None
    if len(local) <= 2:
        local_enmascarada = local
    elif len(local) == 3:
        local_enmascarada = local[:2] + "*"
    else:
        local_enmascarada = local[:2] + "*" * (len(local) - 3) + local[-1]
    return f"{local_enmascarada}@{dominio}"


@mcp.tool()
def describir_cuentas() -> dict:
    """Resuelve cada id corto de cuenta (los mismos "gmail-1", "outlook-2"...
    que devuelve listar_cuentas y que se usan para filtrar en
    buscar_correos/listar_correos/contar_correos) a la direccion de correo
    real de esa cuenta, pero ENMASCARADA (p.ej. "xa***r@gmail.com", dominio
    integro, parte local con las dos primeras letras y la ultima visibles) --
    asi se puede saber a que buzon corresponde cada id sin exponer la
    direccion completa.

    Deterministico: lee prefs.js del perfil de Thunderbird con la misma
    logica y la misma regla de numeracion que usa indexar_correo.py para
    generar el campo "cuenta" (no las reimplementa, las reutiliza), asi
    que los ids siempre casan con los de listar_cuentas. No hace ninguna
    llamada de red ni depende de correo.sqlite -- puede usarse aunque el
    indice de correo no este generado.

    Si prefs.js no existe o no se puede leer, no falla: devuelve la lista
    vacia junto con un "error" explicando el motivo. Si una cuenta
    concreta no resuelve a una direccion de correo real (cuentas
    locales/feeds, que no tienen email), esa entrada lleva
    "direccion": null en vez de fallar.

    Usa esta herramienta cuando el usuario pregunte "que cuenta es
    gmail-3" o quiera saber a que buzon corresponde un id antes de
    filtrar por el.
    """
    try:
        mapa_prefs = leer_prefs_servidores(PERFIL_TB)
        ids_cuenta = construir_ids_cuenta(mapa_prefs)
    except Exception as e:
        return {"cuentas": [], "error": f"No se pudo leer prefs.js del perfil de Thunderbird: {e}"}

    cuentas = []
    for (_host, usuario), cuenta_id in ids_cuenta.items():
        try:
            direccion = _enmascarar_direccion(usuario)
        except Exception:
            direccion = None
        cuentas.append({"cuenta": cuenta_id, "direccion": direccion})

    cuentas.sort(key=lambda c: c["cuenta"])
    return {"cuentas": cuentas}


if __name__ == "__main__":
    mcp.run()
