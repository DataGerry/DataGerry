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
from itertools import batched
from logging import Logger, getLogger
from typing import Any

from flask import current_app

from cmdb.manager import ObjectsManager
from cmdb.manager.types_manager import TypesManager
from cmdb.manager.section_templates_manager import SectionTemplatesManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_model.cmdb_object_key_enum import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.object_model.object_constants import ObjectWriteVerb
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.framework.importer.importers.base_importer import BaseImporter
from cmdb.framework.ipam.reference_disclosure import HiddenTypeIds, hidden_types_of
from cmdb.framework.person_selector.selector_write_rule import SelectorRefusal, check_person_selector_values
from cmdb.framework.importer.configs.object_importer_config import ObjectImporterConfig
from cmdb.framework.importer.importer_constants import (
    UNEXPECTED_OBJECT_IMPORT_ERROR,
    OBJECT_INSERTED_COUNT_DELTA,
    OBJECT_NOT_INSERTED_COUNT_DELTA,
    CONFIG_ITEM_LIMIT_REACHED_MESSAGE,
    IMPORT_INSERT_CHUNK_SIZE,
)
from cmdb.framework.importer.helper.object_import_writer import (
    insert_new_objects,
    plan_overwrite,
    replace_stored_object,
)
from cmdb.framework.importer.helper.object_import_validator import (
    normalize_and_validate_object,
    build_import_type_context,
    apply_new_select_options,
    ImportTypeContext,
)
from cmdb.framework.section_templates import resolve_predefined_select_fields
from cmdb.framework.importer.responses.importer_object_response import ImporterObjectResponse
from cmdb.framework.importer.responses.import_report_response import build_import_summary_message
from cmdb.framework.importer.messages.import_failed_message import ImportFailedMessage
from cmdb.framework.importer.messages.import_success_message import ImportSuccessMessage
from cmdb.framework.importer.parser.base_object_parser import BaseObjectParser
from cmdb.framework.importer.responses.object_parser_response import ObjectParserResponse
from cmdb.framework.config_item_sync import handle_sync_config_item_count
from cmdb.database.mongo_error_helper import is_public_id_duplicate

