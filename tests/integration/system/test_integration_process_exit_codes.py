# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2026 becon GmbH
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Integration test: the exit code of the real DataGerry process, as systemd sees it

Each case runs ``cmdb.__main__._start_app`` in a fresh interpreter with the real ProcessManager, its real
ProcessController and a real fork - only the registered service is a stub (``tests.utils.process_exit_stubs``). A
service that crashes makes the process exit 1, so ``Restart=on-failure`` restarts it; a service that cannot be started
exits 1 too; SIGTERM (``systemctl stop``) and SIGINT (Ctrl+C) make it exit 0. Before the fix every one of these
exited 0
"""
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from cmdb.process_management.process_constants import EXIT_CODE_FAILED, EXIT_CODE_STOPPED
from tests.utils.process_exit_stubs import READY_LINE
# -------------------------------------------------------------------------------------------------------------------- #

REPO_ROOT: Path = Path(__file__).resolve().parents[3]
TIMEOUT_SECONDS: int = 60
CRASHING: str = 'tests.utils.process_exit_stubs.CrashingService'
WAITING: str = 'tests.utils.process_exit_stubs.WaitingService'
NOT_LOADABLE: str = 'tests.utils.process_exit_stubs.NoSuchService'
#: The service reports ready right after the fork; the parent installs its SIGINT handler a moment later
SETTLE_SECONDS: float = 1.0
RUNNER: str = """
import sys
from cmdb.process_management.cmdb_process import CmdbProcess
from cmdb.process_management.process_manager import ProcessManager
import cmdb.__main__ as main_module

ProcessManager._initialize_service_definitions = lambda self: [CmdbProcess('stub', sys.argv[1])]
main_module.app_manager = ProcessManager()
main_module._start_app()
"""


def _run(service: str) -> subprocess.CompletedProcess:
    """Runs DataGerry's start with one service until it ends by itself"""
    return subprocess.run([sys.executable, '-c', RUNNER, service], cwd=REPO_ROOT, capture_output=True, text=True,
                          timeout=TIMEOUT_SECONDS, check=False)


def test_a_crashed_service_ends_the_process_with_1() -> None:
    """The boot-failure case: the service exits non-zero, the process exits 1 - systemd restarts it"""
    assert _run(CRASHING).returncode == EXIT_CODE_FAILED


def test_a_service_that_cannot_be_started_ends_the_process_with_1() -> None:
    """start_app answers False: torn down, exit 1"""
    completed = _run(NOT_LOADABLE)

    assert completed.returncode == EXIT_CODE_FAILED


@pytest.mark.parametrize('signal_number', [signal.SIGTERM, signal.SIGINT], ids=['SIGTERM', 'SIGINT'])
def test_a_requested_stop_ends_the_process_with_0(signal_number: int) -> None:
    """systemctl stop / Ctrl+C: the services are stopped and the process exits 0 - systemd leaves it alone"""
    with subprocess.Popen([sys.executable, '-c', RUNNER, WAITING], cwd=REPO_ROOT, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, text=True) as process:
        try:
            ready: str = process.stdout.readline() if process.stdout else ''
            assert READY_LINE in ready
            time.sleep(SETTLE_SECONDS)
            process.send_signal(signal_number)
            assert process.wait(timeout=TIMEOUT_SECONDS) == EXIT_CODE_STOPPED
        finally:
            if process.poll() is None:
                process.kill()
