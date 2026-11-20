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
Integration tests of the user group mapping (``person_sync.sync_group_mapping``) against a real MongoDB

Pinned: an existing person group is linked and, with both syncs on, takes its user group's name and synced members in
the same call; a created one is complete - the Type's defaults filled - and linked; the ledger undoes both; the link
index refuses a second person group for the same user group (the race the route's pre-check cannot close); the
mappings are read from the stored links. The session's test database carries no production
indexes, so the link index is built here from the model's declaration
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import GroupsManager, ObjectsManager, TypesManager, UsersManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.object_model import CmdbObject
from cmdb.models.special_type_model.person_type_constants import PersonGroupField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.person_types.default_person_types import build_default_person_type
from cmdb.framework.person_sync.sync_engine import SyncContext
from cmdb.framework.person_sync.sync_group_mapping import map_user_group, read_group_mappings
from cmdb.framework.person_sync.sync_settings import GroupSyncSettings, PersonSyncSettings, UserSyncSettings
from cmdb.errors.manager import BaseManagerInsertError
# -------------------------------------------------------------------------------------------------------------------- #

PERSON_TYPE_ID: int = 43401
OTHER_PERSON_TYPE_ID: int = 43402
GROUP_TYPE_ID: int = 43403
USER_ID: int = 43411
USER_GROUP_ID: int = 43421
PERSON_ID: int = 43431
EXISTING_GROUP_ID: int = 43432
SECOND_GROUP_ID: int = 43433
OWN_FIELD: str = 'cost_center'
OWN_DEFAULT: str = 'CC-1'
LABEL: str = 'Mapping Desk'
SYSTEM_REF_INDEX: str = 'system_ref_kind_id'

BOTH_ON: PersonSyncSettings = PersonSyncSettings(users=UserSyncSettings(active=True, default_type_id=PERSON_TYPE_ID),
                                                 groups=GroupSyncSettings(active=True))


def _group(public_id: int) -> dict[str, Any]:
    """An unmapped person group"""
    return {'public_id': public_id, 'type_id': GROUP_TYPE_ID, 'author_id': 1, 'active': True, 'version': '1.0.0',
            'special_type': SpecialType.PERSON_GROUP.value, 'multi_data_sections': [],
            'fields': [{'name': PersonGroupField.NAME.value, 'value': 'old', 'type': 'text'},
                       {'name': PersonGroupField.MEMBERS.value, 'value': [], 'type': 'person'}]}


@pytest.fixture(name='db')
def fixture_db(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The Types (the group Type with an own field carrying a default), a user with its person, two person groups"""
    database = database_manager.connector.client[database_name]
    collection = database[CmdbObject.COLLECTION]
    declared = next(index for index in CmdbObject.get_index_keys() if index.document['name'] == SYSTEM_REF_INDEX)
    collection.create_indexes([declared])

    for type_id, marker in ((PERSON_TYPE_ID, SpecialType.PERSON), (OTHER_PERSON_TYPE_ID, SpecialType.PERSON),
                            (GROUP_TYPE_ID, SpecialType.PERSON_GROUP)):
        document = build_default_person_type(marker, f'it-sync-map-{type_id}', type_id)
        document['system_type'] = False

        if marker == SpecialType.PERSON_GROUP:
            document['fields'].append({'type': 'text', 'name': OWN_FIELD, 'label': 'Cost center', 'required': True,
                                       'value': OWN_DEFAULT})

        database[CmdbType.COLLECTION].insert_one(document)

    database[CmdbUser.COLLECTION].insert_one(CmdbUser.to_json(CmdbUser(
        public_id=USER_ID, user_name='it-sync-map', active=True, group_ids=[USER_GROUP_ID])))
    database[CmdbUserGroup.COLLECTION].insert_one({'public_id': USER_GROUP_ID, 'name': 'it-map', 'label': LABEL,
                                                   'rights': []})
    collection.insert_many([
        {'public_id': PERSON_ID, 'type_id': PERSON_TYPE_ID, 'author_id': 1, 'active': True, 'version': '1.0.0',
         'special_type': SpecialType.PERSON.value, 'multi_data_sections': [], 'fields': [],
         'system_ref': {'kind': 'user', 'id': USER_ID}},
        _group(EXISTING_GROUP_ID),
        _group(SECOND_GROUP_ID),
    ])

    yield database

    collection.delete_many({'type_id': {'$in': [PERSON_TYPE_ID, OTHER_PERSON_TYPE_ID, GROUP_TYPE_ID]}})
    collection.drop_index(SYSTEM_REF_INDEX)
    database[CmdbType.COLLECTION].delete_many(
        {'public_id': {'$in': [PERSON_TYPE_ID, OTHER_PERSON_TYPE_ID, GROUP_TYPE_ID]}})
    database[CmdbUser.COLLECTION].delete_many({'public_id': USER_ID})
    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': USER_GROUP_ID})


def _context(database_manager: MongoDatabaseManager, database_name: str,
             settings: PersonSyncSettings = BOTH_ON) -> SyncContext:
    """The real managers"""
    return SyncContext(ObjectsManager(database_manager, database_name), TypesManager(database_manager, database_name),
                       UsersManager(database_manager, database_name), GroupsManager(database_manager, database_name),
                       settings, CmdbUser(public_id=1, user_name='admin', active=True))


def _user_group(database_manager: MongoDatabaseManager, database_name: str) -> CmdbUserGroup:
    """The stored user group"""
    return GroupsManager(database_manager, database_name).get_group(USER_GROUP_ID)


def _values(document: dict[str, Any]) -> dict[str, Any]:
    """A document's values by field name"""
    return {entry['name']: entry['value'] for entry in document['fields']}


@pytest.mark.usefixtures('db')
class TestMapUserGroup:
    """Linking and creating."""

    def test_an_existing_group_is_linked_and_synced_at_once(self, database_manager: MongoDatabaseManager,
                                                            database_name: str, db: Any) -> None:
        """The link, the label, the user's person"""
        context = _context(database_manager, database_name)
        stored = db[CmdbObject.COLLECTION].find_one({'public_id': EXISTING_GROUP_ID}, {'_id': 0})

        public_id, result = map_user_group(context, WriteLedger(), _user_group(database_manager, database_name),
                                           person_group=stored)

        mapped = db[CmdbObject.COLLECTION].find_one({'public_id': EXISTING_GROUP_ID})
        assert public_id == EXISTING_GROUP_ID
        assert mapped['system_ref'] == {'kind': 'user_group', 'id': USER_GROUP_ID}
        assert _values(mapped) == {PersonGroupField.NAME.value: LABEL, PersonGroupField.MEMBERS.value: [PERSON_ID]}
        assert list(result.edits) == [EXISTING_GROUP_ID]
        assert result.config_items_changed is True

    def test_with_the_group_sync_off_the_group_is_only_linked(self, database_manager: MongoDatabaseManager,
                                                              database_name: str, db: Any) -> None:
        """Its fields untouched"""
        settings = PersonSyncSettings(users=BOTH_ON.users)
        stored = db[CmdbObject.COLLECTION].find_one({'public_id': EXISTING_GROUP_ID}, {'_id': 0})

        map_user_group(_context(database_manager, database_name, settings), WriteLedger(),
                       _user_group(database_manager, database_name), person_group=stored)

        mapped = db[CmdbObject.COLLECTION].find_one({'public_id': EXISTING_GROUP_ID})
        assert mapped['system_ref'] == {'kind': 'user_group', 'id': USER_GROUP_ID}
        assert _values(mapped)[PersonGroupField.NAME.value] == 'old'

    def test_a_created_group_is_complete(self, database_manager: MongoDatabaseManager, database_name: str,
                                         db: Any) -> None:
        """The Type's default filled, the members synced"""
        context = _context(database_manager, database_name)

        public_id, result = map_user_group(context, WriteLedger(), _user_group(database_manager, database_name),
                                           type_instance=context.types_manager.get_type_instance(GROUP_TYPE_ID))

        created = db[CmdbObject.COLLECTION].find_one({'public_id': public_id})
        assert result.created == [public_id]
        assert result.config_items_changed is False
        assert created['system_ref'] == {'kind': 'user_group', 'id': USER_GROUP_ID}
        assert _values(created) == {PersonGroupField.NAME.value: LABEL, PersonGroupField.MEMBERS.value: [PERSON_ID],
                                    OWN_FIELD: OWN_DEFAULT}

    def test_the_ledger_undoes_a_mapping(self, database_manager: MongoDatabaseManager, database_name: str,
                                         db: Any) -> None:
        """The link and the synced fields go back"""
        ledger = WriteLedger()
        stored = db[CmdbObject.COLLECTION].find_one({'public_id': EXISTING_GROUP_ID}, {'_id': 0})
        map_user_group(_context(database_manager, database_name), ledger,
                       _user_group(database_manager, database_name), person_group=stored)

        ledger.undo()

        restored = db[CmdbObject.COLLECTION].find_one({'public_id': EXISTING_GROUP_ID}, {'_id': 0})
        assert restored == stored

    def test_the_index_refuses_a_second_group_for_a_user_group(self, database_manager: MongoDatabaseManager,
                                                               database_name: str, db: Any) -> None:
        """A create racing a mapping loses"""
        context = _context(database_manager, database_name, PersonSyncSettings(users=BOTH_ON.users))
        stored = db[CmdbObject.COLLECTION].find_one({'public_id': EXISTING_GROUP_ID}, {'_id': 0})
        map_user_group(context, WriteLedger(), _user_group(database_manager, database_name), person_group=stored)

        with pytest.raises(BaseManagerInsertError):
            map_user_group(context, WriteLedger(), _user_group(database_manager, database_name),
                           type_instance=context.types_manager.get_type_instance(GROUP_TYPE_ID))

        assert db[CmdbObject.COLLECTION].count_documents({'system_ref.kind': 'user_group'}) == 1


@pytest.mark.usefixtures('db')
class TestReaders:
    """The stored links."""

    def test_the_mappings(self, database_manager: MongoDatabaseManager, database_name: str, db: Any) -> None:
        """One per mapped person group"""
        objects_manager = ObjectsManager(database_manager, database_name)
        db[CmdbObject.COLLECTION].update_one({'public_id': SECOND_GROUP_ID},
                                             {'$set': {'system_ref': {'kind': 'user_group', 'id': USER_GROUP_ID}}})

        assert read_group_mappings(objects_manager) == [
            {'user_group_id': USER_GROUP_ID, 'person_group_id': SECOND_GROUP_ID},
        ]

