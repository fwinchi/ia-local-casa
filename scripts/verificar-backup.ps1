<#
.SYNOPSIS
    Verificacion post-backup contra la Orange Pi. NO restaura nada, solo
    comprueba que lo que hay en el NAS tiene pinta de estar bien.

.DESCRIPTION
    Usa las mismas variables (IP, USUARIO, DESTINO_BASE, USUARIO_WINDOWS) que
    scripts/backup-orangepi.bat, leidas de ese mismo archivo -- no hay ningun
    IP/usuario hardcodeado aqui.

    1. Cuenta ficheros en fotos/, videos/, documentos/ y documentos-onedrive/
       en el NAS y los compara con el conteo de las carpetas de origen locales.
    2. ChromaDB: existencia y tamano de chroma/ en el NAS.
    3. immich-db/immich-db.dump: existe, los 5 primeros bytes son "PGDMP"
       (cabecera de un dump -Fc valido), tamano > 30 MB.
    4. paperless/export/openwebui-volume.tar.gz: existe, tamano > 15 MB.
    5. Frescura: ctime de immich-db.dump (via "find -printf %C+", no mtime --
       rsync preserva el mtime del origen, asi que no sirve para saber cuando
       se escribio en el NAS) debe ser de menos de 48 horas.
    6. Residuos: avisa si existe fotos/FOTOS/ (carpeta anidada de mas, resto
       de un rsync antiguo sin barra final -- ver docs/restauracion-backups.md).

    Salida: log en verificar-backup.log + toast nativo de Windows con el
    resumen (reutiliza el mismo mecanismo WinRT que informe_fotos_semanal.ps1).
    Solo cuenta y compara cifras -- nunca lista ni registra un nombre de
    archivo real.
#>

$ErrorActionPreference = 'Stop'

$RutaBat = Join-Path $PSScriptRoot 'backup-orangepi.bat'
$Log     = "D:\paperless\scripts\verificar-backup.log"

# Discos externos, mismo supuesto que backup-orangepi.bat (fotos/videos en F:).
$FOTOS_LOCAL  = "F:\FOTOS"
$VIDEOS_LOCAL = "F:\VIDEOS"

function Escribir-Log {
    param([string]$Mensaje)
    $linea = "[{0:yyyy-MM-dd HH:mm:ss}] {1}" -f (Get-Date), $Mensaje
    Add-Content -Path $Log -Value $linea -Encoding UTF8
}

function Show-ToastNativo {
    param(
        [string]$Titulo,
        [string[]]$Lineas
    )

    # WinRT sin BurntToast: se cargan los tipos de Windows.UI.Notifications
    # y Windows.Data.Xml.Dom directamente, mismo mecanismo que
    # informe_fotos_semanal.ps1.
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
    [Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null

    $textos = @($Titulo) + $Lineas
    $textosXml = ($textos | ForEach-Object {
        "      <text>$([System.Security.SecurityElement]::Escape($_))</text>"
    }) -join "`n"

    $plantilla = @"
<toast duration="long">
  <visual>
    <binding template="ToastGeneric">
$textosXml
    </binding>
  </visual>
</toast>
"@

    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml($plantilla)
    $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)

    $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
}

function Leer-VariablesBackup {
    param([string]$Ruta)
    if (-not (Test-Path $Ruta)) {
        throw "No se encontro $Ruta"
    }
    $texto = Get-Content -Path $Ruta -Encoding UTF8
    $vars = @{}
    foreach ($linea in $texto) {
        if ($linea -match '^set IP=(.+)$')             { $vars.IP = $Matches[1].Trim() }
        if ($linea -match '^set USUARIO=(.+)$')         { $vars.USUARIO = $Matches[1].Trim() }
        if ($linea -match '^set DESTINO_BASE=(.+)$')    { $vars.DESTINO_BASE = $Matches[1].Trim() }
        if ($linea -match '^set USUARIO_WINDOWS=(.+)$') { $vars.USUARIO_WINDOWS = $Matches[1].Trim() }
    }
    foreach ($clave in @('IP', 'USUARIO', 'DESTINO_BASE', 'USUARIO_WINDOWS')) {
        if (-not $vars.ContainsKey($clave)) {
            throw "No se encontro 'set $clave=' en $Ruta"
        }
    }
    return $vars
}

function Invoke-SSH {
    param([string]$Comando)
    # Via WSL (norma del proyecto: SSH/rsync siempre por wsl --, para usar la
    # clave ed25519 de WSL). $Comando ya llega con sus propias comillas simples
    # y sin variables de PowerShell sin resolver -- wsl -- lo pasa tal cual como
    # un unico argumento al ssh de dentro de WSL, sin necesitar un "bash -c"
    # anidado (comprobado: los metacaracteres del comando remoto sobreviven).
    & wsl -- ssh -o BatchMode=yes -o ConnectTimeout=10 "$($script:Vars.USUARIO)@$($script:Vars.IP)" $Comando 2>&1
}

