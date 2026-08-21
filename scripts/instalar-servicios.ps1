# instalar-servicios.ps1
#
# Proposito: recrea los 4 servicios de Windows (via NSSM) del stack MCP
#   (mcp-paperless, mcp-documentos, mcp-fotos, mcp-correo), eliminando
#   antes cualquier servicio existente con el mismo nombre.
#
# Requisitos:
#   - Debe ejecutarse en una consola de PowerShell con permisos de
#     Administrador (los servicios de Windows no se pueden instalar,
#     eliminar ni iniciar sin ese privilegio).
#   - NSSM (Non-Sucking Service Manager) debe estar instalado y su
#     nssm.exe accesible en el PATH. Para instalarlo:
#       winget install NSSM.NSSM
#
# Nota de seguridad: este script no contiene credenciales ni tokens.
# Los .bat de cada servicio cargan sus propios secretos desde
# secrets.local.bat en tiempo de ejecucion.

# Directorio donde viven los .bat de arranque de cada servicio.
# Editar esta ruta si el stack se instala en otra ubicacion.
$ScriptsDir = 'D:\paperless\scripts'

# Comprobar que nssm.exe esta disponible en el PATH
if (-not (Get-Command nssm.exe -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: no se encontro nssm.exe en el PATH." -ForegroundColor Red
    Write-Host "Instalalo con: winget install NSSM.NSSM" -ForegroundColor Red
    exit 1
}

# Definicion de los 4 servicios del stack MCP
$Servicios = @(
    @{ Nombre = 'mcp-paperless';  Bat = 'start-mcpo.bat';            Puerto = 8001 }
    @{ Nombre = 'mcp-documentos'; Bat = 'start-mcp-documentos.bat';  Puerto = 8002 }
    @{ Nombre = 'mcp-fotos';      Bat = 'start-mcp-fotos.bat';       Puerto = 8003 }
    @{ Nombre = 'mcp-correo';     Bat = 'start-mcp-correo.bat';      Puerto = 8005 }
)

foreach ($Servicio in $Servicios) {
    $Nombre = $Servicio.Nombre
    $Bat = $Servicio.Bat
    $Puerto = $Servicio.Puerto

    Write-Host ""
    Write-Host "=== Procesando servicio '$Nombre' (puerto $Puerto) ===" -ForegroundColor Cyan

    # 1. Si ya existe, detener y eliminar
    $ServicioExistente = Get-Service -Name $Nombre -ErrorAction SilentlyContinue
    if ($ServicioExistente) {
        Write-Host "El servicio '$Nombre' ya existe. Deteniendolo y eliminandolo..."
        nssm stop $Nombre
        nssm remove $Nombre confirm
    }
    else {
        Write-Host "El servicio '$Nombre' no existe todavia. Se creara desde cero."
    }

    # 2. Instalar el servicio apuntando al .bat correspondiente
    Write-Host "Instalando servicio '$Nombre' -> $Bat ..."
    nssm install $Nombre "$ScriptsDir\$Bat"

    # 3. Directorio de trabajo
    nssm set $Nombre AppDirectory "$ScriptsDir"

    # 4-5. Logs de salida estandar y de error
    nssm set $Nombre AppStdout "$ScriptsDir\nssm-$Nombre.log"
    nssm set $Nombre AppStderr "$ScriptsDir\nssm-$Nombre.log"

    # 6. Arranque automatico
    nssm set $Nombre Start SERVICE_AUTO_START

    # 7. Arrancar el servicio
    Write-Host "Arrancando servicio '$Nombre'..."
    nssm start $Nombre
}

# Resumen final del estado de los 4 servicios
Write-Host ""
Write-Host "=== Resumen de servicios instalados ===" -ForegroundColor Cyan
Get-Service -Name ($Servicios | ForEach-Object { $_.Nombre }) | Select-Object Name, Status
