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
Tripwire: every place that writes a user or a user group calls the user -> person sync, or says why it need not

The sync is called where users and user groups are written, not inside their managers - a manager knows neither the
acting user nor the route's ledger. So a new write site would write past the sync without a word. This census reads
every call of a user / user group write method outside the managers and the updaters and holds it to ``CENSUS``: each
site is listed with how it is synced, or why it is exempt. A new site fails here until it is listed; a hooked module
must name the sync's entry point.

Read with ``ast``, so every module is covered whether or not a test imports it
"""
import ast
from collections import Counter
from pathlib import Path

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

CMDB_ROOT: Path = Path(__file__).resolve().parents[2] / 'cmdb'

# The writes of UsersManager and GroupsManager that change what the sync mirrors
WRITE_METHODS: frozenset[str] = frozenset({
    'insert_user', 'update_user', 'delete_user', 'delete_users', 'move_users', 'remove_group_from_users',
    'restore_group_ids', 'handle_users_on_group_delete', 'insert_group', 'update_group', 'delete_group',
})

# Where the methods are defined and the frozen migrations: not call sites of a running system
EXCLUDED: tuple[Path, ...] = (CMDB_ROOT / 'manager', CMDB_ROOT / 'database' / 'updater' / 'versions')

# The names a hooked module calls the sync through
SYNC_ENTRY_POINTS: tuple[str, ...] = ('write_with_person_sync', 'sync_user_outside_request')

HOOKED: str = 'hooked'

# (module relative to cmdb/, method) -> (calls, how it is synced or why it is exempt)
CENSUS: dict[tuple[str, str], tuple[int, str]] = {
    ('interface/rest_api/routes/user_management_routes/users_routes.py', 'insert_user'):
        (1, f'{HOOKED}: write_with_person_sync - insert + sync_user on one ledger'),
    ('interface/rest_api/routes/user_management_routes/users_routes.py', 'update_user'):
        (2, f'{HOOKED}: the user update runs write_with_person_sync; the password change is exempt - the sync never '
            'reads the digest'),
    ('interface/rest_api/routes/user_management_routes/users_routes.py', 'delete_user'):
        (1, f'{HOOKED}: write_with_person_sync - sync_user_deleted, then the delete'),
    ('interface/rest_api/routes/user_management_routes/cmdb_groups/groups_routes.py', 'insert_group'):
        (1, 'exempt: a new user group is mapped to no person group'),
    ('interface/rest_api/routes/user_management_routes/cmdb_groups/groups_routes.py', 'update_group'):
        (1, f'{HOOKED}: write_with_person_sync - sync_user_group'),
    ('interface/rest_api/routes/user_management_routes/cmdb_groups/groups_routes.py', 'delete_group'):
        (1, f'{HOOKED}: write_with_person_sync - unmapped, the members re-synced'),
    ('interface/rest_api/routes/user_management_routes/cmdb_groups/groups_helper.py', 'restore_group_ids'):
        (1, 'exempt: the undo of the group delete - the sync writes of that delete are undone with it'),
    ('interface/rest_api/routes/user_management_routes/cmdb_groups/groups_helper.py',
     'handle_users_on_group_delete'):
        (1, 'exempt here: called inside the group delete route\'s write_with_person_sync, which syncs the members'),
    ('security/auth/providers/ldap_auth_provider.py', 'update_user'):
        (1, f'{HOOKED}: sync_user_outside_request after the group update'),
    ('security/auth/providers/ldap_auth_provider.py', 'insert_user'):
        (1, f'{HOOKED}: sync_user_outside_request after the provisioning'),
    ('interface/cloud_user_helper.py', 'insert_user'):
        (1, f'{HOOKED}: sync_user_outside_request after the admin set-up'),
    ('interface/cloud_user_helper.py', 'update_user'):
        (1, f'{HOOKED}: sync_user_outside_request after the admin set-up'),
    ('database/database_services/collection_validator.py', 'insert_user'):
        (1, 'exempt: the first start creates the admin - no sync can be configured yet'),
    ('database/database_services/collection_validator.py', 'insert_group'):
        (1, 'exempt: the first start creates the default groups - no sync can be configured yet'),
}


def write_calls(root: Path = CMDB_ROOT, excluded: tuple[Path, ...] = EXCLUDED) -> Counter:
    """
    Counts the user / user group write calls per module and method, the excluded folders left out

    Args:
        root (Path): The tree to scan
        excluded (tuple[Path, ...]): Folders under it that are not scanned

    Returns:
        Counter: (module relative to the root, method) -> calls
    """
    calls: Counter = Counter()

    for path in sorted(root.rglob('*.py')):
        if any(path.is_relative_to(folder) for folder in excluded):
            continue

        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in WRITE_METHODS:
                calls[(path.relative_to(root).as_posix(), node.func.attr)] += 1

    return calls


def test_every_write_site_is_listed() -> None:
    """A new site, a gone one, or a changed count - the census says so"""
    assert dict(write_calls()) == {site: count for site, (count, _reason) in CENSUS.items()}


@pytest.mark.parametrize('module', sorted({module for (module, _), (_, reason) in CENSUS.items()
                                           if reason.startswith(HOOKED)}))
def test_a_hooked_module_calls_the_sync(module: str) -> None:
    """Listed as hooked is not enough - the module names the sync's entry point"""
    source: str = (CMDB_ROOT / module).read_text(encoding='utf-8')

    assert any(f'{entry_point}(' in source for entry_point in SYNC_ENTRY_POINTS)


def test_the_scan_counts_attribute_calls_outside_the_excluded_folders(tmp_path: Path) -> None:
    """A method call counts per module; a plain name, another method and an excluded folder do not"""
    (tmp_path / 'routes.py').write_text('m.insert_user(x)\nm.insert_user(y)\ninsert_user(z)\nm.get_user(1)\n')
    (tmp_path / 'manager').mkdir()
    (tmp_path / 'manager' / 'users.py').write_text('self.update_user(x)\n')

    assert dict(write_calls(tmp_path, (tmp_path / 'manager',))) == {('routes.py', 'insert_user'): 2}
