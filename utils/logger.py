"""
Centralised logging. All modules call get_logger() to get a
consistent logger that writes to both console and a rotating file.
"""

import os
import logging
from logging.handlers import RotatingFileHandler
from config import Config

os.makedirs(Config.LOG_DIR, exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # Rotating file handler (5 MB max, keep 5 backups)
    fh = RotatingFileHandler(Config.ERROR_LOG_PATH, maxBytes=5*1024*1024, backupCount=5)
    fh.setLevel(logging.WARNING)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger
