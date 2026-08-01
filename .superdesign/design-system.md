# SlashToken operator console design system

## Product context

SlashToken is a local multilingual LLM gateway. Its single approval client lets a developer configure a Codex route, submit a Chinese, Arabic, or Turkish prompt for analysis, inspect the unchanged and verified paths, approve exactly one path, and watch the Codex event stream. The interface must communicate that optimization is optional, measured, privacy-conscious, and reversible.

The primary job is evidence-based routing, not generic translation. The UI must make route state, fallback reasons, token economics, protected-span checks, and the final approval boundary easy to inspect.

## Visual direction

Use the density and visual grammar of browser developer tools and an editor terminal:

- Dark neutral chrome with thin 1px separators and square panel geometry.
- Dense tabs, compact toolbars, split panes, table-like metric rows, gutter labels, and terminal status bars.
- Monospace-first typography throughout. Use `ui-monospace, "SFMono-Regular", Menlo, Monaco, Consolas, "Liberation Mono", monospace` only.
- Minimal decoration: no large rounded cards, gradients, soft shadows, glass effects, illustrations, or oversized marketing headings.
- Use syntax-highlighting colors sparingly to encode meaning: blue for active/interactive state, cyan for identifiers and paths, green for verified/success state, amber for warnings and savings decisions requiring review, red for errors/interrupts, purple for numeric values and metadata.
- The result should feel like a precise local development instrument even when the workflow is simple.

## Color tokens

- `--bg-root: #1e1e1e` — application background.
- `--bg-chrome: #252526` — top tab strip and toolbars.
- `--bg-panel: #202020` — primary work areas.
- `--bg-input: #181818` — editor and terminal input surfaces.
- `--bg-hover: #2a2d2e` — hover and selected table row background.
- `--line: #3f3f46` — all panel, toolbar, and field separators.
- `--line-strong: #56565c` — focused or emphasized separators.
- `--text: #d4d4d4` — primary UI text.
- `--text-strong: #f0f0f0` — active titles and high-priority values.
- `--text-muted: #969696` — inactive tabs, labels, and explanatory text.
- `--blue: #75a7ff` — active tab underline, focus, primary action.
- `--cyan: #4fc1ff` — project paths, route ids, model identifiers.
- `--green: #89d185` — connected, verified, approved.
- `--amber: #cca700` — analyzing, pending, warning.
- `--orange: #ce9178` — strings and human-entered prompt content.
- `--red: #f14c4c` — errors and interrupt.
- `--purple: #b180d7` — token counts, percentages, costs, numeric metadata.

## Typography

- Use the single monospace stack defined above for every element.
- Base size: 13px desktop, 12px for metadata, labels, status, and controls.
- Page/product label: 13px, weight 600; do not use a large hero title.
- Panel titles and tabs: 12–13px, weight 500–600.
- Terminal/editor content: 13px, line-height 1.55.
- Labels may use lowercase or path-like notation such as `route.input`, `decision.receipt`, and `codex.stream`.

## Geometry and spacing

- Border radius: 0 by default; 2–3px only on compact controls where needed.
- Separator: 1px solid `--line` between every structural region.
- No card shadows.
- Toolbar height: 34–40px.
- Tab height: 36px.
- Compact control height: 30–32px.
- Panel padding: 10–14px; editor padding includes a 36px gutter.
- Use 4px, 6px, 8px, 12px, 16px, and 20px spacing increments.
- Application should use the viewport width with at most 12px outside padding, not a centered marketing container.

## Page architecture

1. Top tab strip: product mark at left; tabs such as `Router`, `Decision`, and `Console`; connection status and session id at right.
2. Configuration toolbar: project path as a location field, model selector, workload selector, and compact checkbox-style flags.
3. Main workspace: prompt editor as the primary upper pane with line-number gutter and an integrated `analyze()` action.
4. Decision workspace: when available, a split-pane comparison for `original.route` and `verified.candidate`, with the decision receipt in an inspector sidebar. Use table rows for metrics rather than decorative statistic cards.
5. Bottom console: persistent terminal-like Codex stream with a tab header, small state indicator, and interrupt action.
6. Footer/status bar: privacy/approval boundary, session state, and supported-language hint.

## Controls

- Inputs/selects: `--bg-input`, 1px border, compact padding, no large radius. Focus uses a blue border or 1px inset outline, never a glow.
- Checkboxes: native or square 14px controls, blue when checked.
- Primary action: blue text/border on dark background or restrained solid blue with dark text; compact, squared, and code-like (`analyze()` or `approve(candidate)`).
- Secondary action: transparent dark background with gray border.
- Danger action: red text and border; solid fill only during active destructive state.
- Disabled: muted foreground with 45% opacity.

## Interaction and motion

- Use 100–140ms color/background transitions only.
- Active tabs receive a 2px bottom blue line.
- Resizable-pane affordances may be implied by 1px splitters, but the MVP need not implement dragging.
- Preserve all existing focus visibility and keyboard accessibility.
- Responsive behavior: below 980px stack the comparison panes while keeping the inspector metrics table; below 680px allow toolbar wrapping and full-width prompt/console panes.

## Content and state rules

- Do not imply that a route is verified before the existing pipeline returns `candidate` status.
- Keep `Original` visually available as the safe fallback.
- Treat the receipt as an inspection artifact: show language, savings, protected spans, optimizer cost, eligibility, and threshold version as structured properties.
- Raw prompt content and stream output use editor/terminal surfaces; do not style them as prose cards.
- Keep the explicit statement that nothing is sent until approval.
- Do not add invented benchmark values or unsupported claims.
