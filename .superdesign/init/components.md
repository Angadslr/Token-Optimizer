# Shared UI components

SlashToken does not use a component framework or shared component directory. The current UI is a single Jinja template in `src/slashtoken/web/templates/index.html`, styled by one vanilla CSS file and driven by one vanilla JavaScript file.

There are no standalone shared primitives such as Button, Input, Card, Select, Checkbox, Table, or Tabs to include here. The reusable visual patterns are CSS classes documented in `theme.md`, while the full page shell is included in `layouts.md`.
