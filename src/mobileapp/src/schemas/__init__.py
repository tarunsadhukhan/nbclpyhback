from typing import Any, Dict, List, Tuple


class Schema:
    """
    Lightweight request-validation base.

    Subclasses declare:
        required = ['field1', 'field2']
        optional = ['field3']          # informational only

    Usage:
        ok, errors = MySchema.validate(request.json)
        if not ok:
            return jsonify({"status": "error", "message": errors[0]}), 400
    """
    required: List[str] = []
    optional: List[str] = []

    @classmethod
    def validate(cls, data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        if not data:
            return False, ["Request body is required"]
        errors = [
            f"'{f}' is required"
            for f in cls.required
            if not data.get(f) and data.get(f) != 0
        ]
        return (len(errors) == 0), errors
