r"""
Winsome Reports — ports of the legacy Winsome Smart-Eye report master ORPSMTEye
(Smart_Eye_Jute_Purnasar_Winsome_Live, E:\sme\SmartEye-Winsome\Reports\SmartEyeReportMulti\*_WIL.rpt).
Mounted at /api/hrmsReports/winsome/reports; same spec shape and routes as NBJCL Reports
(src/hrms/nbjclreports/__init__.py). Registry key "<group>/<key>" = menu path after hrms/winsomereports/
(dbqueries/migrations/run_seed_nbjcl_reports_menu.py --set winsome camel-cases the legacy names).

Winsome runs on legacy tables mirrored under their legacy names (ATTEN, PayWages, PayOEMP, PayPFTranDTL, ...),
so each report is the legacy Crystal command / RPT_* procedure translated to MySQL. Scope = branch 110
(WIL / Factory, see winsomeWagesProcess.WINSOME_SCOPE).
"""
from fastapi import APIRouter

from src.hrms.nbjclreports import mount_reports
from src.hrms.winsomereports import attendance, excel, leave, loans, pf, registration, wages

router = APIRouter()

REPORTS: dict[str, dict] = {
    f"{group}/{key}": spec
    for module in (attendance, registration, wages, loans, pf, leave, excel)
    for group, specs in module.REPORTS.items()
    for key, spec in specs.items()
}

mount_reports(router, "/winsome/reports", REPORTS, "winsome")
