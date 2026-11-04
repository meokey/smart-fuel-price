## What & why

<!-- Link the tracking issue (e.g. "Closes #123" or "Issue #123: ...") and
summarise the change in a sentence or two. -->

## Checks

- [ ] Offline suite green in a **fresh venv** with only
      `requirements-test.txt` installed
- [ ] **Docs synced in this PR** — every surface the change touches was
      checked against the documentation-sync checklist in
      [docs/Release-process.md](https://github.com/meokey/smart-fuel-price/blob/main/docs/Release-process.md)
      (README, Configuration, Providers, wiki Home, FAQ/Troubleshooting,
      Architecture + version markers), or marked N/A here with a reason
- [ ] Doc scripts pass when docs were touched (`scripts/gen_docs.py`
      shows no drift, `check_mermaid.py`, `check_doc_versions.py`)
