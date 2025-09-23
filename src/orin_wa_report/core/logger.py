import logging
import sys
import os

# ANSI escape codes for colors
COLOR_CODES = {
    'DEBUG': '\033[94m',     # Blue
    'INFO': '\033[92m',      # Green
    'WARNING': '\033[93m',   # Yellow
    'ERROR': '\033[91m',     # Red
    'CRITICAL': '\033[95m',  # Magenta
    'RESET': '\033[0m'       # Reset to default
}

class ColorFormatter(logging.Formatter):
    def format(self, record):
        log_color = COLOR_CODES.get(record.levelname, '')
        reset = COLOR_CODES['RESET']
        record.msg = f"{log_color}{record.msg}{reset}"
        return super().format(record)

def get_logger(name=__name__, service: str = None):
    logger = logging.getLogger(name)
    
    # Get log level from environment variable, default to INFO
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, log_level, logging.INFO)

    if not logger.hasHandlers():
        logger.setLevel(level)

        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)

        # Include service in format if provided
        service_fmt = f"[{service}] " if service else ""
        formatter = ColorFormatter(
            f"%(asctime)s - %(levelname)s - {service_fmt}%(filename)s - %(message)s"
        )
        handler.setFormatter(formatter)

        logger.addHandler(handler)

    return logger
