import os

MAX_POD_ITERS = int(os.environ.get("MAX_POD_ITERS", "3"))
EXEC_TIMEOUT_S = int(os.environ.get("EXEC_TIMEOUT_S", "300"))
MAX_PODS = int(os.environ.get("MAX_PODS", "20"))
