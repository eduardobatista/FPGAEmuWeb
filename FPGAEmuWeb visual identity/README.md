# Handoff: FPGAEmuWeb logo and light restyle

## Overview
This package adds a new logo (the "Chip" mark plus the FPGAEmuWeb wordmark) and a light visual restyle of FPGAEmuWeb, a Flask + Bulma app. It covers five screens: Login, Projects, Editor, Emulation and Simulation. The interface language is English.
Target branch: `block-diagram` (https://github.com/eduardobatista/FPGAEmuWeb/tree/block-diagram). The design was made without reading that branch, so check `templates/` and `static/` on the branch and adapt this design to whatever is there, including the block-diagram feature.

## About the design files
The files in `design_reference/` are **HTML design references**: prototypes that show the intended look and behavior. They are not production code. To view them, open `design_reference/FPGAEmuWeb Identity.dc.html` in a browser and keep `support.js` and `Logo.dc.html` in the same folder.
**Task:** restyle the existing Jinja templates and Bulma markup to match the reference. Keep the routes, forms, JS and backend unchanged. This is a restyle only: no framework change and no new features.

## Fidelity
**High fidelity.** Colors, type, spacing, radii and copy are final. Match them, using Bulma classes plus `fpgaemu-theme.css`.

## Suggested implementation steps
1. Copy `fpgaemu-theme.css` to `static/css/` and load it in the base template **after** Bulma.
2. Copy `assets/*` to `static/img/`. In `<head>`, add:
   ```html
   <link rel="icon" href="{{ url_for('static', filename='img/favicon.svg') }}" type="image/svg+xml">
   <link rel="icon" href="{{ url_for('static', filename='img/favicon-32.png') }}" sizes="32x32">
   <link rel="apple-touch-icon" href="{{ url_for('static', filename='img/apple-touch-icon.png') }}">
   ```
3. Replace the navbar brand with `logo-horizontal.svg` at 26px tall. Alternatively, use the inline mark followed by an HTML wordmark (see Logo below).
4. Restyle each template screen by screen (see Screens). Keep the existing element IDs and JS hooks intact.
5. Check the Ace editor theme (see Editor) and the Surfer iframe sizing (see Simulation).

## Design tokens
Fonts: **IBM Plex Sans** (UI) and **IBM Plex Mono** (code, file names, signal labels, logs, numeric values). Both load from Google Fonts.

| Token | Hex | Use |
|---|---|---|
| accent | #048149 | Primary buttons, active states, logo die |
| accent-hover | #006f38 | Primary button hover |
| accent-dark-bg | #4bc680 | Logo accent on dark backgrounds |
| accent-tint | #e5f7eb | Selected list row |
| focus-ring | #cbefd6 | 3px input focus shadow |
| link / link-hover | #00723b / #005a25 | Links |
| ink | #161a19 | Primary text, logo |
| text-2 | #4a5350 | Body text in logs |
| muted | #5b6461 | Secondary text, inactive nav |
| faint | #8a928f | Captions, section labels, line numbers (#b5bcb9) |
| bg | #f5f6f5 | App background |
| surface | #ffffff | Navbar, cards, panels |
| surface-2 | #f8f9f8 | Table header, output panel |
| nav-active | #eef1ef | Active nav pill, file-type chip |
| border | #e1e4e2 | Panel borders |
| border-input | #cfd5d2 | Inputs and secondary buttons |
| danger | #ba2b2e | Stop emulation, delete links (#b63132) |
| warning | #ee921a | Unsaved dot, "simulating" status |
| success tag | bg #ddf6e4 / fg #005f2e | "Compiled" |
| error tag | bg #ffe7e4 / fg #a5292b | "Errors" |

Radii: buttons 7px, inputs 8px, panels 10–12px, tags 20px (pill), app icon 14/64.
Type scale: page title 26–30px/600 · section 20px/600 · body 14–15px · labels 12–13px · board labels 10px mono.
Spacing: navbar 60px tall with 24px side padding · toolbars 56–60px · panel padding 20–28px · gaps 8 / 12 / 16 / 24.
No shadows except on board controls (see Emulation).

## Logo
- The mark is drawn on a 64×64 grid: 12 pins (3 per side, 4×9, rx 1.5), a 40×40 body (rx 7) in ink, a pin-1 dot (r 2.5) in white, and a 16×16 die (rx 3) in accent.
- Files: `logo-mark.svg`, `logo-mark-dark.svg`, `logo-horizontal.svg`, `logo-horizontal-dark.svg`, `favicon.svg`, `app-icon.svg`, `favicon-16.png`, `favicon-32.png`, `apple-touch-icon.png`.
- Wordmark: "FPGA" in Plex Sans 700, "Emu" in 400, "Web" in 600 accent, letter-spacing -0.02em, text height ≈ 0.52 × mark size, gap ≈ 0.3 × mark size.
- The horizontal SVGs use live `<text>`. Convert them to outlines if they will be used outside the app, or build the wordmark in HTML.

## Screens
All app screens share the same navbar: white, 60px tall, bottom border #e1e4e2, logo at 26px, then nav pills (Projects · Editor · Emulation · Simulation, 14px, padding 8×12, radius 7). The active pill uses bg #eef1ef with ink 500. On the right sit the user email (14px muted) and a 32px avatar circle (#e1e6e3).

### S1 Login
- Two equal columns.
- **Left column** (padding 48×64): logo at 34px at the top, then a form block vertically centered (max 380px):
  - "Sign in" at 30px/600;
  - subtitle "Use the account provided by your instructor." at 15px muted;
  - Email and Password inputs, 44px tall, with 14px/500 labels and a 7px gap;
  - a full-width primary button, 46px tall.
  - Footer credit at 13px faint.
- **Right column:** bg #f3f5f4 with a left border, holding the mark at 140px, "VHDL emulation and simulation in the browser" at 22px/600, and "edit · analyze · compile · emulate · simulate" at 13px mono muted.

### S2 Projects
- Grid with a 400px left list and a fluid detail area.
- **List:** "Projects" at 20px/600 and a "New project" primary button (34px tall). Each row has 12px padding and radius 8. The selected row uses bg accent-tint. Each row shows a status dot (accent = compiled, #c3c9c6 = not compiled, danger = errors), the name in 14px mono 500, and meta in 12px faint ("4 files · compiled 2 h ago").
- **Detail:**
  - "Project" caption, then the name in 26px mono 600, plus a status tag.
  - Buttons on the right: Upload, New file, Compile (secondary) and Go to Emulation (primary).
  - A file table inside a white card (radius 10): columns File / Size / Modified / Actions (Edit, Rename, Delete in danger). Each file row has a "VHD" chip (11px mono 600, bg #eef1ef).
  - A hint under the table: "The top-level entity must be in usertop.vhd."

### S3 Editor
- Navbar, then a 56px toolbar:
  - breadcrumb `project / file.vhd` in mono, followed by an 7px warning dot when the file is unsaved;
  - on the right: Templates, Save, Analyze current file | Compile, and Go to Emulation (primary).
- Body: a 220px file sidebar (section label "FILES", 13px mono items, the active one in accent-tint) next to the Ace editor.
- **Ace theme:** white background, Plex Mono at 13.5px with 21px line-height, gutter numbers in #b5bcb9, active line #effaf2. Syntax colors: keywords #5040a8 (weight 500), types #006d78, strings and numbers #a64b00, functions #006c35, comments #8a928f.
- Bottom output panel, 150px tall, on bg #f8f9f8: an "Output" header, GHDL commands with a "$" prompt in faint, and the success line in link green.

### S4 Emulation
- Fluid main area next to a 300px right sidebar.
- **Toolbar:**
  - Start emulation (primary, with a white dot icon), which becomes Stop emulation (danger, with a square icon);
  - Reset inputs (secondary);
  - a status on the right: a dot plus "running · N cycles" or "stopped" in mono.
- **Board:** a white card (radius 12, padding 26×28) with three rows spread vertically.
  - **HEX7–HEX0:** 8 seven-segment digits on a dark plate (#1a1d1c, radius 10). Each digit is 36×62 with 5px segments; lit segments are #fc4447 and unlit ones #2d2726. A 10px mono label sits under each digit.
  - **LEDR17–0 and LEDG7–0:** 14px circles. Off: #e6e9e7 with an inset shadow. On: red #f1383e or green #0fbd59, with a `0 0 8px` glow in the same color.
  - **SW17–0 and KEY3–0:**
    - Switches: a 20×42 track (radius 6, border #cfd5d2) with an 18px knob. When on, the knob is at the top in accent and the track turns #e5f7eb; when off, the white knob sits at the bottom.
    - Keys: 44px squares (radius 9) with a 20px dark cap. At rest they show a `0 2px 0 #cfd5d2` shadow; while pressed they switch to an inset shadow.
  - Group labels are 12px mono muted, letter-spacing .06em.
- **Sidebar sections:** each starts with an uppercase 12px label.
  - Inputs: SW hex, SW bin, KEY bin.
  - Design: Project, Top, Compiled.
  - Log: mono at 12px.

### S5 Simulation
- Navbar, then a 60px toolbar:
  - Testbench select (mono value);
  - Stop time field (value + unit);
  - Run simulation (primary; shows "Running…" while busy);
  - a status (dot + "no results yet" / "simulating…" / "done · 2 us · 14:36");
  - on the right: Download VCD and Open in new tab (secondary).
  - Every toolbar item is `white-space:nowrap; flex:none`.
- The body is the embedded **Surfer** iframe, filling the rest of the screen: padding 16×20×20, border #d6dbd8, radius 10. Load the VCD from the last run. Do not restyle Surfer itself.

## Interactions and state
- Projects: clicking a project selects it and updates the detail pane.
- Editor: clicking a file switches it; keep the existing save and dirty-state logic.
- Emulation: these behaviors already exist in the app, so only restyle them.
  - Switches toggle on click.
  - Keys are active while held down (mousedown sets the key, mouseup or mouseleave releases it).
  - Start and Stop toggle the run state.
  - Reset clears the inputs.
- Simulation: Run sets the busy state, and finishing loads the Surfer view.
- Hover on secondary buttons uses bg #f2f4f3; hover on primary buttons uses accent-hover. Inputs get the accent border plus a 3px focus ring.

## Files
- `fpgaemu-theme.css`: tokens and Bulma overrides (navbar, box, button, input, table, tag).
- `assets/`: logo, favicons and app icon.
- `design_reference/FPGAEmuWeb Identity.dc.html`: all logo options and the 5 screens. Board, list and editor rendering logic is at the bottom of the file.
- `design_reference/Logo.dc.html`: the parametric logo (use `variant="chip"`).
