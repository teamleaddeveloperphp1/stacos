# Styling architecture — STACOS.ai design system in the ITR-1 app

## 1. Audit findings (as of this pass)

Before this change, `frontend/static/itr1/css/main.css` was the marketing
stylesheet from stacos.ai **pasted in verbatim, plus the app's own component
rules appended to the end of the same file.** Concretely, per the audit:

1. **Stylesheets loaded**: exactly one — `itr1/css/main.css` — linked from
   `frontend/templates/itr1/base.html`, `frontend/templates/itr1/return_list.html`
   (which has its own standalone `<head>`, doesn't extend `base.html`), and
   `frontend/templates/app_base.html` (shared shell for the new accounts/services
   apps). All three resolved 200; no 404s, no stale `STATIC_ROOT` copies
   (`STATIC_ROOT` isn't set at all — `collectstatic` has never run — and
   `find -iname main.css` turned up exactly one file on disk).
2. **Bootstrap**: not present anywhere — no CDN link, no vendored files, no
   entry in `requirements.txt`. Class names like `.btn`, `.btn-primary`,
   `.row` are this project's own hand-rolled CSS (coincidentally
   Bootstrap-shaped names, not Bootstrap's grid/utility system — no
   `col-*` classes exist anywhere).
3. **IBM Plex Sans / Mono**: loaded via a Google Fonts `<link>` in each head
   template, not self-hosted. No `@font-face` rule existed anywhere.
4. **Static config**: `STATICFILES_DIRS = [BASE_DIR.parent / 'frontend' / 'static']`,
   no `STATIC_ROOT`. Single source file, always served fresh in `DEBUG` mode.
5. **Base template structure**: all seven return screens extend
   `itr1/base.html`; `return_list.html` does not (own head, duplicated
   font/CSS links — now kept in sync manually since both must load the same
   two files, see §4). The new `accounts/*` templates all extend the shared
   `app_base.html`.

**The actual defect** wasn't "the marketing stylesheet was never loaded" —
it was the opposite mistake: the marketing stylesheet's bare-element
selectors and component classes were live on every app page, unscoped:

- `h1 { font-size: clamp(2.4rem, 5.6vw, 4.8rem); letter-spacing: -0.035em; }`
  rendered "Personal Information" as a ~77px hero headline (confirmed via a
  rendered screenshot before this fix — see `git log` for the before/after).
- `.field label, label { font-family: mono; text-transform: uppercase; }`
  (an earlier, well-intentioned but wrong port of the marketing
  `.form-group label` treatment) made 40+ fields per screen read as dense
  uppercase mono — unreadable at that density.
- Marketing-only component classes (`.hero`, `.countdown`, `.waitlist`,
  `.etymology`, `.stats`, `.cards`/`.card-tile`, `.foot-grid`, `.page-hero`,
  `.cta-strip`, `.fade-up`/`.delay-*`) matched **zero** elements in any
  Django template — confirmed dead weight, deleted outright.

### The "clipped sidebar" bug — investigated, not reproducible

The reported symptom (`ITR-1` rendering as `TR-1`, roughly 10px clipped on
the left) was investigated two ways:

1. **Static audit** of `main.css` for `overflow`, negative `margin-left`,
   `position: fixed`, `left:`, `width: 100vw` — none of these touch
   `nav.itr1-menu`, `body`, or `.app-shell`.
2. **Live rendering**, properly — `google-chrome --headless
   --window-size=W,H --screenshot=...` turned out to be an **unreliable way
   to test this**: that CLI screenshot flag does not reliably set the
   layout viewport to match `--window-size` (confirmed by checking
   `document.documentElement.clientWidth`, which came back 500px while the
   output PNG was cropped to the requested 375×700 — producing exactly the
   false "clipped on the edge" artifact this bug report describes). Once
   verified properly, via `Emulation.setDeviceMetricsOverride` over the
   DevTools Protocol at both 375px and 1440px, `document.body.scrollWidth`
   equals `document.documentElement.clientWidth` exactly (no horizontal
   overflow) and zero elements report `scrollWidth` greater than the
   viewport, on the returns landing page and every screen checked.

**Conclusion:** no clipping bug reproduces in the current codebase. Given
the false-positive risk just demonstrated with the naive headless
screenshot method, if this is still visible in a real browser it is most
likely either a stale asset in that browser's cache or specific to a
viewport/zoom/extension combination not covered here — re-verify with
DevTools' own responsive mode (not a CLI screenshot flag) and report the
exact viewport width and browser if it persists.

