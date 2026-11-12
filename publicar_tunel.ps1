# Lo llama iniciar_publico.bat. Espera la dirección del túnel en cf.log, la sube a GitHub (tunel.json)
# para que la página de Vercel la lea sola, la copia al portapapeles y abre la tienda.
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot
$vercel = 'https://sistema-de-pedidos-frontend-flame.vercel.app/'

$u = $null
for ($i = 0; $i -lt 60 -and -not $u; $i++) {
    Start-Sleep 1
    if (Test-Path 'cf.log') {
        $m = Select-String -Path 'cf.log' -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1
        if ($m) { $u = $m.Matches[0].Value }
    }
}
if (-not $u) { Write-Host 'No se pudo obtener la direccion del tunel. Revisa que cloudflared este instalado.'; exit 1 }
Write-Host "Tunel: $u"

Write-Host 'Publicando la direccion en GitHub...'
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'tunel.json'), "{`"api`": `"$u`"}`n", (New-Object Text.UTF8Encoding $false))
git pull --rebase --autostash -q origin main
git add tunel.json
git commit -q -m "tunel: $u" -- tunel.json
git push -q origin main
if ($LASTEXITCODE -eq 0) {
    Write-Host 'Listo: la pagina de Vercel ya usa esta direccion (enlace normal, sin ?api=).'
} else {
    Write-Host 'AVISO: no se pudo subir a GitHub. Usa el enlace completo con ?api= de abajo.'
}

Start-Sleep 8
$l = $vercel + 'index.html?api=' + $u
Set-Clipboard $vercel
Write-Host ''
Write-Host 'Enlace para compartir (ya copiado al portapapeles):' $vercel
Write-Host 'Enlace de respaldo (siempre funciona):' $l
Start-Process $vercel
