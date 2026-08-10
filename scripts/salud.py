# -*- coding: utf-8 -*-
"""Comprueba el estado del stack y genera un informe HTML."""
import locale, os, re, json, socket, subprocess, urllib.request, webbrowser
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

from config_rutas import BASE, CARPETAS_PDFS

SCRIPTS = Path(__file__).resolve().parent
SALIDA = SCRIPTS / "salud.html"

PAPERLESS = "http://localhost:8010"
TOKEN = os.environ.get("PAPERLESS_TOKEN", "")

ETIQUETA_DISCO_EXTERNO = "Multimedia IA"

PUERTOS = {8001: "Paperless MCP", 8002: "Documentos", 8003: "Fotos/Videos"}
CONTENEDORES = ["paperless", "immich", "litellm", "open-webui", "openwebui"]
MODELOS = ["gptoss-paperless", "vl3-paperless", "bge-m3", "nomic-embed-text"]
TAREAS = ["autocorresponsal", "vigilante-duplicados", "indexar-documentos",
          "organizador-descargas", "mcpo-paperless", "mcp-documentos", "mcp-fotos"]
PATRONES_ESPERADOS = ("decrypted", "encrypted", "cifrad", "encriptad", "signature", "firma digital")

# Fecha en español si el sistema tiene ese locale disponible; si no, formato numérico.
FECHA_LOCALE_OK = False
for _loc in ("es_ES.UTF-8", "es_ES", "Spanish_Spain.1252", "Spanish"):
    try:
        locale.setlocale(locale.LC_TIME, _loc)
        FECHA_LOCALE_OK = True
        break
    except locale.Error:
        continue

res = []   # (categoria, titulo, estado, detalle)   estado: ok | warn | error | info


def add(cat, titulo, estado, detalle=""):
    res.append((cat, titulo, estado, detalle))


def cmd(args, timeout=25):
    try:
        p = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 1, str(e)


def http(url, headers=None, timeout=8):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


RUTA_USUARIO_WIN = re.compile(r'([A-Za-z]:\\[Uu]sers\\)[^\\]+')
RUTA_USUARIO_UNIX = re.compile(r'(/home/)[^/]+')


def redactar_ruta_usuario(texto):
    """Sustituye el nombre de usuario en rutas tipo C:\\Users\\<algo>\\ o
    /home/<algo>/ por ***, antes de escribir en el HTML cualquier texto
    que venga de un .log o de un nombre de archivo real. Hoy esas rutas no
    llegan al HTML por casualidad de formato (las lineas "File ..." de un
    traceback no contienen ni "Traceback" ni "ERROR" en mayusculas, que es
    lo que filtra la seccion de Logs) -- esto lo hace explicito en vez de
    depender de esa coincidencia."""
    texto = RUTA_USUARIO_WIN.sub(lambda m: m.group(1) + "***", texto)
    texto = RUTA_USUARIO_UNIX.sub(lambda m: m.group(1) + "***", texto)
    return texto


def letra_disco_externo():
    """Letra del disco 'Multimedia IA' por etiqueta de volumen (puede cambiar
    de una conexión a otra, igual que en duplicados.py/vigilante.py). None si no
    está conectado o no se encuentra."""
    rc, out = cmd(["powershell", "-NoProfile", "-Command",
                   f'(Get-Volume | Where-Object FileSystemLabel -eq "{ETIQUETA_DISCO_EXTERNO}").DriveLetter'])
    letra = out.strip()
    return f"{letra}:\\" if rc == 0 and letra else None


# ---------- 1. Puertos mcpo ----------
for puerto, nombre in PUERTOS.items():
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect(("127.0.0.1", puerto))
        add("Servicios MCP", f"{nombre} (puerto {puerto})", "ok", "Escuchando")
    except Exception:
        add("Servicios MCP", f"{nombre} (puerto {puerto})", "error",
            "No responde. Lanzar su .bat o revisar la tarea programada.")
    finally:
        s.close()

# ---------- 2. Contenedores Docker ----------
rc, out = cmd(["docker", "ps", "--format", "{{.Names}}|{{.Status}}"])
if rc != 0:
    add("Docker", "Docker", "error", "No responde. ¿Docker Desktop arrancado?")
