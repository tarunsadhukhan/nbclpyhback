import logging
from fastapi import FastAPI, Request
from src.common.routers import router as common_router
from src.authorization.routers import common_router as auth_router
from src.common.companydata import router as company_router
from src.common.companyAdmin.menu import router as co_console_router
from src.common.companyAdmin.roles import router as co_roles_router
from src.common.companyAdmin.users import router as co_users_router
from src.common.portal.roles import router as co_portal_router
from src.common.portal.users import router as co_portal_users_router
from src.common.portal.menu import router as co_portal_menu_router
from src.common.portal.approval import router as co_portal_approval_router
from src.common.ctrldskAdmin.roles import router as co_ctrldsk_router
from src.common.ctrldskAdmin.users import router as co_ctrldsk_users_router
from src.common.ctrldskAdmin.orgs import router as co_ctrldsk_orgs_router
from src.common.companyAdmin.company import router as co_company_router
from src.common.ctrldskAdmin.menuportal import router as co_ctrldsk_menu_router
from src.common.companyAdmin.branch import router as co_branch_router
from src.common.companyAdmin.dept_subdept import router as co_dept_subdept_router
from src.common.supportTicket.report import router as support_ticket_report_router
from src.common.supportTicket.manage import router as support_ticket_manage_router

from src.masters.departments import router as dept_router
from src.masters.mechineMaster import router as machine_router
from src.masters.projectMaster import router as project_router 
from src.procurement.indent import router as indent_router
from src.procurement.po import router as po_router
from src.procurement.inward import router as inward_router
from src.procurement.material_inspection import router as material_inspection_router
from src.procurement.sr import router as sr_router
from src.procurement.drcr_note import router as drcr_note_router
from src.procurement.billpass import router as billpass_router
from src.procurement.price_enquiry import router as price_enquiry_router
from src.procurement.reports import router as procurement_reports_router
from src.masters.party import router as party_router
from src.inventory.issue import router as issue_router
from src.inventory.reports import router as inventory_reports_router
from src.hrms.reports import router as hrms_reports_router

