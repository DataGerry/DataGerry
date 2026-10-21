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
Import-order tripwire for the modules that a script, a hidden import or a test may enter first

Nothing about `import cmdb.x` should depend on which cmdb module a process happened to import before
it, but a two-way dependency between two packages makes it depend on exactly that: whichever half is
entered first re-enters itself while still half-initialised and raises
`ImportError: cannot import name '...' from partially initialized module`. The application, gunicorn
and the test suite all enter through one particular half, so such a cycle stays invisible until
something enters through the other one - a maintenance script, a PyInstaller hidden import, or a new
test module that imports the lower half directly.

The modules pinned here are the ones that were reachable through the
`cmdb.models.location_model` <-> `cmdb.database.predefined_data.cmdb_data` cycle (broken by
deferring the model layer's reach UP into the database layer into `validate_root_location`), plus
`cmdb.security.acl.builder`, whose own cycle with `base_query_builder` is gone since the ACL query
builder was rewritten, `routes/connection.py`, which needed a live app context on import until its
database manager moved from module level into the view, and the five `cmdb.open_celium` modules, which
cycled with `cmdb.manager` until the connector's own manager imports moved into their methods (all
the same rule), and the two `cmdb.framework.search` modules that cycled with `cmdb.manager` while
`Builder` lived inside it. `cmdb/class_schema` has its own, wider tripwire.

The invariant holds for **every** module, and a pinned list alone does not show it: two
`cmdb.framework.search` modules broke while this list did not name them. The full scan imports each of
the ~1,100 modules under `cmdb/` as the first cmdb module of a purged `sys.modules`. It takes about a
minute, too slow for every suite run, so it is a CI step of its own (the lint job) and runs by hand the
same way after touching a package `__init__` re-export or adding a cross-package import:

    python -m tests.utils.first_import_scan

Pure test: no Mongo, no Flask, no fixtures (one subprocess)
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[2]

# Every module here must import as the FIRST cmdb module of a process. The list is the fixed set of
# the cycle above, so it is written out rather than discovered - a new entry means a new module that
# is expected to survive being imported first
MUST_IMPORT_FIRST: tuple[str, ...] = (
    # The two halves of the fixed cycle
    'cmdb.models.location_model',
    'cmdb.models.location_model.location_utils',
    'cmdb.database.predefined_data.cmdb_data',
    'cmdb.database.predefined_data.cmdb_data.cmdb_location_data',
    # Reached the cycle through collection_validator's predefined-root import
    'cmdb.database.database_services',
    'cmdb.database.database_services.collection_validator',
    'cmdb.database.database_services.database_services_constants',
    'cmdb.database.database_services.database_updater',
    'cmdb.database.database_services.updater_helpers',
    # The three process entry points, which reach it through the database services
    'cmdb.interface.gunicorn',
    'cmdb.interface.route_utils',
    'cmdb.interface.rest_api.init_rest_api',
    # Cycled with cmdb.manager.query_builder.base_query_builder until the ACL builder rewrite
    'cmdb.security.acl.builder',
    # Needed a live app context on import until its database manager moved into the view
    'cmdb.interface.rest_api.routes.connection',
    # Cycled with cmdb.manager until the connector's two manager imports moved into their methods
    'cmdb.open_celium',
    'cmdb.open_celium.cached_oc_id_type_enum',
    'cmdb.open_celium.oc_api_connector',
    'cmdb.open_celium.oc_constants',
    'cmdb.open_celium.oc_helpers',
    # Cycled with cmdb.manager while Builder lived inside it: importing the stage vocabulary loaded every
    # manager, and rights_manager / the search pipeline builders import these two back
    'cmdb.framework.search.list_search',
    'cmdb.framework.search.search_reference_match',
)

# Imports each module with sys.modules purged of every cmdb entry first, which is what makes it the
# FIRST cmdb import of that state - the situation a fresh interpreter is in
IMPORT_EACH_FIRST = '''
import importlib
import sys

failures = []

for module in {modules!r}:
    for cached in [name for name in sys.modules if name == 'cmdb' or name.startswith('cmdb.')]:
        del sys.modules[cached]

    try:
        importlib.import_module(module)
    except Exception as err:  # noqa: BLE001 - any failure is a failure of this contract
        failures.append(f'{{module}}: {{type(err).__name__}}: {{err}}')

print('\\n'.join(failures))
sys.exit(1 if failures else 0)
'''


def test_modules_are_importable_as_the_first_cmdb_import():
    """Each pinned module imports cleanly as the first cmdb module of a process"""
    result = subprocess.run(
        [sys.executable, '-c', IMPORT_EACH_FIRST.format(modules=MUST_IMPORT_FIRST)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, f'modules that cannot be imported first:\n{result.stdout}'
