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
Integration tests of the target-Type relocation (``person_sync.sync_relocation``) against a real MongoDB

Pinned, planning: only persons of existing users outside their new target are planned; a reference field naming only
the old Type, a reference section field, a relation side not allowing the new Type, a location node and a value the new
Type cannot keep each block - a reference field allowing the new Type does not. Writing: a move keeps the id, takes the
new Type, drops the fingerprint and restamps the object logs, the object relations and their logs; a copy leaves the
old person unlinked and deactivated, creates a new linked one and moves the mapped group's membership, every other
reference staying on the old; the ledger undoes a move with everything it restamped
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import (
    GroupsManager,
    LocationsManager,
    LogsManager,
    ObjectRelationLogsManager,
    ObjectRelationsManager,
    ObjectsManager,
    RelationsManager,
    TypesManager,
    UsersManager,
)
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.cmdb_object_relation_log import CmdbObjectRelationLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.object_relation_model.cmdb_object_relation import CmdbObjectRelation
from cmdb.models.relation_model.cmdb_relation import CmdbRelation
from cmdb.models.special_type_model.person_type_constants import PersonField, PersonGroupField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.person_types.default_person_types import build_default_person_type
from cmdb.framework.person_sync.person_sync_constants import RelocationBlocker
from cmdb.framework.person_sync.sync_engine import SyncContext
from cmdb.framework.person_sync.sync_relocation import RelocationStores, plan_relocations, relocate_persons
from cmdb.framework.person_sync.sync_relocation_rules import PersonRelocation
from cmdb.framework.person_sync.sync_settings import PersonSyncSettings, UserSyncSettings
# -------------------------------------------------------------------------------------------------------------------- #

OLD_TYPE_ID: int = 43501
NEW_TYPE_ID: int = 43502
HOLDER_TYPE_ID: int = 43503
GROUP_TYPE_ID: int = 43504
TYPE_IDS: list[int] = [OLD_TYPE_ID, NEW_TYPE_ID, HOLDER_TYPE_ID, GROUP_TYPE_ID]
FREE_USER_ID: int = 43511
HELD_USER_ID: int = 43512
GONE_USER_ID: int = 43513
USER_IDS: list[int] = [FREE_USER_ID, HELD_USER_ID]
FREE_PERSON_ID: int = 43521
HELD_PERSON_ID: int = 43522
GONE_PERSON_ID: int = 43523
HOLDER_ID: int = 43531
GROUP_ID: int = 43532
STRICT_RELATION_ID: int = 43541
OPEN_RELATION_ID: int = 43542
STRICT_LINK_ID: int = 43551
OPEN_LINK_ID: int = 43552
LOG_ID: int = 43561
RELATION_LOG_ID: int = 43562
LOCATION_ID: int = 43571
USER_GROUP_ID: int = 43581
OLD_ONLY_FIELD: str = 'badge'
STRICT_FIELD: str = 'owner'
OPEN_FIELD: str = 'backup'
SECTION_FIELD: str = 'shown-field'

MOVED: PersonSyncSettings = PersonSyncSettings(users=UserSyncSettings(active=True, default_type_id=NEW_TYPE_ID))


def _type(type_id: int, marker: SpecialType | None, extra_fields: list[dict[str, Any]]) -> dict[str, Any]:
    """A Type from a person blueprint (the holder borrows the PERSON one), with extra fields"""
    document: dict[str, Any] = build_default_person_type(marker or SpecialType.PERSON, f'it-reloc-{type_id}', type_id)
    document['system_type'] = False
    document['fields'].extend(extra_fields)

    if marker is None:
        document['special_type'] = None

    return document


def _person(public_id: int, user_id: int, **values: Any) -> dict[str, Any]:
    """A synced person in the old Type"""
    fields = [{'name': PersonField.DISPLAY_NAME.value, 'value': f'P{public_id}', 'type': 'text'}]
    fields += [{'name': name, 'value': value, 'type': 'text'} for name, value in values.items()]

    return {'public_id': public_id, 'type_id': OLD_TYPE_ID, 'author_id': 1, 'active': True, 'version': '1.0.0',
            'special_type': SpecialType.PERSON.value, 'multi_data_sections': [], 'fields': fields,
            'system_ref': {'kind': 'user', 'id': user_id}, 'sync_hash': 'h'}


