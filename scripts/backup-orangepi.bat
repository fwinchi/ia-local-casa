@echo off
setlocal enabledelayedexpansion

REM === Configura estas cuatro variables con tus propios datos ===
REM IP o nombre de host del destino en tu red local (aqui un Orange Pi, pero vale cualquier NAS/servidor).
set IP=192.168.1.XXX
REM Usuario SSH con permiso de escritura en el destino.
set USUARIO=TU_USUARIO
REM Ruta base en el destino donde se guardaran los siete subdirectorios (paperless, chroma, fotos, videos, documentos, documentos-onedrive, immich-db).
REM El volcado del volumen de Open WebUI no tiene subdirectorio propio:
REM viaja dentro de paperless/export/, porque se genera ahi antes del scp.
set DESTINO_BASE=/home/TU_USUARIO/backup-nasa
REM Usuario de Windows dueno de la carpeta "Documents\Documentos para indexar"
REM (para construir su ruta /mnt/c/Users/... vista desde WSL). Es tu cuenta
REM de Windows, no tiene por que coincidir con USUARIO (el de arriba es el
REM del destino SSH).
set USUARIO_WINDOWS=TU_USUARIO_WINDOWS
REM === Fin de la configuracion ===

set MARCA=D:\paperless\scripts\.ultimo-backup
set HOY=%date%

REM Si ya se hizo hoy, salir
if exist "%MARCA%" (
    set /p ULTIMO=<"%MARCA%"
    if "!ULTIMO!"=="%HOY%" (
        echo [%date% %time%] Backup ya realizado hoy. Nada que hacer.
        exit /b 0
    )
)

echo [%date% %time%] Iniciando backup

REM 1. Exportar Paperless
docker exec paperless-webserver-1 document_exporter ../export -d
if errorlevel 1 (
    echo ERROR: fallo el export de Paperless
    exit /b 1
)

REM 2. Open WebUI: volcado del volumen Docker (historial de chats,
REM    uploads, vector_db, credenciales de usuarios...) via un
REM    contenedor alpine desechable. --exclude=./cache porque esa
REM    carpeta es solo cache regenerable y pesa ~1 GB (comprobado). El
REM    tar.gz se escribe DENTRO de D:\paperless\export a proposito, y
REM    este paso va ANTES del scp del paso 3 para que quede incluido en
REM    ese mismo scp: si fuera despues, el volcado de hoy no se subiria
REM    hasta manana.
docker run --rm -v open-webui:/data -v D:\paperless\export:/backup alpine sh -c "tar czf /backup/openwebui-volume.tar.gz --exclude=./cache -C /data ."
if errorlevel 1 (
    echo ERROR: fallo el volcado del volumen de Open WebUI
    exit /b 1
)

REM 3. Copiar Paperless (+ el volcado de Open WebUI de arriba) al destino
REM    (volcado completo, no incremental)
scp -r -q "D:\paperless\export" %USUARIO%@%IP%:%DESTINO_BASE%/paperless/
if errorlevel 1 (
    echo ERROR: fallo el scp de Paperless
    exit /b 1
)

REM 4. ChromaDB: espejo exacto con --delete. Es un indice reconstruible,
REM    interesa que el destino refleje exactamente lo que hay hoy.
wsl rsync -a --delete /mnt/d/paperless/chroma/ %USUARIO%@%IP%:%DESTINO_BASE%/chroma/
if errorlevel 1 (
    echo ERROR: fallo el rsync de ChromaDB
    exit /b 1
)

REM 5. Fotos: SIN --delete a proposito. Si el disco externo falla o se
REM    desmonta mal, --delete borraria la copia buena del destino.
REM    Aqui se prefiere acumular a arriesgar.
wsl rsync -a /mnt/f/FOTOS/ %USUARIO%@%IP%:%DESTINO_BASE%/fotos/
if errorlevel 1 (
    echo ERROR: fallo el rsync de fotos
    exit /b 1
)

