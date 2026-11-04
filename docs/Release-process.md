# Release process

The formal rules for changing and releasing Smart Fuel Price. These are
rules, not guidelines — a deviation needs the maintainer's explicit
decision, recorded on the tracking issue or PR. (This page exists so the
process does not live in anyone's memory.)

## 1. Traceability

- Every change starts from a GitHub issue; PR titles/bodies reference the
  issue number; release notes reference the issues they ship.
- One issue → one PR where practical; large changes may ship as a stack of
  small, independently reviewable PRs that merge together.

## 2. Quality gate before merge

- The offline test suite must be green in a **fresh virtual environment**
  installed with only `requirements-test.txt` (a suite that passes in a
  long-lived dev venv proves nothing — it may import packages CI lacks).
- All CI checks green: pytest, hassfest, HACS validation, docs checks.

## 3. Documentation sync — same PR, no exceptions

Every code or behaviour change updates its documentation **in the same
PR**. Shipping code first and sweeping the docs later is not allowed;
deferred is how docs drift (precedent: v2.7.9 / #56 updated
`docs/Configuration.md` but missed README and the wiki landing page, and
needed a follow-up PR #99 to repair).

Check every surface the change touches:

- [ ] `README.md` — Features list; Installation / Configuration sections
      if setup or behaviour changed (this file is also the integration's
      page in HACS)
- [ ] `docs/Configuration.md` — every new or changed sensor, attribute,
      option or button, with its semantics and edge cases
- [ ] `docs/Providers.md` — provider behaviour or coverage; re-run
      `scripts/gen_docs.py` if coverage changed
- [ ] `docs/Home.md` — headline features on the wiki landing page
- [ ] `docs/FAQ.md` / `docs/Troubleshooting.md` — new failure modes or
      behaviour users will ask about
- [ ] `docs/Architecture.md` — design changes; keep `as of vX.Y.Z`
      markers in sync (`scripts/check_doc_versions.py`)
- [ ] Diagrams still accurate (`scripts/check_mermaid.py`)

`docs/` is the canonical home; the GitHub wiki is a read-only mirror
synced by workflow on merge. Never edit the wiki directly.

## 4. Pre-release rule — every update ships as a beta first

Since 2026-11-04, every update goes through a GitHub **pre-release**
before it becomes a full release:

1. Bump `manifest.json` to the target base version on `main`. The beta
   suffix lives only on the tag — the manifest always carries the base
   version, so the beta zip and the final zip are byte-identical.
2. Publish the pre-release with tag `vX.Y.Z-beta.N`. The release
   workflow marks any tag containing `-` as a pre-release automatically;
   plain `vX.Y.Z` tags publish as full releases.
3. **Technical testing of the pre-release itself** (mandatory, against
   the published asset — not a git checkout):
   - download `smart_fuel_price.zip` from the pre-release and install it
     into a test Home Assistant instance;
   - configure entries through the UI config flow for every affected
     provider;
   - let it run and check the logs — no errors or tracebacks from the
     integration;
   - verify each new or changed feature against the behaviour its issue
     / PR specifies (functional acceptance, not just "it loads");
   - record the test outcome on the tracking issue or PR.
4. The maintainer also spot-checks pre-releases.
5. **Promotion**: when testing passes, publish the full release
   `vX.Y.Z` from the same `main` commit, verify the asset actually
   uploaded (name, non-zero size, and the manifest version inside the
   zip), then close the shipped issues.

Beta users opt in per repository in HACS (⋮ → **Redownload** → **Show
beta versions**); the steps are documented for users in the README and
the Installation page.

## 5. Real-HA E2E gate — and the source-data caveat

Before a full release, an end-to-end run on a real Home Assistant test
instance exercises the exact commit to be tagged: the config entry
loads, sensors produce values, and the integration logs no errors.

**Caveat** (maintainer ruling, 2026-11-04; precedent: v2.7.9): if the
gate fails *only* because a data source has not published current data —
e.g. the Gas Wizard city page has no entry dated today — while fetching
itself verifiably works (the page loads, parses, and older entries are
present), that is a source outage, not a defect in this integration, and
the release may proceed. Any other gate failure blocks the release.

## 6. After release

- Confirm the release workflow finished and the asset is the one that
  was verified.
- For docs changes, confirm the wiki sync workflow succeeded.
