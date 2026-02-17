import contextlib
import multiprocessing as mp
import os
import resource
import sys
import time


def worker_with_queue(msg_queue: mp.Queue, limit_mb: int) -> None:
    """Child process that communicates progress before hitting OOM."""
    try:
        # Set address space limit
        limit_bytes = limit_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))

        msg_queue.put({'event': 'started', 'pid': os.getpid()})

        sink = []
        for i in range(1, 20):
            time.sleep(0.5)
            # Send status update
            msg_queue.put({'event': 'progress', 'iteration': i, 'mem_mb': i * 20})

            # Allocate 20MB per step
            sink.append(' ' * (20 * 1024 * 1024))

    except MemoryError:
        # Try to notify parent before dying
        with contextlib.suppress(Exception):
            msg_queue.put({'event': 'oom_failure'})
        sys.exit(1)


def listen_for_messages(msg_queue: mp.Queue) -> None:
    """Function to listen for messages from the child process."""
    while True:
        try:
            msg = msg_queue.get(timeout=1)
            print(f'[Listener] Received message: {msg}')
        except Exception as exc:
            print(f'[Listener] Error: {exc}')
            break


if __name__ == '__main__':
    mp.set_start_method('spawn', force=True)
    queue: mp.Queue = mp.Queue()

    # 150MB limit: iteration 7-8 should trigger OOM
    p = mp.Process(target=worker_with_queue, args=(queue, 150))
    p.start()

    print(f'[Parent] Watching Child {p.pid}...')
    char = None
    while char != 'q':
        # 1. Check for messages in the queue
        with contextlib.suppress(Exception):
            while not queue.empty():
                msg = queue.get_nowait()
                print(f'[Parent Info] {msg}')

        # 2. Check if process is still alive
        if not p.is_alive():
            print(f'[Parent] Child exited. Final Exit Code: {p.exitcode}')

        time.sleep(1)
        # 3. Non-blocking user input check
    print('[Parent] Safe exit.')
