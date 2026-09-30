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
Unit tests for `tests.utils.first_import_scan`, the CI step that imports every module first

Run against a throwaway package written to `tmp_path`, never against `cmdb`: the scan purges its
package from `sys.modules`, which the suite's own imports must not see. The package holds a real
two-way cycle, so the tests show the scan catches what the pinned tripwire list can miss
"""
import sys
from pathlib import Path

import pytest

from tests.utils.first_import_scan import discover_modules, purge_package, scan
# -------------------------------------------------------------------------------------------------------------------- #

PACKAGE: str = 'first_import_scan_fixture_pkg'

# `cycle_a` and `cycle_b` import each other's constant at module level: whichever is imported first
# re-enters itself half-initialised. `clean` and `nested.leaf` import nothing of the package
FIXTURE_FILES: dict[str, str] = {
    '__init__.py': '',
    'cycle_a.py': f'from {PACKAGE}.cycle_b import B_VALUE\nA_VALUE = 1\n',
    'cycle_b.py': f'from {PACKAGE}.cycle_a import A_VALUE\nB_VALUE = 2\n',
    'clean.py': 'CLEAN_VALUE = 3\n',
    'nested/__init__.py': '',
    'nested/leaf.py': 'LEAF_VALUE = 4\n',
}


@pytest.fixture(name='package_root')
def fixture_package_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Writes the fixture package, puts it on `sys.path`, and purges it again afterwards."""
    for relative, source in FIXTURE_FILES.items():
        path = tmp_path / PACKAGE / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')

    monkeypatch.syspath_prepend(str(tmp_path))
    yield tmp_path
    purge_package(PACKAGE)


def test_discover_names_every_module_and_names_a_package_by_its_init(package_root: Path) -> None:
    """Modules are dotted, sorted, and an `__init__.py` stands for its package."""
    assert discover_modules(package_root, PACKAGE) == [
        PACKAGE,
        f'{PACKAGE}.clean',
        f'{PACKAGE}.cycle_a',
        f'{PACKAGE}.cycle_b',
        f'{PACKAGE}.nested',
        f'{PACKAGE}.nested.leaf',
    ]


def test_scan_reports_both_halves_of_a_cycle(package_root: Path) -> None:
    """Each half fails when it is the first module of the package - the case a pinned list can miss."""
    failures = scan(discover_modules(package_root, PACKAGE), PACKAGE)

    assert [failure.split(':')[0] for failure in failures] == [f'{PACKAGE}.cycle_a', f'{PACKAGE}.cycle_b']
    assert all('ImportError' in failure for failure in failures)


def test_scan_passes_modules_without_a_cycle(package_root: Path) -> None:
    """A module that imports nothing of its package is not reported."""
    assert not scan([f'{PACKAGE}.clean', f'{PACKAGE}.nested.leaf'], PACKAGE)


def test_scan_leaves_the_package_purged(package_root: Path) -> None:
    """The scan's last import does not linger for the caller."""
    scan([f'{PACKAGE}.clean'], PACKAGE)

    assert not any(name == PACKAGE or name.startswith(f'{PACKAGE}.') for name in sys.modules)


def test_the_cycle_is_real_outside_the_scan(package_root: Path) -> None:
    """Guards the fixture: without the scan, importing a half first raises too."""
    purge_package(PACKAGE)

    with pytest.raises(ImportError):
        __import__(f'{PACKAGE}.cycle_a')
