# Scripts and docs repositories

## Detect

No other stack matches: PowerShell (`.ps1`, `.psm1`), batch (`.bat`, `.cmd`), shell scripts, HTML
reports, markdown, data files.

## Layout

```
<launchers in root>     .ps1/.bat/.cmd/.sh in the root are contracts and stay
scripts/                helpers that people don't start directly
docs/                   markdown, analyses, HTML reports
data/                   input files, only when every script reading them is updated
README.md
```

- Scripts calling each other by relative path (`. .\lib.ps1`, `& "$PSScriptRoot\helper.ps1"`,
  `call other.bat`) are updated when moved. Keep the resolution style: `.\x.ps1` resolves from the
  working directory, `$PSScriptRoot` from the script folder — switching changes behavior.
- Hard-coded absolute paths (`C:\Users\...`) are contracts: leave them, report them.

## Tests

None by default. A `.ps1` with real logic (parsing, calculations) gets Pester tests
(`tests/<Name>.Tests.ps1`) only when Pester 5 or newer is installed
(`Get-Module -ListAvailable Pester`). Windows ships Pester 3.4: then skip and report.

## Formatter

None.

## Smoke checks

PowerShell syntax check without running anything:

```powershell
$failed = $false
Get-ChildItem -Recurse -Include *.ps1, *.psm1 | ForEach-Object {
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$null, [ref]$parseErrors) | Out-Null
    if ($parseErrors) { Write-Output "$($_.FullName): $($parseErrors[0].Message)"; $failed = $true }
}
if ($failed) { exit 1 }
```

HTML: after moves, every relative `src=`/`href=` points at an existing file.

## Pitfalls

- Windows PowerShell 5.1 reads UTF-8 files without BOM as ANSI. Keep each file's encoding and BOM
  exactly as they are when editing.
- HTML reports are opened by double-click; relative links must keep working from the new folder.
