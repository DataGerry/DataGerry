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
`cmdb.models.location_model` <-> `cmdb.database.predefined_data.cmdb_data` cycle (fixed 2026-09-07 by
deferring the model layer's reach UP into the database layer into `validate_root_location`), plus
`cmdb.security.acl.builder`, whose own cycle with `base_query_builder` is gone since the ACL query
builder was rewritten, `routes/connection.py`, which needed a live app context on import until its
database manager moved from module level into the view, and the five `cmdb.open_celium` modules, which
cycled with `cmdb.manager` until the connector's own manager imports moved into their methods (all
2026-09-07). `cmdb/class_schema` has its own, wider tripwire in
tests/unit/test_class_schema_standalone_imports.py.

As of 2026-09-07 the invariant holds for **every** module: a scan of all 1,010 modules under `cmdb/`,
each imported as the first cmdb module of a purged `sys.modules`, reports zero failures (it was 16).
That scan is not this test - it takes ~55s, too slow to run on every suite - so what is pinned here is
the set of modules that has actually broken, which is where a regression is most likely. Re-run the
full scan by hand after touching a package `__init__` re-export or adding a cross-package import:

    for module in <every cmdb module>:
        purge every sys.modules key that is 'cmdb' or starts with 'cmdb.'
        importlib.import_module(module)

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