else:
    activos = [l.split("|") for l in out.strip().splitlines() if "|" in l]
    for clave in CONTENEDORES:
        encontrados = [(n, e) for n, e in activos if clave in n.lower()]
        if not encontrados:
            if clave == "openwebui" and any("open-webui" in n.lower() for n, _ in activos):
                continue
            if clave == "open-webui" and any("openwebui" in n.lower() for n, _ in activos):
                continue
            add("Docker", clave, "error", "Contenedor no encontrado en ejecución")
        else:
            for n, e in encontrados:
                estado = "ok"
                if "unhealthy" in e.lower() or "restarting" in e.lower():
                    estado = "error"
                elif "starting" in e.lower():
                    estado = "warn"
                add("Docker", n, estado, e)

# ---------- 3. Ollama y modelos ----------
try:
    datos = json.loads(http("http://localhost:11434/api/tags"))
    nombres = [m["name"] for m in datos.get("models", [])]
    add("Ollama", "Servicio", "ok", f"{len(nombres)} modelos disponibles")
    for m in MODELOS:
        if any(n.split(":")[0] == m or n == m for n in nombres):
            add("Ollama", m, "ok", "Presente")
        else:
            add("Ollama", m, "error", "Modelo no encontrado")
except Exception as e:
    add("Ollama", "Servicio", "error", f"No responde: {e}")

# ---------- 4. LiteLLM ----------
try:
    http("http://localhost:4000/health/liveliness")
    add("LiteLLM", "Servicio", "ok", "Responde en el puerto 4000")
except Exception:
    try:
        http("http://localhost:4000/")
        add("LiteLLM", "Servicio", "ok", "Responde en el puerto 4000")
    except Exception as e:
        add("LiteLLM", "Servicio", "error", f"No responde: {e}")

# ---------- 5. Tareas programadas ----------
rc, out = cmd(["schtasks", "/query", "/fo", "csv", "/v"])
if rc != 0:
    add("Tareas programadas", "Consulta", "error", "No se pudo consultar schtasks")
else:
    lineas = out.splitlines()
    for t in TAREAS:
        fila = next((l for l in lineas if f'"\\{t}"' in l), None)
        if not fila:
            add("Tareas programadas", t, "error", "Tarea no existe")
            continue
        campos = re.findall(r'"([^"]*)"', fila)
        ultimo = campos[5] if len(campos) > 5 else "?"
        resultado = campos[6] if len(campos) > 6 else "?"
        if resultado in ("0", "267009", "267011"):
            add("Tareas programadas", t, "ok", f"Última: {ultimo} · código {resultado}")
        else:
            add("Tareas programadas", t, "warn",
                f"Última: {ultimo} · código {resultado} (revisar)")

# ---------- 6. ChromaDB ----------
try:
    import chromadb
    cli = chromadb.PersistentClient(str(BASE / "chroma"))
    total_idx = 0
    for col in cli.list_collections():
        n = col.count()
        if col.name == "documentos":
            total_idx = n
        add("ChromaDB", f"Colección {col.name}", "ok" if n else "warn", f"{n} fragmentos")
except Exception as e:
    total_idx = 0
    add("ChromaDB", "Base", "error", f"No se pudo abrir: {e}")

# ---------- 7. Desfase de PDFs ----------
try:
    pdfs = 0
    for c in CARPETAS_PDFS:
        if c.exists():
            pdfs += len(list(c.rglob("*.pdf")))
        else:
            add("Índice de PDFs", f"Carpeta {c.name}", "error", f"No existe: {c}")
    add("Índice de PDFs", "PDFs en disco", "info", f"{pdfs} archivos")
    if total_idx == 0 and pdfs:
        add("Índice de PDFs", "Estado del índice", "error", "Hay PDFs pero el índice está vacío")
except Exception as e:
    add("Índice de PDFs", "Recuento", "error", str(e))

# ---------- 8. Último indexado ----------
log = SCRIPTS / "indexar.log"
if log.exists():
    edad = datetime.now() - datetime.fromtimestamp(log.stat().st_mtime)
    est = "ok" if edad < timedelta(days=2) else "warn"
    add("Índice de PDFs", "Último indexado", est,
        datetime.fromtimestamp(log.stat().st_mtime).strftime("%d/%m/%Y %H:%M"))
else:
    add("Índice de PDFs", "Último indexado", "warn", "No hay indexar.log")