from src.masters.items import router as item_router
from src.masters.warehouse import router as warehouse_router
from src.masters.isoMenuMap import router as iso_menu_map_router
from src.masters.castFactor import router as costFactor_router
from src.masters.juteQuality import router as jute_quality_router
from src.masters.juteSupplier import router as jute_supplier_router
from src.masters.juteSupplierMap import router as jute_supplier_map_router
from src.masters.yarnTypeMaster import router as yarn_type_router
from src.masters.yarnMaster import router as yarn_master_router
from src.masters.batchPlanMaster import router as batch_plan_master_router
from src.masters.designation import router as designation_router
from src.masters.category import router as category_router
from src.masters.contractor import router as contractor_router
from src.masters.bankDetails import router as bank_details_router
from src.masters.itemBom import router as item_bom_router
from src.bomcosting.costElement import router as cost_element_router
from src.bomcosting.bomCosting import router as bom_costing_router
from src.bomcosting.stdRateCard import router as std_rate_card_router
from src.masters.shift import router as shift_router
from src.masters.spell import router as spell_router
from src.masters.machineType import router as machine_type_router
from src.juteProcurement.jutePO import router as jute_po_router
from src.juteProcurement.juteGateEntry import router as jute_gate_entry_router
from src.juteProcurement.materialInspection import router as jute_material_inspection_router
from src.juteProcurement.mr import router as jute_mr_router
from src.juteProcurement.juteAgentMap import router as jute_agent_map_router
from src.juteProcurement.billPass import router as jute_bill_pass_router
from src.juteProcurement.issue import router as jute_issue_router
from src.juteProcurement.batchDailyAssign import router as batch_daily_assign_router
from src.juteProcurement.reports import router as jute_reports_router
from src.juteSQC.morrahWeight import router as morrah_wt_router
from src.juteSQC.spreader_roll_wt import router as spreader_roll_wt_router
from src.juteSQC.spreader_sliver_wt import router as spreader_sliver_wt_router
from src.juteSQC.breaker_card_swt import router as breaker_card_swt_router
from src.juteSQC.card_sliver_wt import router as card_sliver_wt_router
from src.juteSQC.fin_draw_sliver_wt import router as fin_draw_sliver_wt_router
from src.juteSQC.draw_sliver_wt import router as draw_sliver_wt_router
from src.juteSQC.spinning_sqc import router as spinning_sqc_router
from src.juteSQC.yarn_tpi import router as yarn_tpi_router
from src.juteSQC.qr_cv_15a import router as qr_cv_15a_router
from src.juteSQC.finishing_sqc import router as finishing_sqc_router
from src.juteSQC.weaving_sqc import router as weaving_sqc_router
from src.juteSQC.beam_mr import router as beam_mr_router
from src.juteSQC.fabric_construction import router as fabric_construction_router
from src.juteSQC.cutting_length import router as cutting_length_router
from src.juteSQC.width_picks import router as width_picks_router
from src.juteSQC.stitch import router as stitch_router
from src.juteSQC.bag_weight import router as bag_weight_router
from src.juteSQC.bag_check import router as bag_check_router
from src.juteSQC.packing_mr import router as packing_mr_router
from src.juteSQC.fabric_fault import router as fabric_fault_router
from src.juteSQC.emulsion import router as emulsion_router
from src.juteSQC.humidity import router as humidity_router
from src.juteProduction.spreader_entry import router as spreader_entry_router
from src.juteProduction.spreader_issue import router as spreader_issue_router
from src.juteProduction.spreader_stock import router as spreader_stock_router
from src.juteProduction.spreader_masters import router as spreader_masters_router
from src.juteProduction.drawing_entry import router as drawing_entry_router
from src.juteProduction.drawing_masters import router as drawing_masters_router
from src.juteProduction.spinning_entry import router as spinning_entry_router
from src.juteProduction.spinning_process import router as spinning_process_router
from src.juteProduction.spinning_quality_map import router as spinning_quality_map_router
from src.juteProduction.spinning_masters import router as spinning_masters_router
from src.juteProduction.winding_entry import router as winding_entry_router
from src.juteProduction.stoppage_entry import router as stoppage_entry_router
from src.juteProduction.spng_target_map import router as spng_target_map_router
from src.juteProduction.beaming_masters import router as beaming_masters_router
from src.juteProduction.beaming_target_map import router as beaming_target_map_router
from src.juteProduction.beaming_entry import router as beaming_entry_router
from src.juteProduction.finishing_masters import router as finishing_masters_router
from src.juteProduction.finishing_target_map import router as finishing_target_map_router
from src.juteProduction.finishing_entry import router as finishing_entry_router
from src.juteProduction.weaving_masters    import router as weaving_masters_router
from src.juteProduction.weaving_target_map import router as weaving_target_map_router
from src.juteProduction.weaving_entry      import router as weaving_entry_router
from src.juteProduction.weaving_process    import router as weaving_process_router
from src.juteProduction.reports import router as jute_production_reports_router
from src.juteProduction.winding_reports import router as winding_reports_router
from src.sales.enquiry import router as sales_enquiry_router
from src.sales.quotation import router as quotation_router
from src.sales.salesOrder import router as sales_order_router
from src.sales.deliveryOrder import router as delivery_order_router
from src.sales.salesInvoice import router as sales_invoice_router
from src.sales.reports import router as sales_reports_router
from src.hrms.employee import router as hrms_employee_router
from src.hrms.payScheme import router as hrms_pay_scheme_router
from src.hrms.payParam import router as hrms_pay_param_router
from src.accounting.routers import router as accounting_router
from src.hrms.payRegister import router as hrms_pay_register_router
from src.hrms.payRoll import router as hrms_pay_roll_router
from src.hrms.payComponent import router as hrms_pay_component_router
from src.hrms.leaveType import router as hrms_leave_type_router
from src.hrms.leaveRequest import router as hrms_leave_request_router
from src.hrms.attendance import router as hrms_attendance_router
from src.hrms.payslipPrintComponent import router as hrms_payslip_print_component_router
from src.hrms.bioAttendance import router as hrms_bio_attendance_router
from src.hrms.outsiderRate import router as hrms_outsider_rate_router
from src.hrms.cashHands import router as hrms_cash_hands_router
from src.hrms.canteenDetails import router as hrms_canteen_details_router
from src.common.attachments.router import router as attachments_router
from src.config.cors import add_cors_middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
# from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Vowerp3b API")

# ✅ Add this to trust NGINX proxy headers (like X-Forwarded-Proto)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

# Add CORS middleware
add_cors_middleware(app)

@app.middleware("http")
async def catch_exceptions_middleware(request: Request, call_next):
    try:
        response = await call_next(request)
        return response
    except Exception as e:
        print(f"Global API Error: {e}")
        return JSONResponse(status_code=500, content={"error": "Internal Server Error"})

