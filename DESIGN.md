# mediQ: design system

The visual rules every page follows. The tokens live at the top of `frontend/style.css`;
`/design.html` shows them all, in light and dark. Product truth is in PRODUCT.md.
Guidance followed: impeccable (pbakaus/impeccable) and tasteskill (Leonxlnx/taste-skill),
applied by hand (their bundled scripts are not run in this project).

## The world: "night sky over a clear horizon"

Taken from the home hero the owner chose (a horizon of text characters glowing from cobalt
to ice on night navy). Calm, precise, clinical without being sterile.

| Token | Light | Dark | Job |
|---|---|---|---|
| `--night` | `#050b1f` | same | hero ground, waiting-room board, dark page |
| `--ink` | `#0b1533` | same | text (light mode), deepest surfaces |
| `--cobalt` | `#1e3fd8` | same | **the** brand colour: links, main action, selection |
| `--sky` / `--ice` | `#38bdf8` / `#a5d8ff` | same | bright accents, only on dark grounds |
| `--page` | `#f3f6fc` | `#050b1f` | the page |
| `--surface` | `#ffffff` | `#0c1636` | cards, tables, panels |
| `--tint` | `#e8eefc` | `#13224f` | selected / highlighted / info |
| `--text-muted` | `#4b5876` | `#a3b2d8` | secondary text (7.1:1 / 8.4:1) |
| `--border` / `--border-input` | `#d9e0ee` / `#7f8cab` | `#1f2d5a` / `#5d6fa3` | dividers / fields (≥3:1) |
| `--appbar` | `#0a1640` | `#08122f` | app bar and website header |
| `--action` | cobalt | `#3657f0` | the one main button per screen |
| `--error` | `#b3261e` | `#ff9b93` | errors |
| `--focus` | `#ffd60a` + dark inner ring | same | keyboard focus, always visible |

**Colour strategy.** Restrained on working screens (tinted neutrals + cobalt doing real jobs:
the main action, selection, links, "in consultation"). Committed on the home page: night navy
and the horizon own the first screen.

**Light or dark.** Patients read on phones in daylight and bright waiting rooms; staff work in
bright clinical rooms: **light by default**, dark when the device asks (toggle in the app bar).
The hero and the waiting-room board are dark in both.

## Type

- **Geist** for everything (400 / 500 / 600 / 700), **Noto Sans Devanagari** behind it for Hindi.
- **Geist Mono** only for codes and measurements: token numbers (GEN-014), wait minutes on the
  hero, the board. Never as a "technical" costume.
- Scale: 14 / 16 / 19 / 24 / 32 / 48, the hero headline up to 72px with -0.035em tracking.
  Patient pages use 19px body; staff pages 16px.

## Shape, space, depth, motion

- Radius 6px for controls and cards; 12px (`--radius-lg`) only for the two floating pieces of the
  app frame (sidebar and app bar). Spacing on a 4px grid, more space above a heading than below it.
- One shadow (`--shadow-pop`), only for things that float (menus, toasts). Everything else is
  border + surface.
- Motion 150-250ms, `cubic-bezier(.2,.7,.2,1)`. The hero's horizon is the page's one authored
  moment. "Reduce motion" turns all motion off.

## Bans (each checked by tests/test_design_system.py where it can be)

- **No stripe down one side of a box** (no `border-left: 4px`, no inset side shadow). Use a full
  border, a tint, or a leading icon.
- **No small label above a heading** ("eyebrow").
- No gradient text, no decorative glass/blur, no hard offset shadows.
- No unicode or emoji standing in for icons: drawn SVG icons, one stroke weight.
- No invented numbers presented as real (the hero shows the live queue).
- No same-size icon-card grids as page structure on the website.
- No violet or lavender.

## The app frame (signed-in pages)

- **Floating sidebar** (`frontend/shell.js`): navy like the app bar, 12px in from the edges. Groups:
  My care, Doctor, Hospital, Pharmacy, Admin, showing only what your role can open. Folds to icons
  (names become tooltips); the choice is remembered. Below 900px it is a drawer behind the app
  bar's menu button (Esc or the backdrop closes it).
- **Light/dark switch on every page**: in the app bar on app pages, beside search in the website header.

## Charts (dashboard.html)

- Plain SVG/HTML drawn by `dashboard.js`, no chart library. Real numbers only.
- One hue (cobalt) for magnitude; the current hour / today is the solid bar, the rest a lighter step.
- Parts of a whole use **green, cobalt, amber, red** in that order (red never touches green),
  checked for colour-blind readers in light and dark (`--c-*` tokens; dark has its own steps).
- Status (amber = needs attention, red = critical) always comes with an icon and a word.
- Every axis chart has "Show as a table"; every bar has a hover/focus tooltip.

## Components

All from `ui-*` classes in style.css (buttons, fields, pills, messages, tables, app bar). Status
is always an icon **and** a word, never colour alone. Messages: full tinted border by type
(info cobalt, success green, error red).
