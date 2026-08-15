"""
Genera un HTML con miniaturas de cada grupo de duplicados para revisarlos a ojo.
Marca/desmarca lo que quieras borrar y pulsa el boton para descargar la lista final.
NO BORRA NADA.
"""
import base64
import hashlib
import io
import json
import subprocess
from datetime import datetime
from html import escape
from pathlib import Path

from PIL import Image
import imagehash

Image.MAX_IMAGE_PIXELS = 300_000_000  # limite explicito de PIL contra "bombas de descompresion"

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass

SCRIPTS = Path(__file__).resolve().parent   # antes: D:\paperless\scripts

ETIQUETA_DISCO = "Multimedia IA"
CARPETA_FOTOS = "FOTOS"
CARPETA_VIDEOS = "VIDEOS"
UMBRAL_PHASH = 5
SALIDA = SCRIPTS
MINIATURA = 260

EXT_FOTO = {".jpg", ".jpeg", ".png", ".heic", ".bmp", ".webp", ".tiff", ".gif"}
EXT_VIDEO = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v", ".mpg", ".mpeg", ".3gp"}


def letra_disco():
    ps = f'(Get-Volume | Where-Object FileSystemLabel -eq "{ETIQUETA_DISCO}").DriveLetter'
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True)
    letra = r.stdout.strip()
    if not letra:
        raise SystemExit(f"No se encuentra el disco '{ETIQUETA_DISCO}'. Conectalo.")
    return letra


def sha256(ruta, bloque=1024 * 1024):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        while chunk := f.read(bloque):
            h.update(chunk)
    return h.hexdigest()


def phash(ruta):
    try:
        with Image.open(ruta) as im:
            im.draft("RGB", (512, 512))
            return imagehash.phash(im.convert("RGB"))
    except Exception:
        return None


def listar(carpeta, extensiones):
    if not carpeta.exists():
        return []
    return [p for p in carpeta.rglob("*")
            if p.is_file() and p.suffix.lower() in extensiones]


def dims(ruta):
    try:
        with Image.open(ruta) as im:
            return im.width, im.height
    except Exception:
        return 0, 0


def miniatura_b64(ruta):
    try:
        with Image.open(ruta) as im:
            im = im.convert("RGB")
            im.thumbnail((MINIATURA, MINIATURA))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=80)
            return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def mejor(grupo, es_foto):
    def clave(p):
        w, h = dims(p) if es_foto else (0, 0)
        return (w * h, p.stat().st_size, -p.stat().st_mtime)
    return max(grupo, key=clave)


def agrupar_exactos(archivos, etiqueta):
    print(f"[{etiqueta}] hash exacto ({len(archivos)})...")
    mapa = {}
    for p in archivos:
        try:
            mapa.setdefault(sha256(p), []).append(p)
        except Exception:
            pass
    return [g for g in mapa.values() if len(g) > 1]


def agrupar_perceptuales(archivos, ya_marcados):
    print("[FOTOS] hash perceptual...")
    hashes = []
    for p in archivos:
        if p in ya_marcados:
            continue
        h = phash(p)
        if h is not None:
            hashes.append((p, h))
    grupos, usados = [], set()
    for i, (p1, h1) in enumerate(hashes):
        if p1 in usados:
            continue
        grupo = [(p1, 0)]
        for p2, h2 in hashes[i + 1:]:
            if p2 in usados:
                continue
            d = h1 - h2
            if d <= UMBRAL_PHASH:
                grupo.append((p2, d))
                usados.add(p2)
        if len(grupo) > 1:
            usados.add(p1)
            grupos.append(grupo)
    return grupos


def tarjeta(p, es_foto, conservar, distancia=None):
    b64 = miniatura_b64(p) if es_foto else None
    w, h = dims(p) if es_foto else (0, 0)
    mb = p.stat().st_size / (1024 * 1024)
    res = f"{w}x{h}" if w else "-"
    dist = f" · dist {distancia}" if distancia is not None and distancia > 0 else ""
    clase = "conservar" if conservar else "borrar"
    img = (f'<img src="data:image/jpeg;base64,{b64}">' if b64
           else '<div class="sinimg">sin miniatura</div>')
    chk = "" if conservar else "checked"
    ruta_esc = escape(str(p))
    nombre_esc = escape(p.name)
    dir_esc = escape(str(p.parent))
    etq = ("<span class=\"badge ok\">CONSERVAR</span>" if conservar
           else f'<label class="badge del"><input type="checkbox" data-ruta="{ruta_esc}" {chk}> borrar</label>')
    return f"""
    <div class="card {clase}">
      {img}
      <div class="meta">{etq}</div>
      <div class="meta">{res} · {mb:.2f} MB{dist}</div>
      <div class="ruta" title="{ruta_esc}">{nombre_esc}</div>
      <div class="ruta dir">{dir_esc}</div>
    </div>"""


