from botocore.exceptions import BotoCoreError, ClientError

# DynamoDB error codes that are safe to retry with backoff.
RETRYABLE_AWS_CODES = frozenset(
    {
        "ProvisionedThroughputExceededException",
        "ThrottlingException",
        "RequestLimitExceeded",
        "InternalServerError",
        "ServiceUnavailable",
    }
)


class ToolError(Exception):
    """An expected tool failure, returned to the caller as a structured error."""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def from_aws_error(exc: ClientError | BotoCoreError) -> ToolError:
    """Map a boto3 failure to a ToolError without leaking internal details."""
    if isinstance(exc, ClientError):
        aws_code = exc.response.get("Error", {}).get("Code", "")
        retryable = aws_code in RETRYABLE_AWS_CODES
    else:
        retryable = True  # connection resets and timeouts
    return ToolError("BACKEND_UNAVAILABLE", "the data store did not respond", retryable=retryable)
