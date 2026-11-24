# First release, v0.1.0 (status, 2026-11-24)

PyPI from GitHub Actions; docs from Forgejo to dvkit.org/work-packet/work-packet/.
Follows the dvkit-infra model: a `v*` tag is the only release trigger, and the
release-authority switch picks the forge.

## State

| Item | Status |
|---|---|
| CI pair (`.github/` + `.forgejo/workflows/ci.yml`) from the forgejo-ops templates | already in place, green on both forges |
| Release authority for work-packet/work-packet | `github` (global default; no org/repo override needed) |
| `PYPI_API_TOKEN` on GitHub | org secret on `work-packet`, visibility ALL (set 2026-11-24) |
| Forgejo Actions unit | `has_actions: true` |
| Version | `src/work_packet/__about__.py` → `(0, 1, 0)` |
| Dash JS bundle in the wheel | both CI files now run `npm ci` + `node tools/vendor/build.mjs` before the build, and fail if the wheel lacks `dash/vendor/manifest.json`. `tools/vendor/package-lock.json` added so the bundle is reproducible. Trial-run in act-22.04: OK, 12 MB |
| Docs site | `docs/conf.py`, `docs/index.md`, `docs/requirements.txt` (Sphinx + MyST + furo). Only the pages in `include_patterns` are published (index, four user guides, spec); the design notes and plans are not. Builds with `-W` in act-24.04: 8 pages |
| Docs workflow | `.forgejo/workflows/docs.yml` uploads artifact `docs-work-packet-work-packet` |
| README / pyproject | install line, docs link, `Documentation` project URL |

## Next (the user does these)

1. Review and commit the changes; push `main`. Check both CI runs and the Docs
   run are green, and that dvkit.org/work-packet/work-packet/ appears.
2. `git tag v0.1.0 && git push origin v0.1.0` (Forgejo; the sync mirrors the tag
   to GitHub, whose publish job uploads to PyPI).
3. Check https://pypi.org/project/work-packet/ and `pip install 'work-packet[dash]'`
   in a clean venv.
