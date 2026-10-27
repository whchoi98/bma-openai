# AI Document Studio

Nondeveloper demo: upload XLSX/CSV/TXT/MD or paste notes, request a result in plain
language, preview charts/diagrams/documents, and download real PPTX/DOCX/PNG/SVG.

This is a separate Lambda Web Function and document Runtime. Existing AWS
Operations Desk resources and resource-query permissions are not expanded.
App, BMA and file processing run in us-east-1. The deployed document model is `openai.gpt-6.1-sol`; Luna and Terra are optional deployment candidates, not automatic fallbacks.

## Product requirements

- Three selectable styles: `business`, `aws-desk`, `presentation`.
- Professional office-worker interface, NanumSquare OTF Bold, Korean/English,
  light/dark theme. Avoid infrastructure jargon in the normal workflow.
- Real phase messages, elapsed time and restrained document/chart animation
  while working. No invented percentages or internal reasoning.
- Authenticated downloads and safe previews. HTML is a content preview, not a
  claim that it exactly matches desktop PowerPoint/Word pagination.
- One optional file plus notes per job. XLSX, CSV, TXT and MD. Reuse an earlier
  job's inputs to change style or instructions; each generation is a distinct
  bounded BMA session.
- Original numeric data remains authoritative. Aggregate using code, preserve
  missing values and source references, never invent data to draw a chart.
- No macro/formula execution, remote images, scripts or generic shell/CLI tool.

## Initial limits

Upload 5 MiB, one file, 50,000 note/text characters, five sheets, 10,000 rows,
50 columns, 100,000 total cells, 50 plotted categories, six chart/diagram
assets, 12 slides including title, 20 nodes and 30 edges per diagram.
Worker generation budget 300 seconds, execution timeout 360 seconds,
reserved concurrency two. Data retention seven days.

## Interfaces

### Input parser: `studio/document_tools/input_data.py`

`inspect_source(data: bytes | None, filename: str | None, notes: str = "") -> dict`

```text
{filename,kind,text,notes,warnings,sheets:[
 {id:"sheet_0",name,columns:[{id:"c0",name,type}],rows:[[cell,...]],
  row_count,warnings}
]}
```

Rows are internal, bounded data. Cell values are JSON-safe finite numbers,
strings, booleans or null. Column IDs are stable and never executable.

`source_profile(source) -> dict` returns metadata, each table's first eight
rows, column schema, warnings, and bounded text/notes excerpts.

`aggregate_chart(source, sheet_id, x_column, y_column=None, aggregation="sum",
chart_type="bar", group_by="value") -> dict` returns:

```text
{chart_type,categories,values,x_values?,x_label,y_label,source,
 missing_values,invalid_values,omitted_categories,warnings}
```

Types: bar, line, pie, scatter. Aggregations: sum, mean, count, none.
Grouping: value, month, year. Pie rejects negative/all-zero data. No-numeric
data is a visible error. Scatter uses numeric x/y and aggregation none.
Source metadata includes file, sheet and selected columns. Formula cells use
only saved values; missing formula caches remain missing and are reported.

### Renderer: `studio/document_tools/render.py`

- `render_chart(spec, outdir, style="business", asset_id="chart_1") -> dict`
- `render_diagram(spec, outdir, style="business", asset_id="diagram_1") -> dict`
- `render_documents(blueprint, assets, outdir, style="business",
  formats=("pptx","docx"), source_notes=()) -> dict`

`assets` maps asset IDs to renderer results. Each result has
`id,kind,title,files:[{path,filename,mime}],spec` as appropriate.
Use PNG/SVG for charts and diagrams. PPTX text and charts should be editable
native objects; diagrams should use editable shapes/connectors where possible.

Diagram spec:
`{title,layout:"flow"|"hierarchy"|"timeline",nodes:[{id,label}],
edges:[{source,target,label?}]}`. Reject dangling edges and unsafe paths.

Document blueprint:
`{title,subtitle?,sections:[{heading,paragraphs?:[str],bullets?:[str],
asset_ids?:[str]}]}`. Max eleven sections plus title. Produce requested
PPTX/DOCX and a safe self-contained HTML content preview. Actual source notes
are injected by the server, not taken from invented model citations.
All text and attributes are escaped in SVG/HTML. No remote assets.

### Web API

Bearer app access key protects all `/api/` paths. No AWS access key input.

- GET `/api/config` -> `{model,app_region,styles:[{id,name,description}],
  limits,formats}`. Name/description are `{ko,en}`.
- POST `/api/uploads`, raw body with `Content-Type: application/octet-stream`
  and `X-File-Name: encodeURIComponent(filename)` -> `{upload:{id,name,size,extension}}`.
- POST `/api/jobs` JSON
  `{request_id,upload_id?,notes?,prompt,outputs:["pptx","docx","chart","diagram"],
  style,language,source_job_id?}` -> 202 `{job}`.
- GET `/api/jobs?limit=10&cursor=...` -> `{jobs,next_cursor,complete}`.
- GET `/api/jobs/:id` -> `{job}`.
- GET `/api/jobs/:id/events` SSE `{type:"snapshot",job}` and terminal
  `{type:"complete",job}`. Errors `{type:"error",code}`.
- POST `/api/jobs/:id/cancel` empty JSON -> `{job}`.
- GET `/api/jobs/:id/artifacts/:asset_id` -> authenticated file download.
  `?view=inline` supports safe previews; fetch into Blob URLs for images.

Public job:
`{id,title,prompt,created_at,updated_at,status,phase,style,language,outputs,
source_job_id?,upload?,answer,profile?,artifacts:[{id,filename,mime,kind,
size,title}],warnings:[],errors:[]}`.
Status: queued/running/complete/partial/failed/cancelled/uncertain.
Phase: queued/reading/analyzing/charting/diagramming/writing/packaging/done.
No BMA session ID, S3 key, credentials or lease in public data.

Only last selected job ID and display preferences may be saved in the browser.
Credentials, file contents and notes stay out of browser persistent storage.

### Runtime MCP and state

Trusted worker configures a BMA session with only the document MCP server,
whose immutable CLI `--job-id UUID` selects its input manifest.
Tools: inspect_inputs, read_table, read_text, create_chart, create_diagram,
create_documents. No AWS inventory tools or generic execution tools.

Dedicated private bucket:
`uploads/UUID/{data,meta.json}`, `jobs/UUID/input.json`,
`jobs/UUID/state.json`, `jobs/UUID/artifacts.json`,
`jobs/UUID/outputs/*`, `index/REVERSE_TIME-UUID.json`.
Input manifest is immutable; state is coordinated with conditional writes.
Runtime can read inputs and write only document artifacts, not job state.
Worker can manage job state and BMA sessions, not query AWS resources.

## Work ownership

- Input agent: input_data.py and test_input_data.py.
- Renderer agent: render.py, styles.py, test_render.py.
- Frontend agent: studio/web/static files only, optional frontend test.
- Root: backend, worker, MCP adapter, deployment, integration tests and docs.

Current deployed usage and verification: [Korean guide](../docs/document-studio.md).
