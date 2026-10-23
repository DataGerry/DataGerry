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
Unit tests for cmdb.framework.configuration_transfer.configuration_import

Pure tests: no Mongo. What is pinned here: the predefined templates are read whole, recorded, then removed by the
same criteria; the seeded templates get reserved ids and are recorded by them before the batch; the user settings are
read whole, recorded and all removed; each component imports its own section and restores its counter, in the order
given; and the whole import runs remove -> components -> seed -> clear, stopping at the first failure
"""
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.configuration_transfer import (
    TransferComponentName,
    build_component_section,
    build_transfer_file,
    import_configuration,
)
from cmdb.framework.configuration_transfer import configuration_import as module
from cmdb.framework.configuration_transfer.configuration_import import (
    PREDEFINED_CRITERIA,
    clear_user_settings,
    import_components,
    remove_predefined_templates,
    seed_predefined_templates,
)
from cmdb.framework.configuration_transfer.configuration_transfer_constants import (
    PREDEFINED_TEMPLATES_REMOVED,
    USER_SETTINGS_CLEARED,
    WHOLE_DOCUMENT,
)
# -------------------------------------------------------------------------------------------------------------------- #

# What the transfer file is called in its information section
EXPORT_NAME: str = 'Test export'

TEMPLATES_COLLECTION: str = 'framework.sectionTemplates'
SETTINGS_COLLECTION: str = 'management.users.settings'
IMPORTER_ID: int = 1
PRIORS: list[dict[str, Any]] = [{'_id': 'a', 'public_id': 1}, {'_id': 'b', 'public_id': 2}]
SEEDED: list[dict[str, Any]] = [{'name': 'dg-a'}, {'name': 'dg-b'}]
RESERVED: list[int] = [13, 14]


def _manager(collection: str, deleted: int = 0) -> MagicMock:
    """A manager of the collection whose find answers PRIORS and whose delete answers a count"""
    manager: MagicMock = MagicMock()
    manager.collection = collection
    manager.find.return_value = list(PRIORS)
    manager.delete_many_from_other_collection.return_value = MagicMock(deleted_count=deleted)

    return manager


def _component(name: TransferComponentName, imported: int) -> MagicMock:
    """A component answering an import count"""
    component: MagicMock = MagicMock()
    component.NAME = name
    component.import_items.return_value = imported

    return component


def test_remove_predefined_templates_records_whole_documents_then_deletes() -> None:
    """Read whole (`_id` included), recorded as one batch delete, removed by the same criteria"""
    manager: MagicMock = _manager(TEMPLATES_COLLECTION, deleted=2)
    ledger: MagicMock = MagicMock(spec=WriteLedger)

    assert remove_predefined_templates(manager, ledger) == 2

    manager.find.assert_called_once_with(criteria=PREDEFINED_CRITERIA, projection=WHOLE_DOCUMENT)
    ledger.deleted_many.assert_called_once_with(manager, PRIORS, PREDEFINED_TEMPLATES_REMOVED)
    manager.delete_many_from_other_collection.assert_called_once_with(TEMPLATES_COLLECTION, PREDEFINED_CRITERIA)


def test_seed_predefined_templates_reserves_ids_and_records_them_first() -> None:
    """Reserved ids stamped on the seeded templates, the batch recorded by them, then inserted keeping them"""
    manager: MagicMock = _manager(TEMPLATES_COLLECTION)
    manager.reserve_public_ids.return_value = list(RESERVED)
    ledger: MagicMock = MagicMock(spec=WriteLedger)
    seeded: list[dict[str, Any]] = [dict(template) for template in SEEDED]

    with patch.object(module.SectionTemplateCreator, 'get_predefined_templates', return_value=seeded):
        assert seed_predefined_templates(manager, ledger) == len(SEEDED)

    manager.reserve_public_ids.assert_called_once_with(len(SEEDED))
    ledger.inserted_where.assert_called_once_with(manager, {'public_id': {'$in': RESERVED}})
    manager.insert_many.assert_called_once_with(
        [{'name': 'dg-a', 'public_id': 13}, {'name': 'dg-b', 'public_id': 14}], skip_public=True,
    )


def test_seed_predefined_templates_without_any_writes_nothing() -> None:
    """No template to seed -> no id reserved, nothing recorded"""
    manager: MagicMock = _manager(TEMPLATES_COLLECTION)
    ledger: MagicMock = MagicMock(spec=WriteLedger)

    with patch.object(module.SectionTemplateCreator, 'get_predefined_templates', return_value=[]):
        assert seed_predefined_templates(manager, ledger) == 0

    manager.reserve_public_ids.assert_not_called()
    ledger.inserted_where.assert_not_called()


def test_clear_user_settings_records_whole_documents_then_deletes_all() -> None:
    """Every setting read whole, recorded, the collection emptied"""
    manager: MagicMock = _manager(SETTINGS_COLLECTION, deleted=2)
    ledger: MagicMock = MagicMock(spec=WriteLedger)

    assert clear_user_settings(manager, ledger) == 2

    manager.find.assert_called_once_with(criteria={}, projection=WHOLE_DOCUMENT)
    ledger.deleted_many.assert_called_once_with(manager, PRIORS, USER_SETTINGS_CLEARED)
    manager.delete_many_from_other_collection.assert_called_once_with(SETTINGS_COLLECTION, {}, delete_all=True)


def test_import_components_imports_each_section_and_restores_its_counter_in_order() -> None:
    """Each component handed its own items, counter and the importer; counts in order"""
    types_items: list[dict[str, Any]] = [{'public_id': 4}]
    relations_items: list[dict[str, Any]] = [{'public_id': 2}, {'public_id': 3}]
    transfer_file: dict[str, Any] = build_transfer_file(1, {
        TransferComponentName.TYPES.value: build_component_section(30, types_items),
        TransferComponentName.RELATIONS.value: build_component_section(5, relations_items),
    }, name=EXPORT_NAME)
    types: MagicMock = _component(TransferComponentName.TYPES, 1)
    relations: MagicMock = _component(TransferComponentName.RELATIONS, 2)
    ledger: WriteLedger = WriteLedger()

    imported: dict[str, int] = import_components([types, relations], transfer_file, ledger, IMPORTER_ID)

    assert list(imported.items()) == [(TransferComponentName.TYPES.value, 1),
                                      (TransferComponentName.RELATIONS.value, 2)]
    assert types.mock_calls == [call.import_items(types_items, ledger, IMPORTER_ID),
                                call.restore_counter(30, types_items, ledger)]
    assert relations.mock_calls == [call.import_items(relations_items, ledger, IMPORTER_ID),
                                    call.restore_counter(5, relations_items, ledger)]


def test_import_configuration_runs_the_steps_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the predefined templates, import the components, seed the templates, clear the settings"""
    steps: list[str] = []
    templates: MagicMock = _manager(TEMPLATES_COLLECTION)
    settings: MagicMock = _manager(SETTINGS_COLLECTION)
    imported: dict[str, int] = {TransferComponentName.TYPES.value: 1}
    monkeypatch.setattr(module, 'remove_predefined_templates',
                        lambda manager, ledger: steps.append(('remove', manager)))
    monkeypatch.setattr(module, 'import_components',
                        lambda components, data, ledger, author: steps.append(('import', author)) or imported)
    monkeypatch.setattr(module, 'seed_predefined_templates', lambda manager, ledger: steps.append(('seed', manager)))
    monkeypatch.setattr(module, 'clear_user_settings', lambda manager, ledger: steps.append(('clear', manager)))

    assert import_configuration([], {}, (templates, settings), WriteLedger(), IMPORTER_ID) == imported
    assert steps == [('remove', templates), ('import', IMPORTER_ID), ('seed', templates), ('clear', settings)]


def test_import_configuration_stops_at_the_first_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing component import raises; the templates are not seeded, the settings not cleared"""
    reached: list[str] = []
    monkeypatch.setattr(module, 'remove_predefined_templates', lambda manager, ledger: None)
    monkeypatch.setattr(module, 'import_components', MagicMock(side_effect=RuntimeError('insert failed')))
    monkeypatch.setattr(module, 'seed_predefined_templates', lambda manager, ledger: reached.append('seed'))
    monkeypatch.setattr(module, 'clear_user_settings', lambda manager, ledger: reached.append('clear'))

    with pytest.raises(RuntimeError):
        import_configuration([], {}, (MagicMock(), MagicMock()), WriteLedger(), IMPORTER_ID)

    assert not reached
