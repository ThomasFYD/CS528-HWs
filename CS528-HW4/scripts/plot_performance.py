"""Render retained HW4 metrics with ReportLab charts (optional report dependency)."""

import argparse
import csv
import json
from pathlib import Path

from reportlab.graphics import renderPDF
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, String, Line
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas

INK = colors.HexColor("#17324A")
BLUE = colors.HexColor("#1673A8")
ORANGE = colors.HexColor("#C96C22")
PURPLE = colors.HexColor("#7855A4")
GRAY = colors.HexColor("#607080")
GRID = colors.HexColor("#DFE5EB")
WIDTH, HEIGHT = landscape(letter)


def chart(title, series, labels, hues, xmax, ymax, ystep, xlabel, xmin=0, width=228, height=208):
    drawing = Drawing(width, height)
    drawing.add(String(0, height - 12, title, fontName="Helvetica-Bold", fontSize=10, fillColor=INK))
    for index, (label, hue) in enumerate(zip(labels, hues)):
        x = index * 105
        drawing.add(Line(x, height - 29, x + 14, height - 29, strokeColor=hue, strokeWidth=1.4))
        drawing.add(String(x + 18, height - 32, label, fontName="Helvetica", fontSize=8, fillColor=GRAY))
    plot = LinePlot()
    plot.x, plot.y = 34, 30
    plot.width, plot.height = width - 41, height - 79
    plot.data = series
    plot.joinedLines = 1
    plot.xValueAxis.valueMin, plot.xValueAxis.valueMax = xmin, xmax
    plot.xValueAxis.valueSteps = [1, 2, 3, 4] if xmin == 1 else [0, 30, 60, 90, 120, 150, 180]
    plot.yValueAxis.valueMin, plot.yValueAxis.valueMax = 0, ymax
    plot.yValueAxis.valueStep = ystep
    plot.xValueAxis.labelTextFormat = "%g"
    plot.yValueAxis.labelTextFormat = "%g"
    for axis in (plot.xValueAxis, plot.yValueAxis):
        axis.labels.fontName = "Helvetica"
        axis.labels.fontSize = 7.5
        axis.labels.fillColor = GRAY
        axis.strokeColor = GRAY
        axis.strokeWidth = 0.5
    plot.yValueAxis.visibleGrid = 1
    plot.yValueAxis.gridStrokeColor = GRID
    plot.yValueAxis.gridStrokeWidth = 0.4
    for index, hue in enumerate(hues):
        plot.lines[index].strokeColor = hue
        plot.lines[index].strokeWidth = 1.0
        if index:
            plot.lines[index].strokeDashArray = [3, 2]
    drawing.add(plot)
    drawing.add(String(width / 2, 7, xlabel, fontName="Helvetica", fontSize=8,
                       fillColor=GRAY, textAnchor="middle"))
    return drawing


def text_lines(pdf, lines, x, y, size=9, leading=14, color=GRAY):
    pdf.setFillColor(color)
    pdf.setFont("Helvetica", size)
    for line in lines:
        pdf.drawString(x, y, line)
        y -= leading
    return y


def header(pdf, title, subtitle, page, run_id):
    pdf.setFillColor(INK)
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(38, HEIGHT - 47, title)
    pdf.setFont("Helvetica", 10)
    pdf.setFillColor(GRAY)
    pdf.drawString(38, HEIGHT - 66, subtitle)
    pdf.setStrokeColor(GRID)
    pdf.line(38, HEIGHT - 82, WIDTH - 38, HEIGHT - 82)
    pdf.line(38, 39, WIDTH - 38, 39)
    pdf.setFont("Helvetica", 7.5)
    pdf.drawString(38, 25, f"CS528 HW4 | Yide Fang | Run {run_id} | Figures from retained raw samples")
    pdf.drawRightString(WIDTH - 38, 25, str(page))


def table(pdf, headers, rows, x, top, widths, row_height=24):
    total = sum(widths)
    pdf.setFillColor(colors.HexColor("#EDF3F8"))
    pdf.rect(x, top - row_height, total, row_height, stroke=0, fill=1)
    for row_number, row in enumerate([headers, *rows]):
        y = top - (row_number + 1) * row_height
        if row_number:
            pdf.setStrokeColor(GRID)
            pdf.line(x, y, x + total, y)
        pdf.setFont("Helvetica-Bold" if row_number == 0 else "Helvetica", 8.5)
        pdf.setFillColor(INK)
        left = x
        for value, width in zip(row, widths):
            pdf.drawString(left + 7, y + 8, str(value))
            left += width


