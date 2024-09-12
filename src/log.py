import logging


def init_logger(logger: logging.Logger, log_level: int, log_file_path: str | None = None):
    logger.setLevel(log_level)

    shell_formatter = logging.Formatter(
        "[%(asctime)s][%(levelname)s]: %(message)s", datefmt="%H:%M:%S"
    )
    ch = logging.StreamHandler()
    ch.set_name("shell")
    ch.setLevel(log_level)
    ch.setFormatter(shell_formatter)
    logger.addHandler(ch)

    if log_file_path is None:
        return

    file_formatter = logging.Formatter(
        "[%(asctime)s][%(levelname)s]: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    fh = logging.FileHandler(log_file_path, encoding="utf-8")
    fh.set_name("file")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(file_formatter)
    logger.addHandler(fh)


def set_logger_prefix(logger: logging.Logger, prefix: str = ""):
    default_file_formatter = logging.Formatter(
        "[%(asctime)s][%(levelname)s]: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    default_shell_formatter = logging.Formatter(
        "[%(asctime)s][%(levelname)s]: %(message)s", datefmt="%H:%M:%S"
    )
    file_formatter = logging.Formatter(
        f"[%(asctime)s][%(levelname)s][{prefix}]: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    shell_formatter = logging.Formatter(
        f"[%(asctime)s][%(levelname)s][{prefix}]: %(message)s", datefmt="%H:%M:%S"
    )
    if prefix == "":
        file_formatter = default_file_formatter
        shell_formatter = default_shell_formatter
    for handler in logger.handlers:
        if handler.name == "file":
            handler.setFormatter(file_formatter)
        elif handler.name == "shell":
            handler.setFormatter(shell_formatter)
