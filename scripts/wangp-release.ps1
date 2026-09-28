<#
.SYNOPSIS
    The one sanctioned way to get a change onto the installed "LTX Desktop WanGP"
    app, for both Claude Code and Hermes.

.DESCRIPTION
    Two pipelines exist and only one of them is the product we ship:

        pnpm build:win        -> electron-builder.yml       -> NORMAL LTX Desktop  (WRONG)
        pnpm build:win:wangp  -> electron-builder-wangp.yml -> LTX Desktop WanGP  (this)

    Both flavors come from the SAME source branch (`latest`); the separation is
    entirely in the build target. An agent that runs `pnpm build:win`, or runs
    `local-build.ps1` without `-Config`, silently produces the normal app. This
    wrapper makes that failure loud instead of silent.

    It never touches  ...\Programs\LTX Desktop\  and refuses to install or
    launch anything whose product identity is not "LTX Desktop WanGP".

.EXAMPLE
    pnpm wangp:build      # build the WanGP installer
    pnpm wangp:install    # install ONLY the WanGP artifact
    pnpm wangp:verify     # prove the installed exe is the one we just built
    pnpm wangp:ship       # build + install + verify in one go
#>
param(
    [ValidateSet('build', 'install', 'verify', 'ship')]
    [string]$Stage = 'ship',
    [switch]$SkipPython
)

$ErrorActionPreference = 'Stop'

$ProductName  = 'LTX Desktop WanGP'
$ConfigFile   = 'electron-builder-wangp.yml'
$ScriptDir    = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir   = Split-Path -Parent $ScriptDir
Set-Location $ProjectDir

$NormalDir  = Join-Path $env:LOCALAPPDATA 'Programs\LTX Desktop'
$NormalExe  = Join-Path $NormalDir 'LTX Desktop.exe'
$WanGPDir   = Join-Path $env:LOCALAPPDATA 'Programs\LTX Desktop WanGP'
$WanGPExe   = Join-Path $WanGPDir 'LTX Desktop WanGP.exe'
$ReleaseDir = Join-Path $ProjectDir 'release-wangp'
$LogDir     = Join-Path $env:LOCALAPPDATA 'LTXDesktop\logs'

function Fail($msg, $code) { Write-Host "ABORT: $msg" -ForegroundColor Red; exit $code }

# ---------------------------------------------------------------- build
function Invoke-WangGPBuild {
    if (-not (Test-Path $ConfigFile)) { Fail "missing $ConfigFile - this is the wrong repo" 2 }

    # The identity guard: refuse to run with any other builder config.
    # Comment lines are ignored: the config explains the Lightricks hazard in prose.
    $cfg = (Get-Content $ConfigFile | Where-Object { $_ -notmatch '^\s*#' }) -join "`n"
    if ($cfg -notmatch 'productName:\s*LTX Desktop WanGP') {
        Fail "$ConfigFile does not declare productName 'LTX Desktop WanGP'. Refusing to build." 3
    }
    if ($cfg -notmatch 'appId:\s*com\.tfg\.ltx-desktop-wangp') {
        Fail "$ConfigFile does not declare the WanGP appId. Refusing to build." 3
    }
    # A fork must never inherit upstream's release feed: that is how the fork
    # gets replaced by an upstream installer on first launch.
    if ($cfg -match 'owner:\s*Lightricks') {
        Fail "$ConfigFile still points the updater at Lightricks/ltx-desktop. The fork would be overwritten by upstream. Refusing to build." 4
    }

    Write-Host "=== building $ProductName from $(git rev-parse --short HEAD) ===" -ForegroundColor Cyan
    Write-Host "  config : $ConfigFile"
    Write-Host "  output : $ReleaseDir"
    # Not `$args` (an automatic variable), and the build log goes to the host:
    # anything left on the pipeline would become this function's return value.
    $buildArgs = @('-ExecutionPolicy', 'Bypass', '-File', 'scripts/local-build.ps1', '-Config', $ConfigFile)
    if ($SkipPython) { $buildArgs += '-SkipPython' }
    & powershell @buildArgs | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail "local-build.ps1 exited $LASTEXITCODE" 5 }

    $setup = Join-Path $ReleaseDir "$ProductName-Setup.exe"
    if (-not (Test-Path $setup)) { Fail "no '$ProductName-Setup.exe' in $ReleaseDir" 6 }
    Write-Host "=== artifact: $setup ($([math]::Round((Get-Item $setup).Length/1MB,1)) MB) ===" -ForegroundColor Green
    return $setup
}