def main():
    d = letra_disco()
    raiz = Path(f"{d}:\\")
    fotos = listar(raiz / CARPETA_FOTOS, EXT_FOTO)
    videos = listar(raiz / CARPETA_VIDEOS, EXT_VIDEO)
    print(f"Disco {d}: | Fotos {len(fotos)} | Videos {len(videos)}")

    g_fotos_exact = agrupar_exactos(fotos, "FOTOS")
    marcados = {p for g in g_fotos_exact for p in g}
    g_fotos_perc = agrupar_perceptuales(fotos, marcados)
    g_videos = agrupar_exactos(videos, "VIDEOS")

    print("Generando miniaturas...")
    partes = []
    total_borrar = 0

    secciones = [
        ("Fotos · duplicados EXACTOS (byte a byte, seguros)",
         [[(p, None) for p in g] for g in g_fotos_exact], True),
        (f"Fotos · duplicados PERCEPTUALES (umbral {UMBRAL_PHASH}) · REVISAR",
         g_fotos_perc, True),
        ("Vídeos · duplicados EXACTOS (byte a byte, seguros)",
         [[(p, None) for p in g] for g in g_videos], False),
    ]

    for titulo, grupos, es_foto in secciones:
        partes.append(f'<h2>{titulo} <small>{len(grupos)} grupos</small></h2>')
        if not grupos:
            partes.append('<p class="vacio">Ninguno.</p>')
            continue
        for n, g in enumerate(grupos, 1):
            vivos = []
            for p, dist in g:
                if p.exists():
                    vivos.append((p, dist))
                else:
                    print(f"  AVISO: ya no existe, se omite del grupo: {p}")
            if len(vivos) < 2:
                continue  # el grupo dejó de ser un duplicado real

            rutas = [p for p, _ in vivos]
            keep = mejor(rutas, es_foto)
            cards_list = []
            for p, dist in vivos:
                try:
                    cards_list.append(tarjeta(p, es_foto, p == keep, dist))
                except Exception as e:
                    print(f"  ERROR generando tarjeta de {p}: {e}")
            cards = "".join(cards_list)
            total_borrar += len(rutas) - 1
            partes.append(f'<div class="grupo"><h3>Grupo {n}</h3><div class="fila">{cards}</div></div>')

    html = f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<title>Revisión de duplicados</title>
<style>
 body{{font-family:system-ui,sans-serif;background:#14161a;color:#e6e6e6;margin:0;padding:24px 24px 100px}}
 h1{{font-size:22px}} h2{{margin-top:38px;border-bottom:1px solid #333;padding-bottom:8px;font-size:17px}}
 h2 small{{color:#888;font-weight:400}} h3{{font-size:13px;color:#8ab4f8;margin:18px 0 8px}}
 .grupo{{background:#1c1f25;border-radius:10px;padding:12px 16px;margin-bottom:14px}}
 .fila{{display:flex;flex-wrap:wrap;gap:14px}}
 .card{{width:280px;background:#22262e;border-radius:8px;padding:10px;border:2px solid transparent}}
 .card.conservar{{border-color:#3d9970}} .card.borrar{{border-color:#7a3b3b}}
 .card img{{width:100%;border-radius:5px;display:block;background:#000}}
 .sinimg{{height:120px;display:flex;align-items:center;justify-content:center;color:#666;background:#000;border-radius:5px}}
 .meta{{font-size:12px;color:#aaa;margin-top:7px}}
 .ruta{{font-size:11px;color:#ccc;margin-top:4px;word-break:break-all}}
 .ruta.dir{{color:#777}}
 .badge{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}}
 .badge.ok{{background:#3d9970;color:#fff}}
 .badge.del{{background:#7a3b3b;color:#fff;cursor:pointer}}
 .vacio{{color:#777}}
 .barra{{position:fixed;bottom:0;left:0;right:0;background:#1c1f25;border-top:1px solid #333;
   padding:14px 24px;display:flex;gap:18px;align-items:center}}
 button{{background:#8ab4f8;color:#14161a;border:0;padding:10px 18px;border-radius:6px;
   font-weight:600;cursor:pointer;font-size:14px}}
 #cuenta{{color:#ccc;font-size:14px}}
</style></head><body>
<h1>Revisión de duplicados <small style="color:#888;font-weight:400">{datetime.now():%d/%m/%Y %H:%M}</small></h1>
<p style="color:#aaa;font-size:14px;max-width:760px">Verde = se conserva. Rojo = marcado para borrar.
Desmarca la casilla de cualquier foto que <b>no</b> quieras perder. Al final, pulsa el botón y guarda
el archivo en <code>{SCRIPTS}</code>.</p>
{''.join(partes)}
<div class="barra">
  <button onclick="exportar()">Descargar lista de borrado</button>
  <span id="cuenta"></span>
</div>
<script>
const cbs = () => [...document.querySelectorAll('input[type=checkbox]')];
function actualizar(){{
  const n = cbs().filter(c=>c.checked).length;
  document.getElementById('cuenta').textContent = n + ' archivos marcados para borrar';
}}
cbs().forEach(c=>c.addEventListener('change',()=>{{
  c.closest('.card').style.opacity = c.checked ? 1 : .45;
  actualizar();
}}));
function exportar(){{
  const lista = cbs().filter(c=>c.checked).map(c=>c.dataset.ruta);
  const blob = new Blob([JSON.stringify(lista,null,2)],{{type:'application/json'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'duplicados_confirmados.json';
  a.click();
}}
actualizar();
</script></body></html>"""

    SALIDA.mkdir(parents=True, exist_ok=True)
    destino = SALIDA / "revision.html"
    destino.write_text(html, encoding="utf-8")
    print(f"\nListo: {destino}")
    print(f"Premarcados para borrar: {total_borrar}")


if __name__ == "__main__":
    main()