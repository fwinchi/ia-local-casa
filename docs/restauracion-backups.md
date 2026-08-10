# Restauración de backups — procedimientos verificados

> Documento interno de metodología. Complementa la sección «Restauración probada: Paperless»
> del README: un backup sin restauración probada no es un backup en el que puedas confiar.
> [`scripts/backup-orangepi.bat`](../scripts/backup-orangepi.bat) respalda ocho bloques;
> este documento recoge, uno por uno, el procedimiento real seguido para probar cada
> restauración. Una sección solo se rellena cuando la restauración se ha probado de verdad
> contra una copia aislada — no basta con que el backup se ejecute sin error.

> **Aviso operativo:** `scripts/backup-orangepi.bat` en el repo lleva los cuatro `set` de
> configuración con placeholders (`IP=192.168.1.XXX`, `USUARIO=TU_USUARIO`,
> `DESTINO_BASE=/home/TU_USUARIO/backup-nasa`, `USUARIO_WINDOWS=TU_USUARIO_WINDOWS`), a
> propósito, para poder publicarlo. Cada vez que sincronices una actualización del repo
> sobre la copia viva (`D:\paperless\scripts\backup-orangepi.bat`), esos cuatro valores
> vuelven a quedar en placeholder y hay que restaurarlos a mano con tus datos reales — si
> no, el backup falla en el primer `scp` con `scp: Connection closed`, porque intenta
> conectar contra un host que no existe (`TU_USUARIO@192.168.1.XXX`). Pasó de verdad el
> 10-08-2026 al traer el cambio de `documentos-onedrive/`.

## 1. ChromaDB (índice de documentos, fotos y vídeos)

**Estado:** verificado el 10-08-2026.

1. **Origen del backup**: `%USUARIO%@%IP%:%DESTINO_BASE%/chroma/` — las mismas variables
   que configuras en `backup-orangepi.bat`. Ojo: el subdirectorio correcto es `chroma`
   directamente bajo `%DESTINO_BASE%` (por ejemplo `~/backup-nasa/chroma/`), **no**
   `~/backups/chroma` — esa ruta no existe, es fácil confundirla si trabajas de memoria.
2. **Copia a una carpeta aislada**: `wsl rsync -a` del origen anterior a una carpeta
   aparte en el propio NAS, sin tocar en ningún momento el ChromaDB real
   (`D:\paperless\chroma`).
3. **Levantar un contenedor de prueba**, sin tocar el real:
   ```
   docker run -d --name chroma-restore-test -p 8100:8000 -v <ruta>:/data chromadb/chroma
   ```
   donde `<ruta>` es la carpeta aislada del paso 2.

   **IMPORTANTE**: la imagen de ChromaDB persiste sus datos en `/data`, **no** en
   `/chroma/chroma`. Montar el volumen en `/chroma/chroma` arranca el contenedor con la
   base vacía — `collections` devuelve `[]` aunque la copia esté perfectamente bien.
4. **Verificar** que las colecciones llegan:
   ```
   GET http://localhost:8100/api/v2/tenants/default_tenant/databases/default_database/collections
   ```
5. **Contar en producción para comparar**, sin pasar por ningún contenedor: consulta
   directa sobre `D:\paperless\chroma\chroma.sqlite3` (no vía `PersistentClient`, sino
   SQL directo), cruzando `collections` / `segments` / `embeddings` para sacar el conteo
   real por colección.
6. **Limpiar**: parar y borrar el contenedor de prueba (`docker rm -f
   chroma-restore-test`) y borrar la carpeta aislada del NAS usada en el paso 2.

**Resultado real de esta prueba (10-08-2026):** documentos 545, fotos 2853, vídeos 73 —
coincidencia exacta entre el backup restaurado y la base en producción.

