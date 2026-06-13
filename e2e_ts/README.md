# `e2e_ts/` — TypeScript / Playwright E2E layer

A second, **TypeScript** expression of the functional end-to-end pillar, running
alongside the Python [`functional/`](../functional) suite against the same
system under test (`golf-web-app`). This is the first scheduled piece of the
**G2 polyglot track** (see [docs/test-strategy.md](../docs/test-strategy.md)
§13, B20).

## Why this exists

The harness is deliberately **polyglot**: Python where it is superior (the
data-quality, AI-evaluation, security, and agentic layers), and
**TypeScript/Playwright for web E2E**, where the wider market overwhelmingly
gates on it. Driving the *same* journeys in two languages is the point — it
demonstrates cross-language Playwright fluency and that binding language is
chosen by fit, not habit.

`functional/` remains the primary, complete functional layer. `e2e_ts/` is a
focused demonstration slice — a representative **three journeys**, not a full
mirror (maintaining full parity is ongoing cost for little extra signal):

| Spec | Python counterpart | What it proves |
|---|---|---|
| `tests/member-journey.spec.ts` | `functional/test_member_journey.py` | Login, **book a tee time** (JS slot selection + CSRF form), logout — the headline E2E |
| `tests/public-pages.spec.ts` | `functional/test_public_pages.py` | Site is alive; top-nav renders real pages |
| `tests/access-control.spec.ts` | `functional/test_access_control.py` | Auth-boundary enforcement — maps to risk **R-004** |

### A deliberate dual-idiom

This layer uses the **Page Object Model + a NavBar component object** — idiomatic
for Playwright/TypeScript. The Python `functional/` suite uses **pytest fixtures**
(`login`, `member_page`, the R-018 `page` shim) — idiomatic for pytest-playwright.
The difference is **intentional**: each suite follows its own ecosystem's native
convention. Converting the Python suite to POM is deferred until its coverage grows
(more recurring traffic through the member/admin dashboards), at which point the
locator-centralisation payoff turns real — tracked as **B21** in
[docs/test-strategy.md](../docs/test-strategy.md) §13.

## Layout

```
e2e_ts/
  package.json          # pinned toolchain (Node 22 LTS, exact Playwright)
  playwright.config.ts  # baseURL from env, CI retries, reporters
  tsconfig.json
  fixtures.ts           # credentials, login helper, memberPage, R-018 shim
  components/           # component objects (NavBar — shared site navigation)
  pages/                # page objects (Home, Login, MemberDashboard, Booking)
  tests/                # the three journey specs
  reports/              # generated HTML report (git-ignored)
```

The specs hold **no raw selectors** — every locator lives in a page or component
object. The site navbar is modelled as a *component object* (`components/NavBar`)
rather than duplicated across pages, since the same navigation (brand, public
links, the authenticated user dropdown) appears site-wide.

## G1-ready by construction

Nothing SUT-specific is hard-coded in a spec, so this layer needs **no rewrite**
under a future G1 generalisation (multi-SUT — see the strategy doc). The only
SUT-specific seam is configuration, and it is already externalised:

- **`baseURL`** comes from `SUT_BASE_URL` (default `http://localhost:5000`) in
  `playwright.config.ts`; all navigations are **relative** (`page.goto('/...')`).
- **Credentials** come from `SUT_USERNAME` / `SUT_PASSWORD` (defaults match the
  Python suite), never inlined.
- URL assertions that could leak the host (logout, admin redirect) assert on
  **pathname**, not a hard-coded `localhost`.

A future multi-SUT profile simply supplies those env values; the `.spec.ts`
files do not change.

## R-018 parity

The booking journey carries the same smooth-scroll race mitigation as the Python
suite — a `scrollIntoView` shim injected via `page.addInitScript` in
`fixtures.ts`, mirroring the fixture in `functional/conftest.py` (see F-012 /
F-025 in the strategy doc). The real submit button, form, and handler are still
exercised; only the cosmetic transition is neutralised.

## Running locally

Bring the SUT up first (from the sibling `golf-web-app` repo):

```bash
cd ../golf-web-app
docker compose up -d --build
docker compose exec -T web python seed.py
```

Then, from this directory:

```bash
npm ci                              # install pinned deps
npx playwright install chromium     # one-time browser download
npm test                            # run the suite
npm run report                      # open the HTML report
```

Override the target if the SUT is elsewhere:

```bash
SUT_BASE_URL=http://localhost:8080 npm test
```

## CI

One parallel job (`e2e-ts`) in [.github/workflows/assurance.yml](../.github/workflows/assurance.yml)
brings up its **own** ephemeral SUT (so it never shares booking state with the
Python functional job), then runs `npm ci` → `playwright install` → `npm test`.
The job **gates** (a failure reds the run, matching the Python functional twin);
`retries: 2` on CI absorbs transient flake honestly (a retry-only pass is
reported as *flaky*, not hidden).

## Version pinning

The toolchain is pinned for reproducibility: **Node 22 LTS** (`.nvmrc`,
`engines`, and `actions/setup-node` in CI), an exact `@playwright/test` version,
and a committed `package-lock.json` installed via `npm ci`. Local development
may run a newer Node (e.g. 24) — Playwright behaves identically; the pin governs
CI determinism.

## Known limitation

A server-rendered (Flask/Jinja) UI supports TS **E2E** but not isolated **UI
component** testing, which needs a component framework (React/Vue). That single
capability would only be unlocked by a future small TS frontend slice, gated on
real demand (see G2 in the strategy doc).