print ('mama')
app.include_router(common_router, prefix="/api/common", tags=["Common"])
app.include_router(auth_router, prefix="/api/authRoutes", tags=["Auth"])
app.include_router(company_router, prefix="/api/companyRoutes", tags=["company"])
app.include_router(co_console_router, prefix="/api/companyAdmin", tags=["company-admin-menu"])
app.include_router(co_roles_router, prefix="/api/companyAdmin", tags=["company-admin-roles"])
app.include_router(co_users_router, prefix="/api/companyAdmin", tags=["company-admin-users"])
app.include_router(co_portal_router, prefix="/api/admin/PortalData", tags=["PortalDataInAdmin"])
app.include_router(co_portal_users_router, prefix="/api/admin/PortalData", tags=["PortalDataInAdmin"])
app.include_router(co_portal_menu_router, prefix="/api/admin/PortalData", tags=["PortalDataInAdmin"])
app.include_router(co_portal_approval_router, prefix="/api/admin/PortalData", tags=["PortalDataInAdmin"])
app.include_router(co_ctrldsk_router, prefix="/api/ctrldskAdmin", tags=["ctrldsk-admin-roles"])
app.include_router(co_ctrldsk_users_router, prefix="/api/ctrldskAdmin", tags=["ctrldsk-admin-users"])
app.include_router(co_ctrldsk_orgs_router, prefix="/api/ctrldskAdmin", tags=["ctrldsk-admin-orgs"])
app.include_router(co_company_router, prefix="/api/companyAdmin", tags=["company-admin-company"])
app.include_router(co_ctrldsk_menu_router, prefix="/api/ctrldskAdmin", tags=["ctrldsk-admin-menu"])
app.include_router(co_branch_router, prefix="/api/companyAdmin", tags=["company-admin-branch"])
app.include_router(co_dept_subdept_router, prefix="/api/companyAdmin", tags=["company-admin-dept-subdept"])

# Support-ticket (Zendesk-style) routes — raised from Portal/Tenant Admin,
# managed by the VOW team from the Control Desk. All data lives in vowconsole3.
app.include_router(support_ticket_report_router, prefix="/api/supportTicket", tags=["support-ticket"])
app.include_router(support_ticket_manage_router, prefix="/api/supportTicket", tags=["support-ticket-manage"])
app.include_router(item_router, prefix="/api/itemMaster", tags=["masters-items"])

app.include_router(dept_router, prefix="/api/deptMaster", tags=["masters-departments"])
app.include_router(machine_router, prefix="/api/mechMaster", tags=["masters-machines"])
app.include_router(project_router, prefix="/api/projectMaster", tags=["masters-projects"])

app.include_router(party_router, prefix="/api/partyMaster", tags=["masters-party"])
app.include_router(warehouse_router, prefix="/api/warehouseMaster", tags=["masters-warehouse"])
app.include_router(iso_menu_map_router, prefix="/api/isoMenuMap", tags=["masters-iso-map"])
app.include_router(costFactor_router, prefix="/api/costFactorMaster", tags=["masters-costFactor"])
app.include_router(jute_quality_router, prefix="/api/juteQualityMaster", tags=["masters-jute-quality"])
app.include_router(jute_supplier_router, prefix="/api/juteSupplierMaster", tags=["masters-jute-supplier"])
app.include_router(jute_supplier_map_router, prefix="/api/juteSupplierMap", tags=["masters-jute-supplier-map"])

app.include_router(yarn_type_router, prefix="/api/yarnTypeMaster", tags=["masters-yarn-type"])
app.include_router(yarn_master_router, prefix="/api/yarnMaster", tags=["masters-yarn"])
app.include_router(batch_plan_master_router, prefix="/api/batchPlanMaster", tags=["masters-batch-plan"])
app.include_router(designation_router, prefix="/api/hrmsMasters", tags=["hrms-masters"])
app.include_router(category_router, prefix="/api/hrmsMasters", tags=["hrms-masters"])
app.include_router(contractor_router, prefix="/api/contractorMaster", tags=["masters-contractor"])
app.include_router(bank_details_router, prefix="/api/bankDetailsMaster", tags=["masters-bank-details"])
app.include_router(item_bom_router, prefix="/api/itemBomMaster", tags=["masters-item-bom"])
app.include_router(shift_router, prefix="/api/hrmsMasters", tags=["hrms-masters"])
app.include_router(spell_router, prefix="/api/hrmsMasters", tags=["hrms-masters"])
app.include_router(machine_type_router, prefix="/api/machineTypeMaster", tags=["masters-machine-type"])