from cmdb.errors.database import DocumentInsertError, DocumentLockTimeoutError, DocumentNetworkError
from cmdb.errors.manager import BaseManagerGetError, BaseManagerInsertError
from cmdb.errors.security import AccessDeniedError
from cmdb.errors.manager.objects_manager import (
    ObjectsManagerInsertError,
    ObjectsManagerGetError,
    ObjectsManagerGetTypeError,
    ObjectsManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

#: One row's outcome: exactly one side is set once the row was handled
ImportOutcome = tuple[ImportSuccessMessage | None, ImportFailedMessage | None]

#: A write refusal the import expects and reports as its own message - the object, its type or the database said no
#: A lost connection or a lock timeout is one of them: the database's answer, reported as it is, not as a bug
ANTICIPATED_WRITE_ERRORS: tuple[type[Exception], ...] = (
    AccessDeniedError,
    BaseManagerGetError,
    BaseManagerInsertError,
    DocumentInsertError,
    DocumentLockTimeoutError,
    DocumentNetworkError,
    ObjectsManagerGetError,
    ObjectsManagerGetTypeError,
    ObjectsManagerInsertError,
    ObjectsManagerUpdateError,
)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                ObjectImporter - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class ObjectImporter(BaseImporter):
    """Superclass for object importers"""

    def __init__(self,
                 file: Any,
                 file_type: str,
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
        # The CmdbType the import writes into. The route resolves and authorises it before the
        # importer is built and assigns it here, so the import does not read it a second time;
        # `resolve_target_type` falls back to reading it for any other caller
        self.target_type: CmdbType | None = None
        # The importer's denied Types, read once - when a person selector's ids are first judged
        self.hidden_types: HiddenTypeIds | None = None
        # How many CmdbObjects are stored, counted once when the ConfigItem limit is first checked
        # (cloud mode) and then kept current by this import's own deletes and inserts - see
        # `_stored_object_count`. None until that first check
        self._object_count: int | None = None
        # The types other than the target type this import read, by public_id - see `_known_type`
        self._types: dict[Any, CmdbType | None] = {}

        super().__init__(file=file, file_type=file_type, config=config)


    def _generate_objects(
            self,
            parsed: ObjectParserResponse,
            *args: Any,
            **kwargs: Any) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """
        Generates ``(provided_data, generated_object)`` candidates from the parser response

        For each entry it snapshots what the user provided (via ``_to_provided_json``, captured before
        ``generate_object`` may coerce the entry) and the object to import. The provided snapshot is
        carried through so a rejected/failed object can be reported back exactly as submitted.

        Args:
            parsed (ObjectParserResponse): The parser response holding the raw entries

        Returns:
            list[tuple[dict[str, Any], dict[str, Any]]]: One (provided_data, generated_object) pair per parsed entry
        """
        candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []

        for entry in parsed.entries:
            provided = self._to_provided_json(entry, **kwargs)
            generated = self.generate_object(entry, *args, **kwargs)
            candidates.append((provided, generated))

        return candidates


    def _to_provided_json(  # pylint: disable=unused-argument
            self,
            entry: dict[str, Any],
            **kwargs: Any) -> dict[str, Any]:
        """
        Returns the entry as the user provided it, for the failure report

        The default is a deep copy of the parsed entry (correct for JSON, whose entry is already the
        provided object). Formats whose entry is not a user-facing object (e.g. CSV's index-keyed row)
        override this to reconstruct the provided object.

        Args:
            entry (dict[str, Any]): The parsed entry

        Returns:
            dict[str, Any]: The provided object snapshot
        """
        return copy.deepcopy(entry)


    def generate_object(self, entry: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
        """
        Generates a single CmdbObject dict from one parsed entry (implemented by the subclass)

        Args:
            entry (dict[str, Any]): A single parsed entry from the parser response

        Raises:
            NotImplementedError: This method must be implemented in a subclass

        Returns:
            dict[str, Any]: The generated object dict ready for import
        """
        raise NotImplementedError


    def _import_for_type(
            self,
            candidates: list[tuple[dict[str, Any], dict[str, Any]]],
            type_instance: CmdbType) -> ImporterObjectResponse:
        """
        Imports the candidates against the target type, deriving the normalization inputs from it

        Shared by the JSON and CSV importers: builds the ``ImportTypeContext`` once, imports the batch,
        then persists to the type any select options that unknown imported values introduced. Select
        fields owned by a predefined section template are excluded from that behaviour - an unknown
        value for one of them rejects the object instead (see ``_resolve_predefined_select_fields``).

        Args:
            candidates (list[tuple[dict[str, Any], dict[str, Any]]]): (provided_data, generated_object) pairs to
                import
            type_instance (CmdbType): The target ``CmdbType`` being imported into

        Returns:
            ImporterObjectResponse: The success and failure messages for the batch
        """
        type_context = build_import_type_context(
            type_instance,
            predefined_select_fields=self._resolve_predefined_select_fields(type_instance),
        )
        response = self._import(candidates, type_instance.special_type, type_context)

        # Unknown select values seen during the import become new options on the type (persist once)
        if type_context.new_select_options:
            self._persist_new_select_options(type_instance, type_context.new_select_options)

        return response


    def _resolve_predefined_select_fields(self, type_instance: CmdbType) -> dict[str, str]:
        """
        Determines which of the target type's select fields a predefined section template owns

        Those field definitions are immutable, so the import must not extend their options - it rejects
        an unknown value for them instead. Costs no database read for a type that uses no global
        section template at all

        Args:
            type_instance (CmdbType): The target CmdbType being imported into

        Returns:
            dict[str, str]: {select field name: name of the predefined template owning it}
        """
        section_templates_manager = SectionTemplatesManager(
            self.objects_manager.dbm,
            self.objects_manager.db_name,
        )

        return resolve_predefined_select_fields(type_instance, section_templates_manager)


    def _persist_new_select_options(
            self,
            type_instance: CmdbType,
            new_select_options: dict[str, list[Any]]) -> None:
        """
        Adds the import's newly-seen select values as options on the type and saves it

        Args:
            type_instance (CmdbType): The target ``CmdbType`` (its select fields' options are extended)
            new_select_options (dict[str, list[Any]]): ``{field name: [added option values]}`` from the import
        """
        apply_new_select_options(type_instance, new_select_options)

        types_manager = TypesManager(self.objects_manager.dbm, self.objects_manager.db_name)
        types_manager.update_type(type_instance.public_id, type_instance)


    def resolve_target_type(self) -> CmdbType:
        """
        Returns the CmdbType this import writes into

        The route hands the already resolved (and access-checked) type over in ``target_type``; only
        a caller that built the importer itself pays for the read

        Returns:
            CmdbType: The target type of this import
        """
        if self.target_type is not None:
            return self.target_type

        self.target_type = self.objects_manager.get_object_type(self.get_config().get_type_id())

        return self.target_type


    def _import(
            self,
            candidates: list[tuple[dict[str, Any], dict[str, Any]]],
            special_type: SpecialType | None,
            type_context: ImportTypeContext | None = None) -> ImporterObjectResponse:
        """
        Normalizes, validates and imports the candidate objects, recording per-object success/failure

        Iterates from ``start_element`` for at most ``max_elements`` candidates (0 = no limit), in three steps:

        1. every object is normalized + validated; a rejection goes straight to the report
        2. the objects that carry a public_id are written one at a time, in file order - an existing object of
           that id is overwritten in place when ``overwrite_public`` is set (the stored objects are read with
           one query for all of them). They go first, so the counter is raised past their ids before step 3
           reserves any
        3. the new objects are written in chunks of ``IMPORT_INSERT_CHUNK_SIZE``: one id reservation and one
           unordered insert per chunk, each object's refusal reported as its own

        The report keeps the file order. In cloud mode the ConfigItem limit is checked per object that adds one
        as it is written - step 2 before step 3; an overwrite adds none and is not checked - and the count is
        reported once after the batch, only if anything was written

        Args:
            candidates (list[tuple[dict[str, Any], dict[str, Any]]]): (provided_data, generated_object) pairs to
                import
            special_type (SpecialType | None): The target type's special type, assigned to each object
            type_context (ImportTypeContext | None): The target type's derived inputs (type-stamping,
                                                     required-field and reference-clearing sets); None
                                                     skips those type-driven steps

        Returns:
            ImporterObjectResponse: The success and failure messages for the batch
        """
        run_config = self.get_config()
        selected: list[tuple[dict[str, Any], dict[str, Any]]] = candidates[run_config.start_element:]

        if run_config.max_elements > 0:
            selected = selected[:run_config.max_elements]

        outcomes: list[ImportOutcome] = [(None, None)] * len(selected)
        provided_names: dict[int, set[str | None]] = self._prepare_candidates(
            selected, special_type, type_context, outcomes,
        )
        with_id: list[int] = [row for row in provided_names
                              if selected[row][1].get(CmdbObjectKey.PUBLIC_ID.value) is not None]

        self._write_rows_with_id(selected, with_id, provided_names, outcomes)
        self._insert_new_rows(selected, [row for row in provided_names if row not in set(with_id)], outcomes)

        success_imports: list[ImportSuccessMessage] = [success for success, _ in outcomes if success is not None]
        failed_imports: list[ImportFailedMessage] = [failure for _, failure in outcomes if failure is not None]

        # The ConfigItem count is reported ONCE after the whole batch, not per object - it is a full recount, so a
        # single report reflects every change; hosted cloud only, and best-effort, so it never fails the import
        if success_imports:
            handle_sync_config_item_count(self.request_user)

        return ImporterObjectResponse(
            message=build_import_summary_message(len(success_imports), len(failed_imports)),
            success_imports=success_imports,
            failed_imports=failed_imports,
        )


    def _prepare_candidates(
            self,
            selected: list[tuple[dict[str, Any], dict[str, Any]]],
            special_type: SpecialType | None,
            type_context: ImportTypeContext | None,
            outcomes: list[ImportOutcome]) -> dict[int, set[str | None]]:
        """
        Normalizes and validates every selected candidate, recording each rejection in ``outcomes``

        A candidate that fails with an error nobody anticipated is rejected on its own - the report is per
        object, so one object's defect never discards the objects around it

        Args:
            selected (list[tuple[dict[str, Any], dict[str, Any]]]): The (provided, generated) pairs to import
            special_type (SpecialType | None): The target type's special type
            type_context (ImportTypeContext | None): The target type's derived inputs (see ``ImportTypeContext``)
            outcomes (list[ImportOutcome]): The per-row outcomes, filled in for every rejected row

        Returns:
            dict[int, set[str | None]]: For every row ready to be written, in file order, the field names the
                file provided (the overwrite check compares them against an existing object's type)
        """
        ready: dict[int, set[str | None]] = {}

        for row, (provided, current_import_object) in enumerate(selected):
            try:
                failure, field_names = self._prepare_candidate(
                    provided, current_import_object, special_type, type_context,
                )
            except Exception as err:
                LOGGER.error("[_import] Unexpected error while importing object: %s", err, exc_info=True)
                failure, field_names = _unexpected_failure(provided, err), set()

            if failure is not None:
                outcomes[row] = (None, failure)
            else:
                ready[row] = field_names

        return ready


    def _prepare_candidate(
            self,
            provided: dict[str, Any],
            current_import_object: dict[str, Any],
            special_type: SpecialType | None,
            type_context: ImportTypeContext | None) -> tuple[ImportFailedMessage | None, set[str | None]]:
        """
        Normalizes and validates one candidate and settles what its public_id means

        With ``overwrite_public`` off a provided public_id is dropped, so the object is imported as a brand-new
        object; with it on the id is kept, and step 2 of ``_import`` decides whether it overwrites

        Args:
            provided (dict[str, Any]): The data the user submitted (reported on failure)
            current_import_object (dict[str, Any]): The generated object to normalize, changed in place
            special_type (SpecialType | None): The target type's special type
            type_context (ImportTypeContext | None): The target type's derived inputs (see ``ImportTypeContext``)

        Returns:
            tuple[ImportFailedMessage | None, set[str | None]]: The rejection (None when the object is ready),
                and the field names the file provided
        """
        # Captured BEFORE normalization backfills the rest - the overwrite-compatibility check compares these
        # against the existing object's type
        provided_field_names = self._provided_field_names(current_import_object)

        errors = normalize_and_validate_object(
            current_import_object, special_type, self.request_user.get_public_id(), type_context,
        )

        if not errors and (selector_refusal := self._person_selector_refusal(current_import_object, type_context)):
            errors = [selector_refusal]

        if errors:
            return ImportFailedMessage(failed_object=provided, errors=errors), provided_field_names

        if not self.get_config().overwrite_public:
            current_import_object.pop(CmdbObjectKey.PUBLIC_ID.value, None)

        return None, provided_field_names


    def _person_selector_refusal(self, candidate: dict[str, Any], type_context: ImportTypeContext | None) -> str | None:
        """
        Judges the imported object's person selector ids like the REST write does

        Every id is judged - an import states the whole value, so nothing is introduced by comparison and nothing the
        importer cannot see is kept: an id must name an existing object of a selectable kind the importer may read

        Args:
            candidate (dict[str, Any]): The normalized object (its selector values canonicalised in place)
            type_context (ImportTypeContext | None): The target type's derived inputs

        Raises:
            BaseManagerGetError: When a read fails

        Returns:
            str | None: Why the object is refused, or None
        """
        if type_context is None or not type_context.person_selectors:
            return None

        if self.hidden_types is None:
            self.hidden_types = hidden_types_of(self.request_user)

        refusal: SelectorRefusal | None = check_person_selector_values(
            self.objects_manager, TypesManager(self.objects_manager.dbm, self.objects_manager.db_name),
            self.hidden_types, candidate, list(type_context.person_selectors.values()),
        )

        return refusal.message if refusal else None


    @staticmethod
    def _provided_field_names(current_import_object: dict[str, Any]) -> set[str | None]:
        """
        Collects the field names the import provided (top-level + inside MDS rows)

        Must be called before normalization backfills the type's remaining fields, so the result
        reflects only what the file actually carried.

        Args:
            current_import_object (dict[str, Any]): The generated object (pre-backfill)

        Returns:
            set[str | None]: The provided field names (None for an entry without a name)
        """
        names = {
            field.get(CmdbObjectFieldKey.NAME.value)
            for field in current_import_object.get(CmdbObjectKey.FIELDS.value) or []
        }

        for section in current_import_object.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value) or []:
            for row in section.get(CmdbObjectMdsKey.VALUES.value) or []:
                names.update(
                    entry.get(CmdbObjectFieldKey.NAME.value)
                    for entry in row.get(CmdbObjectMdsRowKey.DATA.value) or []
                )

        return names


    def _write_rows_with_id(
            self,
            selected: list[tuple[dict[str, Any], dict[str, Any]]],
            rows: list[int],
            provided_names: dict[int, set[str | None]],
            outcomes: list[ImportOutcome]) -> None:
        """
        Writes the rows that carry a public_id one at a time, in file order, recording each outcome

        The objects stored under those ids are read with one query for all rows. A row written under an id
        becomes the stored object for a later row of the same id, so a file that names an id twice overwrites
        its own first row, as when the rows were written one by one

        Args:
            selected (list[tuple[dict[str, Any], dict[str, Any]]]): The (provided, generated) pairs
            rows (list[int]): The rows to write, in file order
            provided_names (dict[int, set[str | None]]): The field names each row's file entry provided
            outcomes (list[ImportOutcome]): The per-row outcomes, filled in for every row
        """
        if not rows:
            return

        public_ids: list[int] = [selected[row][1][CmdbObjectKey.PUBLIC_ID.value] for row in rows]

        try:
            stored: dict[int, dict[str, Any]] = {
                document[CmdbObjectKey.PUBLIC_ID.value]: document
                for document in self.objects_manager.find_objects(
                    {CmdbObjectKey.PUBLIC_ID.value: {'$in': public_ids}}, as_dict=True,
                )
            }
        except ObjectsManagerGetError as err:
            LOGGER.error("[_import] Could not read the objects the import overwrites: %s", err, exc_info=True)
            for row in rows:
                outcomes[row] = (None, ImportFailedMessage(failed_object=selected[row][0], errors=[str(err)]))
            return

        for row in rows:
            provided, current_import_object = selected[row]

            try:
                outcomes[row] = self._write_row_with_id(provided, current_import_object, provided_names[row], stored)
            except Exception as err:
                LOGGER.error("[_import] Unexpected error while importing object: %s", err, exc_info=True)
                outcomes[row] = (None, _unexpected_failure(provided, err))


    def _write_row_with_id(
            self,
            provided: dict[str, Any],
            current_import_object: dict[str, Any],
            provided_field_names: set[str | None],
            stored: dict[int, dict[str, Any]]) -> ImportOutcome:
        """
        Writes one object under the public_id it carries, replacing the object stored there

        An existing object is overwritten in place (``_overwrite_row``), with one atomic replace, so a failed
        write leaves it as it was. An overwrite adds no object, so the cloud ConfigItem limit is not asked. An
        unused id - or one whose object was deleted after the import read it - is imported as a new object under
        that id, which needs a free slot under the limit in cloud mode and raises the counter

        Args:
            provided (dict[str, Any]): The data the user submitted (reported on failure)
            current_import_object (dict[str, Any]): The normalized object, carrying its public_id
            provided_field_names (set[str | None]): The field names the file provided
            stored (dict[int, dict[str, Any]]): The stored objects by public_id; updated with this row's write

        Returns:
            ImportOutcome: The row's success or failure
        """
        public_id: int = current_import_object[CmdbObjectKey.PUBLIC_ID.value]
        existing: dict[str, Any] | None = stored.get(public_id)

        try:
            if existing:
                outcome: ImportOutcome | None = self._overwrite_row(
                    provided, current_import_object, provided_field_names, existing, stored,
                )

                if outcome is not None:
                    return outcome

            if current_app.cloud_mode and self.check_config_item_limit_reached(self.request_user):
                raise ObjectsManagerInsertError(CONFIG_ITEM_LIMIT_REACHED_MESSAGE)

            imported_public_id: int = self.objects_manager.insert_object(
                current_import_object,
                object_type=self._known_type(current_import_object.get(CmdbObjectKey.TYPE_ID.value)),
            )
            self._track_object_count_change(OBJECT_INSERTED_COUNT_DELTA)
        except ANTICIPATED_WRITE_ERRORS as err:
            LOGGER.error("[_import] Could not import object: %s", err, exc_info=True)
            return None, _write_failure(provided, err)

        stored[imported_public_id] = current_import_object

        return ImportSuccessMessage(public_id=imported_public_id, obj=current_import_object), None


    def _overwrite_row(
            self,
            provided: dict[str, Any],
            current_import_object: dict[str, Any],
            provided_field_names: set[str | None],
            existing: dict[str, Any],
            stored: dict[int, dict[str, Any]]) -> ImportOutcome | None:
        """
        Overwrites the stored object of the row's public_id with one atomic replace

        The existing object's type must define every provided field and be active, and so must the type the row
        is written as. The replacement is an edit of the stored object (``plan_overwrite``): its author and
        creation time are kept, the importer is its editor and its version is bumped by what changed; the
        success carries the diff, so the route logs it as an EDIT. Nothing is deleted - the object's risk
        assessments, group memberships, relations and attachments still point at it

        Args:
            provided (dict[str, Any]): The data the user submitted (reported on failure)
            current_import_object (dict[str, Any]): The normalized object, carrying its public_id
            provided_field_names (set[str | None]): The field names the file provided
            existing (dict[str, Any]): The stored object of that public_id, as the import read it
            stored (dict[int, dict[str, Any]]): The stored objects by public_id; updated with the written object

        Raises:
            AccessDeniedError: If either type is deactivated
            ObjectsManagerGetTypeError: If a type could not be read
            ObjectsManagerUpdateError: If a type is gone, the model cannot hold an object or the write was refused
            DocumentLockTimeoutError / DocumentNetworkError: A transient failure of the write

        Returns:
            ImportOutcome | None: The row's outcome; None when the object was deleted after the import read it,
                so the row is to be imported under its id as a new object
        """
        public_id: int = current_import_object[CmdbObjectKey.PUBLIC_ID.value]
        existing_type_id: Any = existing.get(CmdbObjectKey.TYPE_ID.value)
        existing_type: CmdbType | None = self._known_type(existing_type_id)
        error: str | None = self._check_overwrite_compatibility(
            public_id, existing_type_id, existing_type, provided_field_names,
        )

        if error:
            return None, ImportFailedMessage(failed_object=provided, errors=[error])

        target_type_id: Any = current_import_object.get(CmdbObjectKey.TYPE_ID.value)

        # Each type once, the stored object's first - the row may change the object's type
        for type_id in dict.fromkeys((existing_type_id, target_type_id)):
            self.objects_manager.guard_writable_type(
                type_id, None, None, ObjectsManagerUpdateError, ObjectWriteVerb.UPDATED.value,
                self._known_type(type_id),
            )

        replacement, changes = plan_overwrite(existing, current_import_object, self.request_user)

        if not replace_stored_object(self.objects_manager, replacement):
            return None

        stored[public_id] = replacement

        return ImportSuccessMessage(public_id=public_id, obj=replacement, changes=changes), None


    def _known_type(self, type_id: Any) -> CmdbType | None:
        """
        Answers a CmdbType by its public_id, reading each type at most once per import

        The target type is known from the start; any other type - one an overwritten object belongs to - is
        read the first time it is asked for and kept, also when it does not exist

        Args:
            type_id (Any): public_id of the type

        Raises:
            ObjectsManagerGetTypeError: If the type could not be read

        Returns:
            CmdbType | None: The type, or None when no type has the id
        """
        if self.target_type is not None and self.target_type.public_id == type_id:
            return self.target_type

        if type_id not in self._types:
            self._types[type_id] = self.objects_manager.get_object_type(type_id)

        return self._types[type_id]


    @staticmethod
    def _check_overwrite_compatibility(
            public_id: int,
            existing_type_id: Any,
            existing_type: CmdbType | None,
            provided_field_names: set[str | None]) -> str | None:
        """
        Checks that the object being overwritten can hold the imported object's fields

        The public_id may belong to an object of another type on the target system. Overwriting is only
        allowed when that existing object's type defines every field the import provides; otherwise the
        object is rejected. The same goes for an existing object whose type cannot be resolved at all:
        without the type there is nothing to check the fields against, so the overwrite is refused
        instead of silently writing fields the type may not define.

        Args:
            public_id (int): The public_id the imported object carries
            existing_type_id (Any): The type_id of the stored object living at that public_id
            existing_type (CmdbType | None): That type, None when it does not exist
            provided_field_names (set[str | None]): The field names the file provided

        Returns:
            str | None: An error message when incompatible, otherwise None
        """
        if not existing_type:
            return (f"Cannot overwrite object {public_id}: its type "
                    f"(ID:{existing_type_id}) does not exist")

        supported_fields = {field.get(FieldKey.NAME.value) for field in existing_type.get_fields()}
        unsupported = provided_field_names - supported_fields

        if unsupported:
            return (f"Cannot overwrite object {public_id}: its type does not support "
                    f"field(s) {sorted(unsupported)}")

        return None


    def _insert_new_rows(
            self,
            selected: list[tuple[dict[str, Any], dict[str, Any]]],
            rows: list[int],
            outcomes: list[ImportOutcome]) -> None:
        """
        Writes the rows without a public_id in chunks, recording each outcome

        The target type is guarded once for all of them (it must exist and be active). In cloud mode the
        ConfigItem limit is applied in file order before anything is written: the rows past it are refused

        Args:
            selected (list[tuple[dict[str, Any], dict[str, Any]]]): The (provided, generated) pairs
            rows (list[int]): The rows to write, in file order
            outcomes (list[ImportOutcome]): The per-row outcomes, filled in for every row
        """
        if not rows:
            return

        # Every generated object carries the import's configured type, so the first row names it for all of them
        type_id: Any = selected[rows[0]][1].get(CmdbObjectKey.TYPE_ID.value)

        try:
            object_type: CmdbType = self.objects_manager.guard_writable_type(
                type_id, None, None, ObjectsManagerInsertError, ObjectWriteVerb.CREATED.value,
                self._known_type(type_id),
            )
        except Exception as err:
            LOGGER.error("[_import] The new objects cannot be written: %s", err, exc_info=True)
            for row in rows:
                outcomes[row] = (None, _write_failure(selected[row][0], err))
            return

        accepted: list[int] = self._rows_within_config_item_limit(selected, rows, outcomes)

        for chunk in batched(accepted, IMPORT_INSERT_CHUNK_SIZE):
            self._insert_chunk(selected, list(chunk), object_type, outcomes)


    def _rows_within_config_item_limit(
            self,
            selected: list[tuple[dict[str, Any], dict[str, Any]]],
            rows: list[int],
            outcomes: list[ImportOutcome]) -> list[int]:
        """
        Takes the rows the ConfigItem limit leaves room for, in file order, refusing the rest (cloud mode only)

        Each taken row is counted as written right away, so the next row is judged against it; a row whose
        insert then fails gives its place back afterwards

        Args:
            selected (list[tuple[dict[str, Any], dict[str, Any]]]): The (provided, generated) pairs
            rows (list[int]): The candidate rows, in file order
            outcomes (list[ImportOutcome]): The per-row outcomes, filled in for every refused row

        Returns:
            list[int]: The rows to write, in file order
        """
        accepted: list[int] = []

        for row in rows:
            if current_app.cloud_mode and self.check_config_item_limit_reached(self.request_user):
                outcomes[row] = (None, ImportFailedMessage(
                    failed_object=selected[row][0], errors=[CONFIG_ITEM_LIMIT_REACHED_MESSAGE],
                ))
                continue

            self._track_object_count_change(OBJECT_INSERTED_COUNT_DELTA)
            accepted.append(row)

        return accepted


    def _insert_chunk(
            self,
            selected: list[tuple[dict[str, Any], dict[str, Any]]],
            chunk: list[int],
            object_type: CmdbType,
            outcomes: list[ImportOutcome]) -> None:
        """
        Writes one chunk of new objects with one id reservation and one unordered insert

        Each object refused on its own is reported on its own; one refused for a public_id clash (a counter
        left below a stored id) is retried once on its own with a freshly drawn id. When the write fails as a
        whole, the objects that were stored nonetheless are read back and reported as imported

        Args:
            selected (list[tuple[dict[str, Any], dict[str, Any]]]): The (provided, generated) pairs
            chunk (list[int]): The rows of the chunk, in file order
            object_type (CmdbType): The guarded target type
            outcomes (list[ImportOutcome]): The per-row outcomes, filled in for every row of the chunk
        """
        documents: list[dict[str, Any]] = [selected[row][1] for row in chunk]

        try:
            failures: dict[int, Exception] = insert_new_objects(self.objects_manager, documents)
        except Exception as err:
            LOGGER.error("[_import] Could not import a chunk of %d objects: %s", len(chunk), err, exc_info=True)
            failures = self._failures_after_a_failed_chunk(documents, err)

        for position, row in enumerate(chunk):
            provided, current_import_object = selected[row]
            failure: Exception | None = failures.get(position)

            if failure is not None and is_public_id_duplicate(failure):
                outcomes[row] = self._retry_with_a_drawn_id(provided, current_import_object, object_type)
            elif failure is not None:
                self._track_object_count_change(OBJECT_NOT_INSERTED_COUNT_DELTA)
                outcomes[row] = (None, _write_failure(provided, failure))
            else:
                outcomes[row] = (ImportSuccessMessage(
                    public_id=current_import_object[CmdbObjectKey.PUBLIC_ID.value], obj=current_import_object,
                ), None)


    def _failures_after_a_failed_chunk(
            self, documents: list[dict[str, Any]], err: Exception) -> dict[int, Exception]:
        """
        Answers which objects of a chunk whose write failed as a whole were not stored

        The failure may have come after some objects were written, so the chunk's ids are read back once:
        a stored object counts as imported, every other one fails with the chunk's error. When the read fails
        too, every object is reported failed

        Args:
            documents (list[dict[str, Any]]): The chunk's objects, with their public_ids once they were reserved
            err (Exception): The error the write raised

        Returns:
            dict[int, Exception]: ``err`` for every object not stored, by its position in ``documents``
        """
        public_ids: list[Any] = [document.get(CmdbObjectKey.PUBLIC_ID.value) for document in documents]
        stored_ids: set[Any] = set()

        if any(public_id is not None for public_id in public_ids):
            try:
                stored_ids = {
                    document[CmdbObjectKey.PUBLIC_ID.value]
                    for document in self.objects_manager.find_objects(
                        {CmdbObjectKey.PUBLIC_ID.value: {'$in': public_ids}}, as_dict=True,
                        projection={CmdbObjectKey.PUBLIC_ID.value: 1},
                    )
                }
            except ObjectsManagerGetError as read_err:
                LOGGER.error("[_import] Could not read back the failed chunk: %s", read_err, exc_info=True)

        return {
            position: err for position, public_id in enumerate(public_ids)
            if public_id is None or public_id not in stored_ids
        }


    def _retry_with_a_drawn_id(
            self,
            provided: dict[str, Any],
            current_import_object: dict[str, Any],
            object_type: CmdbType) -> ImportOutcome:
        """
        Writes one object whose reserved id was taken, on its own, under a freshly drawn id

        The single insert keeps its own duplicate-key retry, so a drawn id that is taken as well is replaced again

        Args:
            provided (dict[str, Any]): The data the user submitted (reported on failure)
            current_import_object (dict[str, Any]): The object; its taken public_id is replaced
            object_type (CmdbType): The guarded target type

        Returns:
            ImportOutcome: The row's success or failure
        """
        try:
            current_import_object[CmdbObjectKey.PUBLIC_ID.value] = self.objects_manager.get_new_object_public_id()
            public_id: int = self.objects_manager.insert_object(
                current_import_object, id_from_counter=True, object_type=object_type,
            )
        except (ObjectsManagerGetError, ObjectsManagerInsertError) as err:
            LOGGER.error("[_import] Could not import object: %s", err, exc_info=True)
            self._track_object_count_change(OBJECT_NOT_INSERTED_COUNT_DELTA)
            return None, ImportFailedMessage(failed_object=provided, errors=[str(err)])

        current_import_object[CmdbObjectKey.PUBLIC_ID.value] = public_id

        return ImportSuccessMessage(public_id=public_id, obj=current_import_object), None


    def start_import(self) -> ImporterObjectResponse:
        """Starting the import process.
        Should call the _import method"""
        raise NotImplementedError


    def check_config_item_limit_reached(self, request_user: CmdbUser) -> bool:
        """
        Checks if the ConfigItem limit of the user has been reached

        Asks the same rule the object route asks (`CmdbUser.is_config_item_limit_reached`), so an
        import and a single create refuse at the same count. The count comes from
        `_stored_object_count`, which reads the database once per import rather than once per object

        Args:
            request_user (CmdbUser): User requesting this operation

        Returns:
            bool: True if the limit has been reached, else False
        """
        return request_user.is_config_item_limit_reached(self._stored_object_count())


    def _stored_object_count(self) -> int:
        """
        Answers how many CmdbObjects are stored, reading the database only the first time

        Later calls answer the first count as adjusted by `_track_object_count_change` for every
        insert this import made. Writes by other requests during the import are not seen,
        which is the same window the object route has between its count and its insert

        Returns:
            int: The number of stored CmdbObjects
        """
        if self._object_count is None:
            self._object_count = self.objects_manager.count_documents()

        return self._object_count


    def _track_object_count_change(self, delta: int) -> None:
        """
        Keeps the counted number of stored CmdbObjects in step with a write this import made

        Does nothing until something has counted - a later first count reads the database, which
        already includes the write

        Args:
            delta (int): OBJECT_INSERTED_COUNT_DELTA for an insert, OBJECT_NOT_INSERTED_COUNT_DELTA
                when an insert counted beforehand failed
        """
        if self._object_count is not None:
            self._object_count += delta


def _unexpected_failure(provided: dict[str, Any], err: Exception) -> ImportFailedMessage:
    """
    The report entry of an object whose import failed with an error the import did not anticipate

    Args:
        provided (dict[str, Any]): The data the user submitted
        err (Exception): The error

    Returns:
        ImportFailedMessage: The entry, naming the error
    """
    return ImportFailedMessage(failed_object=provided, errors=[UNEXPECTED_OBJECT_IMPORT_ERROR.format(detail=err)])


def _write_failure(provided: dict[str, Any], err: Exception) -> ImportFailedMessage:
    """
    The report entry of an object the write refused

    A refusal the import anticipates - the object, the type or the database said no - is reported as its own
    message; anything else as an unexpected error

    Args:
        provided (dict[str, Any]): The data the user submitted
        err (Exception): The refusal

    Returns:
        ImportFailedMessage: The entry
    """
    if isinstance(err, ANTICIPATED_WRITE_ERRORS):
        return ImportFailedMessage(failed_object=provided, errors=[str(err)])

    return _unexpected_failure(provided, err)
