# webapp Module

## Role
Python local reference implementation (FastAPI + uvicorn, entry point `bma-inventory-web`) used for
contract generation, local demos and verification reports. It is **not** deployed; Lambda Web Functions
only run Node.js 24, so production traffic is served by `web/`. `webapp/static/` is the shared UI that
both apps serve and that ships inside the Web Function ZIP.

## Key Files
- `main.py` — `create_app()`: `/`, `/health`, `/api/context`, `/api/chat`, `/api/runs/{run_id}/report.{format}`
- `bma.py` — BMA REST client signed in `APP_REGION`; `INSTRUCTIONS` exported into `web/contract.json`
- `evidence.py` — durable output allow-list (`TOP_FIELDS`, `DATA_FIELDS`, `STATUSES`)
- `runners.py`, `store.py`, `reports.py`, `config.py`
- `static/` — `index.html`, `style.css`, `report.css`, `fonts/NanumSquareB.otf` + `OFL.txt`, generated `app.js`

## Rules
- Do not add non-asset files (including docs) under `static/`; the whole tree is zipped.
- `static/app.js` is generated from `web/ui/app.js`; never edit it by hand.
- Changes to `INSTRUCTIONS` or the evidence allow-lists require re-running `scripts/export_web_contract.py` so the Node app stays in sync.
- Keep behavior aligned with `web/server.js` for the shared endpoints.
