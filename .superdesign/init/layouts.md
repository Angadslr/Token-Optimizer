# Shared layouts

## Approval client shell

- Path: `src/slashtoken/web/templates/index.html`
- Description: The sole page and application shell. It renders the top status bar, routing controls, prompt composer, route comparison and receipt panels, and the Codex output stream.

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>SlashToken</title>
    <link rel="stylesheet" href="{{ url_for('static', path='styles.css') }}">
  </head>
  <body>
    <header class="topbar">
      <div>
        <p class="eyebrow">Verified multilingual routing</p>
        <h1>SlashToken</h1>
      </div>
      <span id="connection" class="status status-warn">Connecting to Codex…</span>
    </header>

    <main>
      <section class="card controls-card">
        <div class="field grow">
          <label for="project">Project</label>
          <input id="project" value="{{ default_project }}">
        </div>
        <div class="field model-field">
          <label for="model">Codex model</label>
          <select id="model"><option value="">Loading models…</option></select>
        </div>
        <label class="toggle">
          <input id="languageOptimization" type="checkbox" checked>
          <span>Language optimization</span>
        </label>
        <label class="toggle">
          <input id="outputOptimization" type="checkbox">
          <span>Output optimization</span>
        </label>
        <div class="field mode-field">
          <label for="mode">Workload</label>
          <select id="mode">
            <option value="agentic_coding">Agentic coding</option>
            <option value="chatbot">Chatbot</option>
          </select>
        </div>
      </section>

      <section class="card composer-card">
        <div class="section-heading">
          <div>
            <p class="eyebrow">Pre-Codex input</p>
            <h2>Write in your language</h2>
          </div>
          <button id="optimize" class="primary">Analyze and optimize</button>
        </div>
        <textarea id="prompt" rows="9" placeholder="Enter a Chinese, Arabic, or Turkish prompt. SlashToken will never submit it before approval."></textarea>
        <p id="message" class="message">Nothing is sent to Codex until you approve a route.</p>
      </section>

      <section id="decision" class="decision-grid hidden">
        <article class="card comparison-card">
          <div class="panel-title">
            <h2>Original</h2>
            <span id="originalTokens" class="metric"></span>
          </div>
          <pre id="originalPrompt"></pre>
          <button id="useOriginal" class="secondary">Use original</button>
        </article>
        <article class="card comparison-card">
          <div class="panel-title">
            <h2>Verified candidate</h2>
            <span id="candidateTokens" class="metric"></span>
          </div>
          <textarea id="candidatePrompt" rows="13"></textarea>
          <button id="useCandidate" class="primary">Approve candidate</button>
        </article>
        <aside class="card receipt-card">
          <p class="eyebrow">Decision receipt</p>
          <h2 id="decisionStatus">Waiting</h2>
          <p id="receipt"></p>
          <dl id="decisionMetrics"></dl>
          <button id="autoSession" class="text-button">Auto-run verified prompts this session</button>
          <button id="autoProject" class="text-button">Remember auto-run for this project</button>
        </aside>
      </section>

      <section class="card output-card">
        <div class="section-heading">
          <div>
            <p class="eyebrow">Codex stream</p>
            <h2>Activity and result</h2>
          </div>
          <button id="interrupt" class="danger" disabled>Interrupt</button>
        </div>
        <pre id="output">Ready.</pre>
      </section>
    </main>
    <script src="{{ url_for('static', path='app.js') }}" defer></script>
  </body>
</html>
```
