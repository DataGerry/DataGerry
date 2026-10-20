# DATAGERRY - OpenSource Enterprise CMDB
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
Unit tests for the SIGTERM handler in cmdb.__main__

``_stop_app`` is installed with ``signal.signal``, which calls it positionally with the signal number and
the interrupted frame. The tests pin that it is a valid handler and stops the process manager whatever it
is handed.

**They run in a subprocess.** Importing ``cmdb.__main__`` applies the application's logging
configuration at module level, which disables every logger created before it - in the test process that
would silently empty ``caplog`` for every later test
"""
import subprocess
import sys
from pathlib import Path
# -------------------------------------------------------------------------------------------------------------------- #

REPO_ROOT: Path = Path(__file__).resolve().parents[2]

PROBE: str = '''
import signal
from unittest.mock import patch

import cmdb.__main__ as main_module

signal.signal(signal.SIGUSR1, main_module._stop_app)
assert signal.getsignal(signal.SIGUSR1) is main_module._stop_app

for frame in (None, object()):
    with patch.object(main_module, 'app_manager') as app_manager:
        main_module._stop_app(signal.SIGTERM, frame)
    app_manager.stop_app.assert_called_once_with()

print('ok')
'''


def test_stop_app_is_a_signal_handler_that_always_stops_the_process_manager() -> None:
    """Accepted by signal.signal, and the shutdown is unconditional - neither argument changes it."""
    result = subprocess.run(
        [sys.executable, '-c', PROBE], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60, check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith('ok')
