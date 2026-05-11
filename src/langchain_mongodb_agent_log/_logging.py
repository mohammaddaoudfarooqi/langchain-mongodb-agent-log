"""Single named logger for the package. Callers configure their own handlers."""
from __future__ import annotations

import logging

LOGGER_NAME = "langchain_mongodb_agent_log"


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
