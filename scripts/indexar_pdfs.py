"""
Indexa documentos (PDF, DOCX, TXT, ODT) de una carpeta en ChromaDB (local, en fichero).
Los embeddings los genera Ollama con bge-m3.
Ejecutar cada vez que anadas documentos nuevos: solo procesa los que faltan.
"""

import hashlib
import json
import urllib.request
from pathlib import Path

import chromadb
import docx
from odf import teletype
from odf.opendocument import load as cargar_odt
from odf.text import P as OdtParrafo
from pypdf import PdfReader

BASE = Path(__file__).resolve().parent.parent   # antes: D:\paperless

CARPETAS_PDFS = [
    Path.home() / "OneDrive" / "Documentos" / "Documentos para indexar",
    Path.home() / "Documents" / "Documentos para indexar",
]
CARPETA_DB = str(BASE / "chroma")
OLLAMA = "http://localhost:11434/api/embeddings"
MODELO = "bge-m3"

TAM_TROZO = 1200      # caracteres por fragmento
SOLAPE = 200          # solape entre fragmentos

EXTENSIONES = [".pdf", ".docx", ".txt", ".odt"]


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


def texto_de_docx(ruta):
    """DOCX no tiene un concepto fiable de "pagina" sin renderizarlo, asi que
    se trata como un unico bloque (pagina 1) y se trocea igual que un PDF."""
    try:
        documento = docx.Document(str(ruta))
        texto = "\n".join(p.text for p in documento.paragraphs)
        return [(1, texto)] if texto.strip() else []
    except Exception as e:
        print(f"  ERROR leyendo: {e}")
        return []


def texto_de_txt(ruta):
    """Mismo criterio que DOCX/ODT: un unico bloque, pagina 1."""
    try:
        try:
            texto = ruta.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            texto = ruta.read_text(encoding="cp1252", errors="replace")
        return [(1, texto)] if texto.strip() else []
    except Exception as e:
        print(f"  ERROR leyendo: {e}")
        return []


def texto_de_odt(ruta):
    """Mismo criterio que DOCX/TXT: un unico bloque, pagina 1."""
    try:
        documento = cargar_odt(str(ruta))
        parrafos = documento.getElementsByType(OdtParrafo)
        texto = "\n".join(teletype.extractText(p) for p in parrafos)
        return [(1, texto)] if texto.strip() else []
    except Exception as e:
        print(f"  ERROR leyendo: {e}")
        return []


EXTRACTORES = {
    ".pdf": texto_de_pdf,
    ".docx": texto_de_docx,
    ".txt": texto_de_txt,
    ".odt": texto_de_odt,
}


def ocr_en_sitio(ruta):
    """Aplica OCR al PDF original. Hace copia previa. Devuelve True si lo procesó."""
    import shutil, subprocess
    BACKUP = BASE / "backup_pdfs"
    PUENTE = BASE / "export" / "ocr_auto"
    try:
        BACKUP.mkdir(parents=True, exist_ok=True)
        PUENTE.mkdir(parents=True, exist_ok=True)
        # Nombre de backup único por ruta de origen: dos PDFs con el mismo
        # nombre en carpetas distintas (p.ej. "factura.pdf" en OneDrive y en
        # Documentos) ya no se pisan el backup entre sí.
        sufijo = hashlib.md5(str(ruta).encode()).hexdigest()[:8]
        shutil.copy2(ruta, BACKUP / f"{ruta.stem}_{sufijo}{ruta.suffix}")
        tmp = PUENTE / ruta.name
        shutil.copy2(ruta, tmp)
        dentro = f"/usr/src/paperless/export/ocr_auto/{ruta.name}"
        r = subprocess.run(
            ["docker", "exec", "paperless-webserver-1", "ocrmypdf",
             "-l", "spa", "--skip-text", "--output-type", "pdf", dentro, dentro],
            capture_output=True, text=True)
        if r.returncode == 0 and tmp.stat().st_size > 0:
            # Escritura atómica: Path.replace() es atómico solo dentro del
            # mismo disco, y PUENTE puede estar en una unidad distinta a la
            # del original (p.ej. D: vs C:\...\OneDrive). Se copia primero a
            # un temporal EN EL MISMO DISCO que ruta, y solo se sustituye el
            # original cuando esa copia ha terminado bien y no está vacía.
            tmp_mismo_disco = ruta.with_name(f"{ruta.stem}.ocr_tmp{ruta.suffix}")
            shutil.copy2(tmp, tmp_mismo_disco)
            if tmp_mismo_disco.stat().st_size == 0:
                tmp_mismo_disco.unlink(missing_ok=True)
                tmp.unlink()
                print("  OCR generó un archivo vacío, no se sustituye el original.")
                return False
            tmp_mismo_disco.replace(ruta)
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

    archivos = []
    for carpeta in CARPETAS_PDFS:
        if carpeta.exists():
            for ext in EXTENSIONES:
                archivos.extend(carpeta.rglob(f"*{ext}"))
        else:
            print(f"AVISO: no existe {carpeta}")
    archivos = sorted(archivos)
    print(f"Encontrados {len(archivos)} documentos ({', '.join(EXTENSIONES)})\n")

    nuevos = 0
    for ruta in archivos:
        id_doc = hashlib.md5(str(ruta).encode()).hexdigest()[:12]

        # Saltar si ya esta indexado
        if col.get(where={"doc": id_doc}, limit=1)["ids"]:
            continue

        tipo = ruta.suffix.lower().lstrip(".")
        print(f"Indexando: {ruta.name}")

        extractor = EXTRACTORES[ruta.suffix.lower()]
        paginas = extractor(ruta)

        if not paginas and ruta.suffix.lower() == ".pdf":
            # Solo el PDF puede ser un escaneo sin texto: DOCX/TXT/ODT
            # siempre son texto nativo, no tiene sentido pasarles OCR.
            print("  Sin texto extraible. Aplicando OCR...")
            if not ocr_en_sitio(ruta):
                continue
            paginas = texto_de_pdf(ruta)
            if not paginas:
                print("  Sigue sin texto. Saltado.")
                continue
            print(f"  OCR aplicado: {len(paginas)} paginas.")
        elif not paginas:
            print("  Sin texto extraible. Saltado.")
            continue

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
                    "tipo": tipo,
                })

        if ids:
            col.add(ids=ids, documents=docs, embeddings=embs, metadatas=metas)
            print(f"  {len(ids)} fragmentos anadidos")
            nuevos += 1

    print(f"\nListo. {nuevos} documentos nuevos indexados.")
    print(f"Total de fragmentos en la base: {col.count()}")


if __name__ == "__main__":
    main()