def build(folder, destination, page_offset=0):
    summary = json.loads((folder / "summary.json").read_text())
    rows = summary["rounds"]
    if len(rows) != 4 or not all(r.get("measurement_valid") for r in rows):
        raise ValueError("Four valid measurement windows are required before plotting")
    with (folder / "web-metrics.csv").open() as stream:
        samples = list(csv.DictReader(stream))
    destination.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(destination), pagesize=(WIDTH, HEIGHT), pageCompression=1)
    pdf.setTitle("CS528 HW4 - Performance measurements")
    pdf.setAuthor("Yide Fang")
    pdf.setSubject("Observed whole-VM metrics, with external-traffic caveat for the two-client run")
    header(pdf, "Performance under 1-4 concurrent clients",
           "f1-micro web VM | 180 seconds per group | 30-second request timeout | 14 October 2026 UTC",
           page_offset + 1, folder.name)
    for index, (title, metric, ymax, step) in enumerate((
            ("CPU busy (%)", "cpu_busy_pct", 12, 3),
            ("Memory used (MiB)", "memory_used_mib", 600, 150),
            ("Outbound bandwidth (Mbps)", "tx_mbps", 16, 4))):
        series = [[(r["clients"], r["web"][stat][metric]) for r in rows] for stat in ("mean", "peak")]
        drawing = chart(title, series, ["Mean", "Peak"], [BLUE, ORANGE], 4, ymax, step,
                        "Concurrent instructor clients", xmin=1)
        renderPDF.draw(drawing, pdf, 38 + index * 244, 299)
    table(pdf, ["Clients", "CPU mean / peak", "Memory peak", "RX peak", "TX peak", "Timeouts"],
          [[r["clients"], f"{r['web']['mean']['cpu_busy_pct']:.2f}% / {r['web']['peak']['cpu_busy_pct']:.2f}%",
            f"{r['web']['peak']['memory_used_mib']:.2f} MiB", f"{r['web']['peak']['rx_mbps']:.2f} Mbps",
            f"{r['web']['peak']['tx_mbps']:.2f} Mbps", r["client_timeout_messages"]] for r in rows],
          38, 276, [58, 160, 126, 126, 126, 120])
    text_lines(pdf, [
        "At four clients, no timeout, unexpected HTTP error log, or server exception was observed in the measurement window.",
        "Two-client caveat: four 404 requests targeted / or /login; a connection reset came from a different public IP.",
        "These are outside the configured workload. Retained whole-VM samples include their effects; no samples were removed.",
        "Quiet mode provides no request throughput or complete HTTP status counts. This run does not establish maximum capacity.",
        "Peak values are maxima of roughly one-second samples, not instantaneous hardware maxima. See definitions on the next pages.",
    ], 38, 131, size=9, leading=16)
    pdf.showPage()

    for index, result in enumerate(rows, 2):
        count = result["clients"]
        run = json.loads((folder / "client" / f"c{count}" / "round.json").read_text())
        data = [s for s in samples if int(s["clients"]) == count]
        def values(key):
            return [(float(s["relative_seconds"]), float(s[key])) for s in data]
        header(pdf, f"{count} concurrent client{'s' if count != 1 else ''}: time series",
               f"15-second warmup excluded | Measurement: {result['measured_seconds']:.2f} s | Web samples: {result['web']['sample_count']}",
               page_offset + index, folder.name)
        specs = [("CPU time (%)", [values("cpu_busy_pct"), values("cpu_iowait_pct")],
                  ["Busy", "I/O wait"], [BLUE, ORANGE], 30, 10),
                 ("Memory used (MiB)", [values("memory_used_mib")], ["Total - available"], [PURPLE], 600, 150),
                 ("Network rate (Mbps)", [values("rx_mbps"), values("tx_mbps")],
                  ["Inbound", "Outbound"], [BLUE, ORANGE], 16, 4)]
        for column, (title, series, labels, hues, ymax, step) in enumerate(specs):
            renderPDF.draw(chart(title, series, labels, hues, 180, ymax, step,
                                 "Seconds after measurement start", height=238), pdf, 38 + column * 244, 269)
        peak = result["web"]["peak"]
        table(pdf, ["CPU busy peak", "Memory peak", "RX peak", "TX peak"], [[
            f"{peak['cpu_busy_pct']:.2f}%", f"{peak['memory_used_mib']:.2f} MiB ({peak['memory_used_pct']:.2f}%)",
            f"{peak['rx_mbps']:.2f} Mbps", f"{peak['tx_mbps']:.2f} Mbps"]],
            38, 251, [164, 224, 164, 164])
        denials = result["cloud_log_counts"].get("expected_country_denials", 0)
        notes = [
            f"UTC window: {run['measurement_start']} to {run['measurement_end']}",
            f"Client timeout messages: {result['client_timeout_messages']}; expected country-denial events: {denials}; all clients alive for the full window.",
        ]
        if count == 2:
            notes += [
                "External-traffic caveat: 3 GET / requests and 1 GET /login returned 404 during this window.",
                "A connection reset came from 66.132.159.21; the load VM's public IP was 34.123.133.194.",
                "The 404 records lack source IPs. They cannot be attributed to that same peer; their paths exclude the load workload.",
            ]
        else:
            notes += ["No unexpected warning/error records or server exception lines were observed in this window."]
        notes += [
            "CPU busy excludes idle, I/O wait and steal. It is a guest logical-CPU percentage, not the shared-core entitlement.",
            "Memory is whole-VM MemTotal - MemAvailable. Network includes GCS downloads, HTTP replies and cloud API traffic.",
            "Raw data: web-resources.jsonl and web-metrics.csv. All original samples and error records are retained.",
        ]
        text_lines(pdf, notes, 38, 186, size=8.5, leading=15)
        pdf.showPage()
    pdf.save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.folder, args.output)
    print(args.output)
