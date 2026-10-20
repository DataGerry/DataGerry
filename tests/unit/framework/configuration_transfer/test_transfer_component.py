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
Unit tests for cmdb.framework.configuration_transfer.transfer_component and transfer_components

Pure tests: no Mongo, no Flask. What is pinned here: a component keeps the manager it is given, exports its own
collection's documents in ascending public_id order filtered by its criteria (handed over as a copy), reads its
counter as the last id handed out and reads it BEFORE the documents; it imports a copy of each entry in one batch
recorded on the ledger before it runs (nothing for no entries), and restores its counter to the larger of the
exported counter and the highest imported id - recorded before the write, undone by writing back its prior value; a
type is stored with the default ACL and the importer as author (and editor, if it had one); the order check accepts
dependencies registered earlier and names a later, a missing or a twice-registered one; and the registry holds the four
components, each once, every one after the ones it references, the predefined section templates left out
"""
from typing import Any
from unittest.mock import MagicMock, call

import pytest

from cmdb.manager import CategoriesManager, SectionTemplatesManager, TypesManager
from cmdb.manager.manager_provider_model.manager_type_enum import ManagerType
from cmdb.manager.relations_manager import RelationsManager
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.framework.configuration_transfer import (
    TRANSFER_COMPONENTS,
    TRANSFER_COMPONENT_NAMES,
    CategoryComponent,
    RelationComponent,
    SectionTemplateComponent,
    TransferComponent,
    TransferComponentName,
    TransferSectionKey,
    TypeComponent,
    component_order_problems,
)
from cmdb.framework.configuration_transfer.configuration_transfer_constants import (
    DUPLICATE_COMPONENT,
    DEPENDENCY_NOT_BEFORE,
    NOT_PREDEFINED,
)
from cmdb.framework.configuration_transfer.transfer_component import PUBLIC_ID_KEY
from cmdb.framework.write_ledger_constants import WriteKind
from cmdb.framework.write_ledger import WriteLedger
from cmdb.security.acl.access_control_list import AccessControlList
# -------------------------------------------------------------------------------------------------------------------- #

TEMPLATES: TransferComponentName = TransferComponentName.SECTION_TEMPLATES
TYPES: TransferComponentName = TransferComponentName.TYPES
CATEGORIES: TransferComponentName = TransferComponentName.CATEGORIES
RELATIONS: TransferComponentName = TransferComponentName.RELATIONS

COLLECTION: str = 'stub.collection'
NEXT_PUBLIC_ID: int = 13
STORED: list[dict[str, Any]] = [{PUBLIC_ID_KEY: 4}, {PUBLIC_ID_KEY: 9}]
CRITERIA: dict[str, Any] = {'kind': {'$ne': 'other'}}


class _StubComponent(TransferComponent):
    """A component of a stub collection, filtered by CRITERIA"""
    NAME = TEMPLATES
    MANAGER_TYPE = ManagerType.TYPES
    EXPORT_CRITERIA = CRITERIA


def _component(name: TransferComponentName, depends_on: tuple[TransferComponentName, ...] = ()) -> type:
    """A stub component class with the given name and dependencies"""
    return type(f'{name.value}_component', (_StubComponent,), {'NAME': name, 'DEPENDS_ON': depends_on})


def _manager() -> MagicMock:
    """A manager of COLLECTION holding STORED, its counter one below NEXT_PUBLIC_ID"""
    manager: MagicMock = MagicMock()
    manager.collection = COLLECTION
    manager.get_many_from_other_collection.return_value = list(STORED)
    manager.get_next_public_id.return_value = NEXT_PUBLIC_ID

    return manager

# -------------------------------------------------------------------------------------------------------------------- #
#                                                       contract                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_component_keeps_its_manager() -> None:
    """The manager it is built on is the one it works with"""
    manager: MagicMock = _manager()

    assert _StubComponent(manager).manager is manager


def test_a_component_depends_on_nothing_and_exports_everything_by_default() -> None:
    """No declared dependencies, no export criteria"""
    assert not TransferComponent.DEPENDS_ON
    assert not TransferComponent.EXPORT_CRITERIA


def test_export_items_reads_its_own_collection_in_ascending_order_by_its_criteria() -> None:
    """The manager's own collection, sorted by public_id ascending, filtered by the component's criteria"""
    manager: MagicMock = _manager()

    assert _StubComponent(manager).export_items() == STORED
    manager.get_many_from_other_collection.assert_called_once_with(
        COLLECTION, sort=PUBLIC_ID_KEY, direction=CmdbDAO.DAO_ASCENDING, criteria=CRITERIA,
    )


def test_export_items_hands_over_a_copy_of_the_criteria() -> None:
    """A read that changes its filter does not change the component class"""
    manager: MagicMock = _manager()
    manager.get_many_from_other_collection.side_effect = lambda *args, criteria, **kwargs: criteria.clear() or []

    _StubComponent(manager).export_items()

    assert _StubComponent.EXPORT_CRITERIA == {'kind': {'$ne': 'other'}}


def test_read_counter_is_the_last_id_handed_out() -> None:
    """The peeked next id minus one - 0 for a collection that never had a counter (next id 1)"""
    assert _StubComponent(_manager()).read_counter() == NEXT_PUBLIC_ID - 1

    fresh: MagicMock = _manager()
    fresh.get_next_public_id.return_value = 1

    assert _StubComponent(fresh).read_counter() == 0
    fresh.get_next_public_id.assert_called_once_with()


def test_export_section_reads_the_counter_before_the_documents() -> None:
    """Counter first, then the documents - a section of both"""
    manager: MagicMock = _manager()

    assert _StubComponent(manager).export_section() == {
        TransferSectionKey.COUNTER.value: NEXT_PUBLIC_ID - 1,
        TransferSectionKey.ITEMS.value: STORED,
    }
    assert [entry[0] for entry in manager.mock_calls] == ['get_next_public_id', 'get_many_from_other_collection']
    assert manager.mock_calls[0] == call.get_next_public_id()

# -------------------------------------------------------------------------------------------------------------------- #
#                                                        import                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

IMPORTER_ID: int = 1
EXPORTED_COUNTER: int = 30


def test_prepare_item_is_a_copy_of_the_entry() -> None:
    """The base stores the entry as the file carries it - as a new dict"""
    item: dict[str, Any] = {PUBLIC_ID_KEY: 4, 'name': 'x'}
    prepared: dict[str, Any] = _StubComponent(_manager()).prepare_item(item, IMPORTER_ID)

    assert prepared == item and prepared is not item


def test_import_items_records_the_batch_before_inserting_it() -> None:
    """One ledger entry by the inserted ids, then one insert_many keeping the ids"""
    manager: MagicMock = _manager()
    ledger: MagicMock = MagicMock(spec=WriteLedger)
    order: list[str] = []
    ledger.inserted_where.side_effect = lambda *args: order.append('ledger')
    manager.insert_many.side_effect = lambda *args, **kwargs: order.append('insert')

    assert _StubComponent(manager).import_items(STORED, ledger, IMPORTER_ID) == len(STORED)

    ledger.inserted_where.assert_called_once_with(manager, {PUBLIC_ID_KEY: {'$in': [4, 9]}})
    manager.insert_many.assert_called_once_with(STORED, skip_public=True)
    assert manager.insert_many.call_args.args[0][0] is not STORED[0]
    assert order == ['ledger', 'insert']


def test_import_items_without_entries_writes_nothing() -> None:
    """No entries -> no ledger entry, no insert"""
    manager: MagicMock = _manager()
    ledger: MagicMock = MagicMock(spec=WriteLedger)

    assert _StubComponent(manager).import_items([], ledger, IMPORTER_ID) == 0
    ledger.inserted_where.assert_not_called()
    manager.insert_many.assert_not_called()


@pytest.mark.parametrize('counter,items,expected', [
    (EXPORTED_COUNTER, STORED, EXPORTED_COUNTER),
    (2, STORED, 9),
    (0, [], 0),
])
def test_restore_counter_sets_the_larger_of_counter_and_ids(counter: int, items: list[dict[str, Any]],
                                                            expected: int) -> None:
    """Exported counter, never below an imported id"""
    manager: MagicMock = _manager()

    assert _StubComponent(manager).restore_counter(counter, items, WriteLedger()) == expected
    manager.set_public_id_counter_of.assert_called_once_with(COLLECTION, expected)


def test_restore_counter_is_recorded_first_and_undone_to_its_prior_value() -> None:
    """A compensated entry before the write; its undo writes back exactly the value the counter had"""
    manager: MagicMock = _manager()
    ledger: WriteLedger = WriteLedger()
    manager.set_public_id_counter_of.side_effect = RuntimeError('down')

    with pytest.raises(RuntimeError):
        _StubComponent(manager).restore_counter(EXPORTED_COUNTER, STORED, ledger)

    assert [entry.kind for entry in ledger.entries] == [WriteKind.COMPENSATED]

    manager.set_public_id_counter_of.side_effect = None
    manager.set_public_id_counter_of.reset_mock()

    assert not ledger.undo()
    manager.set_public_id_counter_of.assert_called_once_with(COLLECTION, NEXT_PUBLIC_ID - 1)


def test_a_type_gets_the_default_acl_and_the_importer_as_author() -> None:
    """ACL replaced, author rewritten, an editor rewritten too; the entry untouched"""
    item: dict[str, Any] = {PUBLIC_ID_KEY: 4, 'acl': {'activated': True}, 'author_id': 8, 'editor_id': 9}

    prepared: dict[str, Any] = TypeComponent(_manager()).prepare_item(item, IMPORTER_ID)

    assert prepared == {PUBLIC_ID_KEY: 4, 'acl': AccessControlList.default_json(), 'author_id': IMPORTER_ID,
                        'editor_id': IMPORTER_ID}
    assert item['acl'] == {'activated': True}


def test_a_type_never_edited_keeps_no_editor() -> None:
    """No editor (absent or None) stays no editor"""
    assert 'editor_id' not in TypeComponent(_manager()).prepare_item({PUBLIC_ID_KEY: 4}, IMPORTER_ID)
    assert TypeComponent(_manager()).prepare_item({PUBLIC_ID_KEY: 4, 'editor_id': None},
                                                  IMPORTER_ID)['editor_id'] is None

# -------------------------------------------------------------------------------------------------------------------- #
#                                                      order check                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_component_order_problems_accepts_dependencies_registered_earlier() -> None:
    """Each component after the ones it depends on -> no problem"""
    order: list[type] = [_component(TEMPLATES), _component(TYPES, (TEMPLATES,)), _component(CATEGORIES, (TYPES,))]

    assert not component_order_problems(order)


def test_component_order_problems_names_a_dependency_registered_later() -> None:
    """A component before its dependency names the pair"""
    order: list[type] = [_component(CATEGORIES, (TYPES,)), _component(TYPES)]

    assert component_order_problems(order) == [
        DEPENDENCY_NOT_BEFORE.format(name=CATEGORIES.value, dependency=TYPES.value)
    ]


def test_component_order_problems_names_a_dependency_never_registered() -> None:
    """Each missing dependency of a component is named"""
    order: list[type] = [_component(RELATIONS, (TYPES, TEMPLATES))]

    assert component_order_problems(order) == [
        DEPENDENCY_NOT_BEFORE.format(name=RELATIONS.value, dependency=TYPES.value),
        DEPENDENCY_NOT_BEFORE.format(name=RELATIONS.value, dependency=TEMPLATES.value),
    ]


def test_component_order_problems_names_a_component_registered_twice() -> None:
    """The second registration is named and its dependencies are not judged again"""
    order: list[type] = [_component(TYPES), _component(TYPES, (RELATIONS,))]

    assert component_order_problems(order) == [DUPLICATE_COMPONENT.format(name=TYPES.value)]

# -------------------------------------------------------------------------------------------------------------------- #
#                                                       registry                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_the_registry_holds_the_four_components_in_import_order() -> None:
    """Templates, types, categories, relations - and the names follow the classes"""
    assert TRANSFER_COMPONENTS == (SectionTemplateComponent, TypeComponent, CategoryComponent, RelationComponent)
    assert TRANSFER_COMPONENT_NAMES == (TEMPLATES.value, TYPES.value, CATEGORIES.value, RELATIONS.value)


def test_the_registry_names_every_component_once() -> None:
    """Every TransferComponentName has exactly one component"""
    assert sorted(TRANSFER_COMPONENT_NAMES) == sorted(name.value for name in TransferComponentName)


def test_the_registered_order_can_be_imported() -> None:
    """Every component after the ones its documents reference"""
    assert not component_order_problems(TRANSFER_COMPONENTS)


def test_each_component_reads_through_its_own_manager() -> None:
    """The manager type each component is built on"""
    assert {component.NAME: component.MANAGER_TYPE for component in TRANSFER_COMPONENTS} == {
        TEMPLATES: ManagerType.SECTION_TEMPLATES,
        TYPES: ManagerType.TYPES,
        CATEGORIES: ManagerType.CATEGORIES,
        RELATIONS: ManagerType.RELATIONS,
    }


def test_only_the_section_templates_are_filtered_and_the_predefined_ones_stay_home() -> None:
    """The predefined templates are seeded from code on every system; everything else is exported whole"""
    assert SectionTemplateComponent.EXPORT_CRITERIA == {SectionTemplateKey.PREDEFINED.value: NOT_PREDEFINED}
    assert all(not component.EXPORT_CRITERIA for component in TRANSFER_COMPONENTS
               if component is not SectionTemplateComponent)


def test_the_declared_dependencies() -> None:
    """Types claim templates; categories and relations name types"""
    assert {component.NAME: component.DEPENDS_ON for component in TRANSFER_COMPONENTS} == {
        TEMPLATES: (),
        TYPES: (TEMPLATES,),
        CATEGORIES: (TYPES,),
        RELATIONS: (TYPES,),
    }


def test_each_component_names_the_collection_its_manager_works_on() -> None:
    """The collection the migration writes is the one the import's manager writes"""
    managers: dict[ManagerType, type] = {
        ManagerType.SECTION_TEMPLATES: SectionTemplatesManager, ManagerType.TYPES: TypesManager,
        ManagerType.CATEGORIES: CategoriesManager, ManagerType.RELATIONS: RelationsManager,
    }

    for component in TRANSFER_COMPONENTS:
        manager = managers[component.MANAGER_TYPE](MagicMock(db_name='db'), 'db')
        assert manager.collection == component.COLLECTION, component.NAME
