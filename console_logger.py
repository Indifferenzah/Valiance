import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
import colorama
from colorama import Fore, Style

colorama.init(autoreset=True)

TTS_LEVEL_NUM = 25  # Tra INFO (20) e WARNING (30)
logging.addLevelName(TTS_LEVEL_NUM, "TTS")

def tts(self, message, *args, **kwargs):
    if self.isEnabledFor(TTS_LEVEL_NUM):
        self._log(TTS_LEVEL_NUM, message, args, **kwargs)

logging.Logger.tts = tts
logging.TTS = TTS_LEVEL_NUM

EXCEPTION_LEVEL_NUM = 35  # Tra INFO (20) e WARNING (30)
logging.addLevelName(EXCEPTION_LEVEL_NUM, "EXCEPTION")

def exception(self, message, *args, **kwargs):
    if self.isEnabledFor(EXCEPTION_LEVEL_NUM):
        self._log(EXCEPTION_LEVEL_NUM, message, args, **kwargs)

logging.Logger.exception = exception
logging.EXCEPTION = EXCEPTION_LEVEL_NUM

class ColoredFormatter(logging.Formatter):
    def format(self, record):
        if record.levelno == logging.INFO:
            record.levelname = f"{Fore.GREEN}[INFO]{Style.RESET_ALL}"
        elif record.levelno == logging.WARNING:
            record.levelname = f"{Fore.YELLOW}[WARNING]{Style.RESET_ALL}"
        elif record.levelno == logging.ERROR:
            record.levelname = f"{Fore.RED}[ERROR]{Style.RESET_ALL}"
        elif record.levelno == logging.DEBUG:
            record.levelname = f"{Fore.BLUE}[DEBUG]{Style.RESET_ALL}"
        elif record.levelno == logging.CRITICAL:
            record.levelname = f"{Fore.RED}[FATAL]{Style.RESET_ALL}"
        elif record.levelno == logging.TTS:
            record.levelname = f"{Fore.CYAN}[TTS]{Style.RESET_ALL}"
        elif record.levelno == logging.EXCEPTION:
            record.levelname = f"{Fore.LIGHTYELLOW_EX}[EXCEPTION]{Style.RESET_ALL}"
        else:
            record.levelname = f"[{record.levelname}]"

        return super().format(record)

def setup_logger():
    logs_dir = 'logs'
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)

    logger = logging.getLogger('valiance_bot')
    logger.setLevel(logging.DEBUG)

    console_formatter = ColoredFormatter('%(asctime)s %(levelname)s: %(message)s', datefmt='[%H:%M:%S]')
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s: %(message)s', datefmt='[%H:%M:%S]')

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(console_formatter)

    today = datetime.now().strftime('%Y-%m-%d')
    base_log_file = os.path.join(logs_dir, f'bot_{today}.log')
    log_file = base_log_file
    counter = 1
    while os.path.exists(log_file):
        log_file = os.path.join(logs_dir, f'bot_{today}_{counter}.log')
        counter += 1
    file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger

logger = setup_logger()
