@echo off
setlocal enabledelayedexpansion

REM === Configura estas cuatro variables con tus propios datos ===
REM IP o nombre de host del destino en tu red local (aqui un Orange Pi, pero vale cualquier NAS/servidor).
set IP=192.168.1.XXX
REM Usuario SSH con permiso de escritura en el destino.
set USUARIO=TU_USUARIO
REM Ruta base en el destino donde se guardaran los cinco subdirectorios (paperless, chroma, fotos, videos, documentos).
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

REM 2. Copiar Paperless al destino (volcado completo, no incremental)
scp -r -q "D:\paperless\export" %USUARIO%@%IP%:%DESTINO_BASE%/paperless/
if errorlevel 1 (
    echo ERROR: fallo el scp de Paperless
    exit /b 1
)

REM 3. ChromaDB: espejo exacto con --delete. Es un indice reconstruible,
REM    interesa que el destino refleje exactamente lo que hay hoy.
wsl rsync -a --delete /mnt/d/paperless/chroma/ %USUARIO%@%IP%:%DESTINO_BASE%/chroma/
if errorlevel 1 (
    echo ERROR: fallo el rsync de ChromaDB
    exit /b 1
)

REM 4. Fotos: SIN --delete a proposito. Si el disco externo falla o se
REM    desmonta mal, --delete borraria la copia buena del destino.
REM    Aqui se prefiere acumular a arriesgar.
wsl rsync -a /mnt/f/FOTOS/ %USUARIO%@%IP%:%DESTINO_BASE%/fotos/
if errorlevel 1 (
    echo ERROR: fallo el rsync de fotos
    exit /b 1
)

REM 5. Videos: mismo criterio que fotos, sin --delete.
wsl rsync -a /mnt/f/VIDEOS/ %USUARIO%@%IP%:%DESTINO_BASE%/videos/
if errorlevel 1 (
    echo ERROR: fallo el rsync de videos
    exit /b 1
)

REM 6. Documentos a indexar: mismo criterio que fotos y videos, sin
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

REM 7. Marcar como hecho hoy - solo si los seis pasos anteriores salieron bien
>"%MARCA%" echo %HOY%
echo [%date% %time%] Backup completado

endlocal
