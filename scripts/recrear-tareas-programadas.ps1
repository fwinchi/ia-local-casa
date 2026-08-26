# recrear-tareas-programadas.ps1
#
# Recreacion desde cero. Las 10 tareas ya estan en RunLevel Limited; este
# script sirve para restaurar tras perdida del Task Scheduler.
#
# Proposito: recrea desde cero las 10 tareas programadas reales del stack
#   (Task Scheduler), todas con RunLevel Limited -- NUNCA Highest. Uso
#   principal: reconstruir el Task Scheduler si se pierde la configuracion
#   (reinstalacion de Windows, migracion a otra maquina, etc.), sin repetir
#   el error historico de crearlas con /rl highest sin necesitarlo (ver
#   seccion 7 del README, "Las tareas programadas reales").
#
# Nota de verificacion (26-08-2026): al generar este script las 10 tareas
# ya estaban en RunLevel Limited (ninguna en Highest) -- Get-ScheduledTask
# lo confirma para las 10. No hacia falta corregir nada ese dia; este
# script no es un parche urgente, es para poder recrearlas igual si algun
# dia hace falta.
#
# Fidelidad: se recrean el trigger, la accion y los argumentos exactos de
# cada tarea (extraidos con `schtasks /Query /TN <tarea> /XML`), mas
# MultipleInstancesPolicy=IgnoreNew (las 10 lo tenian) y las settings
# puntuales que si cambiaban algo (ExecutionTimeLimit sin limite en
# indexar-fotos, StartWhenAvailable en puente-paperless/verificar-backup).
# No se reproducen detalles sin efecto funcional (IdleSettings, el
# StartBoundary exacto al segundo, UseUnifiedSchedulingEngine): esto es
# para reconstruir el Task Scheduler tras un desastre, no un clon binario.
#
# Requisitos:
#   - PowerShell como Administrador.
#   - El usuario indicado debe tener sesion iniciada interactivamente para
#     que las tareas (todas con LogonType Interactive, sin contrasena
#     guardada) se disparen -- por eso no hace falta ninguna credencial en
#     este script.
#
# Uso:
#   .\recrear-tareas-sin-highest.ps1
#   .\recrear-tareas-sin-highest.ps1 -Usuario 'MIDOMINIO\otrousuario' -ScriptsDir 'D:\paperless\scripts'

param(
    # Por defecto, el usuario que ejecuta este script (dominio\usuario o
    # equipo\usuario) -- nunca hardcodeado, para no fijar en el repo el
    # nombre de dominio/usuario real de ninguna maquina concreta.
    [string]$Usuario = "$env:USERDOMAIN\$env:USERNAME",
    [string]$ScriptsDir = 'D:\paperless\scripts'
)

$ErrorActionPreference = 'Stop'

Write-Host "Usuario: $Usuario"
Write-Host "ScriptsDir: $ScriptsDir"
Write-Host ""

$principal = New-ScheduledTaskPrincipal -UserId $Usuario -LogonType Interactive -RunLevel Limited

$settingsBase = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew
$settingsSinLimite = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
$settingsDisponible = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable

function Trigger-ConDelay($base, [string]$delayIso8601) {
    $t = $base
    $t.Delay = $delayIso8601
    return $t
}

function Trigger-Repetido([TimeSpan]$intervalo) {
    New-ScheduledTaskTrigger -Once -At (Get-Date) `
        -RepetitionInterval $intervalo -RepetitionDuration ([TimeSpan]::MaxValue)
}

$Tareas = @(
    @{
        Nombre   = 'autocorresponsal'
        Accion   = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "$ScriptsDir\run-autocorresponsal.vbs"
        Triggers = @(Trigger-Repetido (New-TimeSpan -Minutes 15))
        Settings = $settingsBase
    }
    @{
        Nombre   = 'vigilante-duplicados'
        Accion   = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "$ScriptsDir\run-vigilante.vbs"
        Triggers = @(Trigger-Repetido (New-TimeSpan -Minutes 15))
        Settings = $settingsBase
    }
    @{
        Nombre   = 'copiar-gloda'
        Accion   = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "$ScriptsDir\run-copiar-gloda.vbs"
        Triggers = @(Trigger-Repetido (New-TimeSpan -Hours 1))
        Settings = $settingsBase
    }
    @{
        Nombre   = 'puente-paperless'
        Accion   = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "`"$ScriptsDir\oculto.vbs`" `"$ScriptsDir\puente-paperless.bat`""
        Triggers = @(Trigger-Repetido (New-TimeSpan -Hours 2))
        Settings = $settingsDisponible
    }
    @{
        Nombre   = 'indexar-documentos'
        Accion   = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "$ScriptsDir\oculto.vbs $ScriptsDir\run-indexar.bat"
        Triggers = @(
            New-ScheduledTaskTrigger -AtLogOn
            Trigger-Repetido (New-TimeSpan -Hours 1)
        )
        Settings = $settingsBase
    }
    @{
        Nombre   = 'organizador-descargas'
        Accion   = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "$ScriptsDir\oculto.vbs $ScriptsDir\run-organizador.bat"
        Triggers = @(New-ScheduledTaskTrigger -AtLogOn)
        Settings = $settingsBase
    }
    @{
        Nombre   = 'indexar-fotos'
        Accion   = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "$ScriptsDir\oculto.vbs $ScriptsDir\indexar-fotos.bat"
        Triggers = @(Trigger-ConDelay (New-ScheduledTaskTrigger -AtLogOn) 'PT3M')
        Settings = $settingsSinLimite
    }
    @{
        Nombre   = 'backup-orangepi'
        Accion   = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "$ScriptsDir\oculto.vbs $ScriptsDir\backup-orangepi.bat"
        Triggers = @(Trigger-ConDelay (New-ScheduledTaskTrigger -AtLogOn) 'PT10M')
        Settings = $settingsBase
    }
    @{
        Nombre   = 'verificar-backup'
        Accion   = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "$ScriptsDir\oculto.vbs $ScriptsDir\start-verificar-backup.bat"
        Triggers = @(New-ScheduledTaskTrigger -Daily -At '21:30')
        Settings = $settingsDisponible
    }
    @{
        Nombre   = 'informe-fotos-semanal'
        Accion   = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "`"$ScriptsDir\oculto.vbs`" `"$ScriptsDir\start-informe-fotos.bat`""
        Triggers = @(New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '22:00')
        Settings = $settingsBase
    }
)

foreach ($t in $Tareas) {
    Write-Host "Registrando tarea '$($t.Nombre)'..."
    Register-ScheduledTask -TaskName $t.Nombre -Action $t.Accion -Trigger $t.Triggers `
        -Principal $principal -Settings $t.Settings -Force | Out-Null
}

Write-Host ""
Write-Host "=== Resumen: RunLevel debe ser Limited en las 10 ==="
Get-ScheduledTask -TaskName ($Tareas | ForEach-Object { $_.Nombre }) |
    Select-Object TaskName,
        @{n = 'RunLevel'; e = { $_.Principal.RunLevel } },
        @{n = 'Usuario'; e = { $_.Principal.UserId } },
        State |
    Format-Table -AutoSize
