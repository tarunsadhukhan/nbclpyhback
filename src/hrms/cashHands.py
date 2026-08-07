"""
Cash Hands Report (legacy Data-Portal report 610).

Cash-type attendance (attendance_type = 'C') is *processed* into
daily_cash_outsider_payment â€” hours per employee/date/shift priced at the rate
approved in outsider_rate_approve (the Cash/Daily Rate Entry master) â€” and the
report then prints from that table. Re-processing a period deletes the rows it
previously wrote for that scope and writes them again, so a period always has
exactly one set of payment rows.

Legacy parity notes:
  * amount = ROUND(rate / 8 * hours, 0) â€” the approved rate is a full-shift
    (8 hour) rate and the legacy report rounded to whole rupees.
  * The rate came from worker_master.cash_rate in the old schema; the tenant
    schema has no such column, so it comes from outsider_rate_approve.
  * Columns subloca_id / cont_id / oth_rate are intentionally left unset.
"""

import logging
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import parse_json_body
from src.config.db import get_tenant_db

logger = logging.getLogger(__name__)

router = APIRouter()


# â”€â”€â”€ SQL â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def delete_processed_query():
    """Clear previously processed rows for the same company/branch/period."""
    return text("""
        DELETE p FROM daily_cash_outsider_payment p
        INNER JOIN branch_mst bm ON bm.branch_id = p.branch_id
        WHERE bm.co_id = :co_id
          AND p.pay_date BETWEEN :date_from AND :date_to
          AND (:branch_id IS NULL OR p.branch_id = :branch_id)
    """)


def process_insert_query():
    """
    Compute and store the cash payment rows for a period.

    Hours are summed per employee / date / shift / worked department /
    designation, then priced at the approved rate.

    Rate matching (outsider_rate_approve): app_date is an *effective from* date,
    not an exact-match key â€” a rate approved on the 31st applies to work done
    after it, until a newer approval supersedes it. app_shift is an optional
    override: a row with no shift applies to every shift, and a shift-specific
    approval wins over the general one for the same date. The subquery is
    correlated (not a join) so it can pick exactly one winning rate per row and
    cannot multiply the attendance rows.
    """
    return text("""
        INSERT INTO daily_cash_outsider_payment
            (eb_id, pay_date, shift, dept_id, desig_id,
             working_hours, rate, amount, branch_id, is_active)
        SELECT
            h.eb_id,
            h.attendance_date,
            h.spell,
            h.worked_department_id,
            h.worked_designation_id,
            h.hrs,
            h.rate,
            ROUND(h.rate / 8 * h.hrs, 0),
            h.branch_id,
            1
        FROM (
        SELECT g.*, COALESCE((
            SELECT ra.rate_approve
            FROM outsider_rate_approve AS ra
            WHERE ra.is_active = 1
              AND ra.eb_id = g.eb_id
              AND ra.app_date <= g.attendance_date
              AND (ra.app_shift IS NULL OR ra.app_shift = ''
                   OR ra.app_shift = g.spell)
            ORDER BY ra.app_date DESC,
                     (ra.app_shift = g.spell) DESC,
                     ra.outsider_rate_app_id DESC
            LIMIT 1
        ), 0) AS rate
        FROM (
            SELECT
                da.eb_id, da.attendance_date, da.branch_id,
                da.worked_department_id, da.worked_designation_id,
                COALESCE(sp.spell_name, da.spell) AS spell,
                SUM(da.working_hours - COALESCE(da.idle_hours, 0)) AS hrs
            FROM daily_attendance AS da
            INNER JOIN branch_mst AS bm ON bm.branch_id = da.branch_id
            LEFT JOIN spell_mst AS sp ON sp.spell_id = da.spell_id
            WHERE da.attendance_type = 'C'
              AND da.is_active = 1
              AND da.attendance_date BETWEEN :date_from AND :date_to
              AND bm.co_id = :co_id
              AND (:branch_id IS NULL OR da.branch_id = :branch_id)
            GROUP BY da.eb_id, da.attendance_date, da.branch_id,
                     da.worked_department_id, da.worked_designation_id,
                     COALESCE(sp.spell_name, da.spell)
        ) AS g
        ) AS h
    """)


