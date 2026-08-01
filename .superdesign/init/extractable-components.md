# Extractable components

The application is a single vanilla HTML page, so these are semantic regions rather than existing standalone source components. They should remain inline for the current single-page MVP; extraction into Superdesign components is unnecessary.

## TopBar
- Source: `src/slashtoken/web/templates/index.html`
- Category: layout
- Description: Product identifier, routing descriptor, and live Codex connection state.
- Extractable props: connectionState (string, default: "connecting")
- Hardcoded: SlashToken name, verified multilingual routing label, CSS classes.

## RoutingControls
- Source: `src/slashtoken/web/templates/index.html`
- Category: basic
- Description: Project, model, workload, and optimization settings row.
- Extractable props: none; values are bound by element ids in `app.js`.
- Hardcoded: labels, option text, element ids, CSS classes.

## PromptComposer
- Source: `src/slashtoken/web/templates/index.html`
- Category: basic
- Description: Multilingual prompt input and analyze action.
- Extractable props: none; state is bound by element ids in `app.js`.
- Hardcoded: label, placeholder, action text, CSS classes.

## RouteDecisionWorkspace
- Source: `src/slashtoken/web/templates/index.html`
- Category: layout
- Description: Original and verified candidate comparison beside the routing receipt.
- Extractable props: none; all values are populated by `renderDecision` in `app.js`.
- Hardcoded: panel titles, approval actions, CSS classes.

## CodexOutput
- Source: `src/slashtoken/web/templates/index.html`
- Category: layout
- Description: Streaming activity terminal with interrupt control.
- Extractable props: none; output and state are bound by element ids in `app.js`.
- Hardcoded: labels, initial Ready state, CSS classes.
