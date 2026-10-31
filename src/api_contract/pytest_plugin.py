"""pytest integration: run the contract check inside the test suite.

Installed as a ``pytest11`` entry point, so it is active wherever api-contract
is installed. It does nothing unless asked:

* ``pytest --api-contract`` adds the check to the run: the report is printed
  at the end and a failing contract fails the session (exit code 1);
* the ``api_contract_check`` fixture (or :func:`assert_contract`) asserts in a
  test of your own, with the report as the failure message::

      def test_api_contract(api_contract_check):
          api_contract_check()          # or api_contract_check(fail_on="potentially-breaking")
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest


def assert_contract(
    *, config: Any = None, source: Any = None, fail_on: Any = None, against: str | None = None
) -> Any:
    """Run ``check`` and raise ``AssertionError`` with the text report if it fails."""
    from .config import load_config
    from .core import check
    from .report import text

    result = check(
        load_config(config) if isinstance(config, str) or config is None else config,
        source=source,
        fail_on=fail_on,
        against=against,
    )
    if not result.ok:
        raise AssertionError("\n" + text.render(result))
    return result


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("api-contract")
    group.addoption(
        "--api-contract",
        action="store_true",
        help="also check the API contract (snapshot vs the configured source)",
    )
    group.addoption(
        "--api-contract-against",
        metavar="REV",
        help="read the snapshot from this git revision (implies --api-contract)",
    )


@pytest.fixture
def api_contract_check() -> Callable[..., Any]:
    """``api_contract_check(config=None, source=None, fail_on=None, against=None)``."""
    return assert_contract


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    options = session.config.option
    against = getattr(options, "api_contract_against", None)
    if not (getattr(options, "api_contract", False) or against):
        return
    from .core import check
    from .model import ApiContractError
    from .report import text

    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    try:
        result = check(against=against)
    except ApiContractError as exc:
        message, failed = f"api-contract: error: {exc}\n", True
    else:
        message, failed = text.render(result), not result.ok
    if reporter is not None:
        reporter.write_sep("=", "api-contract")
        reporter.write(message)
    if failed and session.exitstatus == 0:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
