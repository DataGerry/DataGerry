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
Integration tests of the sync engine (``person_sync.sync_engine``) against a real MongoDB

Pinned for a user: its person is created in its target Type - the default or its override - with its values, the
Type's defaults, the link, the fingerprint, credited to the acting user; an unchanged user writes nothing; a changed
one updates the synced values and the version, its own field kept; a deactivated one deactivates the person; nothing
is written while the user sync is off; an unusable target is refused before anything is written. For the groups: the
mapped person group takes its user group's label and the persons of its users, a hand-added member kept; a user
leaving the user group leaves the person group. A deleted user's person is unlinked, deactivated and leaves every mapped
group; a deleted user group's person group is unmapped, its members kept. Every write is in the ledger: undoing it puts
everything back. The change logs follow through the route layer's callbacks
"""
from datetime import datetime, timezone
from typing import Any, Iterator
from unittest.mock import patch

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import GroupsManager, ObjectsManager, TypesManager, UsersManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.object_model import CmdbObject
from cmdb.models.special_type_model.person_type_constants import PersonField, PersonGroupField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser, CmdbUserKey
from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.person_types.default_person_types import build_default_person_type
from cmdb.framework.person_sync.sync_engine import (
    SyncContext,
    SyncResult,
    emit_sync_events,
    sync_user,
    sync_user_deleted,
    sync_user_group,
    sync_user_group_deleted,
    sync_users,
)
from cmdb.framework.person_sync.sync_reads import linked_person_type_ids
from cmdb.framework.person_sync.sync_settings import GroupSyncSettings, PersonSyncSettings, UserSyncSettings
from cmdb.errors.person_sync import PersonSyncTargetError
from cmdb.interface.rest_api.routes.user_management_routes.person_sync_events_helper import build_sync_events
# -------------------------------------------------------------------------------------------------------------------- #

DEFAULT_TYPE_ID: int = 43101
OVERRIDE_TYPE_ID: int = 43102
GROUP_TYPE_ID: int = 43103
TYPE_IDS: list[int] = [DEFAULT_TYPE_ID, OVERRIDE_TYPE_ID, GROUP_TYPE_ID]
USER_ID: int = 43111
OVERRIDE_USER_ID: int = 43112
USER_IDS: list[int] = [USER_ID, OVERRIDE_USER_ID]
USER_GROUP_ID: int = 43121
UNMAPPED_USER_GROUP_ID: int = 43129
OTHER_USER_GROUP_ID: int = 43122
USER_GROUP_LABEL: str = 'Service Desk'
MAPPED_GROUP_ID: int = 43131
OTHER_MAPPED_GROUP_ID: int = 43133
HAND_PERSON_ID: int = 43132
ACTING_USER_ID: int = 1
OWN_PHONE: str = '555-0100'
FIRST_SYNC_VERSION: str = '1.0.0'

ON: PersonSyncSettings = PersonSyncSettings(
    users=UserSyncSettings(active=True, default_type_id=DEFAULT_TYPE_ID,
                           type_overrides={OVERRIDE_USER_ID: OVERRIDE_TYPE_ID}),
    groups=GroupSyncSettings(active=True),
)
WITH_DEFAULT: PersonSyncSettings = PersonSyncSettings(
    users=ON.users, groups=GroupSyncSettings(active=True, default_type_id=GROUP_TYPE_ID))


def _user(public_id: int = USER_ID, **overrides: Any) -> CmdbUser:
    """A user in USER_GROUP_ID with every name and an email"""
    attributes: dict[str, Any] = {'public_id': public_id, 'user_name': f'user{public_id}', 'active': True,
                                  'group_ids': [USER_GROUP_ID], 'first_name': 'Ann', 'last_name': 'Lee',
                                  'email': 'ann.lee@example.org'}
    attributes.update(overrides)

    return CmdbUser(**attributes)


@pytest.fixture(name='db')
def fixture_db(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """Two PERSON Types, a PERSON_GROUP Type, two user groups, a person by hand and a person group mapped to one"""
    database = database_manager.connector.client[database_name]

    for type_id, marker in ((DEFAULT_TYPE_ID, SpecialType.PERSON), (OVERRIDE_TYPE_ID, SpecialType.PERSON),
                            (GROUP_TYPE_ID, SpecialType.PERSON_GROUP)):
        document = build_default_person_type(marker, f'it-sync-engine-{type_id}', type_id)
        document['system_type'] = False
        database[CmdbType.COLLECTION].insert_one(document)

    database[CmdbUserGroup.COLLECTION].insert_many([
        {'public_id': USER_GROUP_ID, 'name': 'service-desk', 'label': USER_GROUP_LABEL, 'rights': []},
        {'public_id': OTHER_USER_GROUP_ID, 'name': 'other', 'label': 'Other', 'rights': []},
    ])
    now = datetime.now(timezone.utc)
    database[CmdbObject.COLLECTION].insert_many([
        {'public_id': HAND_PERSON_ID, 'type_id': DEFAULT_TYPE_ID, 'author_id': 1, 'active': True, 'version': '1.0.0',
         'creation_time': now, 'special_type': 'PERSON', 'multi_data_sections': [],
         'fields': [{'name': PersonField.DISPLAY_NAME.value, 'value': 'Hand', 'type': 'text'}]},
        {'public_id': MAPPED_GROUP_ID, 'type_id': GROUP_TYPE_ID, 'author_id': 1, 'active': True, 'version': '1.0.0',
         'creation_time': now, 'special_type': 'PERSON_GROUP', 'multi_data_sections': [],
         'system_ref': {'kind': 'user_group', 'id': USER_GROUP_ID},
         'fields': [{'name': PersonGroupField.NAME.value, 'value': 'old name', 'type': 'text'},
                    {'name': PersonGroupField.MEMBERS.value, 'value': [HAND_PERSON_ID], 'type': 'person'}]},
    ])

    yield database

    database[CmdbObject.COLLECTION].delete_many({'$or': [{'type_id': {'$in': TYPE_IDS}},
                                                         {'public_id': {'$in': [HAND_PERSON_ID, MAPPED_GROUP_ID, OTHER_MAPPED_GROUP_ID]}}]})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': TYPE_IDS}})
    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': {'$in': [USER_GROUP_ID, OTHER_USER_GROUP_ID]}})
    database[CmdbUser.COLLECTION].delete_many({'public_id': {'$in': USER_IDS}})
    database[CmdbMetaLog.COLLECTION].delete_many({'user_id': ACTING_USER_ID, 'comment': {'$in': [
        'Object created', 'Synced from user management', 'Active status has changed',
        'Unlinked from user management']}})


def _store_user(db: Any, user: CmdbUser) -> None:
    """Stores the user as user management would (its group membership is read from it)"""
    db[CmdbUser.COLLECTION].replace_one({'public_id': user.public_id}, CmdbUser.to_json(user), upsert=True)


def _context(database_manager: MongoDatabaseManager, database_name: str,
             settings: PersonSyncSettings = ON) -> SyncContext:
    """The engine's context on the test tenant, credited to the admin"""
    return SyncContext(
        objects_manager=ObjectsManager(database_manager, database_name),
        types_manager=TypesManager(database_manager, database_name),
        users_manager=UsersManager(database_manager, database_name),
        groups_manager=GroupsManager(database_manager, database_name),
        settings=settings,
        acting_user=CmdbUser(public_id=ACTING_USER_ID, user_name='admin', active=True),
    )


