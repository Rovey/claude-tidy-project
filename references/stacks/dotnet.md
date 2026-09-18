# .NET

## Detect

`*.sln`, `*.slnx`, or `*.csproj` in the root or in `src/`.

## Layout

```
<Name>.sln                          root, contract
src/<Project>/<Project>.csproj
tests/<Project>.Tests/<Project>.Tests.csproj
docs/
scripts/
```

- Move a project folder with `git mv`, then `dotnet sln remove` the old path and `dotnet sln add`
  the new one. Update `ProjectReference` paths, `Directory.Build.props`, publish profiles, installer
  and build scripts in the same commit.
- `AssemblyName` and `RootNamespace` stay unchanged.
- WinForms: a form's `.cs`, `.Designer.cs`, and `.resx` move and get renamed together. Embedded
  resource names derive from namespace and file name, so namespace changes on forms break resource
  lookups: doubt policy.
- Never hand-edit `*.Designer.cs`, apart from keeping its namespace and partial class name
  consistent with the main file. Don't rename WinForms control fields.

## Contracts (in addition to rules.md)

Executable name, `app.config`/`appsettings.json` keys, `Properties/Settings.settings` (a namespace
change resets user settings), registry keys, named pipes, file and folder paths, command-line
arguments, types serialized by name (JSON `$type`, XML serializers, BinaryFormatter).

## Tests

- Existing test project → `dotnet test --nologo`.
- None → `dotnet new xunit -o tests/<Project>.Tests`, target the same TFM as the project under test
  (for `net8.0-windows` add `<UseWindowsForms>true</UseWindowsForms>` only if referenced types need
  it), `dotnet add tests/<Project>.Tests reference src/<Project>/<Project>.csproj`,
  `dotnet sln add tests/<Project>.Tests`. If restore fails, skip test blocks and report.
- Internal classes: add `<InternalsVisibleTo Include="<Project>.Tests" />` to the project file.
- Test logic classes, not forms.

## Formatter

`dotnet format whitespace <Name>.sln`. If `.editorconfig` sets `end_of_line`, skip formatting and
report it (line endings must not change). Commit `style: format with dotnet format`.

## Smoke checks

`dotnet build --nologo -v q`

## Pitfalls

- `bin/` and `obj/` must be ignored before the baseline build; the orchestrator's Phase 0 step
  handles it.
- Build warnings are not failures; new errors are.
