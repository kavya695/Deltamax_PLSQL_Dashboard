# DeltaMax — Roadmap changes (this pass)

All changes are **additive and frontend-only**. No backend file was touched, so your
BigQuery → CSV path and every existing endpoint behave exactly as before. Demo mode is
**off by default**; turning it on never calls the network.

## New files
- `src/lib/demoMode.js` — tiny on/off store for sample-data mode (localStorage-backed).
- `src/lib/demoData.js` — self-contained sample dataset ("Aurora Retail Group" customer
  master data). Same field keys as the real API, only friendlier values, so no page can
  crash on a missing property.
- `src/lib/roles.js` — role config (Exec default / Engineer / Analyst) + landing routes.
- `src/lib/qualityRules.js` — rules-as-code engine: schema, versioning, YAML/JSON
  serialize + parse, dry-run evaluator.
- `src/components/HeaderControls.jsx` — Help button, Demo toggle, Role switcher.
- `src/components/LayeredGraph.jsx` — reusable SVG graph (used by lineage + dependencies).
- `src/pages/QualityRulesPage.jsx` — declarative quality rules UI.
- `src/pages/DataLineagePage.jsx` — source → transform → quality → destination lineage.
- `src/pages/PipelineDependencyPage.jsx` — pipeline dependency map + upstream-risk badges.
- `src/pages/AuditLogPage.jsx` — filterable audit log (sign-ins, alert emails, config changes).
- `src/pages/ModelRegistryPage.jsx` — anomaly model/version registry.

## Edited files (minimal, surgical)
- `src/lib/api.js` — one short-circuit at the top of `api()`: if demo mode is on, return a
  fixture instead of fetching. Off = untouched real path.
- `src/App.jsx` — added Help / Demo toggle / Role switcher to the header, a sample-data
  banner, the glossary modal, role-aware default landing, and 5 new pages into the nav
  (new "Data Quality" section + Audit Log & Model Registry under System).
- `src/pages/LoginPage.jsx` — "Explore with sample data — no account needed" entry.
- `src/main.jsx` — role-aware landing; a real sign-in always turns demo mode off.

## Roadmap status
Phase 0: tooltips (existing InfoTips + new header "What am I looking at?" glossary on every
screen) · sample-data toggle ✔ · **GCP credentials left alone on purpose** (your live
default) · login-flow audit ✔ (below) · persistent help icon ✔.
Phase 1: role-based landing ✔ (Exec default, switchable) · user-testing = needs real people.
Phase 2: data lineage ✔ · rules-as-code ✔ · Ask-DeltaMax = existing agent chat, now with
starter questions in demo · pipeline dependency view ✔.
Phase 3: audit log ✔ · model registry ✔ · drill-downs = already covered by existing detail
modals + new rule/registry drill-ins.
Phase 4/5 (verticals, marketplace): deliberately deferred — they need user interviews and
product decisions. The rules-as-code engine is the foundation for vertical rule packs.

## Login → first-screen audit (where users can get confused)
1. **Microsoft button is a placeholder** — it "succeeds" with an empty email/name, creating
   a blank session. Recommend disabling it or wiring Entra ID before showing it.
2. **No way to look before connecting** — fixed: added the sample-data entry on login.
3. **Everyone landed on the same first screen** — fixed: role-aware landing.
4. **Email "Continue" logs in with no verification** — fine for internal use, but worth a
   note if this ever goes external.

## Two real backend bugs I noticed (left untouched — your base code)
- `/api/trust-score` is defined **twice** in `api.py` (≈lines 178 and 416). FastAPI uses the
  first; the second is dead code.
- `.env` sets `VITE_API_BASE` but `src/lib/api.js` reads `VITE_API_URL` (and
  `RunPipelinesModal.jsx` reads `VITE_API_BASE`). Not breaking today thanks to the hardcoded
  fallback, but the two names disagree.

---

## Update 2 — feedback fixes

**Blank pages fixed (Core Engine, Predictions, MDM, etc.).** The cause was the
sample fixtures using the wrong shapes — e.g. `by_method` was an object but the
page does `[...data.by_method].sort(...)`, which throws and blanks the page. All
demo fixtures were rewritten to match the real API shapes exactly (arrays where
the pages spread/map, correct element field names). Verified by replaying each
page's exact data operations. Live mode was never affected.

**Roles are now a display mode, not a redirect.** Switching role no longer jumps
pages. Instead it changes how much is shown and explained, without deleting
anything (switch back to Engineer to see it all):
- Engineer → everything, full detail, no banners.
- Analyst → the data/quality views that matter, with short explanations; deep
  engine internals and ops pages hidden.
- Exec/CDO → only high-level overviews, with fuller plain-English explanations;
  technical sections hidden.

**See the sample data.** Turning on sample data now opens a preview showing the
dataset: description, headline stats, the schema, and the actual customer rows
(with the deliberate quality problems highlighted). Reopen any time via the eye
icon next to the toggle or "See what's inside" in the banner.

**"Live" badge fixed.** In sample mode the status badge now reads "Sample data ·
Aurora Retail" (purple), not "Live".

---

## Update 3 — role dashboards, sample-data preview, colors

**Role-tailored overviews (grounded in research on how each role consumes a
data-quality dashboard).** The Overview now renders a different dashboard per
role, each with charts + plain-English "In plain terms:" takeaways:
- **Exec / CDO** → a KPI scorecard vs. a 90 target, trust trend with target &
  forecast lines, the four trust pillars renamed to plain language (Accuracy /
  Consistency / Completeness / Timeliness), and a "what needs your attention"
  list. (Execs want scorecards, trend-vs-target, business impact, plain words.)
- **Analyst** → trust-band donut, problem-type breakdown, where problems cluster
  by industry, and a "start here — records to investigate" list. (Analysts want
  distributions, breakdowns, and a worklist.)
- **Engineer** → the observability pillars: pipeline status, freshness/SLA trend,
  volume by lineage, detector flag counts, and drift model health. (Engineers
  want freshness, volume, distribution, pipeline health.)
New file: `src/components/RoleDashboards.jsx`. `HomePage` is kept as a fallback.

**Sample-data preview redesigned.** Tabbed (Overview / Records) so the top is
tidy; the Records tab is a scrollable table of 24 example rows (was 8), with the
deliberate quality problems highlighted.

**Banner color fixed.** The demo banner, toggle, badge and modal now use a
readable red (#dc2626) instead of the near-invisible amber.

---

## Update 4 — engineer default, workflow modal, multi-condition rules

**Engineer = the original dashboard, and the default.** The Engineer role now
shows the original, unchanged Overview (and Core Engine and everything else
exactly as before). Engineer is the default role on load.

**Data Lineage + Pipeline Dependencies → one Workflow view.** The two standalone
pages were removed and merged into a single **Workflow** modal (two tabs). It
opens from a persistent **Workflow** button in the lower-left sidebar, just above
the Sample-data controls, so it's reachable from any page — a quick way to
understand how everything fits together. (The Sample-data toggle, "see inside"
and role switcher now live in that same lower-left footer.)

**Quality rules are now multi-condition, with dropdowns.**
- A rule can have several conditions (Add condition / remove), joined with AND —
  a record must satisfy all of them.
- Field and dataset inputs are dropdown + free-text (type your own or pick from
  the suggested schema), so you don't have to go look at the dataset.
- Added an "is not one of" check; the dry-run now reports which condition failed.
- YAML/JSON export-import and versioning updated for the new shape; old
  single-condition rules still load fine.
