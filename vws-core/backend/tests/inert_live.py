"""LIVE-BAN test seam: only tests of the inert live code lift the ban.

AUTO_LIVE is banned in ``backend.core.config``. The live guard, live security
and executor live branches stay in the tree, inert, and keep their existing
refusal tests. Those tests (and only those) lift the ban for one block so a
synthetic AUTO_LIVE snapshot can reach the inert code and prove it still
refuses. No production code path can lift it; ``test_auto_live_ban`` pins that.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

import backend.core.config as config_module


@contextmanager
def inert_live_code() -> Iterator[None]:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(config_module, "BANNED_EXECUTION_MODES", frozenset())
        yield
