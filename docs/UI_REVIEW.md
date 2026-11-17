# UI quality review (Phase 4C)

Date: 2026-11-15. Scope: every page in light and dark theme, desktop and 375 px phone width. The design
system (`frontend/src/styles/tokens.css`, `app.css`) was kept: only token *values* were adjusted where they
failed WCAG, and new tokens were added for new needs. Components still use tokens only.

Five passes were made, in this order:

1. **UI/UX pass** (ui-ux-pro-max checklist: accessibility → touch → layout → typography → motion → forms →
   navigation → charts). The skill's search database was not installed, so its built-in priority checklist was
   used.
2. **Design critique** of Overview, Configure and History.
3. **Accessibility review** against WCAG 2.1 AA.
4. **UX copy** for labels, errors, safety warnings and empty states.
5. **Rendered check** of every page in both themes at desktop and phone width (see "Rendered check" below).

## 1. Contrast (WCAG 1.4.3 text, 1.4.11 non-text)

Contrast was **computed**, not eyeballed. Glass surfaces were composited over the page background: light
`#f4f7f6`, dark `#141e1b`. The dark theme passed everywhere. The light theme had seven failures, all fixed by
darker steps of the same hue:

| Pair (light theme) | Before | After | Token change |
|---|---|---|---|
| Faint text (hints, table headers, timestamps) | 4.04 | 4.97 | `--text-faint` `#6b7d76` → `#5f6e69` |
| White text on primary button / active step | 3.47 | 4.76 | new `--accent-fill` `#0f8359` (hover `--accent-fill-hover`) |
| Success badge text | 2.75 | 4.65 | `--success` `#0f9d6b` → `#0f734f` |
| Warning badge text | 4.03 | 4.60 | `--warning` `#b45309` → `#a54d09` |
| Active nav item, links | 4.08 | 4.77 | `--accent-strong` `#0b7f56` → `#0b734f` |
| Form field border (1.4.11, needs 3:1) | 1.17 | 3.23 | new `--input-border` `#7d8d87` (dark `#62746d`, 3.44) |
| Focus ring (needs 3:1) | 1.66 | ≥ 3 | `--accent-ring` alpha 0.45 → 0.85 (dark 0.5 → 0.75) |

Chart colours were validated with the dataviz palette validator in Phase 4B. Status dots, chart marks and
the dark theme's focus ring were already at 3:1 or more.

## 2. Phone width (375 px) and touch targets

| Finding | Fix |
|---|---|
| The network map and the charts scaled a fixed 760 / 640 unit drawing down to the phone width. At 375 px the map nodes became about 50 × 20 px (below the 44 px touch target) and text rendered at about 5 px. | `useWidth()` (ResizeObserver) measures the panel, and the SVG draws at that width (1:1). Map tiers that do not fit **wrap onto another row**: nodes stay 132 × 46 px and labels stay 12 px. Charts show fewer date labels when narrow. |
| Wizard step labels were `display:none` at ≤ 520 px, so the step buttons had **no accessible name** (the number is `aria-hidden`). | The labels are now visually hidden but still read by screen readers. |
| Bottom navigation labels were 11 px, node and axis text 10.5–11 px. | All raised to `--text-xs` (12 px). |
| On a phone, selecting a device on the map changed a panel below the fold, so nothing seemed to happen. | The device panel scrolls into view when the panels are stacked. |

There was no page-level horizontal scroll. Wide tables scroll inside their `.table-wrap`, and the wizard step
bar and Configure tabs scroll inside their pill.

## 3. Keyboard and screen readers

| Finding | WCAG | Fix |
|---|---|---|
| Focus was lost between wizard steps: the clicked button unmounts and focus falls to `<body>`. | 2.4.3 | Focus moves to the new step's heading, including after the preview finishes loading. Tested in `Configure.test.jsx`. |
| `aria-current="step"` was on the `<li>`, not on the control. | 4.1.2 | Moved to the step button. |
| Every map node was its own Tab stop. | 2.4.3 | Roving tabindex: the map is one Tab stop. Arrow keys, Home and End move between nodes; Enter or Space selects. |
| Neighbours outside the inventory were buttons that did nothing. | 4.1.2 | `aria-disabled="true"`. |
| Map links were shown only as lines. | 1.1.1 / 1.3.1 | A visually hidden list reads each link ("sw1 Gi0/1 to sw2 Gi0/2 (cdp)"). |
| Chart columns were focusable inside `<svg role="img">` (children of an image are hidden from screen readers), giving 14 Tab stops per chart. | 4.1.2 | One Tab stop per chart. Arrow keys walk the days, and the tooltip is a live region that reads each value. Every chart also has **Show as table**. |
| The user menu used `role="menu"` without the arrow-key behaviour that role promises; Escape did not return focus. | 4.1.2 / 2.4.3 | Disclosure pattern (`aria-expanded` button + list of links); Escape closes it and returns focus to the button. |
| Smooth scrolling ignored reduced motion. | 2.3.3 (AAA, kept anyway) | `reveal()` scrolls instantly when `prefers-reduced-motion: reduce` is set. |
| The Overview dimmed everything every 30 s during the background refresh (a flicker). | — | The background refresh swaps the numbers in place; only **Check status now** shows a busy state. |

