<#
.SYNOPSIS
    Informe semanal de organizar_fotos.py (modo simulacion).

.DESCRIPTION
    1. Ejecuta organizar_fotos.py SIN --aplicar (solo simula, no mueve nada).
    2. Lee el informe que genera (organizacion_fotos.txt).
    3. Extrae SOLO la fecha de cabecera, la cifra de "Ya en su sitio" / "A mover"
       y las 3 carpetas destino con mas ficheros del resumen. La seccion
       ### MOVIMIENTOS (rutas y nombres de archivo reales) nunca se lee.
    4. Si hay algo que mover, muestra un toast nativo de Windows
       (Windows.UI.Notifications via WinRT, sin el modulo BurntToast) con
       ese resumen.
    5. Si "A mover" es 0, no lanza ningun toast.
    6. Registra cada ejecucion en informe_fotos_semanal.log.
#>

$ErrorActionPreference = 'Stop'

$Python  = "$env:USERPROFILE\AppData\Local\Python\bin\python.exe"
$Script  = "D:\paperless\scripts\organizar_fotos.py"
$Informe = "D:\paperless\scripts\organizacion_fotos.txt"
$Log     = "D:\paperless\scripts\informe_fotos_semanal.log"

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
    # y Windows.Data.Xml.Dom directamente, truco estandar en PowerShell 5.1.
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

    # AUMID de Windows PowerShell: permite mostrar el toast sin registrar
    # una app propia ni un acceso directo en el menu Inicio.
    $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
}

try {
    Escribir-Log "Iniciando organizar_fotos.py (sin --aplicar)"

    # 1. Modo simulacion. Nunca se pasa --aplicar: este informe es de solo
    #    lectura, no debe mover ni un archivo.
    $salida = & $Python $Script 2>&1
    $codigoSalida = $LASTEXITCODE

    if ($codigoSalida -ne 0) {
        Escribir-Log "ERROR: organizar_fotos.py termino con codigo $codigoSalida. Salida: $($salida -join ' | ')"
        exit 1
    }

    # 2. Leer el informe recien generado
    if (-not (Test-Path $Informe)) {
        Escribir-Log "ERROR: no se encontro $Informe tras ejecutar el script"
        exit 1
    }
    $texto = Get-Content -Path $Informe -Encoding UTF8

    # 3. Extraer solo lo permitido, cortando la lectura en cuanto aparece
    #    ### MOVIMIENTOS para no procesar esa seccion en ningun caso.
    $fecha = $texto[0] -replace '^ORGANIZACION DE FOTOS - ', ''

    $N = $null
    $M = $null
    foreach ($linea in $texto) {
        if ($linea -match '^Ya en su sitio:\s*(\d+)') { $N = [int]$Matches[1] }
        if ($linea -match '^A mover:\s*(\d+)')        { $M = [int]$Matches[1] }
        if ($linea -eq '### MOVIMIENTOS') { break }
    }

    if ($null -eq $N -or $null -eq $M) {
        Escribir-Log "ERROR: no se pudo extraer 'Ya en su sitio' / 'A mover' del informe"
        exit 1
    }

    $lineaInicio = ($texto | Select-String -Pattern '^### CARPETAS RESULTANTES$').LineNumber
    $lineaFin    = ($texto | Select-String -Pattern '^### MOVIMIENTOS$').LineNumber

    $carpetas = @()
    if ($lineaInicio -and $lineaFin -and $lineaFin -gt $lineaInicio) {
        # LineNumber es 1-based; $texto es 0-based, asi que $texto[$lineaInicio]
        # ya es la primera linea DESPUES de la cabecera "### CARPETAS RESULTANTES",
        # y ($lineaFin - 2) es la ultima linea ANTES de "### MOVIMIENTOS".
        foreach ($linea in $texto[$lineaInicio..($lineaFin - 2)]) {
            if ($linea -match '^\s*(.+?)\s+->\s+(\d+)\s+fotos\s*$') {
                $carpetas += [PSCustomObject]@{ Carpeta = $Matches[1]; Cantidad = [int]$Matches[2] }
            }
        }
    }
    $top3 = $carpetas | Sort-Object -Property Cantidad -Descending | Select-Object -First 3

    $resumenTop3 = ($top3 | ForEach-Object { "$($_.Carpeta) ($($_.Cantidad))" }) -join ', '
    Escribir-Log "Resumen: fecha=$fecha | Ya en su sitio=$N | A mover=$M | top carpetas: $resumenTop3"

    # 5. Nada que mover: no molestar con un toast
    if ($M -eq 0) {
        Escribir-Log "A mover = 0, no se lanza toast"
        exit 0
    }

    # 4. Toast nativo con el resumen
    $lineasToast = @(
        "$fecha - Ya en su sitio: $N | A mover: $M",
        "Top carpetas: $resumenTop3"
    )
    Show-ToastNativo -Titulo "Fotos sin ordenar" -Lineas $lineasToast
    Escribir-Log "Toast mostrado"
}
catch {
    Escribir-Log "ERROR: $($_.Exception.Message)"
    exit 1
}
