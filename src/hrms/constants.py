"""HRMS module constants."""

# Standard status IDs (matching approval workflow)
EMPLOYEE_STATUS = {
    "DRAFT": 21,
    "OPEN": 1,
    "PENDING_APPROVAL": 20,
    "APPROVED": 3,
    "REJECTED": 4,
    "CLOSED": 5,
    "CANCELLED": 6,
}

# HRMS-specific employee lifecycle status IDs
EMPLOYEE_LIFECYCLE_STATUS = {
    "JOINED": 35,
    "REJECTED": 4,
    "BLACKLISTED": 46,
    "RESIGNED": 39,
    "IN_NOTICE": 40,
    "TERMINATED": 41,
    "RETIRED": 42,
}

# Status IDs that require resign details (date + reason saved to hrms_ed_resign_details)
RESIGN_DETAIL_STATUSES = {41, 42, 39, 46}  # Terminated, Retired, Resigned, Blacklisted

# Section names for employee wizard step saves
EMPLOYEE_SECTIONS = [
    "personal",
    "contact",
    "address",
    "education",
    "experience",
    "official",
    "bank",
    "pf",
    "esi",
]

# Employee wizard step definitions
EMPLOYEE_STEPS = [
    {"step_id": 1, "step_name": "Personal Info", "sections": ["personal", "contact", "address", "education", "experience"]},
    {"step_id": 2, "step_name": "Official Info", "sections": ["official", "bank"]},
    {"step_id": 3, "step_name": "Upload Documents", "sections": []},
    {"step_id": 4, "step_name": "Generate Letters", "sections": []},
    {"step_id": 5, "step_name": "Onboarding", "sections": []},
    {"step_id": 6, "step_name": "Shift & Leave", "sections": []},
    {"step_id": 7, "step_name": "Medical Enrollment", "sections": ["pf", "esi"]},
]

# Pay component types
PAY_COMPONENT_TYPES = {
    "INPUT": 0,
    "EARNING": 1,
    "DEDUCTION": 2,
    "SUMMARY": 3,
}
