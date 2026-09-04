import logging
import logging.handlers
import multiprocessing as mp
from typing import Any, TypeVar
from collections.abc import Callable

import seutil as su
from tqdm import tqdm

log_queue = None


def setup_logging_queue():
    """Set up a centralized logging queue for multiprocessing."""
    global log_queue
    # Create a queue for logging
    log_queue = mp.Queue(-1)

    # Configure the QueueHandler
    queue_handler = logging.handlers.QueueHandler(log_queue)
    root = logging.getLogger(su.log.LOGGING_NAMESPACE)
    root.propagate = False
    root.handlers = []
    root.addHandler(queue_handler)
    root.setLevel(logging.INFO)  # Set appropriate level

    # Set up the listener with the handlers that will process the actual logs
    formatter = logging.Formatter(
        "[%(processName)s]: %(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    # Start the logging listener in a separate process
    listener = logging.handlers.QueueListener(log_queue, stream_handler)
    listener.start()

    return listener


def _worker_init(queue: mp.Queue):
    """Initialize logging for a worker process."""
    # Set up queue handler in the child process
    queue_handler = logging.handlers.QueueHandler(queue)
    root = logging.getLogger(su.log.LOGGING_NAMESPACE)
    root.propagate = False
    root.handlers = []
    root.addHandler(queue_handler)
    root.setLevel(logging.INFO)


def pool_w_log(max_workers: int):
    return mp.Pool(max_workers, initializer=_worker_init, initargs=(log_queue,))


T = TypeVar("T")


def process_map_w_log(
    func: Callable[[T], Any], arr: list[T], max_workers: int, desc=""
):
    """Implementation of process_map with tqdm for progress tracking."""
    total = len(arr)

    with mp.Pool(max_workers, initializer=_worker_init, initargs=(log_queue,)) as pool:
        # Use imap for a generator that we can track with tqdm
        results = []
        for result in tqdm(pool.imap(func, arr), total=total, desc=desc):
            results.append(result)
        return results