def cash_hands_detail_query():
    """Processed payment rows with the employee / department / designation names."""
    return text("""
        SELECT
            p.eb_id,
            o.emp_code AS eb_no,
            CONCAT(IFNULL(pd.first_name, ''), ' ', IFNULL(pd.middle_name, ''), ' ',
                   IFNULL(pd.last_name, '')) AS worker_name,
            p.pay_date,
            p.shift,
            sd.sub_dept_code AS dept_code,
            sd.sub_dept_desc AS department,
            dsg.desig AS occupation,
            p.working_hours,
            p.rate,
            p.amount
        FROM daily_cash_outsider_payment AS p
        INNER JOIN branch_mst AS bm ON bm.branch_id = p.branch_id
        LEFT JOIN hrms_ed_personal_details AS pd ON pd.eb_id = p.eb_id
        LEFT JOIN hrms_ed_official_details AS o ON o.eb_id = p.eb_id AND o.active = 1
        LEFT JOIN sub_dept_mst AS sd ON sd.sub_dept_id = p.dept_id
        LEFT JOIN designation_mst AS dsg ON dsg.designation_id = p.desig_id
        WHERE COALESCE(p.is_active, 1) = 1
          AND bm.co_id = :co_id
          AND p.pay_date BETWEEN :date_from AND :date_to
          AND (:branch_id IS NULL OR p.branch_id = :branch_id)
        ORDER BY sd.sub_dept_code, sd.sub_dept_desc, p.shift, dsg.desig, o.emp_code
    """)


def cash_hands_summary_query():
    """Department x shift totals per pay date (the legacy summary page)."""
    return text("""
        SELECT
            p.pay_date,
            sd.sub_dept_code AS dept_code,
            sd.sub_dept_desc AS department,
            p.shift,
            ROUND(SUM(p.working_hours), 2) AS hours,
            ROUND(SUM(p.amount), 2) AS amount
        FROM daily_cash_outsider_payment AS p
        INNER JOIN branch_mst AS bm ON bm.branch_id = p.branch_id
        LEFT JOIN sub_dept_mst AS sd ON sd.sub_dept_id = p.dept_id
        WHERE COALESCE(p.is_active, 1) = 1
          AND bm.co_id = :co_id
          AND p.pay_date BETWEEN :date_from AND :date_to
          AND (:branch_id IS NULL OR p.branch_id = :branch_id)
        GROUP BY p.pay_date, sd.sub_dept_code, sd.sub_dept_desc, p.shift
        ORDER BY p.pay_date, sd.sub_dept_code, p.shift
    """)


# â”€â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_ONES = ("", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
         "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen",
         "Sixteen", "Seventeen", "Eighteen", "Nineteen")
_TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy",
         "Eighty", "Ninety")


def _two_digits(n: int) -> str:
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")).strip()


def amount_in_words(amount: float) -> str:
    """Indian-numbering amount in words (crore / lakh / thousand).

    Lower-case "only" suffix, matching the legacy report's wording exactly
    ("Four Hundred only", "Thirteen Thousand Seven Hundred Seventy One only").
    """
    rupees = int(round(float(amount or 0)))
    if rupees == 0:
        return "Zero only"

    parts: list[str] = []
    for divisor, label in ((10000000, "Crore"), (100000, "Lakh"), (1000, "Thousand")):
        if rupees >= divisor:
            parts.append(f"{_two_digits(rupees // divisor)} {label}")
            rupees %= divisor
    if rupees >= 100:
        parts.append(f"{_ONES[rupees // 100]} Hundred")
        rupees %= 100
    if rupees:
        parts.append(_two_digits(rupees))
    return " ".join(parts) + " only"


def _scope(request: Request) -> dict:
    """Shared co_id / branch_id / date-range params, validated."""
    co_id = request.query_params.get("co_id")
    if not co_id:
        raise HTTPException(status_code=400, detail="co_id is required")
    date_from = request.query_params.get("date_from")
    date_to = request.query_params.get("date_to")
    if not date_from or not date_to:
        raise HTTPException(status_code=400, detail="date_from and date_to are required")
    branch_raw = request.query_params.get("branch_id")
    return {
        "co_id": int(co_id),
        "branch_id": int(branch_raw) if branch_raw not in (None, "", "null") else None,
        "date_from": date_from,
        "date_to": date_to,
    }


