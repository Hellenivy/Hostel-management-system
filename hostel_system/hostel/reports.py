import csv
from datetime import date
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from django.contrib import messages
from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from .decorators import staff_required
from .models import Complaint, Payment, Room, Tenant


# ---------- helpers ----------

def money(value):
    return f"{Decimal(value):,.2f}"


def _range_text(date_from, date_to):
    if date_from and date_to:
        return f"From {date_from:%d %b %Y} to {date_to:%d %b %Y}"
    if date_from:
        return f"From {date_from:%d %b %Y}"
    if date_to:
        return f"Up to {date_to:%d %b %Y}"
    return "All dates"


def _payments_in_range(date_from, date_to):
    queryset = Payment.objects.all()
    if date_from:
        queryset = queryset.filter(date_paid__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(date_paid__date__lte=date_to)
    return queryset


def _report(title, subtitle, headers, rows, summary, num_cols=(), weights=None,
            landscape=False):
    return {
        "title": title,
        "subtitle": subtitle,
        "headers": headers,
        "rows": rows,
        "summary": summary,
        "num_cols": set(num_cols),
        "weights": weights,
        "landscape": landscape,
    }


# ---------- the five reports ----------

def rent_per_month(date_from=None, date_to=None, status="all"):
    months = (
        _payments_in_range(date_from, date_to)
        .annotate(month=TruncMonth("date_paid"))
        .values("month")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("-month")
    )
    rows = [
        [m["month"].strftime("%B %Y"), m["count"], money(m["total"])]
        for m in months
    ]
    grand_total = sum((m["total"] for m in months), Decimal("0"))
    count = sum(m["count"] for m in months)

    return _report(
        "Rent collected per month",
        _range_text(date_from, date_to),
        ["Month", "Payments", "Total collected (KES)"],
        rows,
        [("Total payments", count), ("Total collected (KES)", money(grand_total))],
        num_cols=[1, 2],
    )


def arrears(date_from=None, date_to=None, status="all"):
    owing = []
    for tenant in Tenant.objects.select_related("room").order_by("full_name"):
        balance = tenant.balance()
        if balance <= 0:
            continue
        paid = tenant.payment_set.aggregate(total=Sum("amount"))["total"] or Decimal("0")
        owing.append((tenant, tenant.months_billed(), balance + paid, paid, balance))

    owing.sort(key=lambda item: item[4], reverse=True)

    rows = [
        [
            tenant.full_name,
            tenant.phone,
            tenant.room.room_number if tenant.room else "-",
            "Moved out" if tenant.move_out_date else "Active",
            months,
            money(billed),
            money(paid),
            money(balance),
        ]
        for tenant, months, billed, paid, balance in owing
    ]
    outstanding = sum((item[4] for item in owing), Decimal("0"))

    return _report(
        "Tenants who owe rent",
        f"Balances as at {timezone.localdate():%d %b %Y}",
        ["Tenant", "Phone", "Room", "Status", "Months", "Rent billed (KES)",
         "Paid (KES)", "Balance (KES)"],
        rows,
        [("Tenants owing", len(owing)), ("Total outstanding (KES)", money(outstanding))],
        num_cols=[4, 5, 6, 7],
        landscape=True,
    )


def occupancy(date_from=None, date_to=None, status="all"):
    rows = []
    total_beds = occupied_beds = vacant_rooms = 0

    for room in Room.objects.order_by("room_number"):
        occupied = Tenant.objects.filter(room=room, move_out_date__isnull=True).count()
        free = max(room.capacity - occupied, 0)
        if occupied == 0:
            label = "Vacant"
            vacant_rooms += 1
        elif occupied >= room.capacity:
            label = "Full"
        else:
            label = "Partly occupied"
        total_beds += room.capacity
        occupied_beds += occupied
        rows.append([
            room.room_number, money(room.rent_amount), room.capacity,
            occupied, free, label,
        ])

    percent = occupied_beds * 100 // total_beds if total_beds else 0

    return _report(
        "Room occupancy",
        f"As at {timezone.localdate():%d %b %Y}",
        ["Room", "Rent (KES)", "Beds", "Occupied", "Free", "Status"],
        rows,
        [
            ("Rooms", len(rows)),
            ("Vacant rooms", vacant_rooms),
            ("Beds occupied", f"{occupied_beds} of {total_beds} ({percent}%)"),
        ],
        num_cols=[1, 2, 3, 4],
    )


def payments_report(date_from=None, date_to=None, status="all"):
    payments = (
        _payments_in_range(date_from, date_to)
        .select_related("tenant__room")
        .order_by("-date_paid")
    )
    rows = []
    total = Decimal("0")
    for p in payments:
        total += p.amount
        rows.append([
            timezone.localtime(p.date_paid).strftime("%d %b %Y %H:%M"),
            p.tenant.full_name,
            p.tenant.room.room_number if p.tenant.room else "-",
            f"M-Pesa {p.mpesa_code}" if p.mpesa_code else "Cash / manual",
            money(p.amount),
        ])

    return _report(
        "Payments",
        _range_text(date_from, date_to),
        ["Date", "Tenant", "Room", "Method", "Amount (KES)"],
        rows,
        [("Payments", len(rows)), ("Total (KES)", money(total))],
        num_cols=[4],
    )


def complaints_report(date_from=None, date_to=None, status="all"):
    complaints = Complaint.objects.select_related("tenant__room").order_by("-created_at")
    if status == "open":
        complaints = complaints.filter(status="Open")
    elif status == "resolved":
        complaints = complaints.filter(status="Resolved")

    rows = [
        [
            timezone.localtime(c.created_at).strftime("%d %b %Y"),
            c.tenant.full_name,
            c.tenant.room.room_number if c.tenant.room else "-",
            c.description,
            c.status,
        ]
        for c in complaints
    ]
    open_count = sum(1 for row in rows if row[4] == "Open")

    label = {"open": "Open complaints only", "resolved": "Resolved complaints only"}
    return _report(
        "Complaints",
        label.get(status, "All complaints"),
        ["Date", "Tenant", "Room", "Complaint", "Status"],
        rows,
        [("Complaints", len(rows)), ("Open", open_count),
         ("Resolved", len(rows) - open_count)],
        weights=[1.2, 1.6, 0.8, 4, 1],
    )


REPORTS = {
    "rent-per-month": {
        "title": "Rent collected per month",
        "description": "How much rent came in each month, and how many payments.",
        "build": rent_per_month,
        "filters": "dates",
    },
    "arrears": {
        "title": "Tenants who owe rent",
        "description": "Everyone with an unpaid balance, biggest debt first.",
        "build": arrears,
        "filters": "",
    },
    "occupancy": {
        "title": "Room occupancy",
        "description": "Beds taken and free in every room.",
        "build": occupancy,
        "filters": "",
    },
    "payments": {
        "title": "Payments",
        "description": "Every payment received, with M-Pesa codes. Pick a date range.",
        "build": payments_report,
        "filters": "dates",
    },
    "complaints": {
        "title": "Complaints",
        "description": "Open and resolved complaints from tenants.",
        "build": complaints_report,
        "filters": "status",
    },
}


# ---------- downloads ----------

def _safe_cell(value):
    # Stop spreadsheet programs from running a cell that starts like a formula.
    text = str(value)
    if text and text[0] in "=+-@\t\r":
        return "'" + text
    return text


def _filename(slug, extension):
    return f"{slug}-{timezone.localdate():%Y-%m-%d}.{extension}"


def to_csv_response(report, slug):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{_filename(slug, "csv")}"'
    response.write("\ufeff")  # lets Excel read the file as UTF-8

    writer = csv.writer(response)
    writer.writerow(report["headers"])
    for row in report["rows"]:
        writer.writerow([_safe_cell(cell) for cell in row])
    writer.writerow([])
    for label, value in report["summary"]:
        writer.writerow([_safe_cell(label), _safe_cell(value)])
    return response


def to_pdf_response(report, slug):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    buffer = BytesIO()
    page_size = landscape(A4) if report["landscape"] else A4
    margin = 14 * mm
    document = SimpleDocTemplate(
        buffer, pagesize=page_size, title=report["title"],
        leftMargin=margin, rightMargin=margin, topMargin=margin, bottomMargin=margin,
    )

    styles = getSampleStyleSheet()
    cell = ParagraphStyle("cell", parent=styles["BodyText"], fontSize=8.5, leading=11)
    cell_right = ParagraphStyle("cell_right", parent=cell, alignment=2)
    head = ParagraphStyle("head", parent=cell, fontName="Helvetica-Bold",
                          textColor=colors.white)
    head_right = ParagraphStyle("head_right", parent=head, alignment=2)

    def para(value, style):
        return Paragraph(escape(str(value)), style)

    num_cols = report["num_cols"]
    table_data = [[
        para(h, head_right if i in num_cols else head)
        for i, h in enumerate(report["headers"])
    ]]
    for row in report["rows"]:
        table_data.append([
            para(value, cell_right if i in num_cols else cell)
            for i, value in enumerate(row)
        ])

    available = page_size[0] - 2 * margin
    weights = report["weights"] or [1] * len(report["headers"])
    col_widths = [available * w / sum(weights) for w in weights]

    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#047857")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    story = [
        Paragraph(f"Smart Hostel - {escape(report['title'])}", styles["Title"]),
        Paragraph(escape(report["subtitle"]), styles["Normal"]),
        Paragraph(
            f"Generated on {timezone.localtime():%d %b %Y, %H:%M}", styles["Normal"]
        ),
        Spacer(1, 8 * mm),
    ]
    if report["rows"]:
        story.append(table)
    else:
        story.append(Paragraph("No data for this report.", styles["Normal"]))
    story.append(Spacer(1, 6 * mm))
    for label, value in report["summary"]:
        story.append(Paragraph(
            f"<b>{escape(str(label))}:</b> {escape(str(value))}", styles["Normal"]
        ))

    def page_number(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(
            page_size[0] - margin, 8 * mm, f"Page {doc.page}"
        )

    document.build(story, onFirstPage=page_number, onLaterPages=page_number)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{_filename(slug, "pdf")}"'
    return response


# ---------- views ----------

def _parse_date(request, key):
    raw = request.GET.get(key, "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        messages.error(request, f"'{raw}' is not a valid date. Use the date picker.")
        return None


@staff_required
def reports_index(request):
    report_list = [
        {"slug": slug, "title": spec["title"], "description": spec["description"]}
        for slug, spec in REPORTS.items()
    ]
    return render(request, "hostel/reports.html", {"report_list": report_list})


@staff_required
def report_detail(request, slug):
    spec = REPORTS.get(slug)
    if spec is None:
        raise Http404

    date_from = _parse_date(request, "from")
    date_to = _parse_date(request, "to")
    if date_from and date_to and date_from > date_to:
        messages.error(request, "The 'from' date must not be after the 'to' date.")
        date_from = date_to = None

    status = request.GET.get("status", "all")
    if status not in ("all", "open", "resolved"):
        status = "all"

    report = spec["build"](date_from=date_from, date_to=date_to, status=status)

    output = request.GET.get("format")
    if output == "csv":
        return to_csv_response(report, slug)
    if output == "pdf":
        return to_pdf_response(report, slug)

    table_rows = [
        [{"value": value, "num": i in report["num_cols"]} for i, value in enumerate(row)]
        for row in report["rows"]
    ]
    header_cells = [
        {"value": header, "num": i in report["num_cols"]}
        for i, header in enumerate(report["headers"])
    ]
    params = request.GET.copy()
    params.pop("format", None)

    return render(request, "hostel/report.html", {
        "slug": slug,
        "report": report,
        "header_cells": header_cells,
        "table_rows": table_rows,
        "filters": spec["filters"],
        "date_from": date_from.isoformat() if date_from else "",
        "date_to": date_to.isoformat() if date_to else "",
        "status": status,
        "query": params.urlencode(),
    })