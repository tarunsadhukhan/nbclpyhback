"""Layout of the wages pay slip text against two slips taken from a legacy Smart-Eye print
(PAYSLIPNBJCL.TXT, fortnight ending 30/09/2026)."""
from datetime import date

from src.hrms.wagesPayslipText import PAGE_FEED_LINES, amount_to_words, payslip_text, slip_lines

SLIP_1 = {
    "EDate": date(2026, 9, 30), "SNo": 1, "ACNo": "A/C No. : 31856427507", "IFSC": "IFSC: SBIN0004776",
    "UAN": "UAN: 100340296010", "RecNo": "032177", "EName": "SATENDRA PRASAD", "TP": "T", "CNo": "031551",
    "OcpDptSft": "/01/A", "CPQ": "07/  ", "ESINo": "4108208990", "Prod": 0, "PB": "01",
    "Work_Day": 14, "Work_HR": 112, "BasicRate": 2802, "DARate": 12431.70,
    "FBasic": 1508.77, "DA_Amt": 6693.99, "PF_Gross": 8202.76, "NPFEarnAdj": 1150, "HRA_Amt": 615,
    "Atten_Amt": 14, "TotalGross": 9981.76, "PFEmployee": 797, "ESI_Amt": 74, "Advance": 400,
    "NetPayable": 8711, "TotalDeduction": 1271, "NetPay": 8710.76, "COC": 23917, "YTD_Days": 161,
    "YTD_PFGross": 146199, "YTD_BnsGrs": 696592.71, "PFLoanBal": 61500, "PenBal": 159915,
}
EXPECTED_1 = [
    "                                             30/09/2026                      1",
    "  A/C No. : 31856427507    IFSC: SBIN0004776        UAN: 100340296010        ",
    "",
    "  032177  SATENDRA PRASAD  T   031551       /01/A   07/     4108208990      0            30/09/2026     1 ",
    "",
    "  14.00  112.00    0.00    0.00    0.00    0.00    0.00    0.00 2802.00 12431.70          /01/A    032177 ",
    "",
    "   0.00 1508.77    0.00 6693.99    0.00    0.00    0.00    0.00    0.00    0.00          031551   07/      ",
    "",
    "   0.00 8202.76    0.00    0.00 1150.00  615.00    0.00   14.00         9981.76          SATENDRA PRASAD",
    "",
    " 797.00    0.00   74.00    0.00    0.00    0.00    0.00  400.00    0.00                          8711.00 ",
    "",
    "   0.00    0.00    0.00    0.00 1271.00 8710.76    0.00    0.00         8711.00         EIGHT SEVEN ONE  ONE   ",
    "",
    " 0.00  23917.00  161.00   146199.00696592.71  61500.00    0.00 159915.00    0.00",
    "",
    "",
]
# a 15-digit account number fills its 25 columns, so the IFSC follows with no gap (as the legacy print does)
SLIP_2 = {**SLIP_1, "SNo": 2, "ACNo": "A/C No. : 425110400020017", "IFSC": "IFSC: BKID0004251",
          "UAN": "UAN: 100089584499", "RecNo": "190018", "EName": "ARJUN PRASAD", "CNo": "160332",
          "ESINo": "4108208647", "NetPayable": 7378}


def test_slip_matches_legacy_print():
    assert slip_lines(SLIP_1) == EXPECTED_1


def test_long_account_number_and_words():
    lines = slip_lines(SLIP_2)
    assert lines[1] == "  A/C No. : 425110400020017IFSC: BKID0004251        UAN: 100089584499        "
    assert lines[13].endswith("         7378.00         SEVEN THREE SEVEN EIGHT  ")
    assert amount_to_words(0) == "NIL"


def test_page_feed_on_department_change():
    text = payslip_text([SLIP_1, SLIP_2, {**SLIP_2, "PB": "02"}])
    lines = text.split("\r\n")
    assert len(lines) - 1 == 18 * 3 + PAGE_FEED_LINES  # trailing split element is empty
    assert lines[36:36 + PAGE_FEED_LINES] == [""] * PAGE_FEED_LINES
    assert lines[36 + PAGE_FEED_LINES].endswith("2")
