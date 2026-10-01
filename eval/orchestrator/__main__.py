"""`python -m orchestrator`: the CLI described in `orchestrator.cli`."""
from __future__ import annotations

import sys

from orchestrator.cli import main

if __name__ == "__main__":
    sys.exit(main())
