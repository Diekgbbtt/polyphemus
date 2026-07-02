import time

def wait_for(fn, timeout=120, interval=2):
    """Poll fn() until truthy or non-raising; re-raise last error on timeout."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            r = fn()
            if r:
                return r
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(interval)
    if last:
        raise last
    raise TimeoutError(f"wait_for timed out after {timeout}s")