# BOM Costing routers
app.include_router(cost_element_router, prefix="/api/bomCostElement", tags=["bom-cost-element"])
app.include_router(bom_costing_router, prefix="/api/bomCosting", tags=["bom-costing"])
app.include_router(std_rate_card_router, prefix="/api/stdRateCard", tags=["std-rate-card"])

app.include_router(indent_router, prefix="/api/procurementIndent", tags=["procurement-indent"])
app.include_router(po_router, prefix="/api/procurementPO", tags=["procurement-po"])
app.include_router(inward_router, prefix="/api/procurementInward", tags=["procurement-inward"])
app.include_router(material_inspection_router, prefix="/api/materialInspection", tags=["procurement-material-inspection"])
app.include_router(sr_router, prefix="/api/storesReceipt", tags=["procurement-stores-receipt"])
app.include_router(drcr_note_router, prefix="/api/drcrNote", tags=["procurement-drcr-note"])
app.include_router(billpass_router, prefix="/api/billPass", tags=["procurement-bill-pass"])
app.include_router(procurement_reports_router, prefix="/api/procurementReports", tags=["procurement-reports"])
app.include_router(price_enquiry_router, prefix="/api/priceEnquiry", tags=["procurement-price-enquiry"])

# Jute Procurement routers
app.include_router(jute_po_router, prefix="/api/jutePO", tags=["jute-procurement-po"])
app.include_router(jute_gate_entry_router, prefix="/api/juteGateEntry", tags=["jute-procurement-gate-entry"])
app.include_router(jute_material_inspection_router, prefix="/api/juteMaterialInspection", tags=["jute-procurement-material-inspection"])
app.include_router(jute_mr_router, prefix="/api/juteMR", tags=["jute-procurement-mr"])
app.include_router(jute_agent_map_router, prefix="/api/juteAgentMap", tags=["jute-procurement-agent-map"])
app.include_router(jute_bill_pass_router, prefix="/api/juteBillPass", tags=["jute-procurement-bill-pass"])
app.include_router(jute_issue_router, prefix="/api/juteIssue", tags=["jute-procurement-issue"])
app.include_router(batch_daily_assign_router, prefix="/api/batchDailyAssign", tags=["jute-procurement-batch-daily-assign"])
app.include_router(jute_reports_router, prefix="/api/juteReports", tags=["jute-procurement-reports"])

# Jute SQC routers
app.include_router(morrah_wt_router, prefix="/api/juteSQC", tags=["jute-sqc-morrah-weight"])
app.include_router(spreader_roll_wt_router, prefix="/api/juteSQC", tags=["jute-sqc-spreader-roll-weight"])
app.include_router(spreader_sliver_wt_router, prefix="/api/juteSQC", tags=["jute-sqc-spreader-sliver-weight"])
app.include_router(breaker_card_swt_router, prefix="/api/juteSQC", tags=["jute-sqc-breaker-card"])
app.include_router(card_sliver_wt_router, prefix="/api/juteSQC", tags=["jute-sqc-card-sliver"])
app.include_router(fin_draw_sliver_wt_router, prefix="/api/juteSQC", tags=["jute-sqc-fin-draw"])
app.include_router(draw_sliver_wt_router, prefix="/api/juteSQC", tags=["jute-sqc-draw"])
app.include_router(spinning_sqc_router, prefix="/api/juteSQC", tags=["jute-sqc-spinning"])
app.include_router(yarn_tpi_router, prefix="/api/juteSQC", tags=["jute-sqc-yarn-tpi"])
app.include_router(qr_cv_15a_router, prefix="/api/juteSQC", tags=["jute-sqc-qr-cv-15a"])
app.include_router(finishing_sqc_router, prefix="/api/juteSQC", tags=["jute-sqc-finishing"])
app.include_router(weaving_sqc_router, prefix="/api/juteSQC", tags=["jute-sqc-weaving"])
app.include_router(beam_mr_router, prefix="/api/juteSQC", tags=["jute-sqc-beam-mr"])
app.include_router(fabric_construction_router, prefix="/api/juteSQC", tags=["jute-sqc-fabric-construction"])
app.include_router(cutting_length_router, prefix="/api/juteSQC", tags=["jute-sqc-cutting-length"])
app.include_router(width_picks_router, prefix="/api/juteSQC", tags=["jute-sqc-width-picks"])
app.include_router(stitch_router, prefix="/api/juteSQC", tags=["jute-sqc-stitch"])
app.include_router(bag_weight_router, prefix="/api/juteSQC", tags=["jute-sqc-bag-weight"])
app.include_router(bag_check_router, prefix="/api/juteSQC", tags=["jute-sqc-bag-check"])
app.include_router(packing_mr_router, prefix="/api/juteSQC", tags=["jute-sqc-packing-mr"])
app.include_router(fabric_fault_router, prefix="/api/juteSQC", tags=["jute-sqc-fabric-fault"])
app.include_router(emulsion_router, prefix="/api/juteSQC", tags=["jute-sqc-emulsion"])
app.include_router(humidity_router, prefix="/api/juteSQC", tags=["jute-sqc-humidity"])

