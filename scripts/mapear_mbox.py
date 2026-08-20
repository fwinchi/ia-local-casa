"""
Resuelve la ruta en disco del mbox de cada carpeta indexada en el gloda de
Thunderbird (gloda.sqlite), para poder leer despues asunto/cuerpo con un MCP
de correo -- gloda no guarda esos campos de forma accesible desde Python
(messagesText usa el tokenizer mozporter, ilegible fuera de Thunderbird).

Como se resuelve la ruta
-------------------------
folderLocations.folderURI tiene forma:
  imap://USUARIO@HOST/RUTA               (cuentas IMAP)
  mailbox://nobody@Local%20Folders/RUTA  (carpetas locales)
  mailbox://nobody@Feeds/RUTA            (fuentes RSS)

El host solo no basta para ubicar el directorio en ImapMail\\: si hay varias
cuentas en el mismo servidor (p.ej. varias cuentas @gmail.com), Thunderbird
crea imap.gmail.com, imap.gmail-1.com, imap.gmail-2.com... y el nombre de
esos directorios no contiene el usuario, asi que no se puede adivinar por
patron. La unica fuente fiable de la pareja (host, usuario) -> directorio
real es prefs.js del perfil (claves mail.server.serverN.hostname /
.userName / .directory-rel), asi que se lee ese fichero de texto en vez de
asumir un mapeo posicional.

A partir del directorio de la cuenta, cada nivel intermedio de RUTA lleva
sufijo ".sbd" (asi guarda Thunderbird las subcarpetas); el ultimo nivel es
el fichero mbox tal cual, sin extension.

Privacidad: nunca se imprime el folderURI completo ni el usuario de la
cuenta (email). Las rutas resueltas ya no contienen el usuario (los
directorios de Thunderbird se llaman por host, no por cuenta), pero aun asi
solo se imprimen nombres de carpeta y el directorio de host -- nunca la
ruta completa del perfil.

Sin dependencias externas: os, pathlib, sqlite3, urllib.parse.
"""

import os
import sqlite3
from pathlib import Path
from urllib.parse import unquote, urlparse

PERFIL_TB = Path(os.environ["APPDATA"]) / "Thunderbird" / "Profiles" / "6g35p5va.default-release"
RUTA_GLODA = Path(r"D:\paperless\correo\gloda.sqlite")

CAMPOS_SERVIDOR = ("hostname", "userName", "directory-rel")


def leer_prefs_servidores(perfil: Path) -> dict[tuple[str, str], str]:
    """Lee prefs.js y devuelve {(hostname, userName): directory-rel}.

    directory-rel viene tal cual la guarda Thunderbird, p.ej.
    "ImapMail/imap.gmail-4.com" o "Mail/Local Folders" (con "/", incluso en
    Windows -- Mozilla usa siempre forward slash en este fichero).
    """
    ruta_prefs = perfil / "prefs.js"
    servidores: dict[str, dict[str, str]] = {}

    with open(ruta_prefs, "r", encoding="utf-8", errors="replace") as f:
        for linea in f:
            linea = linea.strip()
            if not linea.startswith('user_pref("mail.server.server'):
                continue
            # user_pref("mail.server.serverN.campo", "valor");
            partes = linea.split('"')
            if len(partes) < 4:
                continue
            clave, valor = partes[1], partes[3]
            resto = clave[len("mail.server."):]
            if "." not in resto:
                continue
            server_id, campo = resto.split(".", 1)
            if campo not in CAMPOS_SERVIDOR:
                continue
            servidores.setdefault(server_id, {})[campo] = valor

    mapa: dict[tuple[str, str], str] = {}
    for datos in servidores.values():
        host = datos.get("hostname")
        usuario = datos.get("userName")
        rel = datos.get("directory-rel")
        if not (host and usuario and rel):
            continue
        if rel.startswith("[ProfD]"):
            rel = rel[len("[ProfD]"):]
        mapa[(host, usuario)] = rel

    return mapa