def _num(v) -> float:
    return float(v) if v is not None else 0.0


def _detail_rows(db: Session, params: dict) -> list[dict]:
    rows = db.execute(cash_hands_detail_query(), params).fetchall()
    out = []
    for i, row in enumerate(rows):
        m = dict(row._mapping)
        out.append({
            "id": i,
            "eb_id": m.get("eb_id"),
            "eb_no": m.get("eb_no"),
            "worker_name": (m.get("worker_name") or "").strip(),
            "pay_date": m["pay_date"].isoformat() if m.get("pay_date") else None,
            "shift": m.get("shift"),
            "dept_code": m.get("dept_code"),
            "department": m.get("department"),
            "occupation": m.get("occupation"),
            "working_hours": _num(m.get("working_hours")),
            "rate": _num(m.get("rate")),
            "amount": _num(m.get("amount")),
        })
    return out


def _summary_rows(db: Session, params: dict) -> list[dict]:
    rows = db.execute(cash_hands_summary_query(), params).fetchall()
    out = []
    for i, row in enumerate(rows):
        m = dict(row._mapping)
        out.append({
            "id": i,
            "pay_date": m["pay_date"].isoformat() if m.get("pay_date") else None,
            "dept_code": m.get("dept_code"),
            "department": m.get("department"),
            "shift": m.get("shift"),
            "hours": _num(m.get("hours")),
            "amount": _num(m.get("amount")),
        })
    return out


