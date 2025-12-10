import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import os

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / "agent.log"

# Configure root logger
logger = logging.getLogger("SelfHealingTerraform")
logger.setLevel(logging.DEBUG)

# File handler (with rotation)
file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=2 * 1024 * 1024,   # 2MB
    backupCount=5
)
file_handler.setLevel(logging.DEBUG)
file_formatter = logging.Formatter(
    "%(asctime)s :: %(levelname)s :: %(name)s :: %(message)s"
)
file_handler.setFormatter(file_formatter)

# Console handler (shows in Streamlit terminal)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter("%(levelname)s :: %(message)s")
console_handler.setFormatter(console_formatter)

# Attach handlers only once
if not logger.handlers:
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


def get_logger():
    return logger
