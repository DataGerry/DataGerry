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
Integration test of the web service's pre-fork sequence against a real MongoDB

Runs in a fresh interpreter, because the test session itself runs threads (its own database manager's keep-alive and
driver monitors) and a census inside it would count them. The child does what `WebCmdbService._run` does before it
forks gunicorn - a manager without keep-alive, a real read, the close, the wait - and reports which threads ran while
connected and which are left; then it forks from the explicit context and reports the child's exit code. What is
pinned: the driver did run threads while connected, none is left after the close and the wait, and the fork succeeds
"""
import json
import subprocess
import sys
from pathlib import Path

from cmdb.database import MongoDatabaseManager
# -------------------------------------------------------------------------------------------------------------------- #

REPO_ROOT: Path = Path(__file__).resolve().parents[3]
CHILD_TIMEOUT_SECONDS: int = 60

CHILD_SCRIPT: str = """
import json, sys
from cmdb.database import MongoDatabaseManager
from cmdb.process_management.fork_safety import FORK_CONTEXT, other_live_threads, wait_until_single_threaded

host, port, database = sys.argv[1], int(sys.argv[2]), sys.argv[3]
dbm = MongoDatabaseManager(host, port, database, start_keepalive=False)
dbm.get_collection('framework.types', database).find_one({})
connected = [thread.name for thread in other_live_threads()]
dbm.connector.disconnect()
remaining = wait_until_single_threaded()
process = FORK_CONTEXT.Process(target=int)
process.start()
process.join()
print(json.dumps({'connected': connected, 'remaining': remaining, 'exitcode': process.exitcode}))
"""


def test_the_web_service_forks_from_a_single_threaded_process(database_manager: MongoDatabaseManager,
                                                              database_name: str) -> None:
    """Driver threads while connected, none after the close and the wait, a clean fork"""
    completed = subprocess.run(
        [sys.executable, '-c', CHILD_SCRIPT, database_manager.host, str(database_manager.port), database_name],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=CHILD_TIMEOUT_SECONDS, check=True,
    )
    report: dict = json.loads(completed.stdout.strip().splitlines()[-1])

    assert report['connected'], 'the driver ran no thread - the test would prove nothing'
    assert report['remaining'] == []
    assert report['exitcode'] == 0