# Jute Production routers (spreader workflow)
app.include_router(spreader_entry_router, prefix="/api/spreaderProd", tags=["jute-production-spreader-entry"])
app.include_router(spreader_issue_router, prefix="/api/spreaderProd", tags=["jute-production-spreader-issue"])
app.include_router(spreader_stock_router, prefix="/api/spreaderProd", tags=["jute-production-spreader-stock"])
app.include_router(spreader_masters_router, prefix="/api/spreaderMasters", tags=["jute-production-masters"])
app.include_router(drawing_entry_router, prefix="/api/drawingProd", tags=["jute-production-drawing-entry"])
app.include_router(drawing_masters_router, prefix="/api/drawingMasters", tags=["jute-production-drawing-masters"])
app.include_router(spinning_entry_router, prefix="/api/spinningProd", tags=["jute-production-spinning-entry"])
app.include_router(spinning_process_router, prefix="/api/spinningProd", tags=["jute-production-spinning-entry"])
app.include_router(spinning_quality_map_router, prefix="/api/spinningProd", tags=["spinning-quality-map"])
app.include_router(spinning_masters_router, prefix="/api/spinningMasters", tags=["jute-production-spinning-masters"])
app.include_router(winding_entry_router, prefix="/api/windingProd", tags=["jute-winding"])
app.include_router(stoppage_entry_router, prefix="/api/stoppageProd", tags=["jute-stoppage"])
app.include_router(spng_target_map_router, prefix="/api/spngTargetMap", tags=["spng-target-map"])
app.include_router(beaming_masters_router, prefix="/api/beamingMasters", tags=["jute-beaming-masters"])
app.include_router(beaming_target_map_router, prefix="/api/beamingTargetMap", tags=["jute-beaming-targets"])
app.include_router(beaming_entry_router, prefix="/api/beamingProd", tags=["jute-beaming"])
app.include_router(finishing_masters_router, prefix="/api/finishingMasters", tags=["jute-finishing-masters"])
app.include_router(finishing_target_map_router, prefix="/api/finishingTargetMap", tags=["jute-finishing-targets"])
app.include_router(finishing_entry_router, prefix="/api/finishingProd", tags=["jute-finishing"])
app.include_router(weaving_masters_router,    prefix="/api/weavingMasters",   tags=["jute-weaving-masters"])
app.include_router(weaving_target_map_router, prefix="/api/weavingTargetMap", tags=["jute-weaving-targets"])
app.include_router(weaving_entry_router,      prefix="/api/weavingProd",      tags=["jute-weaving"])
app.include_router(weaving_process_router,    prefix="/api/weavingProd",      tags=["jute-weaving"])
app.include_router(jute_production_reports_router, prefix="/api/juteProductionReports", tags=["jute-production-reports"])
app.include_router(winding_reports_router, prefix="/api/juteProductionReports", tags=["jute-winding-reports"])

# Inventory routers
app.include_router(issue_router, prefix="/api/inventoryIssue", tags=["inventory-issue"])
app.include_router(inventory_reports_router, prefix="/api/inventoryReports", tags=["inventory-reports"])
app.include_router(hrms_reports_router, prefix="/api/hrmsReports", tags=["hrms-reports"])
app.include_router(hrms_cash_hands_router, prefix="/api/hrmsReports", tags=["hrms-reports"])

# Sales routers
app.include_router(sales_enquiry_router, prefix="/api/salesEnquiry", tags=["sales-enquiry"])
app.include_router(quotation_router, prefix="/api/salesQuotation", tags=["sales-quotation"])
app.include_router(sales_order_router, prefix="/api/salesOrder", tags=["sales-order"])
app.include_router(delivery_order_router, prefix="/api/salesDeliveryOrder", tags=["sales-delivery-order"])
app.include_router(sales_invoice_router, prefix="/api/salesInvoice", tags=["sales-invoice"])
app.include_router(sales_reports_router, prefix="/api/salesReports", tags=["sales-reports"])

