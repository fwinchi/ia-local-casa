"""
Servidor MCP de busqueda de fotos y videos.
Busca en ChromaDB por descripcion, genera una galeria HTML con miniaturas
y la abre automaticamente en el navegador.
"""
import base64
import io
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from html import escape
from pathlib import Path

import chromadb
import requests
from mcp.server.fastmcp import FastMCP
from PIL import Image

from config_rutas import (
    CARPETA_DB as CHROMA_PATH,   # mismo chroma/ que documentos, otra coleccion
    OLLAMA_BASE as OLLAMA,
    MODELO_EMBED_FOTOS as MODELO_EMBED,
)

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass

SCRIPTS = Path(__file__).resolve().parent         # antes: D:\paperless\scripts

COL_FOTOS = "fotos"
COL_VIDEOS = "videos"
SALIDA = SCRIPTS / "resultados_fotos.html"
MINIATURA = 300
DISTANCIA_MAX = 0.55

FFMPEG = shutil.which("ffmpeg") or str(Path.home() / "AppData/Local/Microsoft/WinGet/Links/ffmpeg.exe")
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

mcp = FastMCP("fotos")
cliente = chromadb.PersistentClient(path=CHROMA_PATH)


def coleccion(nombre):
    return cliente.get_or_create_collection(name=nombre, metadata={"hnsw:space": "cosine"})


