"""
Busqueda semantica sobre los PDFs indexados.
Uso:  python buscar.py "donde decia lo de la garantia"
O sin argumentos, para preguntar en bucle.
"""

import json
import sys
import urllib.request

import chromadb

from config_rutas import CARPETA_DB, OLLAMA, MODELO

RESULTADOS = 5


def embedding(texto):
    datos = json.dumps({"model": MODELO, "prompt": texto}).encode()
    req = urllib.request.Request(
        OLLAMA, data=datos, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["embedding"]


def buscar(col, pregunta):
    res = col.query(
        query_embeddings=[embedding(pregunta)],
        n_results=RESULTADOS,
    )
    if not res["ids"][0]:
        print("Sin resultados.")
        return

    for i in range(len(res["ids"][0])):
        meta = res["metadatas"][0][i]
        texto = res["documents"][0][i].replace("\n", " ").strip()
        distancia = res["distances"][0][i]
        print(f"\n[{i + 1}] {meta['archivo']}  (pag. {meta['pagina']})")
        print(f"    Ruta: {meta['ruta']}")
        print(f"    Distancia: {distancia:.3f} (menor = mejor)")
        print(f"    ...{texto[:400]}...")


def main():
    cliente = chromadb.PersistentClient(path=CARPETA_DB)
    col = cliente.get_or_create_collection("documentos")
    print(f"Base cargada: {col.count()} fragmentos\n")

    if len(sys.argv) > 1:
        buscar(col, " ".join(sys.argv[1:]))
        return

    while True:
        pregunta = input("\nPregunta (Enter vacio para salir): ").strip()
        if not pregunta:
            break
        buscar(col, pregunta)


if __name__ == "__main__":
    main()