# HRMS routers
app.include_router(hrms_employee_router, prefix="/api/hrms", tags=["hrms-employee"])
app.include_router(hrms_pay_scheme_router, prefix="/api/hrms", tags=["hrms-pay-scheme"])
app.include_router(hrms_pay_param_router, prefix="/api/hrms", tags=["hrms-pay-param"])
app.include_router(hrms_pay_register_router, prefix="/api/hrms", tags=["hrms-pay-register"])
app.include_router(hrms_pay_roll_router, prefix="/api/hrms", tags=["hrms-pay-roll"])
app.include_router(hrms_pay_component_router, prefix="/api/hrms", tags=["hrms-pay-component"])
app.include_router(hrms_leave_type_router, prefix="/api/hrmsMasters", tags=["hrms-masters"])
app.include_router(hrms_leave_request_router, prefix="/api/hrms", tags=["hrms-leave-request"])
app.include_router(hrms_attendance_router, prefix="/api/hrms", tags=["hrms-attendance"])
app.include_router(hrms_payslip_print_component_router, prefix="/api/hrms", tags=["hrms-payslip-print-component"])
app.include_router(hrms_bio_attendance_router, prefix="/api/hrmsMasters", tags=["hrms-bio-attendance"])
app.include_router(hrms_outsider_rate_router, prefix="/api/hrmsMasters", tags=["hrms-masters"])
app.include_router(hrms_canteen_details_router, prefix="/api/hrms", tags=["hrms-canteen-details"])

# Accounting routers
app.include_router(accounting_router, prefix="/api/accounting", tags=["accounting"])

# Generic file-attachment routes (S3-backed, module-agnostic)
app.include_router(attachments_router, prefix="/api/attachments", tags=["attachments"])


# ── Mobile app (Flask / WSGI) ────────────────────────────────────────────────
# Mounted at root LAST so every FastAPI route above (all /api/*, plus /docs and
# /openapi.json) matches first; any other path falls through to the Flask app.
# The tenant database is chosen from the request Host subdomain inside the Flask
# app (e.g. sls.localhost:8000/dashboard-stats -> "sls" DB). enable_cors=False
# because CORS is already applied by FastAPI's middleware above.
from fastapi.middleware.wsgi import WSGIMiddleware

# The mobile app pulls in heavy, optional CV dependencies (opencv, dlib,
# face_recognition). Guard the mount so a missing mobile-only dependency in a
# given environment degrades to "mobile routes unavailable" instead of taking
# down the entire FastAPI portal. All /api/* routes above are unaffected.
try:
    from src.mobileapp.src import create_app as create_mobile_app

    mobile_flask_app = create_mobile_app(enable_cors=False)
    # Also mounted at /api: the portal frontend prefixes every call with /api
    # (see vowerp3ui NEXT_PUBLIC_API_BASE_URL), so Flask-served portal endpoints
    # like /attendance-report must resolve at /api/attendance-report too. Real
    # FastAPI routes still match first — only unmatched /api/* falls through.
    _mobile_wsgi = WSGIMiddleware(mobile_flask_app)
    app.mount("/api", _mobile_wsgi)
    app.mount("/", _mobile_wsgi)
except BaseException as _mobile_exc:  # pragma: no cover - env-dependent optional mount
    # BaseException (not just Exception): face_recognition calls quit() → SystemExit
    # when its model package is absent, which would otherwise abort app startup.
    import logging

    logging.getLogger("uvicorn.error").warning(
        "Mobile (Flask) app not mounted — optional dependency missing or import "
        "failed: %s. Portal /api/* routes are unaffected.",
        _mobile_exc,
    )


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def startup_event():
    logger.info("Application is starting up...")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Application is shutting down...")

# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     # 👇 Startup logic
#     logger.info("Application is starting up...")
#     yield
#     # 👇 Shutdown logic
#     logger.info("Application is shutting down...")

# app = FastAPI(lifespan=lifespan)

if __name__ == "__main__":
    import os, uvicorn
    # reload_dirs: without it StatReload polls the whole repo (incl. .venv)
    # 4x/second and pins a CPU core. Absolute — a relative "src" silently
    # watches nothing when started from another cwd (edits then never reload).
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True,
                reload_dirs=[os.path.dirname(os.path.abspath(__file__))])
