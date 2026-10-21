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
Import-order tripwire for cmdb/class_schema

Every schema module must be importable ON ITS OWN, as the first cmdb module of a process. That is not
free: a model imports its schema at class-definition time while a schema names the model's key and enum
constants, so a module-level import from cmdb.models inside a schema module closes the cycle

    cmdb.class_schema.x -> cmdb.models.x (package __init__) -> the model -> back into the schema module
    while it is still half-initialised

which raises ImportError for whoever imports the schema half first. The application and the test suite
happen to import the model half first, so the breakage is invisible until a script, a PyInstaller hidden
import or a new test starts at a schema module. Both tests below fail loudly instead:

  - the behavioural one imports all 39 schema modules, each as the first cmdb module of a clean
    interpreter state
  - the static one pins the rule that keeps them that way - no module-level cmdb import outside
    cmdb.class_schema itself

Pure tests: no Mongo, no Flask, no fixtures (one subprocess)
"""
import ast
import subprocess
import sys
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
CLASS_SCHEMA_ROOT: Path = REPO_ROOT / 'cmdb' / 'class_schema'

# The one cmdb package a schema module may name at module level: a sibling schema, which cannot cycle
# back into the model layer
ALLOWED_MODULE_LEVEL_PACKAGE: str = 'cmdb.class_schema'

# Imports each module with sys.modules purged of every cmdb entry first, which is what makes each
# import the FIRST cmdb import of that state - the situation a fresh interpreter is in
IMPORT_EACH_FIRST = '''
import importlib
import sys
from pathlib import Path

modules = sorted(
    '.'.join(path.relative_to(Path('.')).with_suffix('').parts)
    for path in Path('cmdb/class_schema').rglob('*.py')
    if path.name != '__init__.py'
)

failures = []

for module in modules:
    for cached in [name for name in sys.modules if name == 'cmdb' or name.startswith('cmdb.')]:
        del sys.modules[cached]

    try:
        importlib.import_module(module)
    except Exception as err:  # noqa: BLE001 - any failure is a failure of this contract
        failures.append(f'{module}: {type(err).__name__}: {err}')

print(len(modules))
print('\\n'.join(failures))
sys.exit(1 if failures else 0)
'''


def _module_level_imports(path: Path) -> list[str]:
    """
    Collects the module names a Python file imports at MODULE level

    Imports nested inside a function or a class body are ignored - deferring an import into the
    builder function is exactly the fix this rule protects.

    Args:
        path (Path): The Python file to read

    Returns:
        list[str]: Imported module names, one entry per imported module (not per imported symbol)
    """
    imported: list[str] = []

    for node in ast.parse(path.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.append(node.module)

    return imported


def test_class_schema_modules_are_importable_first():
    """Every cmdb/class_schema module imports cleanly as the first cmdb module of a process"""
    result = subprocess.run(
        [sys.executable, '-c', IMPORT_EACH_FIRST],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    checked, _, failures = result.stdout.partition('\n')

    assert result.returncode == 0, f'schema modules that cannot be imported first:\n{failures}'
    # Guards the walk itself: an empty discovery would make the assertion above pass for nothing
    assert int(checked) == len(list(CLASS_SCHEMA_ROOT.rglob('*.py'))) - len(
        list(CLASS_SCHEMA_ROOT.rglob('__init__.py'))
    )


def test_no_schema_module_imports_cmdb_at_module_level():
    """No schema module names a cmdb package other than cmdb.class_schema at module level"""
    offenders: list[str] = []

    for path in sorted(CLASS_SCHEMA_ROOT.rglob('*.py')):
        if path.name == '__init__.py':
            continue

        offenders.extend(
            f'{path.relative_to(REPO_ROOT)}: {module}'
            for module in _module_level_imports(path)
            if module.split('.')[0] == 'cmdb' and not module.startswith(ALLOWED_MODULE_LEVEL_PACKAGE)
        )

    assert not offenders, (
        'move these into the get_<class>_schema() function - a module-level cmdb import closes the '
        'schema <-> model cycle:\n' + '\n'.join(offenders)
    )