**Nota sobre el backup de Open WebUI:** no vive en `%DESTINO_BASE%/openwebui/` — ese
subdirectorio no existe. El volcado (`openwebui-volume.tar.gz`) va dentro de
`%DESTINO_BASE%/paperless/export/`, porque `backup-orangepi.bat` lo genera ahí antes del
`scp` de Paperless (ver el comentario del paso 2 en el script). Si buscas el backup de
Open WebUI, es ahí donde está, no en un subdirectorio propio.

## 2. Fotos

**Estado:** verificado el 10-08-2026.

1. **Origen real**: `F:\FOTOS` — 2997 archivos, 4,7 GB. Backup en NAS:
   `%USUARIO%@%IP%:%DESTINO_BASE%/fotos/` — las mismas variables que configuras en
   `backup-orangepi.bat`.
2. **Verificación por conteo y listado**: contar archivos a ambos lados y comparar los
   listados de rutas relativas con `Compare-Object` — resultado `Count=0`, sin
   diferencias entre origen y backup.
3. **Restauración probada** sobre una subcarpeta concreta (`2023/`, no el árbol
   completo) vía `rsync` a una carpeta temporal aislada, sin tocar el backup real:
   106/106 archivos restaurados correctamente.
4. **Incidencia encontrada y corregida**: había un residuo `fotos/FOTOS/` en el destino
   del NAS — una carpeta anidada de más, resto de un `rsync` antiguo ejecutado sin la
   barra final en el origen. (`rsync origen/ destino/`, con barra, copia el *contenido*
   de `origen`; `rsync origen destino/`, sin barra, copia la carpeta `origen` entera
   dentro de `destino`, añadiendo un nivel de más.) Se identificó y se eliminó del NAS.
5. **Limpiar**: borrar la carpeta temporal usada en el paso 3.

**Resultado real de esta prueba (10-08-2026):** conteo y listado coinciden exactamente
(`Compare-Object` con `Count=0`); restauración de la subcarpeta `2023/` completa, 106/106.

## 3. Vídeos

**Estado:** verificado el 10-08-2026.

1. **Origen real**: `F:\VIDEOS` — 76 archivos, 2,7 GB. Backup en NAS:
   `%USUARIO%@%IP%:%DESTINO_BASE%/videos/`.
2. **Restauración completa** (el volumen es pequeño, no hizo falta limitarla a una
   subcarpeta como en fotos) vía `rsync` a una carpeta temporal aislada.
3. **Verificar** el conteo de archivos restaurados contra el origen.
4. **Limpiar**: borrar la carpeta temporal.

**Resultado real de esta prueba (10-08-2026):** 76/76 archivos restaurados, coincidencia
exacta.

## 4. Documentos

**Estado:** verificado el 10-08-2026 (dos carpetas de origen, cada una en su propio
destino).

1. **Origen real**: las dos carpetas configuradas en `CARPETAS_PDFS`
   (`scripts/config_rutas.py`): `Documents\Documentos para indexar` (6 archivos) y
   `OneDrive\Documentos\Documentos para indexar` (98 archivos) — esta segunda es la que
   no se respaldaba hasta el commit `6696327` («fix: backup de la segunda carpeta
   indexada (OneDrive)»).
2. **Destinos separados a propósito**, no un directorio compartido:
   `%DESTINO_BASE%/documentos/` (carpeta `Documents`) y
   `%DESTINO_BASE%/documentos-onedrive/` (carpeta OneDrive). Motivo: ambos `rsync` van
   sin `--delete` — si compartieran destino, no se podría distinguir al restaurar qué
   archivo vino de cuál de las dos carpetas de origen.
3. **Restauración probada**: `rsync` desde `%DESTINO_BASE%/documentos/` y
   `%DESTINO_BASE%/documentos-onedrive/` a una carpeta temporal aislada, sin tocar el
   backup real. Conteos contra el origen: 6/6 y 98/98.
4. **Limpiar**: borrar la carpeta temporal tras verificar.

**Resultado real de esta prueba (10-08-2026):** 6/6 y 98/98 — coincidencia exacta en las
dos carpetas.

## 5. Base de datos de Immich

**Estado:** verificado el 10-08-2026.

