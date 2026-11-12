[CmdletBinding()]
param(
    [ValidateSet('cases', 'scalability', 'k2')]
    [string]$Experiment = 'scalability',
    [string]$Python = (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'),
    [ValidateSet('isolated', 'chain_independent')]
    [string[]]$ResourceConfigurations = @('isolated', 'chain_independent'),
    [int[]]$Sizes = @(1, 2, 4, 8, 16, 32, 64),
    [ValidateRange(0, 2147483647)]
    [int]$Warmup = 1,
    [ValidateRange(1, 2147483647)]
    [int]$Repetitions = 10,
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
$archiveRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$pythonCommand = Get-Command $Python -ErrorAction Stop
$pythonExecutable = $pythonCommand.Source
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $archiveRoot ('reproduced/' + $Experiment + '-' + [guid]::NewGuid().ToString('N'))
}
if (-not [IO.Path]::IsPathRooted($OutputDirectory)) {
    $OutputDirectory = Join-Path $archiveRoot $OutputDirectory
}
$outputPath = [IO.Path]::GetFullPath($OutputDirectory)
$archivedResults = [IO.Path]::GetFullPath((Join-Path $archiveRoot 'results'))
if ($outputPath -eq $archivedResults -or $outputPath.StartsWith($archivedResults + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'OutputDirectory must not be inside the archived results directory.'
}
if (Test-Path -LiteralPath $outputPath) {
    throw "Output directory already exists: $outputPath"
}

Push-Location -LiteralPath $archiveRoot
try {
    & $pythonExecutable -B -c "import sys,z3; assert sys.version_info[:3] == (3,12,14), sys.version; assert z3.get_version_string() == '4.16.0', z3.get_full_version(); print(sys.version); print(z3.get_full_version())"
    if ($LASTEXITCODE -ne 0) { throw 'Python/Z3 version check failed.' }
    $solverSetup = "import runpy,z3; z3.set_param('parallel.enable',False); z3.set_param('smt.threads',1); "
    if ($Experiment -eq 'cases') {
        $entry = "import sys,z3; from pathlib import Path; z3.set_param('parallel.enable',False); z3.set_param('smt.threads',1); import run_layered_cases as c; c.OUTPUT_DIR=Path(sys.argv[1]); c.main()"
        $entryArguments = @('-B', '-u', '-c', $entry, $outputPath)
    } else {
        $entry = $solverSetup + "runpy.run_path('run_scalability_experiment.py',run_name='__main__')"
        if ($Experiment -eq 'k2') {
            $runSizes = @(2)
            $runConfigurations = @('chain_independent', 'chain_shared_cpu')
        } else {
            $runSizes = $Sizes
            $runConfigurations = $ResourceConfigurations
        }
        $entryArguments = @('-B', '-u', '-c', $entry, '--sizes')
        $entryArguments += @($runSizes | ForEach-Object { [string]$_ })
        $entryArguments += @('--variants', 'valid', '--resource-configurations')
        $entryArguments += $runConfigurations
        $entryArguments += @('--warmup', [string]$Warmup, '--repetitions', [string]$Repetitions, '--output-dir', $outputPath, '--skip-plots')
    }
    Write-Host "Working directory: $archiveRoot"
    Write-Host "Interpreter: $pythonExecutable"
    Write-Host "Output directory: $outputPath"
    Write-Host ('Arguments: ' + ($entryArguments -join ' '))
    & $pythonExecutable @entryArguments
    if ($LASTEXITCODE -ne 0) { throw "Prototype exited with code $LASTEXITCODE" }
} finally {
    Pop-Location
}
