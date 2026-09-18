# Browser extensions without a build step

## Detect

`manifest.json` in the root with `manifest_version`, and no bundler config (`webpack.config.*`,
`vite.config.*`, `rollup.config.*`, `esbuild` scripts). With a bundler, use `node.md`.

## Contracts

- `manifest.json` stays in the root: the unpacked extension is loaded from this folder.
- Unchanged: `key`, `name`, `description`, `version`, `permissions`, `host_permissions`,
  `optional_permissions`, `content_scripts[].matches`, `externally_connectable`, URL patterns in
  `web_accessible_resources`, message `type` strings exchanged between scripts, `chrome.storage`
  keys, element ids and classes that content scripts look for on third-party pages.

## Target layout

```
manifest.json
src/
  background.js         (or background/ when there are several files)
  content-script.js     (or content/)
  popup/                popup.html, popup.js, popup.css
  options/
  lib/                  pure logic without chrome.* or DOM, testable in Node
assets/icons/
tests/                  *.test.js
docs/
README.md
```

- Small extensions (five files or fewer) keep `src/` flat; no empty folders.
- File names in kebab-case: `contentScript.js` → `content-script.js`.
- Update every path in `manifest.json` (`background.service_worker`, `content_scripts[].js/css`,
  `action.default_popup`, `action.default_icon`, `icons`, `options_page`, `options_ui.page`,
  `web_accessible_resources[].resources`), in HTML (`<script src>`, `<link href>`, `<img src>`),
  and in code (`chrome.runtime.getURL`, `chrome.scripting.executeScript({ files })`, `importScripts`).
- Keep the service worker type: never convert a classic worker to `"type": "module"` or back.
- Example data tracked next to a `.example` copy (for example `sample_serials.txt`) may be real
  data: doubt policy.

## Tests

- No `package.json`. Node's built-in runner: `node --test` (finds `**/*.test.js`).
- Only pure logic is tested. Move it to `src/lib/<name>.js` in a form that loads in the browser and
  in Node without a build step:

  ```js
  (function (root) {
    function parseSerials(text) {
      return text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    }

    const api = { parseSerials };
    if (typeof module !== "undefined" && module.exports) {
      module.exports = api;
    } else {
      root.serialParser = api;
    }
  })(typeof self !== "undefined" ? self : this);
  ```

  Load it before its consumer: content scripts list it first in `content_scripts[].js`, a classic
  service worker uses `importScripts("lib/serial-parser.js")`, a popup adds a `<script>` tag first.
- Test file `tests/serial-parser.test.js`:

  ```js
  const test = require("node:test");
  const assert = require("node:assert/strict");
  const { parseSerials } = require("../src/lib/serial-parser.js");

  test("parseSerials drops empty lines and trims whitespace", () => {
    assert.deepEqual(parseSerials(" A1 \r\n\r\nB2\n"), ["A1", "B2"]);
  });
  ```

- Code using `chrome.*` or the DOM is not unit-tested.

## Formatter

None.

## Smoke checks

- `node --check <file>` for every `.js` file that passed `node --check` at baseline.
- Every path referenced from the manifest exists:

  ```bash
  python - <<'EOF'
  import json, pathlib, sys
  manifest = json.loads(pathlib.Path("manifest.json").read_text(encoding="utf-8"))
  paths = []
  background = manifest.get("background", {})
  paths += [background["service_worker"]] if "service_worker" in background else background.get("scripts", [])
  for script in manifest.get("content_scripts", []):
      paths += script.get("js", []) + script.get("css", [])
  action = manifest.get("action") or manifest.get("browser_action") or {}
  if "default_popup" in action:
      paths.append(action["default_popup"])
  icon = action.get("default_icon")
  paths += list(icon.values()) if isinstance(icon, dict) else ([icon] if icon else [])
  paths += list((manifest.get("icons") or {}).values())
  if "options_page" in manifest:
      paths.append(manifest["options_page"])
  if "options_ui" in manifest:
      paths.append(manifest["options_ui"]["page"])
  for entry in manifest.get("web_accessible_resources", []):
      resources = entry.get("resources", []) if isinstance(entry, dict) else [entry]
      paths += [resource for resource in resources if "*" not in resource]
  missing = [path for path in paths if not pathlib.Path(path).is_file()]
  print("missing: " + ", ".join(missing) if missing else "manifest paths ok")
  sys.exit(1 if missing else 0)
  EOF
  ```

- After moves: every relative `src=`/`href=` in HTML files points at an existing file.

## Report follow-up

Add to "Review and merge": after merging, reload the unpacked extension on `chrome://extensions`.