1. **Origen real**: dump de PostgreSQL en formato personalizado (`-Fc`) del contenedor
   `immich_postgres`, 39 MB, en `%DESTINO_BASE%/immich-db/immich-db.dump` (mismas
   variables que `backup-orangepi.bat`).
2. **Verificación de formato**: los 5 primeros bytes del dump deben ser `PGDMP` —
   confirma que es un dump `-Fc` válido antes de intentar restaurarlo con nada.
3. **Copia a una carpeta temporal aislada**: `rsync` del dump desde el NAS, sin tocar el
   original del backup.
4. **Contenedor Postgres de prueba, con la MISMA imagen que el real**: obtenida con
   ```
   docker inspect immich_postgres --format "{{.Config.Image}}"
   ```
   y levantada aparte, en el puerto `5433` (ni `5432`, el real, ni ningún otro en uso).
5. **Crear las extensiones ANTES de `pg_restore`** — si no, la restauración falla en
   cuanto llega a un objeto que las necesita:
   ```sql
   CREATE EXTENSION vector;
   CREATE EXTENSION vchord CASCADE;
   CREATE EXTENSION cube;
   CREATE EXTENSION earthdistance;
   ```
6. **Restaurar**:
   ```
   pg_restore -U postgres -d immich --no-owner --no-privileges
   ```
   `--no-owner --no-privileges` porque el contenedor de prueba no tiene los mismos roles
   que el real — sin esas dos opciones, `pg_restore` falla intentando reasignar
   propietarios y permisos que no existen ahí.
7. **Verificar contando filas** en la copia restaurada contra la base de producción,
   tabla por tabla.
8. **Limpiar**: parar y borrar el contenedor de prueba y la carpeta temporal.

**Resultado real de esta prueba (10-08-2026):** `pg_restore` sin errores. Conteos, copia
restaurada vs. producción: `asset` 3298/3298, `person` 228/228, `person` con nombre
asignado 10/10, `album` 0/0 — coincidencia exacta en las cuatro tablas.

## 6. Open WebUI

**Estado:** verificado el 10-08-2026.

1. **Origen real**: volumen Docker `open-webui` (historial de chats, uploads, vector_db,
   credenciales de usuarios...), comprimido excluyendo `./cache` (modelos de embeddings
   regenerables). Archivo: 21 MB, en
   `%DESTINO_BASE%/paperless/export/openwebui-volume.tar.gz`. **Ojo**: no está en
   `%DESTINO_BASE%/openwebui/` — ese subdirectorio no existe, ver la nota al final del
   bloque 1.
2. **Copia a una carpeta temporal aislada**: `rsync` del `.tar.gz` desde el NAS, sin
   tocar el original del backup.
3. **Verificar que el archivo no está corrupto antes de tocarlo**: `gzip -t` (OK).
4. **Listar el contenido sin extraer**: `tar tzf` — 152 entradas.
5. **Extraer**: 60 MB descomprimidos, incluye `webui.db` (14 MB), sin carpeta `cache`
   (confirma que el `--exclude=./cache` del backup funcionó).
6. **Verificar la integridad de la base SQLite**: `sqlite3 webui.db "PRAGMA
   integrity_check;"` → `ok`.
7. **Contar filas por tabla** en la copia restaurada.
8. **Comparar contra producción**: el volumen vivo se lee sin pararlo, montándolo de
   solo lectura en un contenedor `alpine` con `sqlite3` para consultarlo desde fuera de
   Open WebUI.
9. **Limpiar**: borrar la carpeta temporal usada en el paso 2.

**Resultado real de esta prueba (10-08-2026):** `gzip -t` y `PRAGMA integrity_check`
correctos; conteos, copia restaurada vs. producción: `chat` 151/151, `user` 1/1, `model`
19/19, `prompt` 0/0 — coincidencia exacta en las cuatro tablas.

---

**Los 6 bloques del backup quedan verificados con restauración real el 10-08-2026.**