def usuario_y_host(folder_uri: str) -> tuple[str | None, str | None]:
    """Extrae (usuario, host) de la parte "usuario@host" del folderURI, ya
    decodificados con unquote. Devuelve (None, None) si el URI no tiene esa
    forma. Se expone por separado porque otros scripts (p.ej. el indexador
    de correo) necesitan el (host, usuario) para identificar la cuenta sin
    tener que resolver tambien la ruta del mbox."""
    partes = urlparse(folder_uri)
    if "@" not in partes.netloc:
        return None, None
    usuario_enc, host_enc = partes.netloc.split("@", 1)
    return unquote(usuario_enc), unquote(host_enc)


def resolver_ruta_mbox(folder_uri: str, mapa_prefs: dict[tuple[str, str], str], perfil: Path) -> Path | None:
    """Devuelve la ruta del mbox para un folderURI, o None si no hay cuenta
    reconocida en prefs.js para ese (host, usuario)."""
    usuario, host = usuario_y_host(folder_uri)
    if usuario is None:
        return None

    rel = mapa_prefs.get((host, usuario))
    if rel is None:
        return None

    base = perfil.joinpath(*rel.split("/"))
    ruta_uri = urlparse(folder_uri).path
    segmentos = [unquote(s) for s in ruta_uri.strip("/").split("/") if s]
    if not segmentos:
        return base

    ruta = base
    for seg in segmentos[:-1]:
        ruta = ruta / f"{seg}.sbd"
    return ruta / segmentos[-1]


def directorio_host(ruta_mbox: Path, perfil: Path) -> str:
    """Nombre del directorio de cuenta (p.ej. "imap.gmail-4.com"), para
    mostrar en el listado sin revelar la ruta completa del perfil."""
    try:
        relativa = ruta_mbox.relative_to(perfil)
    except ValueError:
        return "?"
    return relativa.parts[1] if len(relativa.parts) > 1 else relativa.parts[0]


def main() -> None:
    mapa_prefs = leer_prefs_servidores(PERFIL_TB)

    uri_conexion = f"file:/{RUTA_GLODA.resolve().as_posix()}?mode=ro"
    conexion = sqlite3.connect(uri_conexion, uri=True)

    filas = conexion.execute("SELECT folderURI FROM folderLocations").fetchall()
    conexion.close()

    n_existe = 0
    n_no_existe = 0
    n_sin_cuenta = 0
    tamano_total = 0
    encontradas: list[tuple[str, str, int]] = []  # (nombre carpeta, dir host, bytes)

    for (folder_uri,) in filas:
        ruta_mbox = resolver_ruta_mbox(folder_uri, mapa_prefs, PERFIL_TB)
        if ruta_mbox is None:
            n_sin_cuenta += 1
            continue

        if ruta_mbox.is_file():
            n_existe += 1
            tam = ruta_mbox.stat().st_size
            tamano_total += tam
            segmentos = [unquote(s) for s in urlparse(folder_uri).path.strip("/").split("/") if s]
            nombre = "/".join(segmentos)
            encontradas.append((nombre, directorio_host(ruta_mbox, PERFIL_TB), tam))
        else:
            n_no_existe += 1

    print(f"Carpetas indexadas en gloda: {len(filas)}")
    print(f"  Con mbox encontrado en disco:      {n_existe}")
    print(f"  Con ruta resuelta pero SIN mbox:    {n_no_existe}")
    if n_sin_cuenta:
        print(f"  Sin cuenta reconocida en prefs.js:  {n_sin_cuenta}")

    print(f"\nTamano total en disco de los mbox encontrados: {tamano_total / (1024 * 1024):.1f} MB")

    print("\nTop 10 carpetas con mbox mas grande:")
    for nombre, host_dir, tam in sorted(encontradas, key=lambda x: x[2], reverse=True)[:10]:
        print(f"  {tam / (1024 * 1024):8.1f} MB  {nombre}  [{host_dir}]")


if __name__ == "__main__":
    main()