def _person(db: Any, user_id: int = USER_ID) -> dict[str, Any] | None:
    """The person linked to the user"""
    return db[CmdbObject.COLLECTION].find_one({'system_ref.kind': 'user', 'system_ref.id': user_id}, {'_id': 0})


def _values(document: dict[str, Any]) -> dict[str, Any]:
    """A document's field values by name"""
    return {entry['name']: entry['value'] for entry in document['fields']}


def _sync(context: SyncContext, user: CmdbUser) -> SyncResult:
    """One sync of a stored user"""
    return sync_user(context, WriteLedger(), user)


class TestAPerson:
    """A user's person."""

    def test_it_is_created_in_the_default_type(self, db: Any, database_manager: MongoDatabaseManager,
                                               database_name: str) -> None:
        """Values, defaults, marker, link, fingerprint, the acting user as author"""
        _store_user(db, _user())

        result = _sync(_context(database_manager, database_name), _user())

        person = _person(db)
        assert result.created == [person['public_id']]
        assert (person['type_id'], person['special_type'], person['author_id'], person['active']) == (
            DEFAULT_TYPE_ID, 'PERSON', ACTING_USER_ID, True)
        assert _values(person) == {PersonField.DISPLAY_NAME.value: 'Ann Lee', PersonField.FIRST_NAME.value: 'Ann',
                                   PersonField.LAST_NAME.value: 'Lee', PersonField.EMAIL.value: 'ann.lee@example.org'}
        assert all(entry['type'] == 'text' for entry in person['fields'])
        assert person['sync_hash']

    def test_an_override_puts_it_into_its_own_type(self, db: Any, database_manager: MongoDatabaseManager,
                                                   database_name: str) -> None:
        """The user's target, not the default"""
        user = _user(OVERRIDE_USER_ID)
        _store_user(db, user)

        _sync(_context(database_manager, database_name), user)

        assert _person(db, OVERRIDE_USER_ID)['type_id'] == OVERRIDE_TYPE_ID

    def test_an_unchanged_user_writes_nothing(self, db: Any, database_manager: MongoDatabaseManager,
                                              database_name: str) -> None:
        """The fingerprint decides"""
        _store_user(db, _user())
        context = _context(database_manager, database_name)
        _sync(context, _user())
        before = _person(db)

        result = _sync(context, _user())

        assert (result.created, list(result.edits)) == ([], [])
        assert _person(db) == before

    def test_a_changed_user_updates_the_synced_values_only(self, db: Any, database_manager: MongoDatabaseManager,
                                                           database_name: str) -> None:
        """The version moves, the person's own phone number stays"""
        _store_user(db, _user())
        context = _context(database_manager, database_name)
        _sync(context, _user())
        person_id = _person(db)['public_id']
        db[CmdbObject.COLLECTION].update_one({'public_id': person_id}, {'$push': {'fields': {
            'name': PersonField.PHONE_NUMBER.value, 'value': OWN_PHONE, 'type': 'text'}}})
        before = _person(db)

        result = _sync(context, _user(email='ann@example.org'))

        after = _person(db)
        assert list(result.edits) == [person_id]
        assert _values(after)[PersonField.EMAIL.value] == 'ann@example.org'
        assert _values(after)[PersonField.PHONE_NUMBER.value] == OWN_PHONE
        assert after['version'] != FIRST_SYNC_VERSION and after['sync_hash'] != before['sync_hash']
        assert after['editor_id'] == ACTING_USER_ID

    def test_a_deactivated_user_deactivates_the_person(self, db: Any, database_manager: MongoDatabaseManager,
                                                       database_name: str) -> None:
        """The person is active exactly while its user is"""
        _store_user(db, _user())
        context = _context(database_manager, database_name)
        _sync(context, _user())

        _sync(context, _user(active=False))

        assert _person(db)['active'] is False

    def test_nothing_is_written_while_the_user_sync_is_off(self, db: Any, database_manager: MongoDatabaseManager,
                                                           database_name: str) -> None:
        """The pass that switches it on catches up"""
        _store_user(db, _user())

        result = _sync(_context(database_manager, database_name, PersonSyncSettings()), _user())

        assert (result.created, _person(db)) == ([], None)

    def test_an_unusable_target_is_refused_before_anything_is_written(
            self, db: Any, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A deactivated Type - the settings guards keep this from happening; the engine refuses it anyway"""
        db[CmdbType.COLLECTION].update_one({'public_id': DEFAULT_TYPE_ID}, {'$set': {'active': False}})
        _store_user(db, _user())

        with pytest.raises(PersonSyncTargetError):
            _sync(_context(database_manager, database_name), _user())

        assert _person(db) is None


class TestTheMappedGroups:
    """A mapped person group follows its user group."""

    def test_the_users_person_joins_and_the_label_is_the_name(self, db: Any, database_manager: MongoDatabaseManager,
                                                              database_name: str) -> None:
        """The hand-added member stays ahead"""
        _store_user(db, _user())

        result = _sync(_context(database_manager, database_name), _user())

        group = db[CmdbObject.COLLECTION].find_one({'public_id': MAPPED_GROUP_ID})
        assert _values(group) == {PersonGroupField.NAME.value: USER_GROUP_LABEL,
                                  PersonGroupField.MEMBERS.value: [HAND_PERSON_ID, _person(db)['public_id']]}
        assert MAPPED_GROUP_ID in result.edits

    def test_a_user_leaving_the_user_group_leaves_the_person_group(
            self, db: Any, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Only the hand-added member is left"""
        _store_user(db, _user())
        context = _context(database_manager, database_name)
        _sync(context, _user())
        moved = _user(group_ids=[OTHER_USER_GROUP_ID])
        _store_user(db, moved)

        _sync(context, moved)

        group = db[CmdbObject.COLLECTION].find_one({'public_id': MAPPED_GROUP_ID})
        assert _values(group)[PersonGroupField.MEMBERS.value] == [HAND_PERSON_ID]

    def test_a_user_group_resync_sets_name_and_members(self, db: Any, database_manager: MongoDatabaseManager,
                                                       database_name: str) -> None:
        """The user group's own call"""
        _store_user(db, _user())
        _sync(_context(database_manager, database_name, PersonSyncSettings(users=ON.users)), _user())

        sync_user_group(_context(database_manager, database_name), WriteLedger(),
                        CmdbUserGroup(public_id=USER_GROUP_ID, name='service-desk', label=USER_GROUP_LABEL))

        group = db[CmdbObject.COLLECTION].find_one({'public_id': MAPPED_GROUP_ID})
        assert _values(group)[PersonGroupField.MEMBERS.value] == [HAND_PERSON_ID, _person(db)['public_id']]

    def test_with_the_group_sync_off_the_groups_are_left_alone(
            self, db: Any, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Off means unlocked - and untouched"""
        _store_user(db, _user())

        _sync(_context(database_manager, database_name, PersonSyncSettings(users=ON.users)), _user())

        group = db[CmdbObject.COLLECTION].find_one({'public_id': MAPPED_GROUP_ID})
        assert _values(group) == {PersonGroupField.NAME.value: 'old name',
                                  PersonGroupField.MEMBERS.value: [HAND_PERSON_ID]}


class TestANewPersonGroup:
    """An unmapped user group gets its person group in the group sync's default Type."""

    @staticmethod
    def _other_group() -> CmdbUserGroup:
        """The user group nothing is mapped to"""
        return CmdbUserGroup(public_id=OTHER_USER_GROUP_ID, name='other', label='Other')

    def test_it_is_created_named_linked_and_filled(self, db: Any, database_manager: MongoDatabaseManager,
                                                   database_name: str) -> None:
        """In the default Type; the label as name; the user group's users' persons as members"""
        member = _user(group_ids=[OTHER_USER_GROUP_ID])
        _store_user(db, member)
        _sync(_context(database_manager, database_name, PersonSyncSettings(users=ON.users)), member)

        result = sync_user_group(_context(database_manager, database_name, WITH_DEFAULT), WriteLedger(),
                                 self._other_group())

        created = db[CmdbObject.COLLECTION].find_one({'system_ref': {'kind': 'user_group', 'id': OTHER_USER_GROUP_ID}})
        assert (created['type_id'], created['public_id'] in result.created) == (GROUP_TYPE_ID, True)
        assert _values(created) == {PersonGroupField.NAME.value: 'Other',
                                    PersonGroupField.MEMBERS.value: [_person(db)['public_id']]}

    def test_a_mapped_user_group_gets_no_second_one(self, db: Any, database_manager: MongoDatabaseManager,
                                                    database_name: str) -> None:
        """Only its name and members follow"""
        result = sync_user_group(_context(database_manager, database_name, WITH_DEFAULT), WriteLedger(),
                                 CmdbUserGroup(public_id=USER_GROUP_ID, name='service-desk', label=USER_GROUP_LABEL))

        assert result.created == []
        assert db[CmdbObject.COLLECTION].count_documents({'system_ref.kind': 'user_group',
                                                          'system_ref.id': USER_GROUP_ID}) == 1

    @pytest.mark.parametrize('groups', [GroupSyncSettings(active=True),
                                        GroupSyncSettings(active=True, default_type_id=DEFAULT_TYPE_ID)],
                             ids=['no-default', 'a-person-type'])
    def test_an_unusable_default_writes_nothing(self, db: Any, database_manager: MongoDatabaseManager,
                                                database_name: str, groups: GroupSyncSettings) -> None:
        """PersonSyncTargetError before the insert"""
        settings = PersonSyncSettings(users=ON.users, groups=groups)

        with pytest.raises(PersonSyncTargetError):
            sync_user_group(_context(database_manager, database_name, settings), WriteLedger(), self._other_group())

        assert db[CmdbObject.COLLECTION].count_documents({'system_ref.kind': 'user_group',
                                                          'system_ref.id': OTHER_USER_GROUP_ID}) == 0

    def test_the_undo_removes_it(self, db: Any, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The insert is in the ledger"""
        ledger = WriteLedger()
        sync_user_group(_context(database_manager, database_name, WITH_DEFAULT), ledger, self._other_group())

        assert not ledger.undo()
        assert db[CmdbObject.COLLECTION].count_documents({'system_ref.kind': 'user_group',
                                                          'system_ref.id': OTHER_USER_GROUP_ID}) == 0

    def test_with_the_group_sync_off_nothing_is_created(self, db: Any, database_manager: MongoDatabaseManager,
                                                        database_name: str) -> None:
        """The default chosen, the switch off"""
        settings = PersonSyncSettings(users=ON.users, groups=GroupSyncSettings(default_type_id=GROUP_TYPE_ID))

        assert sync_user_group(_context(database_manager, database_name, settings), WriteLedger(),
                               self._other_group()) == SyncResult()


class TestTheBatches:
    """The mapped groups are read in batches and each written once."""

    def test_each_mapped_group_gets_its_users(self, db: Any, database_manager: MongoDatabaseManager,
                                              database_name: str) -> None:
        """Each group its own user group's label and users - Ann in both, the other user in the second only"""
        db[CmdbObject.COLLECTION].insert_one({
            'public_id': OTHER_MAPPED_GROUP_ID, 'type_id': GROUP_TYPE_ID, 'author_id': 1, 'active': True,
            'version': '1.0.0', 'special_type': 'PERSON_GROUP', 'multi_data_sections': [],
            'system_ref': {'kind': 'user_group', 'id': OTHER_USER_GROUP_ID},
            'fields': [{'name': PersonGroupField.NAME.value, 'value': 'old', 'type': 'text'},
                       {'name': PersonGroupField.MEMBERS.value, 'value': [], 'type': 'person'}]})
        users: list[CmdbUser] = [_user(group_ids=[USER_GROUP_ID, OTHER_USER_GROUP_ID]),
                                 _user(OVERRIDE_USER_ID, group_ids=[OTHER_USER_GROUP_ID])]

        for user in users:
            _store_user(db, user)

        result = sync_users(_context(database_manager, database_name), WriteLedger(), users)

        person_id: int = _person(db)['public_id']
        other_id: int = _person(db, OVERRIDE_USER_ID)['public_id']
        assert _values(db[CmdbObject.COLLECTION].find_one({'public_id': MAPPED_GROUP_ID})) == {
            PersonGroupField.NAME.value: USER_GROUP_LABEL, PersonGroupField.MEMBERS.value: [HAND_PERSON_ID, person_id]}
        assert _values(db[CmdbObject.COLLECTION].find_one({'public_id': OTHER_MAPPED_GROUP_ID})) == {
            PersonGroupField.NAME.value: 'Other', PersonGroupField.MEMBERS.value: sorted([person_id, other_id])}
        assert {MAPPED_GROUP_ID, OTHER_MAPPED_GROUP_ID} <= set(result.edits)

    def test_two_users_of_one_group_write_it_once(self, db: Any, database_manager: MongoDatabaseManager,
                                                  database_name: str) -> None:
        """Both persons in one write - not a write per user"""
        users: list[CmdbUser] = [_user(), _user(OVERRIDE_USER_ID)]

        for user in users:
            _store_user(db, user)

        context: SyncContext = _context(database_manager, database_name)

        with patch.object(context.objects_manager, 'update', wraps=context.objects_manager.update) as update:
            sync_users(context, WriteLedger(), users)

        assert [call.args[0] for call in update.call_args_list].count({'public_id': MAPPED_GROUP_ID}) == 1

        group = db[CmdbObject.COLLECTION].find_one({'public_id': MAPPED_GROUP_ID})
        assert _values(group)[PersonGroupField.MEMBERS.value] == [
            HAND_PERSON_ID, *sorted([_person(db)['public_id'], _person(db, OVERRIDE_USER_ID)['public_id']])]

    def test_the_linked_persons_types_are_read(self, db: Any, database_manager: MongoDatabaseManager,
                                               database_name: str) -> None:
        """One per Type a linked person lives in - not the hand-added person's"""
        users: list[CmdbUser] = [_user(), _user(OVERRIDE_USER_ID)]

        for user in users:
            _store_user(db, user)

        sync_users(_context(database_manager, database_name), WriteLedger(), users)

        assert linked_person_type_ids(ObjectsManager(database_manager, database_name)) & set(TYPE_IDS) == {
            DEFAULT_TYPE_ID, OVERRIDE_TYPE_ID}


class TestDeletes:
    """A deleted user, a deleted user group."""

    def test_a_deleted_users_person_becomes_a_former_user(self, db: Any, database_manager: MongoDatabaseManager,
                                                          database_name: str) -> None:
        """Unlinked, deactivated, out of the mapped group; its values kept"""
        _store_user(db, _user())
        context = _context(database_manager, database_name)
        _sync(context, _user())
        person_id = _person(db)['public_id']

        result = sync_user_deleted(context, WriteLedger(), USER_ID)

        assert result.config_items_changed is True
        former = db[CmdbObject.COLLECTION].find_one({'public_id': person_id})
        assert 'system_ref' not in former and 'sync_hash' not in former
        assert former['active'] is False
        assert _values(former)[PersonField.DISPLAY_NAME.value] == 'Ann Lee'
        group = db[CmdbObject.COLLECTION].find_one({'public_id': MAPPED_GROUP_ID})
        assert _values(group)[PersonGroupField.MEMBERS.value] == [HAND_PERSON_ID]

    def test_a_former_user_leaves_the_mapped_group_with_the_group_sync_off(
            self, db: Any, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Unlinked it would stay as a member added by hand - so it leaves whatever the switch; the name is kept"""
        _store_user(db, _user())
        _sync(_context(database_manager, database_name), _user())
        person_id = _person(db)['public_id']

        result = sync_user_deleted(_context(database_manager, database_name, PersonSyncSettings(users=ON.users)),
                                   WriteLedger(), USER_ID)

        group = db[CmdbObject.COLLECTION].find_one({'public_id': MAPPED_GROUP_ID})
        assert _values(group) == {PersonGroupField.NAME.value: USER_GROUP_LABEL,
                                  PersonGroupField.MEMBERS.value: [HAND_PERSON_ID]}
        assert set(result.edits) == {person_id, MAPPED_GROUP_ID}

    def test_a_user_deleted_while_the_sync_is_off_leaves_a_former_user(
            self, db: Any, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Nothing left to mirror: unlinked (so unlocked and deletable), out of the mapped group"""
        _store_user(db, _user())
        _sync(_context(database_manager, database_name), _user())
        person_id = _person(db)['public_id']

        result = sync_user_deleted(_context(database_manager, database_name, PersonSyncSettings()), WriteLedger(),
                                   USER_ID)

        former = db[CmdbObject.COLLECTION].find_one({'public_id': person_id})
        assert 'system_ref' not in former and former['active'] is False
        assert person_id not in _values(db[CmdbObject.COLLECTION].find_one({'public_id': MAPPED_GROUP_ID}))[
            PersonGroupField.MEMBERS.value]
        assert result.config_items_changed is True

    def test_a_group_whose_type_is_gone_is_skipped(self, db: Any, database_manager: MongoDatabaseManager,
                                                   database_name: str) -> None:
        """Not the sync's target: the user's own sync goes on, the group stays as it was"""
        _store_user(db, _user())
        db[CmdbObject.COLLECTION].update_one({'public_id': MAPPED_GROUP_ID}, {'$set': {'type_id': 43199}})

        result = _sync(_context(database_manager, database_name), _user())

        assert _person(db) is not None
        assert MAPPED_GROUP_ID not in result.edits
        group = db[CmdbObject.COLLECTION].find_one({'public_id': MAPPED_GROUP_ID})
        assert _values(group)[PersonGroupField.NAME.value] == 'old name'

    def test_a_deleted_user_groups_person_group_is_unmapped(self, db: Any, database_manager: MongoDatabaseManager,
                                                            database_name: str) -> None:
        """Members kept, the link gone - now a ConfigItem, so the count moved"""
        result = sync_user_group_deleted(_context(database_manager, database_name), WriteLedger(), USER_GROUP_ID)

        group = db[CmdbObject.COLLECTION].find_one({'public_id': MAPPED_GROUP_ID})
        assert 'system_ref' not in group
        assert _values(group)[PersonGroupField.MEMBERS.value] == [HAND_PERSON_ID]
        assert result.config_items_changed is True

    def test_a_user_group_mapped_nowhere_moves_no_count(self, database_manager: MongoDatabaseManager,
                                                        database_name: str) -> None:
        """Nothing unmapped, nothing to report"""
        result = sync_user_group_deleted(_context(database_manager, database_name), WriteLedger(),
                                         UNMAPPED_USER_GROUP_ID)

        assert result == SyncResult()


class TestTheLedger:
    """Every write is the caller's to undo."""

    def test_a_marked_user_is_settled_and_the_undo_marks_it_again(self, db: Any,
                                                                 database_manager: MongoDatabaseManager,
                                                                 database_name: str) -> None:
        """The mark goes with a sync that succeeded and comes back with its undo"""
        marked: CmdbUser = _user(sync_pending=True)
        _store_user(db, marked)
        db[CmdbUser.COLLECTION].update_one({'public_id': USER_ID}, {'$set': {CmdbUserKey.SYNC_PENDING.value: True}})
        ledger = WriteLedger()

        sync_user(_context(database_manager, database_name), ledger, marked)

        assert CmdbUserKey.SYNC_PENDING.value not in db[CmdbUser.COLLECTION].find_one({'public_id': USER_ID})
        assert ledger.undo() == []
        assert db[CmdbUser.COLLECTION].find_one({'public_id': USER_ID})[CmdbUserKey.SYNC_PENDING.value] is True

    def test_marked_users_are_settled_at_once_and_the_undo_marks_each_again(
            self, db: Any, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Two marked users synced together: both marks go, both come back with the undo"""
        users: list[CmdbUser] = [_user(sync_pending=True), _user(OVERRIDE_USER_ID, sync_pending=True)]

        for user in users:
            _store_user(db, user)

        db[CmdbUser.COLLECTION].update_many({'public_id': {'$in': USER_IDS}},
                                            {'$set': {CmdbUserKey.SYNC_PENDING.value: True}})
        ledger = WriteLedger()

        sync_users(_context(database_manager, database_name), ledger, users)

        assert db[CmdbUser.COLLECTION].count_documents(
            {'public_id': {'$in': USER_IDS}, CmdbUserKey.SYNC_PENDING.value: {'$exists': True}}) == 0
        assert ledger.undo() == []
        assert db[CmdbUser.COLLECTION].count_documents(
            {'public_id': {'$in': USER_IDS}, CmdbUserKey.SYNC_PENDING.value: True}) == len(USER_IDS)

    def test_undoing_the_ledger_puts_everything_back(self, db: Any, database_manager: MongoDatabaseManager,
                                                     database_name: str) -> None:
        """The created person goes, the edited group is restored"""
        _store_user(db, _user())
        group_before = db[CmdbObject.COLLECTION].find_one({'public_id': MAPPED_GROUP_ID}, {'_id': 0})
        ledger = WriteLedger()

        sync_user(_context(database_manager, database_name), ledger, _user())

        assert ledger.undo() == []
        assert _person(db) is None
        assert db[CmdbObject.COLLECTION].find_one({'public_id': MAPPED_GROUP_ID}, {'_id': 0}) == group_before


@pytest.mark.usefixtures('rest_api_app_context')
class TestTheEvents:
    """The change logs follow through the route layer's callbacks."""

    def test_create_edit_and_state_change_are_logged(self, db: Any, database_manager: MongoDatabaseManager,
                                                     database_name: str) -> None:
        """CREATE, then EDIT with the sync's comment, then ACTIVE_CHANGE"""
        _store_user(db, _user())
        context = _context(database_manager, database_name)
        events = build_sync_events(context.acting_user)

        emit_sync_events(context.objects_manager, _sync(context, _user()), events)
        emit_sync_events(context.objects_manager, _sync(context, _user(email='ann@example.org')), events)
        emit_sync_events(context.objects_manager, _sync(context, _user(email='ann@example.org', active=False)),
                         events)

        person_id = _person(db)['public_id']
        logs = list(db[CmdbMetaLog.COLLECTION].find({'object_id': person_id}).sort('public_id', 1))
        assert [(log['action'], log['comment']) for log in logs] == [
            (LogAction.CREATE.value, 'Object created'),
            (LogAction.EDIT.value, 'Synced from user management'),
            (LogAction.ACTIVE_CHANGE.value, 'Active status has changed'),
        ]
        assert all(log['user_id'] == ACTING_USER_ID for log in logs)

    def test_an_inactive_persons_unlink_is_logged(self, db: Any, database_manager: MongoDatabaseManager,
                                                  database_name: str) -> None:
        """A user deleted after the switch-off deactivated its person: no field or state change, but the unlink
        is in the change log"""
        _store_user(db, _user(active=False))
        context = _context(database_manager, database_name)
        _sync(context, _user(active=False))
        person_id = _person(db)['public_id']

        emit_sync_events(context.objects_manager, sync_user_deleted(context, WriteLedger(), USER_ID),
                         build_sync_events(context.acting_user))

        logs = list(db[CmdbMetaLog.COLLECTION].find({'object_id': person_id}))
        assert [(log['action'], log['comment']) for log in logs] == [
            (LogAction.EDIT.value, 'Unlinked from user management')]
