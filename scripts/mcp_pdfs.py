"""
Servidor MCP: busqueda semantica en los PDFs de OneDrive indexados en ChromaDB.
Se sirve via mcpo para Open WebUI.
"""

import json
import os
import urllib.request
from pathlib import Path

import chromadb
import requests
from mcp.server.fastmcp import FastMCP

BASE = Path(__file__).resolve().parent.parent   # antes: D:\paperless
CARPETA_DB = str(BASE / "chroma")
OLLAMA = "http://localhost:11434/api/embeddings"
MODELO = "bge-m3"
PAPERLESS_API = "http://localhost:8010/api"

# Las mismas carpetas que indexa indexar_pdfs.py. abrir_pdf solo puede abrir
# archivos dentro de ellas, nunca una ruta arbitraria del sistema.
CARPETAS_PDFS = [
    (Path.home() / "OneDrive" / "Documentos").resolve(),
    (Path.home() / "Documents" / "Documentos para indexar").resolve(),
]

mcp = FastMCP("pdfs-onedrive")

cliente = chromadb.PersistentClient(path=CARPETA_DB)
col = cliente.get_or_create_collection(
    "documentos", metadata={"hnsw:space": "cosine"}
)


def embedding(texto):
    datos = json.dumps({"model": MODELO, "prompt": texto}).encode()
    req = urllib.request.Request(
        OLLAMA, data=datos, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["embedding"]


@mcp.tool()
def buscar_en_pdfs(pregunta: str, resultados: int = 5) -> str:
    """Busca por significado en los PDFs personales del usuario guardados en
    OneDrive (informes medicos, tramites, hacienda, seguros, manuales, guias).

    Estos documentos NO estan en Paperless-ngx: son archivos aparte.
    Usa esta herramienta cuando el usuario pregunte por el contenido de algun
    documento suyo que no aparezca en Paperless.

    Args:
        pregunta: la consulta en lenguaje natural.
        resultados: cuantos fragmentos devolver (por defecto 5).
    """
    res = col.query(
        query_embeddings=[embedding(pregunta)],
        n_results=resultados,
    )
    if not res["ids"][0]:
        return "Sin resultados."

    salida = []
    for i in range(len(res["ids"][0])):
        meta = res["metadatas"][0][i]
        texto = res["documents"][0][i].replace("\n", " ").strip()
        salida.append(
            f"[{i + 1}] {meta['archivo']} (pagina {meta['pagina']})\n"
            f"Ruta: {meta['ruta']}\n"
            f"Distancia: {res['distances'][0][i]:.3f}\n"
            f"Texto: {texto}\n"
        )
    return "\n".join(salida)


@mcp.tool()
def listar_pdfs_indexados() -> str:
    """Devuelve la lista de archivos PDF que estan indexados y por tanto se
    pueden consultar con buscar_en_pdfs."""
    datos = col.get(include=["metadatas"])
    archivos = sorted({m["archivo"] for m in datos["metadatas"]})
    return f"{len(archivos)} PDFs indexados:\n" + "\n".join(archivos)


@mcp.tool()
def abrir_pdf(ruta: str) -> str:
    """Abre un PDF del usuario en el visor predeterminado de Windows para que
    pueda verlo. Usa la ruta exacta devuelta por buscar_en_pdfs.

    Args:
        ruta: ruta completa del archivo, tal como aparece en los resultados.
    """
    ruta_path = Path(ruta).resolve()
    if not any(ruta_path.is_relative_to(c) for c in CARPETAS_PDFS):
        return (f"Ruta no permitida: {ruta}. abrir_pdf solo puede abrir archivos "
                f"dentro de las carpetas indexadas ({', '.join(str(c) for c in CARPETAS_PDFS)}).")
    if not ruta_path.is_file():
        return f"No existe el archivo: {ruta}"
    if ruta_path.suffix.lower() != ".pdf":
        return "Solo se pueden abrir archivos PDF."
    os.startfile(str(ruta_path))
    return f"Abierto en el visor de Windows: {ruta_path.name}"


def _cabecera():
    token = os.environ.get("PAPERLESS_TOKEN")
    if not token:
        return None
    return {"Authorization": f"Token {token}"}


def _contar(cab, filtros):
    """Cuenta documentos con un filtro dado usando page_size=1: solo lee el
    campo "count" de la respuesta, nunca descarga la lista de documentos."""
    params = dict(filtros)
    params["page_size"] = 1
    r = requests.get(f"{PAPERLESS_API}/documents/", headers=cab, params=params, timeout=30)
    r.raise_for_status()
    return r.json()["count"]


def _listar_nombres(cab, recurso):
    """Id -> nombre de un catálogo pequeño (tipos o interlocutores), paginando
    si hiciera falta. Son listas cortas, a diferencia de los documentos."""
    nombres, url = {}, f"{PAPERLESS_API}/{recurso}/?page_size=200"
    while url:
        r = requests.get(url, headers=cab, timeout=30)
        r.raise_for_status()
        datos = r.json()
        for item in datos["results"]:
            nombres[item["id"]] = item["name"]
        url = datos["next"]
    return nombres


@mcp.tool()
def contar_documentos() -> dict:
    """Cuenta los documentos archivados en Paperless: total, desglose por tipo
    de documento y por interlocutor. No descarga ni lee el contenido de
    ningún documento, solo números ya calculados por la API (campo "count"
    con page_size=1 en cada consulta) — así el modelo no tiene que razonar
    sobre un JSON grande para contar, que es donde suele equivocarse.

    Usa esta herramienta para preguntas tipo "¿cuántos documentos/facturas
    tengo archivados?", "¿cuántos son de tal proveedor?" o "¿cuántos son de
    tal tipo?". Para el contenido de un documento concreto sigue usando las
    herramientas de Paperless normales, no esta.
    """
    cab = _cabecera()
    if cab is None:
        return {"error": "Falta la variable de entorno PAPERLESS_TOKEN."}

    try:
        total = _contar(cab, {})

        por_tipo = {}
        for id_tipo, nombre in _listar_nombres(cab, "document_types").items():
            n = _contar(cab, {"document_type__id": id_tipo})
            if n:
                por_tipo[nombre] = n
        sin_tipo = _contar(cab, {"document_type__isnull": "true"})
        if sin_tipo:
            por_tipo["sin_tipo"] = sin_tipo

        por_correspondiente = {}
        for id_corr, nombre in _listar_nombres(cab, "correspondents").items():
            n = _contar(cab, {"correspondent__id": id_corr})
            if n:
                por_correspondiente[nombre] = n
        sin_correspondiente = _contar(cab, {"correspondent__isnull": "true"})
        if sin_correspondiente:
            por_correspondiente["sin_correspondiente"] = sin_correspondiente

        return {
            "total": total,
            "por_tipo": por_tipo,
            "por_correspondiente": por_correspondiente,
        }
    except requests.RequestException as e:
        return {"error": f"No se pudo consultar Paperless: {e}"}


if __name__ == "__main__":
    mcp.run()