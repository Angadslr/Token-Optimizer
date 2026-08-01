# Page dependency trees

## `/` — Approval client

Entry: `src/slashtoken/web/templates/index.html`

Dependencies:

- `src/slashtoken/web/templates/index.html`
  - `src/slashtoken/web/static/styles.css`
  - `src/slashtoken/web/static/app.js`
- `src/slashtoken/web/app.py`
  - supplies `default_project`
  - serves `/static`
  - implements `/api/analyze`, `/api/optimize`, `/api/chat`, `/api/settings`, `/api/usage`, and `/ws/codex`

The template contains all visual markup. The stylesheet contains all visual tokens and responsive behavior. The JavaScript mutates text, classes, disabled states, select options, decision metrics, and streaming output but creates no additional layout outside those existing elements.
