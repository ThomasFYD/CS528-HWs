#!/usr/bin/env python3
"""Build the HW5 PDF from reviewed evidence; no cloud or network operations."""
import argparse
import hashlib
from html import escape
import io
import json
import os
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Image, Paragraph, Preformatted, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "report" / "report-content.json"
INK = colors.HexColor("#17324A")
GRAY = colors.HexColor("#526273")
PALE = colors.HexColor("#EEF3F7")
RULE = colors.HexColor("#DDE5EC")
LEFT = RIGHT = 54
TOP = 48
BOTTOM = 58
REPORTER_SHA = "095e77c433957dd45185d4c0fce3efa3a948866308839bdabb9c22dbb93c87b0"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_inputs(spec):
    if len(spec["pages"]) != 18:
        raise ValueError("Expected the reviewed 18-page report plan")
    for asset in spec["assets"]:
        path = ROOT / asset["path"]
        if digest(path) != asset["sha256"]:
            raise ValueError(f"Image differs from reviewed original: {asset['path']}")
    if digest(ROOT / "reporter.py") != REPORTER_SHA:
        raise ValueError("Reporter no longer matches unchanged HW4 source")
    evidence = ROOT / "report" / "evidence"
    audit = read_json(evidence / "formal-run-review.json")
    run = evidence / audit["run_id"]
    summary = read_json(run / "summary.json")
    execution = read_json(run / "experiment.json")
    if not execution["complete"] or execution["exit_codes"] != [0, 0]:
        raise ValueError("Formal client run was not complete")
    if execution["commands"][0] != execution["commands"][1]:
        raise ValueError("Saved client command lines differ")
    for command in execution["commands"]:
        if command[command.index("-n") + 1] != "50000" or command[command.index("-r") + 1] != "528":
            raise ValueError("Unexpected client count or seed")
    if audit["counts"] != {"requests": 100000, "failed_requests": 4347, "request_timings": 100000}:
        raise ValueError("Formal database counts differ from report")
    if summary["http_status_counts"] != audit["statuses"] or not summary["integrity"]["complete"]:
        raise ValueError("Summary and independent audit disagree")
    for key, values in audit["timing"].items():
        if summary["timing"][key] != values:
            raise ValueError(f"Timing evidence differs: {key}")
    shots = read_json(ROOT / "report" / "screenshots" / "manifest.json")
    if not shots["complete"] or [x["page"] for x in shots["images"]] != list(range(1, 10)):
        raise ValueError("Nine curl screenshots are required")
    cleanup = read_json(evidence / "cleanup-verification.json")
    if (cleanup["sql"]["state"] != "STOPPED" or
            cleanup["sql"]["settings"]["activationPolicy"] != "NEVER" or
            cleanup["vms"] != {"web": None, "reporter": None} or
            cleanup["address"] is not None or cleanup["guard"] is not None):
        raise ValueError("Saved cleanup state differs from report")
    billing = read_json(evidence / "billing" / "services-20261022-054140.json")
    if billing["status"] != "accepted_for_report_with_user_confirmed_activity_scope":
        raise ValueError("Billing scope has not been confirmed")
    return {"assets_verified": len(spec["assets"]), "request_count": 100000,
            "client_exits": execution["exit_codes"], "cleanup_verified": True}


def styles(scale):
    definitions = {
        "title": ("Helvetica-Bold", 22, 27, 0, 12, INK),
        "h1": ("Helvetica-Bold", 16, 20, 0, 12, INK),
        "h2": ("Helvetica-Bold", 11, 14, 8, 6, INK),
        "body": ("Helvetica", 9.4, 13, 0, 8, INK),
        "small": ("Helvetica", 8.2, 11, 0, 6, GRAY),
        "caption": ("Helvetica", 8.3, 11, 3, 9, GRAY),
        "cell": ("Helvetica", 8.1, 10.5, 0, 0, INK),
        "code": ("Courier", 7.5, 9.3, 0, 10, INK),
    }
    result = {}
    for name, (font, size, leading, before, after, color) in definitions.items():
        result[name] = ParagraphStyle(
            name, fontName=font, fontSize=size * scale, leading=leading * scale,
            spaceBefore=before * scale, spaceAfter=after * scale, textColor=color,
            splitLongWords=True,
        )
    return result


