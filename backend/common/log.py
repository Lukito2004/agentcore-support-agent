import json
import logging
import sys


class JsonFormatter(logging.Formatter):
    """One JSON object per line, so CloudWatch Logs Insights can query fields directly."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {"level": record.levelname, "message": record.getMessage()}
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False  # skip Lambda's plain-text root handler
    return logger