## 4. Design critique (Overview, Configure, History)

- **Configure, step 1:** the three target types were three *primary* buttons, so the selected type looked
  like the main call to action. They are now a segmented control, and the only primary action is picking a
  target.
- **Production tag:** red (`danger`) in Configure and amber (`warning`) elsewhere. It is now amber
  everywhere, because "production" means *take care*, not *error*.
- **History:** status moved next to the device name, where the eye looks first.
- **Overview:** the device panel's empty state repeated its subtitle. One empty state now explains what
  selecting a device shows.
- Kept as they were: the KPI → map → charts reading order, the 5-step wizard with the commands preview
  before anything is sent, and the masked command and transcript panels.

## 5. Copy

- **One term per concept:** a push record is a **job** everywhere (Overview said "changes", History said
  "pushes").
- **Wizard step 4** is "Create job" (it was "Approval", but most jobs need no approval). The button before
  it is "Continue to create the job".
- **Safety warnings** say what happens and what to do:
  - **Telnet:** one shared wording (`TELNET_WARNING` in `lib/labels.js`) instead of four different ones.
  - **Custom commands on production devices:** explains why they are off and what to use instead.
  - **Rolled back:** says the device is back on its previous configuration.
- **Empty states** follow "what this is, why it is empty, how to start" (devices, catalog, audit, Overview).
  The 404 page no longer says "This page arrives in no phase"; it links to the Overview.
- **Session expiry** names the two limits (30 minutes idle, 8 hours in total).
- **Backend errors** that did not say how to fix the problem were rewritten:
  - status checks turned off;
  - experimental driver on a production device;
  - missing plan secrets;
  - a job that can no longer be run.

## Rendered check

The production build (`ENV=production`, FastAPI serving `dist/` with the real CSP) was driven with headless
Microsoft Edge (Playwright). A temporary admin was signed in. **12 pages × 2 themes × 2 widths = 48 views**:
Overview, Devices, Configure, Router link, First-time setup, Catalog, History, Your account, Users, Audit
log, SSH host keys and the 404 page, each in light and dark at 1280 × 800 and 375 × 812.

On every view the script checked:
- no horizontal page scroll;
- no console errors;
- every visible control is at least 44 px tall, including the `::after` hit area of `.btn.small`;
- the theme background matches the colour scheme.

The screenshots were also looked at by eye. The temporary admin and its sessions were deleted afterwards.

The first run found three problems. All are fixed:

| Finding | Cause | Fix |
|---|---|---|
| **CSP violation on every page**: "Loading the font 'data:font/woff2…' violates font-src 'self'". | Vite inlines assets under 4 KB as `data:` URIs, including one small Inter subset. | `build.assetsInlineLimit` never inlines `.woff2` (`vite.config.js`). The CSP stays strict. |
| The logo icon sat dark in the top-left corner of its green square. | `.brand span { display:block; color: muted }` is more specific than `.brand-mark`, so it overrode the grid centring and the icon colour. | Selector raised to `.brand .brand-mark`. |
| A focus ring was drawn around the whole page content after navigation. | `<main tabindex="-1">` takes focus on each page change (for screen readers), and Chromium shows `:focus-visible` on it. | No ring on `main[tabindex='-1']`, the same rule the wizard step headings already use. |

The mobile brand link was also raised to a 44 px minimum height.

**Final run: 48 / 48 views pass.**

Not covered: the wizard's later steps and job progress need a device in the inventory. Those steps are
covered by the Vitest tests (`Configure.test.jsx`, `Push.test.jsx`, `Wizards.test.jsx`).
