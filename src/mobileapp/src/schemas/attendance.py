from src.mobileapp.src.schemas import Schema


class MarkAttendanceSchema(Schema):
    required = ['image']
    optional = ['att_type', 'attendance_type', 'attendance_date',
                'department_id', 'designation_id', 'shift_id',
                'shift_hours', 'working_hours', 'idle_hours']


class ManualAttendanceSchema(Schema):
    required = ['emp_code']
    optional = ['att_type', 'attendance_type', 'attendance_date', 'branch_id',
                'department_id', 'designation_id', 'shift_id',
                'shift_hours', 'working_hours', 'idle_hours',
                'status', 'attendance_source', 'get_location', 'machine_ids']


class CheckFaceSchema(Schema):
    required = ['image']


class AttendanceReportSchema(Schema):
    """Query-param schema — validate from request.args."""
    required = ['from_date', 'to_date']
    optional = ['department_id', 'emp_code', 'designation_id', 'att_type', 'spell_id']
