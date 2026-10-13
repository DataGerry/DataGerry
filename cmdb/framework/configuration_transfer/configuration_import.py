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
Writes a checked configuration transfer file into a reset system - every write on one ledger

The steps, in the order `import_configuration` runs them:

    1. the predefined section templates are removed - they share the id counter with the user's templates, so the
       file's template ids could collide with them
    2. every component inserts its entries under their public_ids and gets its counter back, in import order
    3. the predefined section templates are seeded again from code; they draw fresh ids above the restored counter
       (nothing references them by id - a type claims a global template by name)
    4. every user's settings are cleared - the ones written between the reset and the import name the old system's
       types

Nothing here checks the file: the caller has judged it completely before (`configuration_transfer_validation`) and
made sure the system is reset (`reset_scope.find_import_blockers`). A failure in any step raises; the caller undoes
the ledger, which takes every step back - the removed predefined templates included
"""
from typing import Any, Sequence

from cmdb.manager.base_manager import BaseManager
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.section_templates import SectionTemplateCreator
from cmdb.framework.configuration_transfer.configuration_transfer_constants import (
    PREDEFINED_TEMPLATES_REMOVED,
    USER_SETTINGS_CLEARED,
    WHOLE_DOCUMENT,
    TransferFileKey,
    TransferSectionKey,
)
from cmdb.framework.configuration_transfer.transfer_component import PUBLIC_ID_KEY, TransferComponent
# -------------------------------------------------------------------------------------------------------------------- #

PREDEFINED_CRITERIA: dict[str, Any] = {SectionTemplateKey.PREDEFINED.value: True}


def remove_predefined_templates(templates_manager: BaseManager, ledger: WriteLedger) -> int:
    """
    Removes the predefined section templates, their snapshots recorded first so the undo can put them back

    Args:
        templates_manager (BaseManager): The section templates' manager
        ledger (WriteLedger): The import's ledger

    Raises:
        BaseManagerGetError: When the templates could not be read
        BaseManagerDeleteError: When they could not be deleted

    Returns:
        int: The number of templates removed
    """
    priors: list[dict[str, Any]] = templates_manager.find(criteria=dict(PREDEFINED_CRITERIA), projection=WHOLE_DOCUMENT)
    ledger.deleted_many(templates_manager, priors, PREDEFINED_TEMPLATES_REMOVED)

    return templates_manager.delete_many_from_other_collection(
        templates_manager.collection, dict(PREDEFINED_CRITERIA)
    ).deleted_count


def seed_predefined_templates(templates_manager: BaseManager, ledger: WriteLedger) -> int:
    """
    Inserts the predefined section templates the seeding code builds, under ids drawn from the counter

    The ids are reserved first, so the batch can be recorded on the ledger by them before it runs

    Args:
        templates_manager (BaseManager): The section templates' manager
        ledger (WriteLedger): The import's ledger

    Raises:
        BaseManagerGetError: When the ids could not be reserved
        BaseManagerInsertError: When the templates could not be stored

    Returns:
        int: The number of templates seeded
    """
    templates: list[dict[str, Any]] = SectionTemplateCreator().get_predefined_templates()

    if not templates:
        return 0

    public_ids: list[int] = templates_manager.reserve_public_ids(len(templates))

    for template, public_id in zip(templates, public_ids):
        template[PUBLIC_ID_KEY] = public_id

    ledger.inserted_where(templates_manager, {PUBLIC_ID_KEY: {'$in': public_ids}})
    templates_manager.insert_many(templates, skip_public=True)

    return len(templates)


def clear_user_settings(user_settings_manager: BaseManager, ledger: WriteLedger) -> int:
    """
    Deletes every user's settings, their snapshots recorded first so the undo can put them back

    Args:
        user_settings_manager (BaseManager): The user settings' manager
        ledger (WriteLedger): The import's ledger

    Raises:
        BaseManagerGetError: When the settings could not be read
        BaseManagerDeleteError: When they could not be deleted

    Returns:
        int: The number of settings deleted
    """
    priors: list[dict[str, Any]] = user_settings_manager.find(criteria={}, projection=WHOLE_DOCUMENT)
    ledger.deleted_many(user_settings_manager, priors, USER_SETTINGS_CLEARED)

    return user_settings_manager.delete_many_from_other_collection(user_settings_manager.collection, {}).deleted_count


def import_components(components: Sequence[TransferComponent], transfer_file: dict[str, Any], ledger: WriteLedger,
                      author_id: int) -> dict[str, int]:
    """
    Inserts every component's entries and restores its counter, in the order given

    Args:
        components (Sequence[TransferComponent]): The components, in import order
        transfer_file (dict[str, Any]): The checked transfer file
        ledger (WriteLedger): The import's ledger
        author_id (int): public_id of the importing user

    Raises:
        BaseManagerInsertError: When a component's entries could not be stored
        BaseManagerUpdateError: When a counter could not be written

    Returns:
        dict[str, int]: The number of documents imported per component, in import order
    """
    sections: dict[str, Any] = transfer_file[TransferFileKey.COMPONENTS.value]
    imported: dict[str, int] = {}

    for component in components:
        section: dict[str, Any] = sections[component.NAME.value]
        items: list[dict[str, Any]] = section[TransferSectionKey.ITEMS.value]

        imported[component.NAME.value] = component.import_items(items, ledger, author_id)
        component.restore_counter(section[TransferSectionKey.COUNTER.value], items, ledger)

    return imported


def import_configuration(components: Sequence[TransferComponent], transfer_file: dict[str, Any],
                         managers: tuple[BaseManager, BaseManager], ledger: WriteLedger,
                         author_id: int) -> dict[str, int]:
    """
    Writes a checked transfer file into a reset system: templates out, components in, templates seeded, settings
    cleared

    Args:
        components (Sequence[TransferComponent]): The components, in import order
        transfer_file (dict[str, Any]): The checked transfer file
        managers (tuple[BaseManager, BaseManager]): The section templates' and the user settings' managers
        ledger (WriteLedger): The import's ledger - the caller undoes it when this raises
        author_id (int): public_id of the importing user

    Raises:
        BaseManagerGetError | BaseManagerInsertError | BaseManagerUpdateError | BaseManagerDeleteError: When a step
            failed; the steps before it are on the ledger

    Returns:
        dict[str, int]: The number of documents imported per component, in import order
    """
    templates_manager, user_settings_manager = managers

    remove_predefined_templates(templates_manager, ledger)
    imported: dict[str, int] = import_components(components, transfer_file, ledger, author_id)
    seed_predefined_templates(templates_manager, ledger)
    clear_user_settings(user_settings_manager, ledger)

    return imported
