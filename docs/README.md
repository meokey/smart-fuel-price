# Documentation (canonical)

This directory is the **single source of truth** for user documentation.
The [GitHub wiki](https://github.com/meokey/smart-fuel-price/wiki) is a
read-only mirror: `.github/workflows/wiki-sync.yml` copies `docs/*.md`
there on every push to `main`. **Edit docs here in a PR — never edit the
wiki directly**, or the next sync will overwrite your change.

Conventions:

- File names map 1:1 to wiki page names (`Providers.md` → the Providers
  page). `_Sidebar.md` is the wiki sidebar.
- Anything between `<!-- GENERATED:...:START -->` / `END` markers is
  produced by `scripts/gen_docs.py` — do not hand-edit; run the script.
  CI fails the PR if generated output is stale.
- Docs that describe code behavior carry an `as of vX.Y.Z` marker;
  `scripts/check_doc_versions.py` warns (in CI) when the code has moved on.
- Mermaid diagrams are linted by `scripts/check_mermaid.py` in CI.
