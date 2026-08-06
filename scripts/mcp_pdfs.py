"""
Servidor MCP: busqueda semantica en los PDFs de OneDrive indexados en ChromaDB.
Se sirve via mcpo para Open WebUI.
"""

import json
import urllib.request
from pathlib import Path

import chromadb
from mcp.server.fastmcp import FastMCP

BASE = Path(__file__).resolve().parent.parent   # antes: D:\paperless
CARPETA_DB = str(BASE / "chroma")
OLLAMA = "http://localhost:11434/api/embeddings"
MODELO = "bge-m3"

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
    import os
    if not os.path.isfile(ruta):
        return f"No existe el archivo: {ruta}"
    if not ruta.lower().endswith(".pdf"):
        return "Solo se pueden abrir archivos PDF."
    os.startfile(ruta)
    return f"Abierto en el visor de Windows: {os.path.basename(ruta)}"
if __name__ == "__main__":
    mcp.run()