def embed(texto):
    r = requests.post(
        f"{OLLAMA}/api/embeddings",
        json={"model": MODELO_EMBED, "prompt": f"search_query: {texto}"},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["embedding"]


def _b64(im):
    im = im.convert("RGB")
    im.thumbnail((MINIATURA, MINIATURA))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode()


def miniatura_foto(ruta):
    try:
        with Image.open(ruta) as im:
            return _b64(im)
    except Exception:
        return None


def miniatura_video(ruta):
    """Saca un fotograma con ffmpeg para usarlo como miniatura."""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / "t.jpg"
            subprocess.run(
                [FFMPEG, "-y", "-ss", "3", "-i", str(ruta), "-frames:v", "1",
                 "-vf", f"scale='min({MINIATURA},iw)':-2", "-q:v", "5", str(destino)],
                capture_output=True, creationflags=NO_WINDOW, timeout=60,
            )
            if destino.exists() and destino.stat().st_size > 0:
                with Image.open(destino) as im:
                    return _b64(im)
    except Exception:
        pass
    return None


def galeria(consulta, items, es_video):
    cards = []
    for meta, doc, dist in items:
        ruta = Path(meta.get("ruta", ""))
        b64 = None
        if ruta.exists():
            b64 = miniatura_video(ruta) if es_video else miniatura_foto(ruta)
        img = (f'<img src="data:image/jpeg;base64,{b64}">' if b64
               else '<div class="sinimg">sin vista previa</div>')
        nombre_esc = escape(meta.get('nombre', ''))
        carpeta_esc = escape(str(meta.get('carpeta', '.')))
        fecha_esc = escape(str(meta.get('fecha', '?')))
        desc_esc = escape(doc)
        ruta_href = escape(str(ruta).replace(chr(92), '/'))
        extra = (f" &middot; {escape(str(meta.get('duracion','?')))} &middot; {escape(str(meta.get('resolucion','?')))}"
                 if es_video else "")
        play = '<div class="play">&#9654;</div>' if es_video else ""
        cards.append(f"""
        <div class="card">
          <a href="file:///{ruta_href}" target="_blank">
            <div class="wrap">{img}{play}</div>
          </a>
          <div class="nombre">{nombre_esc}</div>
          <div class="meta">{fecha_esc} &middot; {carpeta_esc}{extra} &middot; {1-dist:.0%}</div>
          <div class="desc">{desc_esc}</div>
        </div>""")

    tipo = "Videos" if es_video else "Fotos"
    consulta_esc = escape(consulta)
    html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<title>{tipo}: {consulta_esc}</title><style>
 body{{font-family:system-ui,sans-serif;background:#14161a;color:#e6e6e6;margin:0;padding:24px}}
 h1{{font-size:20px}} h1 small{{color:#888;font-weight:400}}
 .rej{{display:flex;flex-wrap:wrap;gap:16px;margin-top:20px}}
 .card{{width:300px;background:#22262e;border-radius:10px;padding:12px}}
 .wrap{{position:relative}}
 .card img{{width:100%;border-radius:6px;display:block;background:#000}}
 .play{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
   font-size:38px;color:#fff;text-shadow:0 0 12px #000;pointer-events:none}}
 .sinimg{{height:140px;display:flex;align-items:center;justify-content:center;color:#666;background:#000;border-radius:6px}}
 .nombre{{font-size:13px;color:#8ab4f8;margin-top:9px;word-break:break-all}}
 .meta{{font-size:11px;color:#888;margin-top:3px}}
 .desc{{font-size:12px;color:#bbb;margin-top:7px;line-height:1.45}}
 .vacio{{color:#888}}
</style></head><body>
<h1>{tipo}: "{consulta_esc}" <small>{len(items)} resultados &middot; {datetime.now():%d/%m %H:%M}</small></h1>
<p style="color:#888;font-size:13px">Haz clic para abrir el archivo original.</p>
<div class="rej">{''.join(cards) if cards else '<p class="vacio">Sin resultados.</p>'}</div>
</body></html>"""
    SALIDA.write_text(html, encoding="utf-8")
    return SALIDA


def _buscar(nombre_col, consulta, maximo, es_video):
    col = coleccion(nombre_col)
    if col.count() == 0:
        return "El indice esta vacio. Ejecuta el script de indexado primero."

    res = col.query(
        query_embeddings=[embed(consulta)],
        n_results=min(maximo, col.count()),
        include=["documents", "metadatas", "distances"],
    )
    items = [
        (m, d, dist)
        for m, d, dist in zip(res["metadatas"][0], res["documents"][0], res["distances"][0])
        if dist <= DISTANCIA_MAX
    ]
    if not items:
        return f"No he encontrado nada que coincida con '{consulta}'."

    ruta_html = galeria(consulta, items, es_video)
    try:
        os.startfile(str(ruta_html))
        aviso = "He abierto la galeria en el navegador."
    except Exception:
        aviso = f"Galeria guardada en {ruta_html}"

    lineas = [f"{len(items)} resultados para '{consulta}'. {aviso}", ""]
    for m, d, dist in items:
        extra = f", {m.get('duracion')}" if es_video else ""
        lineas.append(f"- {m.get('nombre')} ({m.get('fecha')}{extra}): {d[:110]}")
    return "\n".join(lineas)


@mcp.tool()
def buscar_fotos(consulta: str, maximo: int = 12) -> str:
    """Busca FOTOGRAFIAS por su contenido y abre una galeria con los resultados.

    Usa esto cuando el usuario pida encontrar fotos o imagenes por lo que
    aparece en ellas (personas, lugares, objetos, escenas, texto visible).
    Haz UNA sola llamada por peticion.

    Args:
        consulta: Descripcion breve en espanol de lo que se busca.
        maximo: Numero maximo de fotos a devolver (por defecto 12).
    """
    return _buscar(COL_FOTOS, consulta, maximo, es_video=False)


@mcp.tool()
def buscar_videos(consulta: str, maximo: int = 12) -> str:
    """Busca VIDEOS por su contenido y abre una galeria con los resultados.

    Usa esto cuando el usuario pida encontrar videos, clips o grabaciones por
    lo que aparece en ellos. Haz UNA sola llamada por peticion.

    Args:
        consulta: Descripcion breve en espanol de lo que se busca.
        maximo: Numero maximo de videos a devolver (por defecto 12).
    """
    return _buscar(COL_VIDEOS, consulta, maximo, es_video=True)


@mcp.tool()
def estadisticas_fotos() -> str:
    """Devuelve cuantas fotos y videos hay indexados y en que carpetas estan."""
    salida = []
    for nombre, etiqueta in ((COL_FOTOS, "Fotos"), (COL_VIDEOS, "Videos")):
        col = coleccion(nombre)
        total = col.count()
        if total == 0:
            salida.append(f"{etiqueta}: 0 indexados.")
            continue
        datos = col.get(include=["metadatas"])
        carpetas, anios = {}, {}
        for m in datos["metadatas"]:
            c = m.get("carpeta", "?")
            carpetas[c] = carpetas.get(c, 0) + 1
            a = (m.get("fecha") or "????")[:4]
            anios[a] = anios.get(a, 0) + 1
        c = ", ".join(f"{k} ({v})" for k, v in sorted(carpetas.items(), key=lambda x: -x[1])[:8])
        y = ", ".join(f"{k}: {v}" for k, v in sorted(anios.items()))
        salida.append(f"{etiqueta}: {total} indexados. Carpetas: {c}. Por anio: {y}")
    return "\n".join(salida)


if __name__ == "__main__":
    mcp.run()