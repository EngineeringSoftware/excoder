import logging
import logging.handlers
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from queue import Queue
from typing import Any, TypeVar
import sys

from tqdm import tqdm


def get_handlers(
    level, formatter: logging.Formatter, log_path: Path
) -> list[logging.Handler]:
    # Console handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    log_path.parent.mkdir(exist_ok=True, parents=True)
    file_handler = logging.FileHandler(log_path)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    return [console_handler, file_handler]


@contextmanager
def setup_thread_logging(level, log_path: Path):
    """Set up a centralized logging queue for multithreading."""
    global log_queue
    # Create a queue for logging
    log_queue = Queue(-1)

    # Configure the QueueHandler
    queue_handler = logging.handlers.QueueHandler(log_queue)
    root = logging.getLogger()
    root.propagate = False
    root.handlers = []
    root.addHandler(queue_handler)
    root.setLevel(logging.CRITICAL + 1)
    logging.getLogger(__name__.split(".")[0]).setLevel(level)
    logging.getLogger("__main__").setLevel(level)
    formatter = logging.Formatter(
        "{%(threadName)s}[%(levelname)s]:%(asctime)s - %(message)s @%(filename)s:%(lineno)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Start the logging listener in a separate thread
    listener = logging.handlers.QueueListener(
        log_queue, *get_handlers(level, formatter, log_path)
    )
    listener.start()
    try:
        yield
    finally:
        listener.stop()


T = TypeVar("T")


def thread_map_w_log(func: Callable[[T], Any], arr: list[T], max_workers: int, desc=""):
    """Implementation of thread_map with tqdm for progress tracking."""
    from concurrent.futures import as_completed

    total = len(arr)

    with ThreadPoolExecutor(max_workers) as pool:
        # Use submit to create futures that we can track with tqdm
        futures = [pool.submit(func, item) for item in arr]
        results = []
        for future in tqdm(as_completed(futures), total=total, desc=desc):
            results.append(future.result())
        return results
