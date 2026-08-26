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

## GHSA-36p7-vc44-83pf — ChromaDB, code injection vulnerability

**Estado:** revisada el 26-08-2026. No explotable — PersistentClient embebido, sin
servidor HTTP, sin auth multi-tenant, embeddings precalculados.

- **Paquete:** `chromadb`, fijado en [`requirements.txt`](../requirements.txt) en
  `1.5.9` — dentro del rango vulnerable (`>= 0.4.17, <= 1.5.9`).
- **Parche:** ninguno publicado todavía (`first_patched_version` vacío en el advisory).
- **Severidad:** crítica.

Mismo vector de fondo que GHSA-f4j7-r4q5-qw2c (arriba): código de inyección en el SDK
cliente que solo se dispara si Chroma calcula el embedding él mismo. La mitigación es la
misma — todos los scripts pasan siempre el embedding ya calculado por Ollama, nunca
`documents=`/`query_texts=` sin `embeddings=`/`query_embeddings=` — ver el aviso en
[`scripts/config_rutas.py:37-47`](../scripts/config_rutas.py) y el desglose de llamadas
revisadas en la entrada de arriba.

## GHSA-2wm9-hf6c-p5cr — ChromaDB allows any authenticated users to arbitrarily read, write, update, or delete data in any tenant's collection

**Estado:** revisada el 26-08-2026. No explotable — PersistentClient embebido, sin
servidor HTTP, sin auth multi-tenant, embeddings precalculados.

- **Paquete:** `chromadb`, fijado en [`requirements.txt`](../requirements.txt) en
  `1.5.9` — dentro del rango vulnerable (`>= 0.4.17, <= 1.5.9`).
- **Parche:** ninguno publicado todavía (`first_patched_version` vacío en el advisory).
- **Severidad:** alta.

El vector requiere un servidor Chroma multi-tenant con autenticación habilitada, donde un
usuario autenticado en un tenant pueda leer/escribir la colección de otro. Se revisó cada
script del repo que abre Chroma (`indexar_documentos.py`, `indexar_fotos.py`,
`indexar_videos.py`, `mcp_documentos.py`, `mcp_fotos.py`, `buscar.py`, `salud.py`): todos
usan `chromadb.PersistentClient(path=...)`, embebido en el propio proceso — sin servidor,
sin tenants ni usuarios que autenticar. No hay superficie de ataque para este vector.

## GHSA-xph7-9rjv-w5fr — ChromaDB's SimpleRBACAuthorizationProvider doesn't check which tenant, database, or collection a permission applies to

**Estado:** revisada el 26-08-2026. No explotable — PersistentClient embebido, sin
servidor HTTP, sin auth multi-tenant, embeddings precalculados.

- **Paquete:** `chromadb`, fijado en [`requirements.txt`](../requirements.txt) en
  `1.5.9` — dentro del rango vulnerable (`>= 0.5.0, <= 1.5.9`).
- **Parche:** ninguno publicado todavía (`first_patched_version` vacío en el advisory).
- **Severidad:** alta.

El vector está en `SimpleRBACAuthorizationProvider`, un proveedor de autorización que solo
existe en modo servidor con RBAC configurado. Este repo no instancia
`SimpleRBACAuthorizationProvider` ni ningún servidor Chroma — cada script abre su propio
`PersistentClient` local, sin capa de autorización que explotar.
