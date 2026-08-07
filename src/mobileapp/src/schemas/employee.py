from src.mobileapp.src.schemas import Schema


class RegisterEmployeeSchema(Schema):
    required = ['emp_code', 'name', 'image']
    optional = ['department_id', 'designation_id', 'shift_id',
                'department',    'designation',    'shift']


class UpdateEmployeeSchema(Schema):
    """At least one editable field must be present — validated in the route."""
    required = []
    optional = ['name', 'emp_code', 'department_id',
                'designation_id', 'shift_id', 'face_image']


class UpdateFaceSchema(Schema):
    required = ['image']
