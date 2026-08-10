# Restauración de backups — procedimientos verificados

> Documento interno de metodología. Complementa la sección «Restauración probada: Paperless»
> del README: un backup sin restauración probada no es un backup en el que puedas confiar.
> [`scripts/backup-orangepi.bat`](../scripts/backup-orangepi.bat) respalda siete bloques;
> este documento recoge, uno por uno, el procedimiento real seguido para probar cada
> restauración. Una sección solo se rellena cuando la restauración se ha probado de verdad
> contra una copia aislada — no basta con que el backup se ejecute sin error.

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

*(pendiente de probar)*

## 3. Vídeos

*(pendiente de probar)*

## 4. Documentos

*(pendiente de probar)*

## 5. Base de datos de Immich

*(pendiente de probar)*

## 6. Open WebUI

*(pendiente de probar)*