As defensive hardening regardless, `app.css` adds `overflow-x: hidden` on
`html`/`body` and `min-width: 0` + `overflow-wrap: break-word` on the flex
row children most likely to grow long text (`.header-row`, `.return-card-top`,
`.dashboard-header > div`, sidebar nav links) so a future long taxpayer name
or Hindi string wraps instead of pushing the layout wider than the viewport.

## 2. Why the marketing stylesheet can't just be linked in

Copying `main.css` (marketing) into the app wholesale means ~95% of it
matches nothing (marketing-only component classes) while the bare-element
selectors that *do* match make things actively worse (the oversized `h1`,
`section { padding: 100px 0; }` if any dense UI used a bare `<section>`,
`img, svg { display: block }` affecting inline icon alignment). It also
still doesn't load IBM Plex — the marketing CSS has no `@import`/`@font-face`;
the webfont only loads because of separate `<link>` tags in the marketing
site's own HTML.

## 3. The three-layer structure

```
frontend/static/itr1/css/
  tokens.css   -- the design system: CSS custom properties only, no selectors
  app.css      -- every real app component, built against tokens.css
```

Load order in every head template, fonts first so they're requested before
any CSS references them:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500;600&family=Noto+Sans+Devanagari:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{% static 'itr1/css/tokens.css' %}">
<link rel="stylesheet" href="{% static 'itr1/css/app.css' %}">
```

`Noto Sans Devanagari` is in the font stack because IBM Plex Sans has no
Devanagari glyphs — without a fallback, the Hindi UI would silently render
in the browser's system font instead. Verified rendering हिन्दी text
correctly with no missing-glyph boxes and no layout overflow at both
375px and 1440px viewports.

No Bootstrap is present in this project, so there was no "keep vs. remove"
decision to make for §4.4 of the brief — `app.css` is the only component
layer.

## 4. Token list (`tokens.css`)

**From the marketing palette, verbatim:**
`--white`, `--off-white`, `--grey-50`, `--grey-100`, `--grey-200`,
`--grey-300`, `--grey-500`, `--grey-700`, `--ink`, `--blue`, `--blue-dark`,
`--blue-bright`, `--blue-light`, `--rule`, `--shadow-sm`, `--shadow-md`,
`--shadow-lg`, `--font-sans`, `--font-mono` (the latter two with a
Devanagari fallback added, see §3).

**Added for the app — the marketing palette is deliberately blues-only and
has no status colours:**

| Token | Value | Used for |
|---|---|---|
| `--ok` / `--ok-bg` / `--ok-border` | `#0F7B4F` / `#EAF5F0` / `#BFDFCE` | Confirmed chip, success banners, refund-due ticker |
| `--warn` / `--warn-bg` / `--warn-border` | `#8A5A00` / `#FDF6E7` / `#EBD9AC` | In-progress chip, advisory findings, old-regime badge |
| `--err` / `--err-bg` / `--err-border` | `#A8232B` / `#FBEDEE` / `#E8C2C5` | Has-errors chip, validation error rows |
| `--neutral` / `--neutral-bg` / `--neutral-border` | aliases of grey-500/100/rule | Not-started / coming-soon chips |
| `--card-gap`, `--card-pad`, `--field-gap`, `--radius` | `20px`, `24px`, `16px`, `4px` | Dense-form spacing — the marketing 100px section rhythm doesn't apply to a 40-field screen |

**Rule going forward: every colour in `app.css` (or any future component
CSS) must resolve to one of these tokens. No hex literals in component
rules** — verified with `grep -oE '#[0-9a-fA-F]{3,6}' app.css`, which
returns nothing outside `tokens.css` itself.

## 5. Component → token map (`app.css`)

