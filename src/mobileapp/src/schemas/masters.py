from src.mobileapp.src.schemas import Schema


class DepartmentSchema(Schema):
    required = ['name']


class ShiftSchema(Schema):
    required = ['name', 'start_time', 'end_time']


class OccupationSchema(Schema):
    required = ['name']


class CompanyBranchSchema(Schema):
    """Used for branch lookup — company_id must be supplied as query param."""
    required = ['company_id']
