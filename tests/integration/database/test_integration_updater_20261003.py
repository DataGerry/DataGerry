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
Integration tests for cmdb.database.updater.versions.updater_20261003 against a real MongoDB

Seeds CmdbTypes with every ``acl`` shape a database written before the complete-block rule may hold, plus two complete
ones, runs the migration, and asserts:

  - the selection matches every incomplete shape and neither complete one
  - each incomplete ``acl`` became the complete block, and the complete ones were not touched
  - no access decision changed: the single read (``acl_grants_access``) and the listing clause
    (``build_denied_types_criteria``) answer, for every group and permission, what they answered before
  - ``GET /types/<id>`` - which answers the stored document - now shows the complete block
  - the version is bumped, and a second run changes nothing
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261003 import INCOMPLETE_ACL_CRITERIA, Update20261003
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.security.acl.access_control_list import AccessControlList
from cmdb.security.acl.builder import build_denied_types_criteria
from cmdb.security.acl.helpers import acl_grants_access
from cmdb.security.acl.permission import AccessControlPermission
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

ABSENT: object = object()
GRANTED_INCLUDES: dict[str, list[str]] = {'2': ['READ', 'UPDATE']}
COMPLETE_ON: dict[str, Any] = {'activated': True, 'groups': {'includes': GRANTED_INCLUDES}}
GROUP_IDS: list[int] = [1, 2, 3]

# public_id -> the stored acl (ABSENT = no key at all)
INCOMPLETE: dict[int, Any] = {
    97801: ABSENT,
    97802: None,
    97803: 'on',
    97804: {'groups': {'includes': GRANTED_INCLUDES}},
    97805: {'activated': None, 'groups': {'includes': {}}},
    97806: {'activated': False},
    97807: {'activated': False, 'groups': None},
    97808: {'activated': False, 'groups': {}},
    97809: {'activated': False, 'groups': {'includes': None}},
    97810: {'activated': True, 'groups': None},
}
COMPLETE: dict[int, Any] = {
    97811: AccessControlList.default_json(),
    97812: COMPLETE_ON,
}
ALL_IDS: list[int] = [*INCOMPLETE, *COMPLETE]

UPDATER_SETTINGS_ID: str = 'updater'
SETTINGS_COLLECTION: str = 'settings.conf'
CREATION_DATE: int = 20261003


def _type_doc(public_id: int, acl: Any) -> dict[str, Any]:
    """A type with the given stored acl"""
    doc: dict[str, Any] = make_type_doc(public_id, f'acl-shape-{public_id}')
    doc.pop(TypeSchemaKey.ACL.value, None)

    if acl is not ABSENT:
        doc[TypeSchemaKey.ACL.value] = acl

    return doc