# ---------- 9. Errores recientes en logs ----------
for l in SCRIPTS.glob("*.log"):
    try:
        texto = l.read_text(encoding="utf-8", errors="replace")[-20000:]
        lineas_error = [x for x in texto.splitlines()
                         if "Traceback" in x or re.search(r"\bERROR\b", x)]
        # PDFs cifrados/firmados: no cuentan como fallo, pero se informan aparte
        # en vez de descartarse en silencio. El texto exacto del mensaje depende
        # de la versión de pypdf, por eso se comprueban varias variantes.
        esperados = [x for x in lineas_error
                     if any(p in x.lower() for p in PATRONES_ESPERADOS)]
        fallos = [x for x in lineas_error if x not in esperados]

        partes = []
        if fallos:
            ultimo_fallo = redactar_ruta_usuario(fallos[-1][:120])
            partes.append(f"{len(fallos)} línea(s) con error. Última: {ultimo_fallo}")
        if esperados:
            partes.append(f"{len(esperados)} esperado(s) (PDF cifrado/firmado, no cuentan como fallo)")

        if fallos:
            add("Logs", l.name, "warn", " · ".join(partes))
        elif esperados:
            add("Logs", l.name, "ok", " · ".join(partes))
        else:
            add("Logs", l.name, "ok", "Sin errores")
    except Exception as e:
        add("Logs", l.name, "warn", str(e))

# ---------- 10. Carpeta consume atascada ----------
consume = BASE / "consume"
if consume.exists():
    ahora = datetime.now()
    atascados = [f for f in consume.iterdir()
                 if f.is_file() and ahora - datetime.fromtimestamp(f.stat().st_mtime) > timedelta(hours=1)]
    if atascados:
        nombres = ", ".join(redactar_ruta_usuario(f.name) for f in atascados[:5])
        add("Paperless", "Carpeta consume", "error",
            f"{len(atascados)} archivo(s) sin procesar hace más de 1 hora: {nombres}")
    else:
        add("Paperless", "Carpeta consume", "ok", "Vacía o recién llegado")
else:
    add("Paperless", "Carpeta consume", "warn", f"No existe: {consume}")

# ---------- 11. Paperless: pendientes y sin corresponsal ----------
if not TOKEN:
    add("Paperless", "API", "warn",
        "Sin PAPERLESS_TOKEN. Lanza este informe desde salud.bat.")
else:
    cab = {"Authorization": f"Token {TOKEN}"}
    try:
        tags = json.loads(http(f"{PAPERLESS}/api/tags/?page_size=200", cab))
        idp = next((t["id"] for t in tags["results"] if t["name"] == "ai-process"), None)
        if idp:
            d = json.loads(http(f"{PAPERLESS}/api/documents/?tags__id__all={idp}&page_size=1", cab))
            n = d.get("count", 0)
            add("Paperless", "Pendientes de AIssist", "warn" if n > 5 else "ok",
                f"{n} documento(s) con ai-process")
        d = json.loads(http(f"{PAPERLESS}/api/documents/?correspondent__isnull=true&page_size=1", cab))
        n = d.get("count", 0)
        add("Paperless", "Sin corresponsal", "warn" if n else "ok", f"{n} documento(s)")
        d = json.loads(http(f"{PAPERLESS}/api/documents/?page_size=1", cab))
        add("Paperless", "Documentos totales", "info", str(d.get("count", "?")))
    except Exception as e:
        add("Paperless", "API", "error", f"No responde o token inválido: {e}")

# ---------- 12. Discos ----------
disco_externo = letra_disco_externo()
unidades = ["D:\\", "C:\\"]
if disco_externo:
    unidades.append(disco_externo)
else:
    add("Discos", f"Disco externo ({ETIQUETA_DISCO_EXTERNO})", "error",
        "No conectado (no se encuentra ningún volumen con esa etiqueta)")

for unidad in unidades:
    es_externo = unidad == disco_externo
    etiqueta = f"{unidad} — disco externo ({ETIQUETA_DISCO_EXTERNO})" if es_externo else unidad
    try:
        import shutil
        u = shutil.disk_usage(unidad)
        libre = u.free / 1e9
        pct = u.free / u.total * 100
        est = "ok" if libre > 50 else ("warn" if libre > 20 else "error")
        add("Discos", etiqueta, est, f"{libre:.0f} GB libres ({pct:.0f} %)")
    except Exception:
        add("Discos", etiqueta, "error" if es_externo else "warn", "No accesible")

