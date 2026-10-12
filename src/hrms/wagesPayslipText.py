"""
Wages pay slip as a fixed-position text file for the mill's pre-printed stationery — a port of
the legacy Smart-Eye report "WAGES PAY SLIP" (FrmSmartEyeReportMulti2.WagesPaySlip_NJB, query
TBLF5 'WagesSlip').

Pure formatting, no database or web imports, so the layout can be tested on its own. Each slip
is 18 lines; when the department changes the legacy report feeds 54 blank lines first. Column
positions mirror the legacy Print / SPC calls one for one, including its quirks (the C/F column
prints B/F; a value wider than its column pushes the rest of the line right).
"""
from decimal import ROUND_HALF_UP, Decimal

LINE_END = "\r\n"
PAGE_FEED_LINES = 54

_DIGIT_WORDS = {"0": "ZERO ", "1": "ONE  ", "2": "TWO  ", "3": "THREE ", "4": "FOUR ", "5": "FIVE ",
                "6": "SIX  ", "7": "SEVEN ", "8": "EIGHT ", "9": "NINE "}


def amount_to_words(amount: int) -> str:
    """Legacy PayAmtToWd: the net amount spelt digit by digit (8711 -> 'EIGHT SEVEN ONE  ONE  ')."""
    if amount == 0:
        return "NIL"
    return "".join(_DIGIT_WORDS.get(ch, ch) for ch in str(amount))


def _s(v) -> str:
    return "" if v is None else str(v)


def _num(v, places: int = 2) -> str:
    """VB Format(Val(x), "##0.00") / "##0": rounds half away from zero."""
    d = Decimal(str(v)) if v not in (None, "") else Decimal(0)
    return str(d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def _left(v, width: int) -> str:
    """Print(value, SPC(width - Len(value))): value then padding; never truncated."""
    return _s(v).ljust(width)


def _right(text: str, width: int) -> str:
    """Print(SPC(width - Len(text)), text): right-aligned; never truncated."""
    return text.rjust(width)


def slip_lines(r: dict) -> list[str]:
    """The 18 lines of one slip. `r` uses the legacy query's column names."""
    edate = r["EDate"].strftime("%d/%m/%Y")
    name = _s(r.get("EName"))[:15].ljust(15)
    n = lambda key, width=8, places=2: _right(_num(r.get(key), places), width)  # noqa: E731
    net_words = amount_to_words(int(Decimal(_num(r.get("NetPayable"), 0))))
    return [
        " " * 35 + " " * 10 + _left(edate, 20) + _right(_num(r.get("SNo"), 0), 13),
        "  " + _left(r.get("ACNo"), 25) + _left(r.get("IFSC"), 25) + _left(r.get("UAN"), 25),
        "",
        ("  " + _left(r.get("RecNo"), 8) + name + "  " + _left(r.get("TP"), 4) + _left(r.get("CNo"), 8) + " " * 5
         + _left(r.get("OcpDptSft"), 8) + _left(r.get("CPQ"), 8) + _left(r.get("ESINo"), 10) + n("Prod", 7, 0)
         + " " + " " * 10 + " " + _left(edate, 10) + " " + _right(_num(r.get("SNo"), 0), 5) + " "),
        "",
        (n("Work_Day", 7) + n("Work_HR") + n("NS_HR") + n("FB_HR") + n("Holiday_HR") + n("Lost_HR") + n("OT_HR")
         + n("LayOff_HR") + n("BasicRate") + " " + n("DARate") + " " + " " * 8 + " " + _left(r.get("OcpDptSft"), 8)
         + " " + _left(r.get("RecNo"), 5) + " "),
        "",
        (n("Basic", 7) + n("FBasic") + n("AdjBasic") + n("DA_Amt") + n("NS_Amt") + n("Holiday_Amt")
         + n("LayOffHR_Amt") + n("STL_Amt") + n("Increment") + n("ElecMeter") + " " + " " * 8 + " "
         + _left(r.get("CNo"), 8) + " " + _left(r.get("CPQ"), 8) + " "),
        "",
        (n("PFEarnAdj", 7) + n("PF_Gross") + n("Incentive_Amt") + n("OT_Amt") + n("NPFEarnAdj") + n("HRA_Amt")
         + n("MiscEarn") + n("Atten_Amt") + n("TotalGross", 16) + " " + " " * 8 + " " + name),
        "",
        (n("PFEmployee", 7) + _right(_num(0), 8) + n("ESI_Amt") + n("PTax_Amt") + n("LWF_Amt") + n("HRDeduction")
         + n("STLAdv") + n("Advance") + n("UTHWAdv") + " " * 8 + " " + " " * 8 + " " + n("NetPayable", 15) + " "),
        "",
        (n("PFLoanCap", 7) + n("PFLoanInt") + n("PFDedAdj") + n("NPFDedAdj") + n("TotalDeduction") + n("NetPay")
         + n("BF") + n("BF")  # legacy prints B/F again in the C/F column
         + " " * 8 + n("NetPayable") + " " * 8 + " " + _right(net_words, 22) + " "),
        "",
        (n("STL_Days", 5) + "  " + n("COC") + n("YTD_Days") + " " * 3 + n("YTD_PFGross") + n("YTD_BnsGrs", 9)
         + n("PFLoanBal", 10) + n("PFIntBal") + " " + n("PenBal") + n("SPLAdvBal")),
        "",
        "",
    ]


def payslip_text(rows: list[dict]) -> str:
    """All slips in the order given; `rows` carry the page-break key 'PB' (department code)."""
    out: list[str] = []
    pb = rows[0].get("PB") if rows else None
    for r in rows:
        if r.get("PB") != pb:
            out.extend([""] * PAGE_FEED_LINES)
            pb = r.get("PB")
        out.extend(slip_lines(r))
    return "".join(line + LINE_END for line in out)
