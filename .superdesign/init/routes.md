# Routes

SlashToken uses FastAPI rather than a client-side router. All browser-visible UI is served by `src/slashtoken/web/app.py`; there is one HTML route and supporting API/WebSocket routes.

| URL | Method | Handler | UI use |
| --- | --- | --- | --- |
| `/` | GET | `index` | Renders `src/slashtoken/web/templates/index.html` with the current working directory as `default_project`. |
| `/static/*` | GET | FastAPI `StaticFiles` | Serves `styles.css` and `app.js`. |
| `/api/analyze` | POST | `analyze` | Returns language, risk, protected spans, and original token evidence. |
| `/api/optimize` | POST | `optimize` | Produces the candidate, receipt, route state, metrics, and auto-run eligibility. |
| `/api/chat` | POST | `chat` | Executes an explicitly selected route through the configured provider. |
| `/api/settings` | GET | `get_settings` | Returns resolved user/project/session settings. |
| `/api/settings` | PATCH | `patch_settings` | Updates settings for the requested scope. |
| `/api/usage` | GET | `usage` | Returns aggregate usage. |
| `/ws/codex` | WebSocket | `codex_socket` | Lists models, submits approved prompts, streams Codex events, handles approvals, and interrupts runs. |

## HTML route source

```python
package_dir = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=package_dir / "templates")
app.mount("/static", StaticFiles(directory=package_dir / "static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"default_project": str(Path.cwd())},
    )
```

## Key page summary

### `/` — Approval client

The page configures project/model/workload settings, accepts a multilingual prompt, displays an unchanged-versus-verified route comparison with a decision receipt, then streams one approved route into Codex.
