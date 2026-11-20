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

# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Integration tests of the reconciliation pass (``person_sync.sync_pass``) against a real MongoDB

Pinned: the pass gives every user a person in its target Type, a second pass writes nothing; a user changed while the
sync was off is caught up; a person whose user is gone becomes a former user and leaves the mapped groups (also
with the group sync off); a mapped
group takes its label and its users' persons, one whose user group is gone is unmapped; every ``sync_pending`` mark
goes; an unusable target is refused before anything is written; a pass that dies after the persons is finished by the
next, which creates no second person. Switching off deactivates every synced person and
removes its fingerprint, the link kept; the pass that switches on again reactivates them
"""
from typing import Any, Iterator
from unittest.mock import patch

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import GroupsManager, ObjectsManager, TypesManager, UsersManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.object_model import CmdbObject
from cmdb.models.special_type_model.person_type_constants import PersonField, PersonGroupField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser, CmdbUserKey
from cmdb.framework.person_types.default_person_types import build_default_person_type
from cmdb.framework.person_sync.sync_engine import SyncContext
from cmdb.framework.person_sync.sync_pass import run_sync_pass, switch_off_pass
from cmdb.framework.person_sync.sync_settings import GroupSyncSettings, PersonSyncSettings, UserSyncSettings
from cmdb.errors.person_sync import PersonSyncTargetError
from cmdb.errors.manager import BaseManagerUpdateError
# -------------------------------------------------------------------------------------------------------------------- #

PERSON_TYPE_ID: int = 43301
GROUP_TYPE_ID: int = 43302
ANN_ID: int = 43311
BO_ID: int = 43312
USER_IDS: list[int] = [ANN_ID, BO_ID]
USER_GROUP_ID: int = 43321
GONE_USER_GROUP_ID: int = 43322
MAPPED_GROUP_ID: int = 43331
ORPHAN_GROUP_ID: int = 43332
FORMER_PERSON_ID: int = 43341
GONE_USER_ID: int = 43349
LABEL: str = 'Pass Desk'

ON: PersonSyncSettings = PersonSyncSettings(users=UserSyncSettings(active=True, default_type_id=PERSON_TYPE_ID),
                                            groups=GroupSyncSettings(active=True))


def _user(public_id: int, first_name: str, **extra: Any) -> dict[str, Any]:
    """A stored user in USER_GROUP_ID"""
    return CmdbUser.to_json(CmdbUser(public_id=public_id, user_name=f'pass-{public_id}', active=True,
                                     group_ids=[USER_GROUP_ID], first_name=first_name, last_name='Lee')) | extra


def _group_object(public_id: int, user_group_id: int, members: list[int]) -> dict[str, Any]:
    """A person group mapped to the user group"""
    return {'public_id': public_id, 'type_id': GROUP_TYPE_ID, 'author_id': 1, 'active': True, 'version': '1.0.0',
            'special_type': 'PERSON_GROUP', 'multi_data_sections': [],
            'system_ref': {'kind': 'user_group', 'id': user_group_id},
            'fields': [{'name': PersonGroupField.NAME.value, 'value': 'old', 'type': 'text'},
                       {'name': PersonGroupField.MEMBERS.value, 'value': members, 'type': 'person'}]}


@pytest.fixture(name='db')
def fixture_db(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """Two users (Bo marked pending), a former user's person, a mapped and an orphaned person group"""
    database = database_manager.connector.client[database_name]

    for type_id, marker in ((PERSON_TYPE_ID, SpecialType.PERSON), (GROUP_TYPE_ID, SpecialType.PERSON_GROUP)):
        document = build_default_person_type(marker, f'it-sync-pass-{type_id}', type_id)
        document['system_type'] = False
        database[CmdbType.COLLECTION].insert_one(document)

    database[CmdbUser.COLLECTION].insert_many([_user(ANN_ID, 'Ann'), _user(BO_ID, 'Bo', sync_pending=True)])
    database[CmdbUserGroup.COLLECTION].insert_one({'public_id': USER_GROUP_ID, 'name': 'pass-desk', 'label': LABEL,
                                                   'rights': []})
    database[CmdbObject.COLLECTION].insert_many([
        {'public_id': FORMER_PERSON_ID, 'type_id': PERSON_TYPE_ID, 'author_id': 1, 'active': True,
         'version': '1.0.0', 'special_type': 'PERSON', 'multi_data_sections': [],
         'system_ref': {'kind': 'user', 'id': GONE_USER_ID}, 'sync_hash': 'old',
         'fields': [{'name': PersonField.DISPLAY_NAME.value, 'value': 'Gone', 'type': 'text'}]},
        _group_object(MAPPED_GROUP_ID, USER_GROUP_ID, [FORMER_PERSON_ID]),
        _group_object(ORPHAN_GROUP_ID, GONE_USER_GROUP_ID, []),
    ])

    yield database

    database[CmdbObject.COLLECTION].delete_many({'type_id': {'$in': [PERSON_TYPE_ID, GROUP_TYPE_ID]}})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': [PERSON_TYPE_ID, GROUP_TYPE_ID]}})
    database[CmdbUser.COLLECTION].delete_many({'public_id': {'$in': USER_IDS}})
    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': USER_GROUP_ID})


