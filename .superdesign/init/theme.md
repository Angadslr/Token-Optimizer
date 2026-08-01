# Theme

## Part 1 — Compact token summary

- CSS approach: vanilla global CSS in `src/slashtoken/web/static/styles.css`; no Tailwind or component library.
- Color scheme: light only via `color-scheme: light`.
- Canvas: `#f3f5ef`; surface: `#ffffff`; primary ink: `#17211b`; muted text: `#657269`; line: `#dce2da`.
- Accent: `#256d46`; dark accent: `#174b31`; soft accent: `#e6f2e9`.
- Warning: `#8a5b00`; danger: `#a32929`; terminal: background `#111a15`, text `#dceade`.
- Fonts: Inter/system sans for interface text; `ui-monospace, SFMono-Regular, Menlo, monospace` for preformatted output.
- Type: h1 `30px`; h2 `20px`; labels/metrics `13px`; eyebrow/status `12px`.
- Spacing: page gaps `18px`; card padding `20px`; controls gap `16px`; form padding `11px 12px`.
- Radius: cards `16px`; controls/buttons/pre blocks `10px`; status pills `999px`.
- Shadow: cards `0 10px 35px rgba(23, 33, 27, .05)`.
- Breakpoints: decision receipt spans at `1040px`; single-column mobile layout and full-width buttons at `720px`.

## Part 2 — Raw source

### `src/slashtoken/web/static/styles.css`

```css
:root {
  color-scheme: light;
  --ink: #17211b;
  --muted: #657269;
  --surface: #ffffff;
  --canvas: #f3f5ef;
  --line: #dce2da;
  --accent: #256d46;
  --accent-dark: #174b31;
  --accent-soft: #e6f2e9;
  --warn: #8a5b00;
  --danger: #a32929;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

* { box-sizing: border-box; }
body { margin: 0; background: var(--canvas); color: var(--ink); }
.topbar { display: flex; align-items: center; justify-content: space-between; padding: 24px max(24px, calc((100vw - 1440px) / 2)); background: var(--ink); color: white; }
h1, h2, p { margin-top: 0; }
h1 { margin-bottom: 0; font-size: 30px; letter-spacing: -0.04em; }
h2 { margin-bottom: 0; font-size: 20px; }
.eyebrow { margin-bottom: 6px; color: #7cad8e; font-size: 12px; font-weight: 800; letter-spacing: .11em; text-transform: uppercase; }
main { width: min(1440px, calc(100% - 32px)); margin: 24px auto 64px; display: grid; gap: 18px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; box-shadow: 0 10px 35px rgba(23, 33, 27, .05); padding: 20px; }
.controls-card { display: flex; align-items: end; gap: 16px; flex-wrap: wrap; }
.grow { flex: 1 1 340px; }
.model-field { flex: 1 1 250px; }
.mode-field { min-width: 170px; }
.field { display: grid; gap: 7px; }
label { color: var(--muted); font-size: 13px; font-weight: 700; }
input, select, textarea { width: 100%; border: 1px solid #bdc8be; border-radius: 10px; background: #fbfcfa; color: var(--ink); font: inherit; padding: 11px 12px; }
textarea { resize: vertical; line-height: 1.55; }
input:focus, select:focus, textarea:focus { outline: 3px solid rgba(37, 109, 70, .16); border-color: var(--accent); }
.toggle { display: flex; gap: 9px; align-items: center; min-height: 42px; white-space: nowrap; }
.toggle input { width: 18px; height: 18px; accent-color: var(--accent); }
.section-heading, .panel-title { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
button { border: 0; border-radius: 10px; cursor: pointer; font: inherit; font-weight: 800; padding: 11px 16px; }
button:disabled { cursor: not-allowed; opacity: .45; }
.primary { background: var(--accent); color: white; }
.primary:hover { background: var(--accent-dark); }
.secondary { background: var(--accent-soft); color: var(--accent-dark); }
.danger { background: #fbe6e6; color: var(--danger); }
.text-button { width: 100%; margin-top: 9px; background: transparent; border: 1px solid var(--line); color: var(--accent-dark); }
.message { margin: 12px 0 0; color: var(--muted); }
.decision-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(260px, .62fr); gap: 18px; }
.hidden { display: none; }
.comparison-card { display: flex; flex-direction: column; min-height: 390px; }
.comparison-card pre, .comparison-card textarea { flex: 1; }
pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; line-height: 1.5; }
.comparison-card pre { border: 1px solid var(--line); border-radius: 10px; background: #fbfcfa; padding: 12px; margin-bottom: 14px; }
.comparison-card textarea { margin-bottom: 14px; }
.metric { color: var(--accent-dark); font-size: 13px; font-weight: 800; }
.receipt-card { background: #f8fbf7; }
.receipt-card dl { display: grid; grid-template-columns: 1fr auto; gap: 9px; margin: 20px 0; font-size: 13px; }
.receipt-card dt { color: var(--muted); }
.receipt-card dd { margin: 0; font-weight: 800; }
.output-card pre { min-height: 180px; max-height: 560px; overflow: auto; border-radius: 10px; background: #111a15; color: #dceade; padding: 16px; }
.status { border-radius: 999px; padding: 7px 11px; font-size: 12px; font-weight: 800; }
.status-ok { background: #d8f0df; color: #124c2d; }
.status-warn { background: #fff0c8; color: var(--warn); }
@media (max-width: 1040px) { .decision-grid { grid-template-columns: 1fr 1fr; } .receipt-card { grid-column: 1 / -1; } }
@media (max-width: 720px) { .topbar { padding: 20px; } .decision-grid { grid-template-columns: 1fr; } .receipt-card { grid-column: auto; } .section-heading { align-items: flex-start; flex-direction: column; } button { width: 100%; } }
```

There is no Tailwind configuration or separate theme-provider source.
