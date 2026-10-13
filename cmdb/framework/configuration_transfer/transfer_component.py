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
The contract every component of a configuration transfer fulfils

A component owns one collection's part of the transfer: it exports that collection's documents with their public_ids
and its counter, and imports the documents of a checked file under those public_ids and restores the counter. The
checks themselves are the transport layer's (`configuration_transfer_validation`), where the entity rules live.
Adding a further part of DataGerry to the transfer is one new subclass plus its place in the registered order
(`transfer_components.TRANSFER_COMPONENTS`) - the envelope, the routes and the version check do not change.

`component_order_problems` keeps the registered order honest: a component is imported after every component its
documents reference (a CmdbCategory names CmdbType ids, so types come first)
"""
from typing import Any, ClassVar, Sequence

from cmdb.manager.base_manager import BaseManager
from cmdb.manager.manager_provider_model.manager_type_enum import ManagerType
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.configuration_transfer.configuration_transfer_constants import (
    TransferComponentName,
    COUNTER_RESTORED,
    DUPLICATE_COMPONENT,
    DEPENDENCY_NOT_BEFORE,
)
from cmdb.framework.configuration_transfer.transfer_file import build_component_section
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID_KEY: str = 'public_id'


class TransferComponent:
    """
    One collection's part of a configuration transfer

    A subclass names itself, the components it depends on, the manager of its collection and - when only part of
    the collection belongs to the user's configuration - which documents it exports

    Attributes:
        NAME (TransferComponentName): The component's name, the key of its section in a transfer file
        DEPENDS_ON (tuple[TransferComponentName, ...]): The components whose documents this one's reference
        MANAGER_TYPE (ManagerType): The manager of the component's collection, as the routes resolve it
        COLLECTION (str): The component's collection - what the migration of an older file writes and reads
        EXPORT_CRITERIA (dict[str, Any]): Which documents of the collection are exported; empty means all of them
    """
    NAME: ClassVar[TransferComponentName]
    DEPENDS_ON: ClassVar[tuple[TransferComponentName, ...]] = ()
    MANAGER_TYPE: ClassVar[ManagerType]
    COLLECTION: ClassVar[str]
    EXPORT_CRITERIA: ClassVar[dict[str, Any]] = {}


    def __init__(self, manager: BaseManager) -> None:
        """
        Initialises the component on the manager of its collection

        Args:
            manager (BaseManager): The manager of the component's collection, for the requesting tenant
        """
        self.manager: BaseManager = manager


    def export_items(self) -> list[dict[str, Any]]:
        """
        Reads the documents this component exports, as they are stored

        Read raw - not through the model - so the file carries exactly what the database holds, and only the
        `_id` (which the target database assigns itself) is left out

        Raises:
            BaseManagerGetError: When the documents could not be read

        Returns:
            list[dict[str, Any]]: The documents, each with its public_id, in ascending public_id order
        """
        return self.manager.get_many_from_other_collection(
            self.manager.collection, sort=PUBLIC_ID_KEY, direction=CmdbDAO.DAO_ASCENDING,
            criteria=dict(self.EXPORT_CRITERIA),
        )


    def read_counter(self) -> int:
        """
        Reads the component's public_id counter: the highest id its collection ever handed out

        Raises:
            BaseManagerGetError: When the counter could not be read

        Returns:
            int: The counter, 0 when the collection never had one
        """
        return self.manager.get_next_public_id() - 1


    def export_section(self) -> dict[str, Any]:
        """
        Builds the component's section of a transfer file

        The counter is read before the documents, so a document inserted between the two reads can only make an
        item's id exceed the counter - which the import reconciles - never leave the counter pointing at nothing

        Raises:
            BaseManagerGetError: When the counter or the documents could not be read

        Returns:
            dict[str, Any]: The section: the counter and the documents
        """
        counter: int = self.read_counter()

        return build_component_section(counter, self.export_items())


    def prepare_item(self, item: dict[str, Any], author_id: int) -> dict[str, Any]:
        """
        Turns a checked file entry into the document the import stores - a copy, the entry left untouched

        The base stores the entry as the file carries it; a component whose documents carry something the
        importing system owns (an author, an ACL) overrides this

        Args:
            item (dict[str, Any]): The file entry
            author_id (int): public_id of the importing user

        Returns:
            dict[str, Any]: The document to store
        """
        del author_id

        return dict(item)


    def import_items(self, items: list[dict[str, Any]], ledger: WriteLedger, author_id: int) -> int:
        """
        Inserts the checked entries under their public_ids, in one batch, recorded on the ledger

        The batch is recorded BEFORE it runs, by the ids it inserts: an insert that fails midway may have stored
        part of it, and the undo deletes exactly those ids - which only this import can have written, since the
        collection was empty. A supplied id is never replaced: a clash fails the batch instead of storing the
        document under another id

        Args:
            items (list[dict[str, Any]]): The component's checked entries
            ledger (WriteLedger): The import's ledger
            author_id (int): public_id of the importing user

        Raises:
            BaseManagerInsertError: When the batch could not be stored

        Returns:
            int: The number of documents inserted
        """
        documents: list[dict[str, Any]] = [self.prepare_item(item, author_id) for item in items]

        if not documents:
            return 0

        ledger.inserted_where(self.manager, {PUBLIC_ID_KEY: {'$in': [doc[PUBLIC_ID_KEY] for doc in documents]}})
        self.manager.insert_many(documents, skip_public=True)

        return len(documents)


    def restore_counter(self, counter: int, items: list[dict[str, Any]], ledger: WriteLedger) -> int:
        """
        Sets the component's counter as the exporting system had it, never below an imported id

        Recorded on the ledger before it is written, with the value it had: the undo writes exactly that value
        back. Not "the highest id still stored" - the undo runs newest first, so when it reaches the counter the
        documents inserted after it may still be stored, or ones removed before it not yet restored

        Args:
            counter (int): The exported counter
            items (list[dict[str, Any]]): The component's imported entries
            ledger (WriteLedger): The import's ledger

        Raises:
            BaseManagerGetError: When the current counter could not be read
            BaseManagerUpdateError: When the counter could not be written

        Returns:
            int: The value the counter was set to
        """
        collection: str = self.manager.collection
        value: int = max([counter, *(item[PUBLIC_ID_KEY] for item in items)])
        prior: int = self.read_counter()

        ledger.compensated(
            collection,
            COUNTER_RESTORED.format(collection=collection, value=value),
            undo=lambda: self.manager.set_public_id_counter_of(collection, prior),
            verify=lambda: self.read_counter() == prior,
        )
        self.manager.set_public_id_counter_of(collection, value)

        return value


def component_order_problems(components: Sequence[type[TransferComponent]]) -> list[str]:
    """
    Judges an order of components: each registered once, each after every component it depends on

    Args:
        components (Sequence[type[TransferComponent]]): The components in the order they are imported

    Returns:
        list[str]: The problems, empty when the order can be imported as it stands
    """
    problems: list[str] = []
    seen: set[TransferComponentName] = set()

    for component in components:
        if component.NAME in seen:
            problems.append(DUPLICATE_COMPONENT.format(name=component.NAME.value))
            continue

        problems += [DEPENDENCY_NOT_BEFORE.format(name=component.NAME.value, dependency=dependency.value)
                     for dependency in component.DEPENDS_ON if dependency not in seen]
        seen.add(component.NAME)

    return problems