def _context(database_manager: MongoDatabaseManager, database_name: str,
             settings: PersonSyncSettings = ON) -> SyncContext:
    """The pass's context on the test tenant, credited to the admin"""
    return SyncContext(ObjectsManager(database_manager, database_name), TypesManager(database_manager, database_name),
                       UsersManager(database_manager, database_name), GroupsManager(database_manager, database_name),
                       settings, CmdbUser(public_id=1, user_name='admin', active=True))


def _person(db: Any, user_id: int) -> dict[str, Any] | None:
    """The person linked to the user"""
    return db[CmdbObject.COLLECTION].find_one({'system_ref.kind': 'user', 'system_ref.id': user_id})


def _values(document: dict[str, Any]) -> dict[str, Any]:
    """A document's values by field name"""
    return {entry['name']: entry['value'] for entry in document['fields']}


def _object(db: Any, public_id: int) -> dict[str, Any]:
    """A stored object"""
    return db[CmdbObject.COLLECTION].find_one({'public_id': public_id})


class TestTheFirstPass:
    """Switching the sync on."""

    def test_every_user_gets_a_person(self, db: Any, database_manager: MongoDatabaseManager,
                                      database_name: str) -> None:
        """In the target Type, with its values"""
        result = run_sync_pass(_context(database_manager, database_name))

        for user_id, name in ((ANN_ID, 'Ann Lee'), (BO_ID, 'Bo Lee')):
            person = _person(db, user_id)
            assert person['type_id'] == PERSON_TYPE_ID and person['public_id'] in result.created
            assert _values(person)[PersonField.DISPLAY_NAME.value] == name

    def test_a_former_users_person_is_unlinked_and_leaves_the_group(self, db: Any,
                                                                    database_manager: MongoDatabaseManager,
                                                                    database_name: str) -> None:
        """Deactivated, its values kept - now a ConfigItem, so the count moved"""
        result = run_sync_pass(_context(database_manager, database_name))

        assert result.config_items_changed is True
        former = _object(db, FORMER_PERSON_ID)
        assert 'system_ref' not in former and 'sync_hash' not in former and former['active'] is False
        assert FORMER_PERSON_ID not in _values(_object(db, MAPPED_GROUP_ID))[PersonGroupField.MEMBERS.value]

    def test_with_the_group_sync_off_a_former_user_still_leaves_the_group(
            self, db: Any, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Only the former user goes - the name and the rest stay, the orphaned group stays mapped"""
        db[CmdbObject.COLLECTION].update_one({'public_id': MAPPED_GROUP_ID},
                                             {'$push': {'fields.1.value': 43399}})

        result = run_sync_pass(_context(database_manager, database_name, PersonSyncSettings(users=ON.users)))

        assert _values(_object(db, MAPPED_GROUP_ID)) == {
            PersonGroupField.NAME.value: 'old', PersonGroupField.MEMBERS.value: [43399],
        }
        assert MAPPED_GROUP_ID in result.edits
        assert result.left_members == {MAPPED_GROUP_ID: [FORMER_PERSON_ID]}
        assert 'system_ref' in _object(db, ORPHAN_GROUP_ID)

    def test_the_mapped_groups_follow(self, db: Any, database_manager: MongoDatabaseManager,
                                      database_name: str) -> None:
        """The label and the users' persons; an orphaned group is unmapped"""
        run_sync_pass(_context(database_manager, database_name))

        assert _values(_object(db, MAPPED_GROUP_ID)) == {
            PersonGroupField.NAME.value: LABEL,
            PersonGroupField.MEMBERS.value: sorted([_person(db, ANN_ID)['public_id'], _person(db, BO_ID)['public_id']]),
        }
        assert 'system_ref' not in _object(db, ORPHAN_GROUP_ID)

    def test_the_pending_marks_go(self, db: Any, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The pass caught Bo up"""
        run_sync_pass(_context(database_manager, database_name))

        assert CmdbUserKey.SYNC_PENDING.value not in db[CmdbUser.COLLECTION].find_one({'public_id': BO_ID})

    def test_an_unusable_target_writes_nothing(self, db: Any, database_manager: MongoDatabaseManager,
                                               database_name: str) -> None:
        """Judged before the first write"""
        db[CmdbType.COLLECTION].update_one({'public_id': PERSON_TYPE_ID}, {'$set': {'active': False}})

        with pytest.raises(PersonSyncTargetError):
            run_sync_pass(_context(database_manager, database_name))

        assert _person(db, ANN_ID) is None
        assert 'system_ref' in _object(db, FORMER_PERSON_ID)


class TestTheNextPasses:
    """A resync, and switching off and on."""

    def test_a_second_pass_writes_nothing(self, db: Any, database_manager: MongoDatabaseManager,
                                          database_name: str) -> None:
        """Every fingerprint unchanged"""
        context = _context(database_manager, database_name)
        run_sync_pass(context)

        result = run_sync_pass(context)

        assert (result.created, result.edits, result.config_items_changed) == ([], {}, False)

    def test_a_user_changed_while_off_is_caught_up(self, db: Any, database_manager: MongoDatabaseManager,
                                                   database_name: str) -> None:
        """Only that person is edited"""
        context = _context(database_manager, database_name)
        run_sync_pass(context)
        db[CmdbUser.COLLECTION].update_one({'public_id': ANN_ID}, {'$set': {'email': 'ann@example.org'}})

        result = run_sync_pass(context)

        assert list(result.edits) == [_person(db, ANN_ID)['public_id']]
        assert _values(_person(db, ANN_ID))[PersonField.EMAIL.value] == 'ann@example.org'

    def test_switching_off_and_on(self, db: Any, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Off: deactivated, fingerprint gone, linked. On: active again (the seeded admin has a person too)"""
        context = _context(database_manager, database_name)
        run_sync_pass(context)
        person_ids = [_person(db, user_id)['public_id'] for user_id in USER_IDS]

        off = switch_off_pass(context)

        assert set(person_ids) <= set(off.edits)
        for user_id in USER_IDS:
            person = _person(db, user_id)
            assert person['active'] is False and 'sync_hash' not in person

        run_sync_pass(context)

        assert all(_person(db, user_id)['active'] is True for user_id in USER_IDS)

    def test_with_the_user_sync_off_the_pass_does_nothing(self, db: Any, database_manager: MongoDatabaseManager,
                                                          database_name: str) -> None:
        """Nothing read, nothing written"""
        result = run_sync_pass(_context(database_manager, database_name, PersonSyncSettings()))

        assert (result.created, _person(db, ANN_ID)) == ([], None)


def test_a_pass_that_died_halfway_is_finished_by_the_next(db: Any, database_manager: MongoDatabaseManager,
                                                          database_name: str) -> None:
    """The persons written, the groups not: the second pass writes the groups and no second person"""
    context = _context(database_manager, database_name)
    real_bulk_write = ObjectsManager.bulk_write
    calls: list[int] = []

    def _second_fails(manager: ObjectsManager, operations: list[Any], **kwargs: Any) -> int:
        calls.append(len(operations))
        if len(calls) == 2:
            raise BaseManagerUpdateError('lost the group write')
        return real_bulk_write(manager, operations, **kwargs)

    with patch.object(ObjectsManager, 'bulk_write', _second_fails), pytest.raises(BaseManagerUpdateError):
        run_sync_pass(context)

    assert _values(_object(db, MAPPED_GROUP_ID))[PersonGroupField.NAME.value] == 'old'

    result = run_sync_pass(context)

    assert result.created == []
    assert db[CmdbObject.COLLECTION].count_documents({'system_ref.kind': 'user', 'system_ref.id': ANN_ID}) == 1
    assert _values(_object(db, MAPPED_GROUP_ID))[PersonGroupField.NAME.value] == LABEL
