# Vulnerabilidades conocidas en dependencias

> Registro de CVEs detectadas por Dependabot en dependencias del repo, con el análisis de
> si son explotables dado cómo se usa realmente la librería aquí — no basta con mirar el
> rango de versión afectado, GitHub marca la alerta por versión instalada sin conocer el
> patrón de uso del código.

## GHSA-f4j7-r4q5-qw2c — ChromaDB, RCE por inyección de código (CVE-2026-45829)

**Estado:** revisada el 20-08-2026. No explotable con el uso actual del repo.

- **Paquete:** `chromadb`, fijado en [`requirements.txt`](../requirements.txt) en
  `1.5.9` — el último release del rango vulnerable (`>= 1.0.0, <= 1.5.9`).
- **Parche:** ninguno publicado todavía (`first_patched_version` vacío en el advisory).
  Dependabot seguirá marcando la alerta hasta que Chroma publique una versión corregida.
- **Severidad:** crítica (CVSS 9.3), pero el vector de ataque real depende de cómo se
  invoque la librería — ver desglose abajo.

### Qué es vulnerable en realidad

El advisory agrupa dos vulnerabilidades distintas (detalle técnico en
[chroma-core/chroma#6717](https://github.com/chroma-core/chroma/issues/6717)):

1. **RCE del servidor** (la que describe el resumen del advisory: endpoint HTTP
   `/api/v2/tenants/{tenant}/databases/{db}/collections`, `trust_remote_code` sin
   autenticar). Solo afecta al **servidor Python (FastAPI)** de Chroma — el propio issue
   lo aclara explícitamente: *"Chroma has two server-side implementations: one in Python
   and the other in Rust. By default you will get a Rust Server, and this vulnerability
   only affect the Python Backend"*.

   **Este repo no arranca ningún servidor Chroma** (ni Python ni Rust): todos los scripts
   usan `chromadb.PersistentClient(path=CARPETA_DB)` embebido en el propio proceso, sin
   ningún endpoint HTTP expuesto. **Este vector no aplica aquí.**

2. **RCE del SDK cliente** (código en `chromadb/api/models/CollectionCommon.py`, método
   `_embed()`) — este sí vive en la librería cliente, `PersistentClient` incluido. Se
   dispara cuando una colección tiene una `embedding_function` maliciosa guardada en su
   configuración y el código deja que Chroma calcule el embedding internamente (llamando
   `.add()`/`.query()`/`.get()` con `documents=`/`query_texts=` sin pasar un embedding ya
   calculado).

   Se revisó cada llamada de este tipo en el repo y **todas** pasan el embedding ya
   calculado por Ollama, nunca dejan que Chroma lo calcule:
   - [`scripts/indexar_documentos.py:236`](../scripts/indexar_documentos.py) — `col.add(..., embeddings=embs, ...)`
   - [`scripts/indexar_fotos.py:153`](../scripts/indexar_fotos.py) — `col.upsert(..., embeddings=[vec], ...)`
   - [`scripts/mcp_documentos.py:49`](../scripts/mcp_documentos.py) — `col.query(query_embeddings=[embedding(pregunta)], ...)`
   - [`scripts/mcp_fotos.py:155`](../scripts/mcp_fotos.py) — `col.query(query_embeddings=[embed(consulta)], ...)`
   - [`scripts/buscar.py:28`](../scripts/buscar.py) — `col.query(query_embeddings=[embedding(pregunta)], ...)`

   Con eso, `_embed()` nunca llega a invocarse en el flujo actual del repo, así que
   tampoco se dispara este vector con el código tal como está hoy.

### Vector residual (a vigilar)

El código vulnerable **sí está presente** en la versión instalada. Si en el futuro se
añade una llamada nueva a Chroma usando `documents=` o `query_texts=` **sin** pasar
también `embeddings=`/`query_embeddings=` ya calculados, ese vector se activaría — ver el
aviso en la cabecera de `CARPETA_DB` en
[`scripts/config_rutas.py`](../scripts/config_rutas.py), puesto ahí a propósito para que
salte a la vista al tocar cualquier script que use Chroma.

Revisar esta entrada de nuevo cuando Dependabot deje de marcar la alerta (parche
publicado) o si se añade algún uso nuevo de `.add()`/`.upsert()`/`.query()`/`.get()` sin
embedding explícito.