REM 6. Videos: mismo criterio que fotos, sin --delete.
wsl rsync -a /mnt/f/VIDEOS/ %USUARIO%@%IP%:%DESTINO_BASE%/videos/
if errorlevel 1 (
    echo ERROR: fallo el rsync de videos
    exit /b 1
)

REM 7. Documentos a indexar: mismo criterio que fotos y videos, sin
REM    --delete. La ruta tiene un espacio ("Documentos para indexar"), y
REM    wsl reconstruye la linea de comandos como texto antes de pasarla a
REM    Linux, asi que las comillas dobles del .bat no sobreviven solas:
REM    hace falta meterlo todo en "bash -c" con comillas simples dentro,
REM    para que sea bash quien parsee la ruta como un unico argumento.
wsl bash -c "rsync -a '/mnt/c/Users/%USUARIO_WINDOWS%/Documents/Documentos para indexar/' '%USUARIO%@%IP%:%DESTINO_BASE%/documentos/'"
if errorlevel 1 (
    echo ERROR: fallo el rsync de documentos
    exit /b 1
)

REM 8. Documentos a indexar, segunda carpeta de CARPETAS_PDFS (config_rutas.py):
REM    OneDrive\Documentos\Documentos para indexar. Antes no se respaldaba
REM    (README: "solo se respalda una de las dos carpetas, a proposito", con
REM    el razonamiento de que OneDrive ya la sincroniza a la nube de
REM    Microsoft) - corregido porque esa cobertura no es equivalente a un
REM    backup propio: un fallo o borrado accidental en OneDrive se replica
REM    igual a la nube. Mismo motivo de "bash -c" que el paso 7 (ruta con
REM    espacios). Destino separado (documentos-onedrive/, no documentos/):
REM    ambos rsync van sin --delete, y si compartieran carpeta de destino no
REM    se podria distinguir al restaurar que archivo vino de cual de las dos
REM    carpetas de origen.
wsl bash -c "rsync -a '/mnt/c/Users/%USUARIO_WINDOWS%/OneDrive/Documentos/Documentos para indexar/' '%USUARIO%@%IP%:%DESTINO_BASE%/documentos-onedrive/'"
if errorlevel 1 (
    echo ERROR: fallo el rsync de documentos de OneDrive
    exit /b 1
)

REM 9. Base de datos de Immich: pg_dump dentro de su propio contenedor
REM    Postgres (immich_postgres), igual que el export de Paperless usa
REM    su propio contenedor. -Fc (formato personalizado) en vez de SQL
REM    plano: se restaura con pg_restore, no con psql. Las extensiones de
REM    vectores (vchord, vector/pgvector) no necesitan nada especial: se
REM    ha comprobado con pg_restore -l que el volcado registra sus
REM    CREATE EXTENSION como cualquier otra. La contrasena no hace falta
REM    aqui: docker exec entra como root dentro del contenedor, que
REM    autentica en local por socket sin pedirla.
docker exec immich_postgres pg_dump -U postgres -d immich -Fc -f /tmp/immich-db.dump
if errorlevel 1 (
    echo ERROR: fallo el pg_dump de Immich
    exit /b 1
)
docker cp immich_postgres:/tmp/immich-db.dump "%TEMP%\immich-db.dump"
if errorlevel 1 (
    echo ERROR: fallo el docker cp del dump de Immich
    exit /b 1
)
REM Limpieza dentro del contenedor: no crítica, no bloquea el backup si falla.
docker exec immich_postgres rm -f /tmp/immich-db.dump
scp -q "%TEMP%\immich-db.dump" %USUARIO%@%IP%:%DESTINO_BASE%/immich-db/
if errorlevel 1 (
    echo ERROR: fallo el scp del dump de Immich
    exit /b 1
)

REM 10. Marcar como hecho hoy - solo si los nueve pasos anteriores salieron bien
>"%MARCA%" echo %HOY%
echo [%date% %time%] Backup completado

endlocal
