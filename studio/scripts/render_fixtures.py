#!/usr/bin/env python3
"""Render README screenshot fixtures with the real Studio renderers; no AWS/BMA/model calls.

Usage: .studio-venv/bin/python studio/scripts/render_fixtures.py OUTDIR {ko,en}
Writes OUTDIR/fixtures.json for studio/scripts/fixture_server.mjs. The document wording stands in
for model output; numbers, charts, diagrams and Office files come from the production code paths.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from studio.document_tools.input_data import aggregate_chart, inspect_source  # noqa: E402
from studio.document_tools.job import MIME, DocumentJob  # noqa: E402
from studio.document_tools.render import render_chart, render_diagram, render_documents  # noqa: E402

EXAMPLES = ROOT / "studio/examples"
ACCESS_KEY = "local-fixture-access-key"
MODEL = "openai.gpt-6.1-sol"
TEXT = {
    "ko": {
        "sales_file": "monthly-sales.xlsx",
        "sales_prompt": "첨부한 월별 매출을 막대 차트로 만들고, 차트를 포함한 발표자료와 Word 보고서를 만들어 줘.",
        "sales_title": "상반기 월별 매출 보고",
        "chart_title": "월별 매출",
        "sales_answer": "다음 파일을 만들었습니다.\n\n- 발표자료: 요약, 월별 추이 차트, 확인 사항\n- Word 보고서: 같은 구성과 원본 출처\n"
                        "- 막대 차트: PNG와 SVG\n\n원본 표의 여섯 개 값만 사용했고 다른 수치는 추가하지 않았습니다.",
        "sales_sections": [
            {"heading": "요약", "bullets": ["상반기 합계 1,080", "6월 250으로 최고치, 1월 120의 두 배 이상",
                                          "4월 160은 3월 180보다 낮음"]},
            {"heading": "월별 추이", "paragraphs": ["1월부터 3월까지 증가한 뒤 4월에 한 번 줄었고 5월과 6월에 다시 늘었습니다."],
             "asset_ids": ["chart_1"]},
            {"heading": "확인 사항", "bullets": ["4월 감소 원인은 원본 자료에 없어 별도 확인이 필요합니다."]},
        ],
        "notes_file": "onboarding-notes.txt",
        "notes_prompt": "이 온보딩 메모를 업무 흐름도로 정리하고 PPT와 Word 안내서를 만들어 줘.",
        "notes_title": "신입사원 온보딩 안내",
        "diagram_title": "온보딩 업무 흐름",
        "nodes": ["인사팀 · 서류 접수", "IT팀 · 계정과 장비", "팀장 · 첫 주 일정", "멘토 · 질의응답", "인사팀 · 적응 확인"],
        "notes_answer": "다음 파일을 만들었습니다.\n\n- 짧은 PPT: 업무 흐름도와 담당별 역할\n- Word 안내서: 흐름도, 업무 안내, 적용 범위\n"
                        "- 업무 흐름도: PNG와 SVG\n\n메모에 없는 일정이나 담당자는 추가하지 않았습니다.",
        "notes_sections": [
            {"heading": "업무 흐름", "paragraphs": ["메모의 다섯 단계를 순서대로 정리했습니다."], "asset_ids": ["diagram_1"]},
            {"heading": "담당별 역할", "bullets": ["인사팀: 입사 서류 접수, 적응 상태 확인", "IT팀: 계정과 장비 준비",
                                              "팀장: 첫 주 일정 안내", "멘토: 질의응답"]},
            {"heading": "적용 범위", "paragraphs": ["데모용 메모의 다섯 단계만 다룹니다."]},
        ],
    },
    "en": {
        "sales_file": "monthly-sales-en.xlsx",
        "sales_prompt": "Turn the attached monthly revenue into a bar chart, then build a slide deck and a Word report "
                        "that include the chart.",
        "sales_title": "First-half monthly revenue report",
        "chart_title": "Monthly revenue",
        "sales_answer": "I created the following files.\n\n- Slide deck: summary, monthly trend chart, follow-ups\n"
                        "- Word report: the same structure with source notes\n- Bar chart: PNG and SVG\n\n"
                        "Only the six values in the source table were used; no other figures were added.",
        "sales_sections": [
            {"heading": "Summary", "bullets": ["First-half total: 1,080", "June peaked at 250, more than double January's 120",
                                               "April (160) was lower than March (180)"]},
            {"heading": "Monthly trend", "paragraphs": ["Revenue rose from January to March, dipped once in April, "
                                                        "then grew again in May and June."], "asset_ids": ["chart_1"]},
            {"heading": "Follow-ups", "bullets": ["The source does not explain the April dip; confirm it separately."]},
        ],
        "notes_file": "onboarding-notes-en.txt",
        "notes_prompt": "Turn these onboarding notes into a workflow diagram and build a short PPT and Word guide.",
        "notes_title": "New-hire onboarding guide",
        "diagram_title": "Onboarding workflow",
        "nodes": ["HR intake", "IT setup", "Team lead", "Mentor Q&A", "HR check-in"],
        "notes_answer": "I created the following files.\n\n- Short PPT: workflow diagram and responsibilities\n"
                        "- Word guide: diagram, task guide and scope\n- Workflow diagram: PNG and SVG\n\n"
                        "No schedule or owner that is not in the notes was added.",
        "notes_sections": [
            {"heading": "Workflow", "paragraphs": ["The five steps from the notes, in order."], "asset_ids": ["diagram_1"]},
            {"heading": "Responsibilities", "bullets": ["HR: receive documents, check settling in",
                                                        "IT: prepare account and equipment",
                                                        "Team lead: first-week schedule", "Mentor: Q&A session"]},
            {"heading": "Scope", "paragraphs": ["Covers only the five steps in the demo notes."]},
        ],
    },
}
PHASES = ["queued", "reading", "analyzing", "charting", "diagramming", "writing", "packaging", "done"]


def artifacts(*results):
    """Public artifact rows in the same id/filename/mime shape that DocumentJob stores."""
    rows = []
    for result in results:
        for file in result["files"]:
            path = Path(file["path"]).resolve()
            extension = file["filename"].rsplit(".", 1)[1]
            rows.append({"id": f"{result['id']}_{extension}", "filename": file["filename"], "mime": MIME[extension],
                         "kind": result["kind"], "title": result["title"], "size": path.stat().st_size, "path": str(path)})
    return rows


def documents(text, key, assets, outdir, style, source):
    # Reuse the production source-note wording that create_documents injects
    notes = DocumentJob._source_notes(SimpleNamespace(source=source, assets=assets))
    blueprint = {"title": text[f"{key}_title"], "sections": text[f"{key}_sections"]}
    return render_documents(blueprint, assets, outdir, style=style, formats=("pptx", "docx"), source_notes=notes)


def render(outdir, language):
    text = TEXT[language]
    sales_dir, notes_dir = outdir / "sales", outdir / "notes"
    sales_dir.mkdir()
    notes_dir.mkdir()

    source = inspect_source((EXAMPLES / text["sales_file"]).read_bytes(), text["sales_file"])
    spec = aggregate_chart(source, "sheet_0", "c0", "c1", "sum", "bar", "value")
    spec["title"] = text["chart_title"]
    chart = render_chart(spec, sales_dir, style="business", asset_id="chart_1")
    sales = documents(text, "sales", {"chart_1": chart}, sales_dir, "business", source)

    notes = inspect_source(None, None, (EXAMPLES / text["notes_file"]).read_text(encoding="utf-8"))
    nodes = [{"id": f"step_{index}", "label": label} for index, label in enumerate(text["nodes"], 1)]
    edges = [{"source": a["id"], "target": b["id"]} for a, b in zip(nodes, nodes[1:])]
    diagram = render_diagram({"title": text["diagram_title"], "layout": "flow", "nodes": nodes, "edges": edges},
                             notes_dir, style="aws-desk", asset_id="diagram_1")
    guide = documents(text, "notes", {"diagram_1": diagram}, notes_dir, "aws-desk", notes)

    earlier = (datetime.now(timezone.utc) - timedelta(minutes=12)).isoformat(timespec="milliseconds")
    history = [{"id": str(uuid4()), "title": text["notes_title"], "prompt": text["notes_prompt"],
                "created_at": earlier, "updated_at": earlier, "status": "complete", "phase": "done",
                "completed_steps": [phase for phase in PHASES if phase != "charting"], "style": "aws-desk",
                "language": language, "outputs": ["pptx", "docx", "diagram"], "answer": text["notes_answer"],
                "artifacts": artifacts(diagram, guide), "warnings": [], "errors": []}]
    draft = {"title": text["sales_title"], "prompt": text["sales_prompt"], "file": str(EXAMPLES / text["sales_file"]),
             "answer": text["sales_answer"], "artifacts": artifacts(chart, sales),
             "warnings": [item for item in spec.get("warnings", []) if isinstance(item, str)]}
    manifest = {"access_key": ACCESS_KEY, "model": MODEL, "history": history, "draft": draft}
    (outdir / "fixtures.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    render(Path(sys.argv[1]), sys.argv[2])