def make_flowable(item, width, style_map, scale):
    if item["type"] == "paragraph":
        return Paragraph(item["text"], style_map[item.get("style", "body")])
    if item["type"] == "code":
        lines = item["text"].splitlines()
        if max((len(line) for line in lines), default=0) * 4.5 * scale > width:
            raise ValueError("A code line exceeds its page width")
        return Preformatted(item["text"], style_map["code"])
    if item["type"] == "image":
        path = ROOT / item["path"]
        pixels_w, pixels_h = ImageReader(str(path)).getSize()
        factor = min(width / pixels_w, item.get("max_height", 540) / pixels_h)
        image = Image(str(path), width=pixels_w * factor, height=pixels_h * factor)
        image.hAlign = "CENTER"
        image.spaceAfter = 3
        return image
    if item["type"] == "table":
        rows = [item["headers"], *item["rows"]]
        cells = [[Paragraph(escape(str(value)), style_map["cell"]) for value in row] for row in rows]
        weights = item["widths"]
        widths = [width * value / sum(weights) for value in weights]
        table = Table(cells, colWidths=widths, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), PALE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 5 * scale),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5 * scale),
            ("LEFTPADDING", (0, 0), (-1, -1), 6 * scale),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6 * scale),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ]))
        table.spaceAfter = 8 * scale
        return table
    raise ValueError(f"Unknown report item: {item['type']}")


def plan_pages(spec):
    pages = []
    for number, source in enumerate(spec["pages"], 1):
        size = landscape(letter) if source["size"] == "landscape" else letter
        width = size[0] - LEFT - RIGHT
        available = size[1] - TOP - BOTTOM
        accepted = None
        for scale in (1.0, 0.97, 0.94, 0.91):
            style_map = styles(scale)
            arranged, used = [], 0
            for item in source["items"]:
                flowable = make_flowable(item, width, style_map, scale)
                measured_width, height = flowable.wrap(width, 10000)
                before = flowable.getSpaceBefore()
                after = flowable.getSpaceAfter()
                used += before + height + after
                arranged.append((flowable, measured_width, height, before, after))
            if used <= available:
                accepted = {"number": number, "title": source["title"], "size": size,
                            "scale": scale, "used": used, "available": available,
                            "items": arranged}
                break
        if accepted is None:
            raise ValueError(f"Page {number} exceeds layout budget: {used:.1f} > {available:.1f} pt. "
                             "Report source needs adjustment; no PDF was written.")
        pages.append(accepted)
    return pages


def footer(pdf, page, date):
    width = page["size"][0]
    pdf.setStrokeColor(RULE)
    pdf.line(LEFT, 40, width - RIGHT, 40)
    pdf.setFillColor(GRAY)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(LEFT, 27, f"CS528 HW5 | Yide Fang | {date}")
    pdf.drawRightString(width - RIGHT, 27, str(page["number"]))


def verify_pdf(path, spec):
    reader = PdfReader(path)
    if len(reader.pages) != len(spec["pages"]):
        raise ValueError("Unexpected PDF page count")
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    missing = [term for term in spec["checks"] if term not in text]
    if missing:
        raise ValueError(f"Expected report values are missing from PDF text: {missing}")
    return {"pages": len(reader.pages), "key_values_present": True,
            "pdf_sha256": digest(path), "pdf_bytes": Path(path).stat().st_size}


def build(output, spec, pages):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter, pageCompression=1)
    pdf.setTitle(spec["title"] + ": " + spec["subtitle"])
    pdf.setAuthor(spec["author"])
    pdf.setSubject("Verified Cloud SQL experiment, curl evidence, operation timing and billing snapshot")
    for page in pages:
        pdf.setPageSize(page["size"])
        pdf.bookmarkPage(f"page-{page['number']}")
        pdf.addOutlineEntry(page["title"], f"page-{page['number']}", level=0)
        y = page["size"][1] - TOP
        for flowable, width, height, before, after in page["items"]:
            y -= before + height
            x = LEFT
            if isinstance(flowable, Image):
                x = (page["size"][0] - width) / 2
            flowable.drawOn(pdf, x, y)
            y -= after
        footer(pdf, page, spec["date"])
        pdf.showPage()
    pdf.save()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".pending.pdf")
    temporary.write_bytes(buffer.getvalue())
    verification = verify_pdf(temporary, spec)
    os.replace(temporary, output)
    return verification


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Read-only evidence and layout preflight")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path, help="Read-only validation of a generated PDF")
    args = parser.parse_args()
    spec = read_json(CONTENT)
    if args.verify:
        print(json.dumps(verify_pdf(args.verify, spec), indent=2))
        return
    facts = verify_inputs(spec)
    pages = plan_pages(spec)
    layout = [{k: page[k] for k in ("number", "title", "scale", "used", "available")} for page in pages]
    if args.check:
        print(json.dumps({"evidence": facts, "layout": layout, "ready_to_build": True}, indent=2))
        return
    if not args.output:
        parser.error("Choose --check, --verify FILE, or --output FILE")
    result = build(args.output, spec, pages)
    record = {"output": str(args.output.resolve()), "verification": result,
              "evidence": facts, "layout": layout, "visual_review": "pending"}
    args.output.with_suffix(".build.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))
    print("PDF generated. Visual review of rendered pages is still required.")


if __name__ == "__main__":
    main()