# -------------------------------------------------------------- install
function Install-WangGP($setup) {
    # Refuse to be pointed at the normal app, ever.
    if ($setup -like '*LTX Desktop-Setup.exe') { Fail 'refusing to install the NORMAL app' 7 }
    if ((Split-Path $setup -Leaf) -notlike "*$ProductName*") { Fail "not a WanGP artifact: $setup" 7 }

    foreach ($p in @('LTX Desktop WanGP')) {
        Get-Process -Name $p -ErrorAction SilentlyContinue | Stop-Process -Force
    }
    Start-Sleep -Seconds 2

    $normalBefore = if (Test-Path $NormalExe) { (Get-Item $NormalExe).LastWriteTimeUtc } else { $null }
    Write-Host "=== installing $ProductName (normal app untouched) ===" -ForegroundColor Cyan
    # /S = silent. /D must be LAST and unquoted.
    $p = Start-Process -FilePath $setup -ArgumentList @('/S', "/D=$WanGPDir") -Wait -PassThru
    if ($p.ExitCode -ne 0) { Fail "installer exit $($p.ExitCode)" 8 }
    Start-Sleep -Seconds 2

    # The normal app must be bit-identical to before.
    if (Test-Path $NormalExe) {
        $normalAfter = (Get-Item $NormalExe).LastWriteTimeUtc
        if ($normalBefore -and $normalAfter -ne $normalBefore) {
            Fail "the NORMAL app was modified ($NormalExe). That must never happen." 9
        }
        Write-Host "  normal app unchanged: $NormalExe" -ForegroundColor DarkGray
    }
}

# --------------------------------------------------------------- verify
function Test-WangGPInstalled($expectHash) {
    if (-not (Test-Path $WanGPExe)) { Fail "not installed: $WanGPExe" 10 }
    $exe = Get-Item $WanGPExe
    $hash = (Get-FileHash $WanGPExe -Algorithm SHA256).Hash
    Write-Host "  exe        : $WanGPExe"
    Write-Host "  built      : $($exe.LastWriteTime)"
    Write-Host "  sha256     : $($hash.Substring(0,32))..."

    if ($expectHash -and $hash -ne $expectHash) {
        Fail 'installed exe hash does not match the artifact we just built' 11
    }
    foreach ($rel in @('resources\Wan2GP\wgp.py', 'resources\backend\ltx2_server.py', 'resources\app.asar')) {
        if (-not (Test-Path (Join-Path $WanGPDir $rel))) { Fail "installed app is missing $rel" 12 }
    }
    Write-Host "  packaged   : wgp.py, ltx2_server.py, app.asar present" -ForegroundColor Green

    # Read the newest session log and report what the BACKEND actually did.
    $log = Get-ChildItem $LogDir -Filter 'session_*.log' -ErrorAction SilentlyContinue |
           Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $log) { Fail "no session log in $LogDir" 13 }
    $txt = Get-Content $log.FullName -Raw
    $mode = if ($txt -match 'WanGP mode:\s*(\S+)') { $Matches[1] } else { 'unknown' }
    Write-Host "  session log: $($log.Name)"
    Write-Host "  WanGP mode  : $mode"
    if ($mode -ne 'worker') {
        Write-Host "NOTE: mode is '$mode', not 'worker'." -ForegroundColor Yellow
        Write-Host "      The packaged app ships no Wan2GP\.venv and no checkpoints," -ForegroundColor Yellow
        Write-Host "      so it cannot reach WanGP worker mode unaided. The source" -ForegroundColor Yellow
        Write-Host "      checkout at $ProjectDir has both and is what dev/testing uses." -ForegroundColor Yellow
    }
    return $hash
}

# ------------------------------------------------------------------ run
$built = $null
switch ($Stage) {
    'build'   { $null = Invoke-WangGPBuild; break }
    'install' { $setup = Join-Path $ReleaseDir "$ProductName-Setup.exe"
                if (-not (Test-Path $setup)) { Fail "no artifact in $ReleaseDir - run 'pnpm wangp:build' first" 6 }
                Install-WangGP $setup; break }
    'verify'  { $null = Test-WangGPInstalled $null; break }
    'ship'    { $built = Invoke-WangGPBuild
                Install-WangGP $built
                # Compare like with like: the app exe the installer carries, not the installer.
                $builtExe = Join-Path $ReleaseDir "win-unpacked\$ProductName.exe"
                $builtHash = (Get-FileHash $builtExe -Algorithm SHA256).Hash
                $null = Test-WangGPInstalled $builtHash
                Write-Host "`nSHIPPED $ProductName" -ForegroundColor Green }
}
