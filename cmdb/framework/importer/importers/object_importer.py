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
from datetime import datetime, timezone
from logging import Logger, getLogger

from flask import current_app

from cmdb.manager import ObjectsManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.framework.importer.importers.base_importer import BaseImporter
from cmdb.framework.importer.configs.object_importer_config import ObjectImporterConfig
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


    def _generate_objects(self, parsed: ObjectParserResponse, *args, **kwargs) -> list[dict]:
        """
        Generates the object dicts from the parser response

        Delegates the per-entry generation to ``generate_object`` (implemented by the subclass);
        any extra positional/keyword arguments (e.g. the target type's ``fields``) are forwarded

        Args:
            parsed (ObjectParserResponse): The parser response holding the raw entries

        Returns:
            list[dict]: One generated object dict per parsed entry
        """
        object_instance_list: list[dict] = []

        for entry in parsed.entries:
            object_instance_list.append(self.generate_object(entry, *args, **kwargs))

        return object_instance_list


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


    def _import(self, import_objects: list) -> ImporterObjectResponse:
        """
        Imports the generated objects, recording per-object success/failure

        Iterates from ``start_element`` for at most ``max_elements`` objects (0 = no limit). Each
        object is inserted (overwriting an existing object of the same public_id when
        ``overwrite_public`` is set); an object that already has a public_id while overwrite is
        disabled, or any object whose write fails, is recorded as a failed import. In cloud mode the
        ConfigItem count is reported once after the batch, only if anything was written

        Args:
            import_objects (list): The generated objects to import (output of ``_generate_objects``)

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
        for offset, current_import_object in enumerate(import_objects[run_config.start_element:]):
            if run_config.max_elements > 0 and offset >= run_config.max_elements:
                break

            current_public_id = current_import_object.get(CmdbObjectKey.PUBLIC_ID.value)

            # Object already has a public_id but overwriting is disabled -> reject
            if current_public_id is not None and not run_config.overwrite_public:
                failed_imports.append(ImportFailedMessage(
                    error_message='Object import for object - has PublicID but not overwrite setting',
                    obj=current_import_object,
                ))
                continue

            try:
                imported_public_id = self._import_single_object(current_import_object)
            except (ObjectsManagerGetError, ObjectsManagerDeleteError, ObjectsManagerInsertError) as err:
                LOGGER.error("[_import] Could not import object: %s", err, exc_info=True)
                failed_imports.append(ImportFailedMessage(error_message=err, obj=current_import_object))
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
        Inserts a single object, replacing an existing object with the same public_id

        A public_id that already exists is overwritten (its creation time is preserved and the old
        object deleted first); an object without a public_id is assigned a fresh one. In cloud mode
        the ConfigItem limit is enforced before the insert. The object dict is mutated in place with
        its resolved public_id / creation_time / last_edit_time

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
            # Overwrite: preserve the original creation time, then remove the old object before re-insert
            current_import_object[CmdbObjectKey.CREATION_TIME.value] = existing[CmdbObjectKey.CREATION_TIME.value]
            #TODO: The public_id of the object also needs to be deleted from all static ObjectGroups
            self.objects_manager.delete_with_follow_up(public_id, self.request_user)
        elif not public_id:
            # New object without an id -> assign a fresh public_id
            public_id = self.objects_manager.get_new_object_public_id()
            current_import_object[CmdbObjectKey.PUBLIC_ID.value] = public_id

        current_import_object[CmdbObjectKey.LAST_EDIT_TIME.value] = datetime.now(timezone.utc)

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
