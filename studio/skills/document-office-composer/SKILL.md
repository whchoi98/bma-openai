---
name: document-office-composer
description: Turn uploaded text, notes and data into concise editable Word and PowerPoint files in the selected business style.
---

Inspect the source first. Structure a useful business document with a title,
clear section headings, short paragraphs and relevant visuals. Do not invent
business facts, dates, outcomes or numeric findings absent from the inputs.

Follow the selected business, aws-desk or presentation style. Use the selected
language and plain professional prose without em dashes, middle-dot separators,
decorative emoji or repetitive filler.

Create needed chart/diagram assets before calling create_documents. Refer to
the returned chart_N or diagram_N IDs. Call create_documents once, last.
Use at most eleven sections plus the title. Keep text short enough for slides:
at most four paragraphs of 600 characters and six bullets of 200 characters
per section. At most two visual assets per section.

Only report files actually returned by the tools. The HTML view is a content
preview, not a promise of identical desktop Office pagination. Do not invent
download URLs; the web application supplies authenticated downloads.