# â”€â”€â”€ Endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@router.post("/cash-hands-process")
def process_cash_hands(  # sync: parse_json_body bridges from a worker thread
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Process (or re-process) a period into daily_cash_outsider_payment.

    Body: { co_id, branch_id?, date_from, date_to }. Any rows previously
    processed for the same company/branch/period are deleted first, so
    re-processing never leaves duplicates behind.
    """
    try:
        body = parse_json_body(request)
        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        date_from = body.get("date_from")
        date_to = body.get("date_to")
        if not date_from or not date_to:
            raise HTTPException(status_code=400, detail="date_from and date_to are required")
        branch_raw = body.get("branch_id")
        params = {
            "co_id": int(co_id),
            "branch_id": int(branch_raw) if branch_raw not in (None, "", "null") else None,
            "date_from": date_from,
            "date_to": date_to,
        }

        deleted = db.execute(delete_processed_query(), params).rowcount
        inserted = db.execute(process_insert_query(), params).rowcount
        db.commit()

        totals = db.execute(text("""
            SELECT ROUND(SUM(p.working_hours), 2) AS hours,
                   ROUND(SUM(p.amount), 2) AS amount,
                   SUM(p.rate = 0) AS missing_rate
            FROM daily_cash_outsider_payment AS p
            INNER JOIN branch_mst AS bm ON bm.branch_id = p.branch_id
            WHERE COALESCE(p.is_active, 1) = 1
              AND bm.co_id = :co_id
              AND p.pay_date BETWEEN :date_from AND :date_to
              AND (:branch_id IS NULL OR p.branch_id = :branch_id)
        """), params).fetchone()
        t = dict(totals._mapping) if totals else {}

        return {
            "message": f"Processed {inserted} payment row(s)",
            "deleted": deleted,
            "inserted": inserted,
            "total_hours": _num(t.get("hours")),
            "total_amount": _num(t.get("amount")),
            # Rows whose worker has no approved rate for that date/shift price
            # at zero â€” surfaced so the user can fix them in Daily Rate Entry.
            "rows_without_rate": int(t.get("missing_rate") or 0),
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error processing cash hands: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cash-hands")
async def get_cash_hands(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Processed cash payment rows for the period (detail sheet / grid)."""
    try:
        return {"data": _detail_rows(db, _scope(request))}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching cash hands: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cash-hands-summary")
async def get_cash_hands_summary(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Department x shift totals for the period (summary sheet / PDF page 2)."""
    try:
        return {"data": _summary_rows(db, _scope(request))}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching cash hands summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cash-hands-pdf")
async def get_cash_hands_pdf(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Cash Hands Report as PDF, laid out like the legacy FPDF report:

      * portrait A4, one page per pay date + department + spell,
      * the payment table (S.No â€¦ Sign) with a Total line and the amount in
        words, then the Checked By / Approved By / To Accounts signature block,
      * a final "Cash Hand Report Summary" page listing every group with the
        grand total and the total in words.

    The MachineName column is kept for layout parity but left blank â€” the
    processed payment rows carry no machine, exactly as in the legacy output.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
            Table, TableStyle,
        )

        params = _scope(request)
        detail = _detail_rows(db, params)
        summary = _summary_rows(db, params)

        # Font sizes mirror the legacy FPDF report exactly (Arial -> Helvetica,
        # regular weight throughout — the legacy report never bolded a header):
        # title 16, voucher/date line 10 (12 on the summary page), table 8
        # (10 on the summary page), signature block 12.
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "CashTitle", parent=styles["Title"], fontName="Helvetica",
            fontSize=16, spaceAfter=2)
        normal = ParagraphStyle("CashNormal", parent=styles["Normal"], fontSize=10)
        sign_text = ParagraphStyle("CashSign", parent=styles["Normal"], fontSize=12,
                                   leading=14)
        cell = ParagraphStyle("CashCell", parent=styles["Normal"], fontSize=8,
                              leading=9.5)

        def fmt_date(iso: str | None) -> str:
            if not iso:
                return ""
            y, m, d = iso.split("-")
            return f"{d}-{m}-{y}"

        bio = BytesIO()
        doc = SimpleDocTemplate(
            bio, pagesize=A4,
            topMargin=10 * mm, bottomMargin=10 * mm,
            # legacy ruled the sheet from x=10mm to x=205mm on A4
            leftMargin=10 * mm, rightMargin=5 * mm,
            title="Cash Hand Report",
        )

        # S.No, EB No, Worker Name, Spell, MachineName, Department, Occupation,
        # Rate, Hours, Amount, Sign â€” the legacy column set and running order.
        HEAD = ["S.No", "EB No", "Worker Name", "Spell", "MachineName",
                "Department", "Occupation", "Rate", "Hours", "Amount", "Sign"]
        # Legacy column rules: 10|20|35|65|73|93|123|153|165|177|195|205 mm.
        WIDTHS = [10 * mm, 15 * mm, 30 * mm, 8 * mm, 20 * mm, 30 * mm,
                  30 * mm, 12 * mm, 12 * mm, 18 * mm, 10 * mm]

        GRID = [
            ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (7, 1), (9, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]

        def signature_block() -> list:
            """Checked By / Approved By â€¦ To Accounts â€” repeated on each page."""
            sign_tbl = Table(
                [["Checked By", "", "Approved By", ""],
                 ["Time Keeper", "Department Incharge",
                  "Personal Department", "General Manager"]],
                colWidths=[47 * mm, 47 * mm, 47 * mm, 47 * mm],
            )
            sign_tbl.setStyle(TableStyle([
                ("FONTSIZE", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 1), (-1, 1), 14),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            return [
                Spacer(1, 8 * mm),
                sign_tbl,
                Spacer(1, 6 * mm),
                Paragraph("To Accounts,", sign_text),
                Paragraph(
                    "The above mentioned amount can be relased to the workers.",
                    sign_text),
                Spacer(1, 12 * mm),
                Table([["Authorised Signature"], ["Commercial Dept."]],
                      colWidths=[60 * mm], hAlign="RIGHT",
                      style=TableStyle([("FONTSIZE", (0, 0), (-1, -1), 12)])),
            ]

        story: list = []

        if not detail:
            story.append(Paragraph("Cash Hand Report", title_style))
            story.append(Paragraph(
                "No processed cash payment rows for this period. "
                "Run Process first.", normal))
        else:
            # One page per pay date + department + spell, as the legacy report
            # printed one voucher sheet per group.
            groups: dict[tuple, list[dict]] = {}
            for row in detail:
                groups.setdefault(
                    (row["pay_date"], row["department"], row["shift"]), []
                ).append(row)

            for gi, (key, rows) in enumerate(groups.items()):
                pay_date, _dept, _shift = key
                story.append(Paragraph("Cash Hand Report", title_style))
                hdr = Table(
                    [["ExtraCashBookVoucherNo", f"Date : {fmt_date(pay_date)}"]],
                    colWidths=[120 * mm, 75 * mm],
                )
                hdr.setStyle(TableStyle([
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
                ]))
                story.append(hdr)
                story.append(Spacer(1, 3 * mm))

                data = [HEAD]
                g_hours = g_amount = 0.0
                for i, row in enumerate(rows, start=1):
                    data.append([
                        i,
                        row["eb_no"] or "",
                        Paragraph(row["worker_name"] or "", cell),
                        row["shift"] or "",
                        "",                                    # MachineName
                        Paragraph(row["department"] or "", cell),
                        Paragraph(row["occupation"] or "", cell),
                        f"{row['rate']:.0f}",
                        f"{row['working_hours']:.2f}",
                        f"{row['amount']:.0f}",
                        "",                                    # Sign
                    ])
                    g_hours += row["working_hours"]
                    g_amount += row["amount"]

                data.append(["", "", "Total", "", "", "", "",
                             "", f"{g_hours:.0f}", f"{g_amount:.0f}", ""])
                tbl = Table(data, colWidths=WIDTHS, repeatRows=1)
                tbl.setStyle(TableStyle(GRID))
                story.append(tbl)
                story.append(Spacer(1, 4 * mm))
                story.append(Paragraph(
                    f"(Amount in Figure : {amount_in_words(g_amount)})", normal))
                story.extend(signature_block())

                if gi < len(groups) - 1 or summary:
                    story.append(PageBreak())

            if summary:
                story.append(Paragraph("Cash Hand Report Summary", title_style))
                s_hdr = Table(
                    [["ExtraCashBookVoucherNo",
                      f"Date : {fmt_date(params['date_from'])}"]],
                    colWidths=[120 * mm, 75 * mm],
                )
                s_hdr.setStyle(TableStyle([
                    ("FONTSIZE", (0, 0), (-1, -1), 12),
                    ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
                ]))
                story.append(s_hdr)
                story.append(Spacer(1, 3 * mm))

                # The legacy summary has no Date column (it was a single-day
                # voucher run); add one only when the range really spans days.
                multi_day = len({r["pay_date"] for r in summary}) > 1
                s_head = (["S.No", "Date", "Department", "Spell", "Hours", "Amount"]
                          if multi_day else
                          ["S.No", "Department", "Spell", "Hours", "Amount"])
                s_widths = ([14 * mm, 26 * mm, 62 * mm, 22 * mm, 30 * mm, 34 * mm]
                            if multi_day else
                            [14 * mm, 78 * mm, 26 * mm, 34 * mm, 36 * mm])

                s_data = [s_head]
                t_hours = t_amount = 0.0
                for i, r in enumerate(summary, start=1):
                    line = [i]
                    if multi_day:
                        line.append(fmt_date(r["pay_date"]))
                    line += [Paragraph(r["department"] or "", normal), r["shift"] or "",
                             f"{r['hours']:.2f}", f"{r['amount']:.0f}"]
                    s_data.append(line)
                    t_hours += r["hours"]
                    t_amount += r["amount"]

                total_line = ["", "Total"] if not multi_day else ["", "", "Total"]
                total_line += ["", f"{t_hours:.0f}", f"{t_amount:.0f}"]
                s_data.append(total_line)

                s_tbl = Table(s_data, colWidths=s_widths, repeatRows=1)
                s_tbl.setStyle(TableStyle([
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("ALIGN", (-2, 1), (-1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]))
                story.append(s_tbl)
                story.append(Spacer(1, 5 * mm))
                story.append(KeepTogether(Paragraph(
                    f"Total Amount in Words : {amount_in_words(t_amount)}",
                    normal)))

        doc.build(story)
        bio.seek(0)
        filename = f"CashHandReport_{params['date_from']}_{params['date_to']}.pdf"
        return StreamingResponse(
            iter([bio.getvalue()]),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error building cash hands PDF: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