function Contar-Remoto {
    param([string]$RutaRemota)
    $salida = Invoke-SSH "find '$RutaRemota' -type f 2>/dev/null | wc -l"
    if ($LASTEXITCODE -ne 0 -or -not $salida) { return $null }
    return [int]($salida | Select-Object -Last 1)
}

function Contar-Local {
    param([string]$RutaLocal)
    if (-not (Test-Path $RutaLocal)) { return $null }
    return (Get-ChildItem -Path $RutaLocal -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count
}

try {
    Escribir-Log "Iniciando verificacion post-backup"

    $script:Vars = Leer-VariablesBackup -Ruta $RutaBat

    # Placeholders del repo anonimizado (ver scripts/backup-orangepi.bat):
    # si aparecen aqui es que se esta leyendo la copia sanitizada, no la
    # copia viva con los datos reales. Abortar sin intentar conectar --
    # intentarlo solo daria un "no se pudo conectar" enganoso.
    if ($script:Vars.IP -eq '192.168.1.XXX' -or $script:Vars.USUARIO -eq 'TU_USUARIO') {
        $msg = "backup-orangepi.bat es la copia anonimizada del repo (IP/USUARIO son placeholders); ejecuta esto desde D:\paperless\scripts\, con los valores reales."
        Escribir-Log "ERROR: $msg"
        Show-ToastNativo -Titulo "Verificacion de backup" -Lineas @($msg)
        exit 1
    }

    $DB = $script:Vars.DESTINO_BASE

    # Comprobacion de conectividad antes de nada: si esto falla, no tiene
    # sentido seguir intentando el resto de comprobaciones una a una.
    $eco = Invoke-SSH "echo OK"
    if ($LASTEXITCODE -ne 0 -or $eco -notmatch 'OK') {
        Escribir-Log "ERROR: no se pudo conectar por SSH a $($script:Vars.USUARIO)@$($script:Vars.IP)"
        Show-ToastNativo -Titulo "Verificacion de backup" -Lineas @("No se pudo conectar a la Orange Pi ($($script:Vars.IP))")
        exit 1
    }

    $problemas = @()
    $lineasLog = @()

    # 1. Conteo de ficheros: fotos, videos, documentos, documentos-onedrive
    $bloquesArchivos = @(
        @{ Nombre = 'Fotos';                Local = $FOTOS_LOCAL; Remoto = "$DB/fotos" }
        @{ Nombre = 'Videos';                Local = $VIDEOS_LOCAL; Remoto = "$DB/videos" }
        @{ Nombre = 'Documentos';            Local = "C:\Users\$($script:Vars.USUARIO_WINDOWS)\Documents\Documentos para indexar"; Remoto = "$DB/documentos" }
        @{ Nombre = 'Documentos OneDrive';   Local = "C:\Users\$($script:Vars.USUARIO_WINDOWS)\OneDrive\Documentos\Documentos para indexar"; Remoto = "$DB/documentos-onedrive" }
    )
    foreach ($bloque in $bloquesArchivos) {
        $nLocal  = Contar-Local  -RutaLocal  $bloque.Local
        $nRemoto = Contar-Remoto -RutaRemota $bloque.Remoto
        if ($null -eq $nLocal -or $null -eq $nRemoto) {
            $problemas += "$($bloque.Nombre): no se pudo contar (origen o destino no accesible)"
            $lineasLog += "$($bloque.Nombre): local=$nLocal remoto=$nRemoto (INCOMPLETO)"
        }
        elseif ($nLocal -ne $nRemoto) {
            $problemas += "$($bloque.Nombre): $nRemoto en NAS vs $nLocal en origen"
            $lineasLog += "$($bloque.Nombre): local=$nLocal remoto=$nRemoto (DIFERENTE)"
        }
        else {
            $lineasLog += "$($bloque.Nombre): $nRemoto/$nRemoto OK"
        }
    }

    # 2. ChromaDB: existencia y tamano
    $existeChroma = Invoke-SSH "test -d '$DB/chroma' && echo SI || echo NO"
    if ($existeChroma -match 'SI') {
        $tamanoChroma = (Invoke-SSH "du -sh '$DB/chroma' 2>/dev/null | cut -f1" | Select-Object -Last 1)
        $lineasLog += "ChromaDB: existe, tamano $tamanoChroma"
    }
    else {
        $problemas += "ChromaDB: no existe $DB/chroma en el NAS"
        $lineasLog += "ChromaDB: NO EXISTE"
    }

    # 3. immich-db.dump: existe, cabecera PGDMP, tamano > 30 MB
    $rutaDump = "$DB/immich-db/immich-db.dump"
    $existeDump = Invoke-SSH "test -f '$rutaDump' && echo SI || echo NO"
    if ($existeDump -match 'SI') {
        $cabecera = (Invoke-SSH "head -c 5 '$rutaDump'" | Select-Object -Last 1)
        $tamanoDumpBytes = [int64](Invoke-SSH "stat -c%s '$rutaDump' 2>/dev/null" | Select-Object -Last 1)
        if ($cabecera -ne 'PGDMP') {
            $problemas += "immich-db.dump: cabecera '$cabecera' distinta de PGDMP -- dump posiblemente corrupto"
        }
        if ($tamanoDumpBytes -lt (30 * 1MB)) {
            $problemas += "immich-db.dump: {0:N1} MB, menor de 30 MB esperados" -f ($tamanoDumpBytes / 1MB)
        }
        $lineasLog += "immich-db.dump: cabecera=$cabecera tamano={0:N1} MB" -f ($tamanoDumpBytes / 1MB)
    }
    else {
        $problemas += "immich-db.dump: no existe en el NAS"
        $lineasLog += "immich-db.dump: NO EXISTE"
    }

    # 4. openwebui-volume.tar.gz: existe, tamano > 15 MB
    $rutaOpenWebUI = "$DB/paperless/export/openwebui-volume.tar.gz"
    $existeOpenWebUI = Invoke-SSH "test -f '$rutaOpenWebUI' && echo SI || echo NO"
    if ($existeOpenWebUI -match 'SI') {
        $tamanoOpenWebUIBytes = [int64](Invoke-SSH "stat -c%s '$rutaOpenWebUI' 2>/dev/null" | Select-Object -Last 1)
        if ($tamanoOpenWebUIBytes -lt (15 * 1MB)) {
            $problemas += "openwebui-volume.tar.gz: {0:N1} MB, menor de 15 MB esperados" -f ($tamanoOpenWebUIBytes / 1MB)
        }
        $lineasLog += "openwebui-volume.tar.gz: tamano={0:N1} MB" -f ($tamanoOpenWebUIBytes / 1MB)
    }
    else {
        $problemas += "openwebui-volume.tar.gz: no existe en el NAS"
        $lineasLog += "openwebui-volume.tar.gz: NO EXISTE"
    }

    # 5. Frescura: ctime de immich-db.dump (no mtime, rsync/scp lo preserva del origen)
    if ($existeDump -match 'SI') {
        $ctimeTexto = (Invoke-SSH "find '$rutaDump' -printf '%C+' 2>/dev/null" | Select-Object -Last 1)
        $horasDesde = $null
        if ($ctimeTexto -match '^\d{4}-\d{2}-\d{2}\+\d{2}:\d{2}:\d{2}') {
            $ctimeLimpio = $ctimeTexto -replace '\.\d+$', ''
            try {
                $ctimeFecha = [datetime]::ParseExact($ctimeLimpio, 'yyyy-MM-dd+HH:mm:ss', $null)
                $horasDesde = ((Get-Date) - $ctimeFecha).TotalHours
            }
            catch {
                $lineasLog += "Frescura: no se pudo interpretar la fecha '$ctimeTexto'"
            }
        }
        if ($null -eq $horasDesde) {
            $problemas += "Frescura: no se pudo determinar el ctime de immich-db.dump"
        }
        elseif ($horasDesde -gt 48) {
            $problemas += "Frescura: ultimo backup hace {0:N0} horas (> 48h)" -f $horasDesde
            $lineasLog += "Frescura: {0:N0} horas desde el ultimo backup (> 48h)" -f $horasDesde
        }
        else {
            $lineasLog += "Frescura: {0:N0} horas desde el ultimo backup, OK" -f $horasDesde
        }
    }

    # 6. Residuos: fotos/FOTOS/ (ver docs/restauracion-backups.md, bloque 2)
    $existeResiduo = Invoke-SSH "test -d '$DB/fotos/FOTOS' && echo SI || echo NO"
    if ($existeResiduo -match 'SI') {
        $problemas += "Residuo: existe $DB/fotos/FOTOS (carpeta anidada de un rsync antiguo sin barra final)"
        $lineasLog += "Residuo fotos/FOTOS/: SI, revisar"
    }
    else {
        $lineasLog += "Residuo fotos/FOTOS/: no existe, OK"
    }

    # Log completo de esta ejecucion
    foreach ($linea in $lineasLog) { Escribir-Log $linea }

    # Toast con el resumen -- solo cifras y estado, ningun nombre de archivo
    if ($problemas.Count -eq 0) {
        Escribir-Log "Verificacion OK: sin problemas detectados"
        Show-ToastNativo -Titulo "Backup verificado: OK" -Lineas @(
            "Los 6 bloques cuentan bien y el backup esta al dia.",
            "Sin residuos detectados."
        )
    }
    else {
        Escribir-Log "Verificacion con $($problemas.Count) problema(s): $($problemas -join ' | ')"
        $resumenProblemas = ($problemas | Select-Object -First 3) -join ' · '
        Show-ToastNativo -Titulo "Backup: revisar $($problemas.Count) problema(s)" -Lineas @(
            $resumenProblemas
        )
    }
}
catch {
    Escribir-Log "ERROR: $($_.Exception.Message)"
    try {
        Show-ToastNativo -Titulo "Verificacion de backup" -Lineas @("Fallo al verificar: $($_.Exception.Message)")
    }
    catch {}
    exit 1
}
