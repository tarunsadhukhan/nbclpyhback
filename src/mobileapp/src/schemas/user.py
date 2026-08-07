from src.mobileapp.src.schemas import Schema


class SignupSchema(Schema):
    required = ['email_id', 'name', 'password']


class LoginSchema(Schema):
    """Accepts email_id or username (legacy) as the login identifier."""
    required = ['password']

    @classmethod
    def validate(cls, data):
        ok, errors = super().validate(data)
        if not ok:
            return ok, errors
        if not data.get('email_id') and not data.get('username'):
            return False, ["'email_id' is required"]
        return True, []
