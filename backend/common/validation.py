import re

from common.errors import ToolError

CUSTOMER_ID_PATTERN = re.compile(r"^CUST-\d{3,10}$")
ORDER_ID_PATTERN = re.compile(r"^\d{1,12}$")


def require_id(args: dict, field: str, pattern: re.Pattern) -> str:
    value = args.get(field)
    if not isinstance(value, str) or not pattern.fullmatch(value.strip()):
        raise ToolError("INVALID_ARGUMENT", f"{field} is missing or has an invalid format")
    return value.strip()