# ---------- 13. Cuarentena de duplicados ----------
cuar = BASE / "cuarentena_duplicados"
if cuar.exists():
    n = len(list(cuar.rglob("*")))
    add("Duplicados", "Cuarentena", "warn" if n > 50 else "ok" if n else "ok",
        f"{n} archivo(s) esperando revisión")
else:
    add("Duplicados", "Cuarentena", "ok", "Sin cuarentena creada")

# ---------- HTML ----------
n_err = sum(1 for r in res if r[2] == "error")
n_warn = sum(1 for r in res if r[2] == "warn")

if n_err:
    cab_txt, cab_cls = f"{n_err} problema(s) que requieren atención", "malo"
elif n_warn:
    cab_txt, cab_cls = f"{n_warn} aviso(s) para revisar", "medio"
else:
    cab_txt, cab_cls = "Todo funciona correctamente", "bien"

ICONO = {"ok": "OK", "warn": "AVISO", "error": "FALLO", "info": "—"}

cats = []
for cat, *_ in res:
    if cat not in cats:
        cats.append(cat)

filas = ""
for cat in cats:
    grupo = [r for r in res if r[0] == cat]
    peor = "error" if any(r[2] == "error" for r in grupo) else (
        "warn" if any(r[2] == "warn" for r in grupo) else "ok")
    filas += f'<h2 class="{peor}">{cat}</h2><table>'
    for _, titulo, estado, detalle in grupo:
        filas += (f'<tr class="{estado}"><td class="et">{ICONO[estado]}</td>'
                  f'<td class="ti">{escape(str(titulo))}</td><td class="de">{escape(str(detalle))}</td></tr>')
    filas += "</table>"

fecha_txt = (datetime.now().strftime('%A %d de %B de %Y, %H:%M') if FECHA_LOCALE_OK
             else datetime.now().strftime('%d/%m/%Y, %H:%M'))

html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<title>Estado del sistema</title><style>
body{{background:#14161a;color:#d6dae0;font-family:Segoe UI,sans-serif;
     margin:0;padding:28px 32px;font-size:15px}}
h1{{margin:0 0 4px;font-size:26px;color:#eaeef4}}
.fecha{{color:#8b94a3;font-size:13px;margin-bottom:20px}}
.resumen{{padding:14px 18px;border-radius:6px;font-size:18px;font-weight:600;margin-bottom:26px}}
.resumen.bien{{background:#16301f;color:#8fe0a6;border-left:5px solid #3fa35f}}
.resumen.medio{{background:#332a14;color:#f0cf8a;border-left:5px solid #d9a441}}
.resumen.malo{{background:#3a1c1a;color:#f3a79a;border-left:5px solid #c4503f}}
h2{{font-size:16px;margin:26px 0 8px;padding-left:10px;border-left:4px solid #5b8dc0;color:#eaeef4}}
h2.warn{{border-left-color:#d9a441}} h2.error{{border-left-color:#c4503f}}
table{{width:100%;border-collapse:collapse;margin-bottom:6px}}
td{{padding:7px 10px;border-bottom:1px solid #23272f;vertical-align:top}}
.et{{width:70px;font-size:11px;font-weight:700;letter-spacing:.5px}}
.ti{{width:280px;color:#eaeef4}}
.de{{color:#9aa3b2;font-size:13.5px}}
tr.ok .et{{color:#5fae76}}
tr.info .et{{color:#6b7280}}
tr.warn{{background:#2a2317}} tr.warn .et{{color:#e2b45c}} tr.warn .de{{color:#e2c88a}}
tr.error{{background:#2e1a18}} tr.error .et{{color:#e08476}} tr.error .de{{color:#f0b3a6}}
tr.error .ti,tr.warn .ti{{font-weight:600}}
</style></head><body>
<h1>Estado del sistema</h1>
<div class="fecha">{fecha_txt}</div>
<div class="resumen {cab_cls}">{cab_txt}</div>
{filas}
</body></html>"""

SALIDA.write_text(html, encoding="utf-8")
print(f"Informe generado: {SALIDA}")
print(f"{n_err} fallo(s), {n_warn} aviso(s)")
try:
    webbrowser.open(SALIDA.as_uri())
except Exception:
    pass
