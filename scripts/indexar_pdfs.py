"""
Indexa los PDFs de una carpeta en ChromaDB (local, en fichero).
Los embeddings los genera Ollama con nomic-embed-text.
Ejecutar cada vez que anadas PDFs nuevos: solo procesa los que faltan.
"""

import hashlib
import json
import urllib.request
from pathlib import Path

import chromadb
from pypdf import PdfReader

BASE = Path(__file__).resolve().parent.parent   # antes: D:\paperless

CARPETAS_PDFS = [
    Path.home() / "OneDrive" / "Documentos",
    Path.home() / "Documents" / "Documentos para indexar",
]
CARPETA_DB = str(BASE / "chroma")
OLLAMA = "http://localhost:11434/api/embeddings"
MODELO = "bge-m3"

TAM_TROZO = 1200      # caracteres por fragmento
SOLAPE = 200          # solape entre fragmentos


def embedding(texto):
    datos = json.dumps({"model": MODELO, "prompt": texto}).encode()
    req = urllib.request.Request(
        OLLAMA, data=datos, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["embedding"]


def trocear(texto):
    trozos = []
    inicio = 0
    while inicio < len(texto):
        trozos.append(texto[inicio:inicio + TAM_TROZO])
        inicio += TAM_TROZO - SOLAPE
    return trozos


def texto_de_pdf(ruta):
    try:
        lector = PdfReader(str(ruta))
        paginas = []
        for i, pagina in enumerate(lector.pages):
            t = pagina.extract_text() or ""
            if t.strip():
                paginas.append((i + 1, t))
        return paginas
    except Exception as e:
        print(f"  ERROR leyendo: {e}")
        return []
def ocr_en_sitio(ruta):
    """Aplica OCR al PDF original. Hace copia previa. Devuelve True si lo procesó."""
    import shutil, subprocess
    BACKUP = BASE / "backup_pdfs"
    PUENTE = BASE / "export" / "ocr_auto"
    try:
        BACKUP.mkdir(parents=True, exist_ok=True)
        PUENTE.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ruta, BACKUP / ruta.name)
        tmp = PUENTE / ruta.name
        shutil.copy2(ruta, tmp)
        dentro = f"/usr/src/paperless/export/ocr_auto/{ruta.name}"
        r = subprocess.run(
            ["docker", "exec", "paperless-webserver-1", "ocrmypdf",
             "-l", "spa", "--skip-text", "--output-type", "pdf", dentro, dentro],
            capture_output=True, text=True)
        if r.returncode == 0 and tmp.stat().st_size > 0:
            shutil.copy2(tmp, ruta)
            tmp.unlink()
            return True
        tmp.unlink(missing_ok=True)
        print(f"  OCR no aplicable: {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else 'error'}")
        return False
    except Exception as e:
        print(f"  Error en OCR: {e}")
        return False

def main():
    cliente = chromadb.PersistentClient(path=CARPETA_DB)
    col = cliente.get_or_create_collection(
        "documentos", metadata={"hnsw:space": "cosine"}
    )

    pdfs = []
    for carpeta in CARPETAS_PDFS:
        if carpeta.exists():
            pdfs.extend(carpeta.rglob("*.pdf"))
        else:
            print(f"AVISO: no existe {carpeta}")
    pdfs = sorted(pdfs)
    print(f"Encontrados {len(pdfs)} PDFs\n")

    nuevos = 0
    for ruta in pdfs:
        id_doc = hashlib.md5(str(ruta).encode()).hexdigest()[:12]

        # Saltar si ya esta indexado
        if col.get(where={"doc": id_doc}, limit=1)["ids"]:
            continue

        print(f"Indexando: {ruta.name}")
        paginas = texto_de_pdf(ruta)
        if not paginas:
            print("  Sin texto extraible. Aplicando OCR...")
            if not ocr_en_sitio(ruta):
                continue
            paginas = texto_de_pdf(ruta)
            if not paginas:
                print("  Sigue sin texto. Saltado.")
                continue
            print(f"  OCR aplicado: {len(paginas)} paginas.")

        ids, docs, embs, metas = [], [], [], []
        for num_pagina, texto in paginas:
            for j, trozo in enumerate(trocear(texto)):
                if len(trozo.strip()) < 50:
                    continue
                ids.append(f"{id_doc}-{num_pagina}-{j}")
                docs.append(trozo)
                embs.append(embedding(trozo))
                metas.append({
                    "doc": id_doc,
                    "archivo": ruta.name,
                    "ruta": str(ruta),
                    "pagina": num_pagina,
                })

        if ids:
            col.add(ids=ids, documents=docs, embeddings=embs, metadatas=metas)
            print(f"  {len(ids)} fragmentos anadidos")
            nuevos += 1

    print(f"\nListo. {nuevos} PDFs nuevos indexados.")
    print(f"Total de fragmentos en la base: {col.count()}")


if __name__ == "__main__":
    main()
