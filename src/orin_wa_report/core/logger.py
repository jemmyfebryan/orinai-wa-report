import logging
import sys

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

    if not logger.hasHandlers():
        logger.setLevel(logging.INFO)

        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)

        # Include service in format if provided
        service_fmt = f"[{service}] " if service else ""
        formatter = ColorFormatter(
            f"%(asctime)s - %(levelname)s - {service_fmt}%(filename)s - %(message)s"
        )
        handler.setFormatter(formatter)

        logger.addHandler(handler)

    return logger