@pytest.fixture(name='types')
def fixture_types(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds every shape + preserves the updater setting, restoring everything afterwards"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)
    previous_setting: dict[str, Any] | None = settings.find_one({'_id': UPDATER_SETTINGS_ID})

    types.delete_many({'public_id': {'$in': ALL_IDS}})
    types.insert_many([_type_doc(public_id, acl) for public_id, acl in {**INCOMPLETE, **COMPLETE}.items()])

    yield types

    types.delete_many({'public_id': {'$in': ALL_IDS}})
    if previous_setting is not None:
        settings.replace_one({'_id': UPDATER_SETTINGS_ID}, previous_setting, upsert=True)
    else:
        settings.delete_many({'_id': UPDATER_SETTINGS_ID})


def _stored_acl(types, public_id: int) -> Any:
    """The stored acl of a seeded type (ABSENT when there is no key)"""
    return types.find_one({'public_id': public_id}).get(TypeSchemaKey.ACL.value, ABSENT)


def _decisions(types) -> dict[tuple[int, int, str], tuple[bool, bool]]:
    """(type, group, permission) -> (single read grants, listing grants), for every seeded type"""
    decisions: dict[tuple[int, int, str], tuple[bool, bool]] = {}

    for group_id in GROUP_IDS:
        for permission in AccessControlPermission:
            denied: set[int] = {
                document['public_id'] for document in types.find(
                    {'$and': [{'public_id': {'$in': ALL_IDS}}, build_denied_types_criteria(group_id, permission)]},
                )
            }
            for public_id in ALL_IDS:
                stored: Any = _stored_acl(types, public_id)
                acl = AccessControlList.from_data(stored) if isinstance(stored, dict) else None
                decisions[(public_id, group_id, permission.value)] = (
                    acl_grants_access(acl, group_id, permission), public_id not in denied,
                )

    return decisions


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """One run of the migration"""
    Update20261003(database_manager, database_name).start_update()


class TestTheSelection:
    """Evaluated by the database itself, against every shape."""

    def test_every_incomplete_shape_and_no_complete_one_is_selected(self, types) -> None:
        """The selection is exactly the incomplete set"""
        selected: set[int] = {
            document['public_id'] for document in types.find(
                {'$and': [{'public_id': {'$in': ALL_IDS}}, INCOMPLETE_ACL_CRITERIA]},
            )
        }

        assert selected == set(INCOMPLETE)


class TestTheRewrite:
    """Each incomplete acl becomes the block it reads as; the complete ones stay."""

    @pytest.mark.parametrize('public_id', list(INCOMPLETE))
    def test_an_incomplete_acl_becomes_its_normalized_block(
        self, types, database_manager: MongoDatabaseManager, database_name: str, public_id: int,
    ) -> None:
        """The stored value is now normalize_stored of what was there"""
        before: Any = INCOMPLETE[public_id]

        _run(database_manager, database_name)

        expected = AccessControlList.normalize_stored(None if before is ABSENT else before)
        assert _stored_acl(types, public_id) == expected

    def test_the_groups_of_an_unswitched_acl_survive(
        self, types, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A hand-built ACL with groups but no switch keeps its groups, switched off"""
        _run(database_manager, database_name)

        assert _stored_acl(types, 97804) == {'activated': False, 'groups': {'includes': GRANTED_INCLUDES}}

    @pytest.mark.parametrize('public_id', list(COMPLETE))
    def test_a_complete_block_is_not_touched(
        self, types, database_manager: MongoDatabaseManager, database_name: str, public_id: int,
    ) -> None:
        """Nothing to repair"""
        _run(database_manager, database_name)

        assert _stored_acl(types, public_id) == COMPLETE[public_id]

    def test_no_access_decision_changes(
        self, types, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Both readers answer, for every type, group and permission, what they answered before"""
        before = _decisions(types)

        _run(database_manager, database_name)

        assert _decisions(types) == before

    def test_the_two_readers_agree_afterwards(
        self, types, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """One shape, one answer: the single read and the listing never disagree on a repaired type"""
        _run(database_manager, database_name)

        assert all(single == listing for single, listing in _decisions(types).values())


class TestTheSingleRead:
    """GET /types/<id> answers the stored document, so it shows the repair."""

    def test_a_former_switch_only_acl_is_read_as_the_complete_block(
        self, rest_api, types, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """{'activated': False} - the shape the dev databases held - comes back complete"""
        del types
        _run(database_manager, database_name)

        response = rest_api.get('/types/97806')

        assert response.status_code == 200
        assert response.get_json()['result'][TypeSchemaKey.ACL.value] == AccessControlList.default_json()


class TestTheRun:
    """The version, and the re-run."""

    def test_version_bumped(self, types, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The persisted updater version records the migration"""
        del types
        _run(database_manager, database_name)

        settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)
        assert settings.find_one({'_id': UPDATER_SETTINGS_ID})['version'] == CREATION_DATE

    def test_second_run_changes_nothing(
        self, types, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """After one run nothing is selected, so the documents stay as the first run left them"""
        _run(database_manager, database_name)
        after_first: list[dict[str, Any]] = list(types.find({'public_id': {'$in': ALL_IDS}}))

        _run(database_manager, database_name)

        assert list(types.find({'public_id': {'$in': ALL_IDS}})) == after_first
        assert types.count_documents({'$and': [{'public_id': {'$in': ALL_IDS}}, INCOMPLETE_ACL_CRITERIA]}) == 0