| App component | Treatment |
|---|---|
| Sidebar shell (`nav.itr1-menu`) | `--white` bg, `1px solid var(--rule)` right edge |
| Sidebar title | Sans 600, `--ink` |
| Sidebar sub-line (taxpayer · PAN) | 12.5px, `--grey-500` |
| 7 step links | 14px sans; active gets `--blue` text + 2px `--blue` left border; hover `--grey-50` |
| Status chips | `.chip` base (mono, 10.5px, uppercase, tracked) + `.chip-{status}` modifiers on `--ok`/`--warn`/`--err`/`--neutral` triplets |
| `← Dashboard` link | `--grey-500`, `--blue` on hover |
| Language switcher | Active `--blue` 600; inactive `--grey-500` |
| Breadcrumb | Mono, 11.5px, uppercase, 0.12em tracking, `--grey-500` |
| Page title (`h1` inside `.itr1-header`) | **1.7rem, explicitly overridden** — not the global marketing clamp |
| `NEW REGIME` / `OLD REGIME` badge | Chip shape, `--blue-light`/`--warn-bg` |
| Summary strip | 13px `--grey-500`; ticker in `--ok`/`--warn` per state |
| Fieldset cards | `--white` bg, `1px solid var(--rule)`, `--radius`, `--card-pad`, `--shadow-sm`; legend sans 600 15px |
| Field labels | **13px `--grey-700` sans 500 — not mono-uppercase.** Fixed in this pass; see §1. |
| Inputs/selects | `1px solid var(--rule)`, `--radius`, focus ring `rgba(0,61,165,.12)` |
| Helper text | 12.5px `--grey-500` |
| Info banner (GTI etc.) | `--blue-light` bg |
| Advisory banner | `--warn-bg`/`--warn-border`/`--warn` |
| Validation error rows | `--err-bg`, 3px `--err` left border; rule code mono `--grey-500` |
| Trace drawer / computation tables | `--grey-50` header strip, `font-variant-numeric: tabular-nums`, right-aligned amounts |
| `Save` | ghost button (white bg, `--blue` text/border) |
| `Confirm` | solid `--blue` (verified: `getComputedStyle(...).backgroundColor === 'rgb(0, 61, 165)'`) |
| Autosave indicator | 12.5px `--grey-500`; failure `--err` |
| Footer meta | Mono 11px `--grey-500` |
| Return card (landing page) | Card shell; progress bar `--blue` fill on `--grey-100` track |
| `No returns yet` empty state | Dashed `--rule` border, centred |
| Services dashboard card | Same card shell, `.chip-available`/`.chip-coming_soon` |

Dropped outright (matched nothing in any template): `.hero`, `.countdown`,
`.waitlist`, `.etymology`, `.stats`/`.stats-grid`, `.cards`/`.card-tile`,
`.foot-grid`/`.foot-col`/`.foot-bottom`, `.page-hero`, `.cta-strip`,
`.fade-up`/`.delay-*`, `.topbar`/`.pill`/`.blip`, `.nav-links`/`.nav-toggle`
(marketing's own responsive nav, unrelated to `.app-topbar`), `.split`,
`.feat-list`, `.tbadge`, `.dark-band`, `.form-row`/`.form-group`, `.bg-grey`,
`.container`, `.section-head`, bare `section { padding: 100px 0 }`, bare
`footer {}` (kept `.itr1-footer` as a real class instead), the global
marketing `h1`/`h2`/`h3` clamp.

## 6. Verification performed

- `manage.py check` clean; full test suite green (50/50) — no view/form/model
  logic touched, CSS and templates only.
- Rendered the returns landing page and Personal Information screen via
  Chrome DevTools Protocol (not the unreliable `--screenshot` CLI flag) at
  375px and 1440px: `document.body.scrollWidth === document.documentElement.clientWidth`
  in every case, zero elements overflow.
- `getComputedStyle(document.body).fontFamily` → `"IBM Plex Sans", "Noto Sans Devanagari", ...`
  with the Google Fonts request actually firing (network tab / no fallback
  glyphs visible in the screenshot).
- `getComputedStyle(<Confirm button>).backgroundColor` → `rgb(0, 61, 165)`.
- No element carries the marketing 100px section padding (the rule no
  longer exists in `app.css`).
- Hindi (`/set-locale/hi/`) renders Devanagari cleanly with the added font
  fallback, no overflow at the longer Hindi string lengths tested.
- `grep -oE '#[0-9a-fA-F]{3,6}' app.css` → no matches outside `tokens.css`.

## 7. Rule for future UI

New app UI is styled against `tokens.css` custom properties only. No raw
hex literals in component CSS — if a needed colour isn't a token yet, add
it to `tokens.css` (as a real semantic token, not a one-off), not inline.
