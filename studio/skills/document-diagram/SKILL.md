---
name: document-diagram
description: Convert supplied process notes and structures into bounded flow, hierarchy or timeline diagrams.
---

Inspect the supplied source. Use create_diagram with nodes and edges supported
by the user's text. Keep labels short and use flow, hierarchy or timeline
according to the source. Maximum twenty nodes and thirty edges.

Every edge must reference a declared node. Do not invent dependencies,
causality or dates to make a diagram look complete. Clarify missing information
in the answer. Do not emit arbitrary SVG, JavaScript, shell commands or URLs.

Use returned diagram asset IDs in a document only after successful rendering.
