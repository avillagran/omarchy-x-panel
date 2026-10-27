"""Bounded subprocess output: byte budget and total deadline before collection."""
import os
import selectors
import signal
import subprocess
import time


def capture(command, *, timeout=5, limit=262144, env=None):
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               env=env, start_new_session=True)
    chunks = bytearray()
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Process deadline exceeded")
                if not selector.select(remaining):
                    raise TimeoutError("Process deadline exceeded")
                chunk = os.read(process.stdout.fileno(), min(65536, limit + 1 - len(chunks)))
                if not chunk:
                    break
                chunks.extend(chunk)
                if len(chunks) > limit:
                    raise ValueError("Process output exceeds byte budget")
        if process.wait(timeout=max(0.001, deadline - time.monotonic())):
            raise ValueError("Process failed")
        return chunks.decode("utf-8")
    finally:
        # Kill descendants too, including a producer that kept stdout open.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.stdout.close()
        process.wait()


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.write(capture(sys.argv[1:]))
    except (OSError, ValueError, TimeoutError, subprocess.SubprocessError):
        sys.exit(1)
