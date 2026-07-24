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
Implementation of ObjectImporter
"""
import copy
from logging import Logger, getLogger

from flask import current_app

from cmdb.manager import ObjectsManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.framework.importer.importers.base_importer import BaseImporter
from cmdb.framework.importer.configs.object_importer_config import ObjectImporterConfig
from cmdb.framework.importer.helper.object_import_validator import normalize_and_validate_object
from cmdb.framework.importer.responses.importer_object_response import ImporterObjectResponse
from cmdb.framework.importer.messages.import_failed_message import ImportFailedMessage
from cmdb.framework.importer.messages.import_success_message import ImportSuccessMessage
from cmdb.framework.importer.parser.base_object_parser import BaseObjectParser
from cmdb.framework.importer.responses.object_parser_response import ObjectParserResponse
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper import (
    handle_sync_config_item_count,
)

from cmdb.errors.manager.objects_manager import (
    ObjectsManagerDeleteError,
    ObjectsManagerInsertError,
    ObjectsManagerGetError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                ObjectImporter - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class ObjectImporter(BaseImporter):
    """Superclass for object importers"""

    def __init__(self,
                 file,
                 file_type,
                 config: ObjectImporterConfig | None = None,
                 parser: BaseObjectParser | None = None,
                 objects_manager: ObjectsManager | None = None,
                 request_user: CmdbUser | None = None) -> None:
        """
        Basic importer super class for object imports
        Normally should be started by start_import
        Args:
            file: File instance, name, content or loaded path to file
            file_type: file type - used with content-type
            config: importer configuration
            parser: the parser instance based on content-type
            objects_manager: manager used to read/insert/delete CmdbObjects
            request_user: the instance of the started user
        """
        self.parser: BaseObjectParser | None = parser
        self.objects_manager: ObjectsManager | None = objects_manager
        self.request_user: CmdbUser | None = request_user

        super().__init__(file=file, file_type=file_type, config=config)


    def _generate_objects(self, parsed: ObjectParserResponse, *args, **kwargs) -> list[tuple[dict, dict]]:
        """
        Generates ``(provided_data, generated_object)`` candidates from the parser response

        For each entry it snapshots what the user provided (via ``_to_provided_json``, captured before
        ``generate_object`` may coerce the entry) and the object to import. The provided snapshot is
        carried through so a rejected/failed object can be reported back exactly as submitted.

        Args:
            parsed (ObjectParserResponse): The parser response holding the raw entries

        Returns:
            list[tuple[dict, dict]]: One (provided_data, generated_object) pair per parsed entry
        """
        candidates: list[tuple[dict, dict]] = []

        for entry in parsed.entries:
            provided = self._to_provided_json(entry, **kwargs)
            generated = self.generate_object(entry, *args, **kwargs)
            candidates.append((provided, generated))

        return candidates


    def _to_provided_json(self, entry: dict, **kwargs) -> dict:  # pylint: disable=unused-argument
        """
        Returns the entry as the user provided it, for the failure report

        The default is a deep copy of the parsed entry (correct for JSON, whose entry is already the
        provided object). Formats whose entry is not a user-facing object (e.g. CSV's index-keyed row)
        override this to reconstruct the provided object.

        Args:
            entry (dict): The parsed entry

        Returns:
            dict: The provided object snapshot
        """
        return copy.deepcopy(entry)


    def generate_object(self, entry: dict, *args, **kwargs) -> dict:
        """
        Generates a single CmdbObject dict from one parsed entry (implemented by the subclass)

        Args:
            entry (dict): A single parsed entry from the parser response

        Raises:
            NotImplementedError: This method must be implemented in a subclass

        Returns:
            dict: The generated object dict ready for import
        """
        raise NotImplementedError


    def _import(
            self,
            candidates: list[tuple[dict, dict]],
            special_type: SpecialType | None) -> ImporterObjectResponse:
        """
        Normalizes, validates and imports the candidate objects, recording per-object success/failure

        Iterates from ``start_element`` for at most ``max_elements`` candidates (0 = no limit). Each
        object is normalized + validated (rejects go straight to the report), then inserted
        (overwriting an existing object of the same public_id when ``overwrite_public`` is set). An
        object that already has a public_id while overwrite is disabled, or any object whose write
        fails, is reported as failed (with the data the user provided). In cloud mode the ConfigItem
        count is reported once after the batch, only if anything was written.

        Args:
            candidates (list[tuple[dict, dict]]): (provided_data, generated_object) pairs to import
            special_type (SpecialType | None): The target type's special type, assigned to each object

        Returns:
            ImporterObjectResponse: The success and failure messages for the batch
        """
        run_config = self.get_config()

        success_imports: list[ImportSuccessMessage] = []
        failed_imports: list[ImportFailedMessage] = []
        # Whether any object was written, so the ConfigItem count is synced once at the end
        # (cloud mode) only when the batch actually changed the total
        did_write: bool = False

        # ``offset`` is relative to start_element, so it doubles as the count of processed objects
        for offset, (provided, current_import_object) in enumerate(candidates[run_config.start_element:]):
            if run_config.max_elements > 0 and offset >= run_config.max_elements:
                break

            # Normalize the server-owned fields and validate; a rejected object is reported and skipped
            errors = normalize_and_validate_object(current_import_object, special_type)
            if errors:
                failed_imports.append(ImportFailedMessage(failed_object=provided, errors=errors))
                continue

            current_public_id = current_import_object.get(CmdbObjectKey.PUBLIC_ID.value)

            # Object already has a public_id but overwriting is disabled -> reject
            if current_public_id is not None and not run_config.overwrite_public:
                failed_imports.append(ImportFailedMessage(
                    failed_object=provided,
                    errors=['Object has a public_id but overwriting is disabled'],
                ))
                continue

            try:
                imported_public_id = self._import_single_object(current_import_object)
            except (ObjectsManagerGetError, ObjectsManagerDeleteError, ObjectsManagerInsertError) as err:
                LOGGER.error("[_import] Could not import object: %s", err, exc_info=True)
                failed_imports.append(ImportFailedMessage(failed_object=provided, errors=[str(err)]))
            else:
                did_write = True
                success_imports.append(ImportSuccessMessage(
                    public_id=imported_public_id,
                    obj=current_import_object,
                ))

        # Sync the ConfigItem count to the Service Portal ONCE after the whole batch (cloud mode),
        # not per object - the count is a full recount so a single report reflects every change
        if current_app.cloud_mode and did_write:
            self._sync_config_item_count()

        return ImporterObjectResponse(
            message=f'Import of {len(success_imports)} objects',
            success_imports=success_imports,
            failed_imports=failed_imports,
        )


    def _import_single_object(self, current_import_object: dict) -> int:
        """
        Inserts a single (already normalized/validated) object, replacing an existing one of the same id

        A public_id that already exists is overwritten (the old object is deleted first); an object
        without a public_id is assigned a fresh one. In cloud mode the ConfigItem limit is enforced
        before the insert. The lifecycle fields (creation_time, last_edit_time, ...) are already set
        by the normalization step, so this method does not touch them.

        Args:
            current_import_object (dict): The object to insert

        Raises:
            ObjectsManagerGetError: If the existing-object lookup fails
            ObjectsManagerDeleteError: If deleting the object being overwritten fails
            ObjectsManagerInsertError: If the insert fails or the ConfigItem limit is reached

        Returns:
            int: The public_id the object was imported under
        """
        public_id = current_import_object.get(CmdbObjectKey.PUBLIC_ID.value)
        existing = self.objects_manager.get_object(public_id) if public_id else None

        if existing:
            #TODO: The public_id of the object also needs to be deleted from all static ObjectGroups
            self.objects_manager.delete_with_follow_up(public_id, self.request_user)
        elif not public_id:
            # New object without an id -> assign a fresh public_id
            public_id = self.objects_manager.get_new_object_public_id()
            current_import_object[CmdbObjectKey.PUBLIC_ID.value] = public_id

        if current_app.cloud_mode and self.check_config_item_limit_reached(self.request_user):
            raise ObjectsManagerInsertError("Config item limit reached!")

        self.objects_manager.insert_object(current_import_object)

        return public_id


    def start_import(self) -> ImporterObjectResponse:
        """Starting the import process.
        Should call the _import method"""
        raise NotImplementedError


    def _sync_config_item_count(self) -> None:
        """
        Reports the current CmdbObject count to the DataGerry Service Portal once (cloud mode)

        Called a single time after the whole import batch (not per object): the reported count is a
        full recount, so one report reflects every insert/delete in the run. Best-effort - a portal
        or transport failure is logged and swallowed so it never fails the import
        """
        try:
            handle_sync_config_item_count(self.request_user, self.objects_manager.count_documents())
        except Exception as error:
            LOGGER.error("Could not sync config items count to service portal. Error: %s", error)


    def check_config_item_limit_reached(self, request_user: CmdbUser) -> bool:
        """
        Checks if the ConfigItem Limit of the User has been reached

        Args:
            request_user (CmdbUser): User requesting this operation

        Returns:
            bool: True if the limit has been reached, else False
        """
        objects_count: int = self.objects_manager.count_documents()

        return objects_count >= request_user.config_items_limit
