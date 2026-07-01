from __future__ import annotations

from io import BytesIO

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt


SECTION_LABELS = [
    ("abstract", "摘要"),
    ("problem", "待研究问题"),
    ("rationale", "解决思路与知识缺口"),
    ("hypotheses", "核心假设"),
    ("methods", "方法论"),
    ("experiments", "实验设计"),
    ("results", "结果边界"),
    ("limitations_ethics", "局限与伦理"),
]


def build_report_docx(report: dict, review: dict, mode: str) -> bytes:
    document = Document()
    section = document.sections[0]
    section.top_margin = Cm(2.2)
    section.bottom_margin = Cm(2.2)
    section.left_margin = Cm(2.4)
    section.right_margin = Cm(2.4)

    normal = document.styles["Normal"]
    normal.font.name = "Microsoft YaHei"
    normal.font.size = Pt(10.5)

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title.add_run(report.get("title", "教育学科学假设与研究计划"))
    title_run.bold = True
    title_run.font.size = Pt(20)

    badge = document.add_paragraph()
    badge.alignment = WD_ALIGN_PARAGRAPH.CENTER
    badge.add_run("草稿版" if mode == "draft" else "复审通过版").bold = True

    for key, label in SECTION_LABELS:
        document.add_heading(label, level=1)
        value = report.get(key, "")
        if isinstance(value, list):
            for item in value:
                text = item.get("statement", str(item)) if isinstance(item, dict) else str(item)
                document.add_paragraph(text, style="List Bullet")
        else:
            document.add_paragraph(str(value))

    document.add_heading("参考文献", level=1)
    for reference in report.get("references", []):
        document.add_paragraph(
            f"{reference.get('title', '')} {reference.get('url', '')}", style="List Number"
        )

    document.add_heading("质量复审", level=1)
    document.add_paragraph(f"总体结论：{review.get('overall', '尚未复审')}")
    for name, item in review.get("checks", {}).items():
        document.add_paragraph(
            f"{name}：{item.get('status')} — {item.get('message')}", style="List Bullet"
        )

    output = BytesIO()
    document.save(output)
    return output.getvalue()

