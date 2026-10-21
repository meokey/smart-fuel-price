# FAQ

**Why is everything in ¢/L instead of $/L?**
Canadian pumps quote cents per litre, and GasBuddy's API natively reports
¢/L — so the integration passes the number through raw. `168.9 ¢/L` is what
you'd see on the sign.

**Why is tomorrow's forecast "unknown" in the morning?**
The source publishes it on its own schedule (usually by the evening). The
integration shows `unknown` rather than a stale or guessed value.

**Does it submit prices anywhere?**
No. All sources are read-only; the integration only fetches.

**Can I track multiple cities or stations?**
Yes — add one integration entry per city/provider/station group. They are
independent entries with their own cache settings.

**Will EV charging prices be added?**
It's on the roadmap — see
[issue #33](https://github.com/meokey/smart-fuel-price/issues/33).
EV pricing is per kWh, so it will be a separate device type.

**Is this in the HACS default store?**
Not yet — install via custom repository for now (see
[Installation](https://github.com/meokey/smart-fuel-price/wiki/Installation)).
The default-store application ([hacs/default#11765](https://github.com/hacs/default/pull/11765))
was submitted on Oct 10, 2026 and reviewed by a HACS maintainer on
Oct 21, 2026; the requested changes shipped in v2.7.6 and a re-review has
been requested. The PR page itself always shows the live status.

**How do I report a bug or request a feature?**
Use the [issue templates](https://github.com/meokey/smart-fuel-price/issues/new/choose).
One question in each: do you plan to implement it yourself? "Just suggesting"
is a perfectly good answer — it just avoids duplicate work.
