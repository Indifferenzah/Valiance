import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
import colorama
from colorama import Fore, Style

colorama.init(autoreset=True)

class ColoredFormatter(logging.Formatter):
    def format(self, record):
        if record.levelno == logging.INFO:
            record.levelname = f"{Fore.GREEN}[INFO]{Style.RESET_ALL}"
        elif record.levelno == logging.WARNING:
            record.levelname = f"{Fore.YELLOW}[WARN]{Style.RESET_ALL}"
        elif record.levelno == logging.ERROR:
            record.levelname = f"{Fore.RED}[ERROR]{Style.RESET_ALL}"
        elif record.levelno == logging.DEBUG:
            record.levelname = f"{Fore.BLUE}[DEBUG]{Style.RESET_ALL}"
        elif record.levelno == logging.CRITICAL:
            record.levelname = f"{Fore.RED}[FATAL]{Style.RESET_ALL}"
        else:
            record.levelname = f"[{record.levelname}]"

        return super().format(record)

def setup_logger():
    logs_dir = 'logs'
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)

    logger = logging.getLogger('valiance_bot')
    logger.setLevel(logging.DEBUG)

    console_formatter = ColoredFormatter('%(asctime)s %(levelname)s - %(message)s', datefmt='[%d-%m-%Y] [%H:%M:%S]')
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='[%d-%m-%Y] [%H:%M:%S]')

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(console_formatter)

    today = datetime.now().strftime('%Y-%m-%d')
    log_file = os.path.join(logs_dir, f'bot_{today}.log')
    file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=5)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger

logger = setup_logger()