@pytest.fixture(name='db')
def fixture_db(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """
    The free person carries an empty old-only field, a relation allowing the new Type, a log and a relation log; the
    held person is referenced strictly, by a section, sits on a strict relation, is placed and holds an old-only value,
    and is a member of a mapped group; the gone user's person is linked to nobody
    """
    database = database_manager.connector.client[database_name]
    database[CmdbType.COLLECTION].insert_many([
        _type(OLD_TYPE_ID, SpecialType.PERSON, [{'type': 'text', 'name': OLD_ONLY_FIELD, 'label': 'Badge'}]),
        _type(NEW_TYPE_ID, SpecialType.PERSON, []),
        _type(HOLDER_TYPE_ID, None, [
            {'type': 'ref', 'name': STRICT_FIELD, 'label': 'Owner', 'ref_types': [OLD_TYPE_ID]},
            {'type': 'ref', 'name': OPEN_FIELD, 'label': 'Backup', 'ref_types': [OLD_TYPE_ID, NEW_TYPE_ID]},
        ]),
        _type(GROUP_TYPE_ID, SpecialType.PERSON_GROUP, []),
    ])
    database[CmdbUser.COLLECTION].insert_many([
        CmdbUser.to_json(CmdbUser(public_id=user_id, user_name=f'it-reloc-{user_id}', active=True,
                                  group_ids=[USER_GROUP_ID], first_name='Ann', last_name='Lee'))
        for user_id in USER_IDS
    ])
    database[CmdbObject.COLLECTION].insert_many([
        _person(FREE_PERSON_ID, FREE_USER_ID, **{OLD_ONLY_FIELD: ''}),
        _person(HELD_PERSON_ID, HELD_USER_ID, **{OLD_ONLY_FIELD: 'B-7'}),
        _person(GONE_PERSON_ID, GONE_USER_ID),
        {'public_id': HOLDER_ID, 'type_id': HOLDER_TYPE_ID, 'author_id': 1, 'active': True, 'version': '1.0.0',
         'multi_data_sections': [], 'fields': [
             {'name': STRICT_FIELD, 'value': HELD_PERSON_ID, 'type': 'ref'},
             {'name': OPEN_FIELD, 'value': FREE_PERSON_ID, 'type': 'ref'},
             {'name': SECTION_FIELD, 'value': HELD_PERSON_ID, 'type': 'ref-section-field'},
         ]},
        {'public_id': GROUP_ID, 'type_id': GROUP_TYPE_ID, 'author_id': 1, 'active': True, 'version': '1.0.0',
         'special_type': SpecialType.PERSON_GROUP.value, 'multi_data_sections': [],
         'system_ref': {'kind': 'user_group', 'id': USER_GROUP_ID},
         'fields': [{'name': PersonGroupField.NAME.value, 'value': 'Desk', 'type': 'text'},
                    {'name': PersonGroupField.MEMBERS.value, 'value': [HELD_PERSON_ID, FREE_PERSON_ID],
                     'type': 'person'}]},
    ])
    database[CmdbRelation.COLLECTION].insert_many([
        {'public_id': STRICT_RELATION_ID, 'relation_name': 'it-strict', 'parent_type_ids': [OLD_TYPE_ID],
         'child_type_ids': [HOLDER_TYPE_ID]},
        {'public_id': OPEN_RELATION_ID, 'relation_name': 'it-open', 'parent_type_ids': [OLD_TYPE_ID, NEW_TYPE_ID],
         'child_type_ids': [HOLDER_TYPE_ID]},
    ])
    database[CmdbObjectRelation.COLLECTION].insert_many([
        {'public_id': STRICT_LINK_ID, 'relation_id': STRICT_RELATION_ID, 'relation_parent_id': HELD_PERSON_ID,
         'relation_parent_type_id': OLD_TYPE_ID, 'relation_child_id': HOLDER_ID,
         'relation_child_type_id': HOLDER_TYPE_ID},
        {'public_id': OPEN_LINK_ID, 'relation_id': OPEN_RELATION_ID, 'relation_parent_id': FREE_PERSON_ID,
         'relation_parent_type_id': OLD_TYPE_ID, 'relation_child_id': HOLDER_ID,
         'relation_child_type_id': HOLDER_TYPE_ID},
    ])
    database[CmdbMetaLog.COLLECTION].insert_one({'public_id': LOG_ID, 'log_type': 'CmdbObjectLog',
                                                 'object_id': FREE_PERSON_ID, 'type_id': OLD_TYPE_ID})
    database[CmdbObjectRelationLog.COLLECTION].insert_one({
        'public_id': RELATION_LOG_ID, 'object_relation_id': OPEN_LINK_ID,
        'object_relation_parent_id': FREE_PERSON_ID, 'relation_parent_type_id': OLD_TYPE_ID,
        'object_relation_child_id': HOLDER_ID, 'relation_child_type_id': HOLDER_TYPE_ID,
    })
    database[CmdbLocation.COLLECTION].insert_one({'public_id': LOCATION_ID, 'object_id': HELD_PERSON_ID,
                                                  'type_id': OLD_TYPE_ID})

    yield database

    database[CmdbObject.COLLECTION].delete_many({'$or': [{'type_id': {'$in': TYPE_IDS}},
                                                         {'system_ref.id': {'$in': USER_IDS + [GONE_USER_ID]}}]})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': TYPE_IDS}})
    database[CmdbUser.COLLECTION].delete_many({'public_id': {'$in': USER_IDS}})
    database[CmdbRelation.COLLECTION].delete_many({'public_id': {'$in': [STRICT_RELATION_ID, OPEN_RELATION_ID]}})
    database[CmdbObjectRelation.COLLECTION].delete_many({'public_id': {'$in': [STRICT_LINK_ID, OPEN_LINK_ID]}})
    database[CmdbMetaLog.COLLECTION].delete_many({'$or': [{'public_id': LOG_ID},
                                                          {'object_id': {'$gte': FREE_PERSON_ID}}]})
    database[CmdbObjectRelationLog.COLLECTION].delete_many({'public_id': RELATION_LOG_ID})
    database[CmdbLocation.COLLECTION].delete_many({'public_id': LOCATION_ID})


def _context(database_manager: MongoDatabaseManager, database_name: str) -> SyncContext:
    """The real managers on the new settings"""
    return SyncContext(ObjectsManager(database_manager, database_name), TypesManager(database_manager, database_name),
                       UsersManager(database_manager, database_name), GroupsManager(database_manager, database_name),
                       MOVED, CmdbUser(public_id=1, user_name='admin', active=True))


def _stores(database_manager: MongoDatabaseManager, database_name: str) -> RelocationStores:
    """The real stamped stores"""
    return RelocationStores(LogsManager(database_manager, database_name),
                            RelationsManager(database_manager, database_name),
                            ObjectRelationsManager(database_manager, database_name),
                            ObjectRelationLogsManager(database_manager, database_name),
                            LocationsManager(database_manager, database_name))


def _plan(database_manager: MongoDatabaseManager, database_name: str) -> dict[int, PersonRelocation]:
    """The planned relocations by person"""
    return {relocation.person_id: relocation for relocation in plan_relocations(
        _context(database_manager, database_name), _stores(database_manager, database_name), MOVED.users)}


def _relocate(database_manager: MongoDatabaseManager, database_name: str, ledger: WriteLedger) -> Any:
    """Plans and writes every relocation, copying the blocked"""
    context = _context(database_manager, database_name)
    stores = _stores(database_manager, database_name)

    return relocate_persons(context, stores, ledger, plan_relocations(context, stores, MOVED.users), True)


@pytest.mark.usefixtures('db')
class TestPlan:
    """What is planned, and what blocks."""

    def test_only_existing_users_persons_are_planned(self, database_manager: MongoDatabaseManager,
                                                     database_name: str) -> None:
        """The gone user's person is the pass's"""
        assert sorted(_plan(database_manager, database_name)) == [FREE_PERSON_ID, HELD_PERSON_ID]

    def test_the_free_person_can_move(self, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """An empty old-only field, an open reference and an open relation do not block"""
        free: PersonRelocation = _plan(database_manager, database_name)[FREE_PERSON_ID]

        assert (free.from_type_id, free.to_type_id, free.blockers) == (OLD_TYPE_ID, NEW_TYPE_ID, ())

    def test_the_held_person_names_every_blocker(self, database_manager: MongoDatabaseManager,
                                                 database_name: str) -> None:
        """Value, strict reference, section, strict relation, location"""
        held: PersonRelocation = _plan(database_manager, database_name)[HELD_PERSON_ID]

        assert held.blockers == (
            RelocationBlocker.LOST_FIELDS.value.format(names=[OLD_ONLY_FIELD], type_id=NEW_TYPE_ID),
            RelocationBlocker.REFERENCE_FIELD.value.format(holder_id=HOLDER_ID, name=STRICT_FIELD,
                                                           type_ids=[OLD_TYPE_ID]),
            RelocationBlocker.REFERENCE_SECTION.value.format(holder_id=HOLDER_ID, name=SECTION_FIELD),
            RelocationBlocker.RELATION_SIDE.value.format(relation_id=STRICT_LINK_ID,
                                                         definition_id=STRICT_RELATION_ID,
                                                         type_ids=[OLD_TYPE_ID], side='parent'),
            RelocationBlocker.LOCATION.value,
        )


@pytest.mark.usefixtures('db')
class TestRelocate:
    """Moving and copying."""

    def test_a_move_keeps_the_person_and_restamps_its_type(self, database_manager: MongoDatabaseManager,
                                                           database_name: str, db: Any) -> None:
        """The id, the new Type, no fingerprint; logs, relation, relation log restamped"""
        result = _relocate(database_manager, database_name, WriteLedger())

        moved = db[CmdbObject.COLLECTION].find_one({'public_id': FREE_PERSON_ID})
        assert moved['type_id'] == NEW_TYPE_ID
        assert moved['system_ref'] == {'kind': 'user', 'id': FREE_USER_ID}
        assert 'sync_hash' not in moved
        assert OLD_ONLY_FIELD not in [entry['name'] for entry in moved['fields']]
        assert FREE_PERSON_ID in result.edits
        assert db[CmdbMetaLog.COLLECTION].find_one({'public_id': LOG_ID})['type_id'] == NEW_TYPE_ID
        assert db[CmdbObjectRelation.COLLECTION].find_one(
            {'public_id': OPEN_LINK_ID})['relation_parent_type_id'] == NEW_TYPE_ID
        assert db[CmdbObjectRelationLog.COLLECTION].find_one(
            {'public_id': RELATION_LOG_ID})['relation_parent_type_id'] == NEW_TYPE_ID

    def test_a_copy_leaves_the_old_person_and_moves_the_group(self, database_manager: MongoDatabaseManager,
                                                              database_name: str, db: Any) -> None:
        """Old unlinked + inactive, references kept on it; new linked in the new Type; the group holds the new one"""
        result = _relocate(database_manager, database_name, WriteLedger())

        old = db[CmdbObject.COLLECTION].find_one({'public_id': HELD_PERSON_ID})
        new = db[CmdbObject.COLLECTION].find_one({'system_ref.kind': 'user', 'system_ref.id': HELD_USER_ID})
        group = db[CmdbObject.COLLECTION].find_one({'public_id': GROUP_ID})
        holder = db[CmdbObject.COLLECTION].find_one({'public_id': HOLDER_ID})
        assert (old['active'], old['type_id'], 'system_ref' in old, 'sync_hash' in old) == (
            False, OLD_TYPE_ID, False, False)
        assert (new['type_id'], new['active']) == (NEW_TYPE_ID, True)
        assert result.created == [new['public_id']]
        assert result.config_items_changed is True
        members = next(entry['value'] for entry in group['fields'] if entry['name'] == PersonGroupField.MEMBERS.value)
        assert members == [new['public_id'], FREE_PERSON_ID]
        assert next(entry['value'] for entry in holder['fields'] if entry['name'] == STRICT_FIELD) == HELD_PERSON_ID
        assert db[CmdbObjectRelation.COLLECTION].find_one(
            {'public_id': STRICT_LINK_ID})['relation_parent_type_id'] == OLD_TYPE_ID

    def test_the_ledger_undoes_everything(self, database_manager: MongoDatabaseManager, database_name: str,
                                          db: Any) -> None:
        """Persons, group, log, relation and relation log as they were; the new person gone"""
        before: dict[str, Any] = {
            'objects': list(db[CmdbObject.COLLECTION].find({'type_id': {'$in': TYPE_IDS}}, {'_id': 0})),
            'log': db[CmdbMetaLog.COLLECTION].find_one({'public_id': LOG_ID}, {'_id': 0}),
            'link': db[CmdbObjectRelation.COLLECTION].find_one({'public_id': OPEN_LINK_ID}, {'_id': 0}),
            'relation_log': db[CmdbObjectRelationLog.COLLECTION].find_one({'public_id': RELATION_LOG_ID}, {'_id': 0}),
        }
        ledger = WriteLedger()
        _relocate(database_manager, database_name, ledger)

        assert ledger.undo() == []

        assert list(db[CmdbObject.COLLECTION].find({'type_id': {'$in': TYPE_IDS}}, {'_id': 0})) == before['objects']
        assert db[CmdbMetaLog.COLLECTION].find_one({'public_id': LOG_ID}, {'_id': 0}) == before['log']
        assert db[CmdbObjectRelation.COLLECTION].find_one({'public_id': OPEN_LINK_ID}, {'_id': 0}) == before['link']
        assert db[CmdbObjectRelationLog.COLLECTION].find_one(
            {'public_id': RELATION_LOG_ID}, {'_id': 0}) == before['relation_log']

    def test_blocked_persons_without_the_copy_choice_are_a_programming_error(
            self, database_manager: MongoDatabaseManager, database_name: str, db: Any) -> None:
        """Nothing written"""
        context = _context(database_manager, database_name)
        stores = _stores(database_manager, database_name)

        with pytest.raises(ValueError):
            relocate_persons(context, stores, WriteLedger(), plan_relocations(context, stores, MOVED.users), False)

        assert db[CmdbObject.COLLECTION].find_one({'public_id': FREE_PERSON_ID})['type_id'] == OLD_TYPE_ID
