# Design

How Inspectra looks and why. The tokens live in `app/static/css/tokens.css`; page styles add only what is specific to them.

## Principle

A tool for people working: a manager at a desk (wide screen first) and an inspector on a street with one hand free
(phone, bright daylight). Clear numbers, calm surfaces, one accent colour. Brand lives in the details, not in decoration.

## Colour

| Token | Light | Use |
| --- | --- | --- |
| `--accent` / `--accent-strong` / `--accent-tint` | `#1b74c4` / `#0d5fae` / `#e6f0fa` | actions, links, selection |
| `--navy` (`--rail-bg`) | `#0b2540` | the manager's side rail |
| `--ink`, `--ink-soft`, `--ink-faint` | `#0e1a2b`, `#3b4c63`, `#5a6b81` | text, all at least 4.5:1 on the surfaces |
| `--surface`, `--surface-sunk`, `--bg`, `--line` | white, `#f5f8fb`, `#f3f6fa`, `#e1e8f0` | cards, wells, page, borders |
| `--live`, `--warn`, `--bad` (+ `-tint`) | green, amber, red | state only: online, needs attention, error |

A dark theme redefines the same tokens (`:root[data-theme="dark"]`); both the manager pages and the field app follow it.
Never use a hard-coded hex in a page stylesheet when a token exists.

## Type

Heebo (Hebrew), Noto Sans Arabic, Montserrat (Latin and Cyrillic). Numbers are always Latin digits and 24-hour time.
Nothing smaller than 13 px in the field app.

## Layout

- **Manager pages:** a fixed navy rail on the inline-start side, content up to a readable width, KPI strips and cards.
  Below ~900 px the rail becomes a top bar with a bottom tab bar.
- **Login and sign-up:** one centred card, logo on top, a quiet language button in the card's corner; sign-up is two
  columns from 560 px.
- **Field app:** full-screen map, a bottom sheet with three snap points, controls (menu, zoom, recentre) stacked at the
  thumb's edge, 44 px or larger targets.

## Behaviour

- Right-to-left is a first-class layout (logical properties, `dir` set on the server).
- Errors are shown next to the thing that failed and announced (`role="alert"`); success is a short toast.
- Dialogs trap focus, close with Escape, and ask before discarding typed input.
- Motion is short and decorative only; `prefers-reduced-motion` is respected.
