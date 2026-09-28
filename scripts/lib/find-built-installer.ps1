# Returns the Setup .exe electron-builder produced in a release directory: the
# newest *Setup.exe, so a stale installer from an earlier (e.g. WanGP-branded)
# build is never reported, and the temporary *Setup.__uninstaller.exe is skipped.
function Find-BuiltInstaller {
    param([Parameter(Mandatory)][string]$ReleaseDir)
    Get-ChildItem -Path $ReleaseDir -Filter "*Setup.exe" -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}
