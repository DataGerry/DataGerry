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
Unit tests for cmdb.interface.rest_api.routes.importer_routes.importer_type_helper

Covers parse_uploaded_types (decodes the multipart upload, aborts 400 when it is missing), the
resolve_error_key fallback for entries without a usable public_id, and the per-entry create/update
steps, which report a message instead of raising so the rest of the batch keeps running. The manager
is stubbed throughout - no database is involved.
"""
import json
from types import SimpleNamespace
from typing import Any

import pytest
from flask import Flask, request
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.importer_routes.importer_type_constants import TypeImportError
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.interface.rest_api.routes.importer_routes.importer_type_helper import (
    parse_uploaded_types,
    stamp_import_authorship,
    stamp_import_edit,
    special_type_license_error,
    build_import_update_payload,
    resolve_error_key,
    create_type_from_entry,
    update_type_from_entry,
)
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

app = Flask(__name__)

NEW_PUBLIC_ID: int = 4711
EXISTING_PUBLIC_ID: int = 4712
MISSING_PUBLIC_ID: int = 9999
BOOM: str = 'boom'
IMPORTER_ID: int = 42


class _StubTypesManager:
    """Records the writes the helpers perform and can be told to fail at a chosen step."""

    def __init__(
        self,
        new_public_id: int | Exception = NEW_PUBLIC_ID,
        matched_count: int = 1,
        insert_error: Exception | None = None,
        update_error: Exception | None = None,
    ) -> None:
        self.new_public_id = new_public_id
        self.matched_count = matched_count
        self.insert_error = insert_error
        self.update_error = update_error
        self.inserted: list[Any] = []
        self.updated: list[tuple[int, Any]] = []

    def get_new_type_public_id(self) -> int:
        """Return the next public_id, or raise when the stub was configured to fail."""
        if isinstance(self.new_public_id, Exception):
            raise self.new_public_id

        return self.new_public_id

    def insert_type(self, new_type: Any) -> None:
        """Record the insert, or raise when the stub was configured to fail."""
        if self.insert_error:
            raise self.insert_error

        self.inserted.append(new_type)

    def update_type(self, public_id: int, update_type: Any) -> SimpleNamespace:
        """Record the update and report how many documents it matched, mirroring UpdateResult."""
        if self.update_error:
            raise self.update_error

        self.updated.append((public_id, update_type))

        return SimpleNamespace(matched_count=self.matched_count)


class TestParseUploadedTypes:
    """parse_uploaded_types decodes the upload form field or aborts 400 when it is absent."""

    def test_decodes_uploaded_json_list(self) -> None:
        """A JSON list in the upload field is decoded into Python objects."""
        payload = [{'name': 'first'}, {'name': 'second'}]

        with app.test_request_context(
            '/', method='POST',
            data={'uploadFile': json.dumps(payload)},
            content_type='multipart/form-data',
        ):
            assert parse_uploaded_types(request) == payload

    def test_decodes_empty_list(self) -> None:
        """An empty JSON list is a valid upload and yields no entries."""
        with app.test_request_context(
            '/', method='POST',
            data={'uploadFile': json.dumps([])},
            content_type='multipart/form-data',
        ):
            assert parse_uploaded_types(request) == []

    @pytest.mark.parametrize('form_data', [{}, {'uploadFile': ''}], ids=['absent', 'empty'])
    def test_missing_upload_aborts_400(self, form_data: dict[str, Any]) -> None:
        """A missing or empty upload field aborts with 400."""
        with app.test_request_context('/', method='POST', data=form_data, content_type='multipart/form-data'):
            with pytest.raises(HTTPException) as exc:
                parse_uploaded_types(request)

            assert exc.value.code == 400

    @pytest.mark.parametrize(
        'payload',
        [{'name': 'single-type'}, 'a string', 42],
        ids=['single-dict', 'string', 'number'],
    )
    def test_non_list_payload_aborts_400(self, payload: Any) -> None:
        """A payload that does not decode to a list is rejected instead of being iterated."""
        with app.test_request_context(
            '/', method='POST',
            data={'uploadFile': json.dumps(payload)},
            content_type='multipart/form-data',
        ):
            with pytest.raises(HTTPException) as exc:
                parse_uploaded_types(request)

            assert exc.value.code == 400
            assert TypeImportError.INVALID_UPLOAD_PAYLOAD.value in exc.value.description


class TestResolveErrorKey:
    """resolve_error_key prefers the public_id and falls back to the entry position."""

    def test_uses_public_id_when_present(self) -> None:
        """An entry carrying a public_id is keyed by it."""
        assert resolve_error_key({'public_id': EXISTING_PUBLIC_ID}, 3) == str(EXISTING_PUBLIC_ID)

    @pytest.mark.parametrize(
        'entry',
        [{}, {'public_id': None}, 'not-a-dict', None],
        ids=['no-public-id', 'null-public-id', 'string-entry', 'none-entry'],
    )
    def test_falls_back_to_index(self, entry: Any) -> None:
        """An entry without a usable public_id is keyed by its position instead of raising."""
        assert resolve_error_key(entry, 2) == 'entry_2'


class TestStampImportAuthorship:
    """stamp_import_authorship rewrites an uploaded type's authorship onto the importing user."""

    def test_replaces_the_foreign_authorship(self) -> None:
        """The importing user becomes the author and the foreign edit history is dropped."""
        entry = {
            TypeSchemaKey.AUTHOR_ID.value: 777,
            TypeSchemaKey.EDITOR_ID.value: 888,
            TypeSchemaKey.LAST_EDIT_TIME.value: '2020-01-01T00:00:00',
        }

        stamp_import_authorship(entry, IMPORTER_ID)

        assert entry[TypeSchemaKey.AUTHOR_ID.value] == IMPORTER_ID
        assert entry[TypeSchemaKey.EDITOR_ID.value] is None
        assert entry[TypeSchemaKey.LAST_EDIT_TIME.value] is None

    def test_sets_the_fields_when_the_upload_omits_them(self) -> None:
        """An upload carrying no authorship at all still ends up fully stamped."""
        entry: dict[str, Any] = {}

        stamp_import_authorship(entry, IMPORTER_ID)

        assert entry == {
            TypeSchemaKey.AUTHOR_ID.value: IMPORTER_ID,
            TypeSchemaKey.EDITOR_ID.value: None,
            TypeSchemaKey.LAST_EDIT_TIME.value: None,
        }


class TestSpecialTypeLicenseError:
    """special_type_license_error blocks importing an IPAM special type onto an unlicensed instance."""

    def test_special_type_is_rejected_when_ipam_is_locked(self) -> None:
        """A locked instance reports the entry instead of installing the special type."""
        entry = {TypeSchemaKey.SPECIAL_TYPE.value: 'SUBNET'}

        result = special_type_license_error(entry, ipam_locked=True)

        assert result == TypeImportError.SPECIAL_TYPE_NOT_LICENSED.format(special_type='SUBNET')

    def test_special_type_is_allowed_when_ipam_is_licensed(self) -> None:
        """A licensed instance imports the special type normally."""
        entry = {TypeSchemaKey.SPECIAL_TYPE.value: 'SUBNET'}

        assert special_type_license_error(entry, ipam_locked=False) is None

    @pytest.mark.parametrize(
        'entry',
        [{}, {TypeSchemaKey.SPECIAL_TYPE.value: ''}, {TypeSchemaKey.SPECIAL_TYPE.value: None}, 'not-a-dict'],
        ids=['absent', 'empty', 'null', 'non-dict'],
    )
    def test_ordinary_entry_is_never_blocked(self, entry: Any) -> None:
        """An entry carrying no special_type is unaffected by the licence state."""
        assert special_type_license_error(entry, ipam_locked=True) is None


class TestStampImportEdit:
    """stamp_import_edit records the importing user as the editor of a replaced type."""

    def test_records_the_importer_as_editor(self) -> None:
        """The editor becomes the importer and the edit time is stamped server-side."""
        entry: dict[str, Any] = {TypeSchemaKey.EDITOR_ID.value: 888}

        stamp_import_edit(entry, IMPORTER_ID)

        assert entry[TypeSchemaKey.EDITOR_ID.value] == IMPORTER_ID
        assert entry[TypeSchemaKey.LAST_EDIT_TIME.value] is not None

    def test_leaves_the_authorship_fields_alone(self) -> None:
        """Unlike the create stamp, this one never touches author_id or creation_time."""
        entry: dict[str, Any] = {
            TypeSchemaKey.AUTHOR_ID.value: 777,
            TypeSchemaKey.CREATION_TIME.value: 'original',
        }

        stamp_import_edit(entry, IMPORTER_ID)

        assert entry[TypeSchemaKey.AUTHOR_ID.value] == 777
        assert entry[TypeSchemaKey.CREATION_TIME.value] == 'original'


class TestBuildImportUpdatePayload:
    """build_import_update_payload drops the fields an import update must not write."""

    def test_omits_the_preserved_fields(self) -> None:
        """author_id and creation_time are absent, so the $set leaves the stored values untouched."""
        instance = CmdbType.from_data(make_type_doc(EXISTING_PUBLIC_ID, 'imported-type'))

        payload = build_import_update_payload(instance)

        assert TypeSchemaKey.AUTHOR_ID.value not in payload
        assert TypeSchemaKey.CREATION_TIME.value not in payload

    def test_keeps_everything_else(self) -> None:
        """The rest of the type is still written, so an update remains a full replacement."""
        instance = CmdbType.from_data(make_type_doc(EXISTING_PUBLIC_ID, 'imported-type'))

        payload = build_import_update_payload(instance)

        assert payload[TypeSchemaKey.PUBLIC_ID.value] == EXISTING_PUBLIC_ID
        assert payload[TypeSchemaKey.NAME.value] == 'imported-type'
        assert 'fields' in payload


class TestCreateTypeFromEntry:
    """create_type_from_entry assigns a server-side public_id and reports failures as messages."""

    def test_locked_special_type_is_rejected_without_consuming_a_public_id(self) -> None:
        """A blocked entry is reported before any id is assigned, so the counter is not advanced."""
        entry = make_type_doc(0, 'imported-ipam-type', special_type='SUBNET')
        types_manager = _StubTypesManager()

        result = create_type_from_entry(entry, types_manager, IMPORTER_ID, ipam_locked=True)

        assert result == TypeImportError.SPECIAL_TYPE_NOT_LICENSED.format(special_type='SUBNET')
        assert types_manager.inserted == []
        assert entry['public_id'] == 0  # untouched - get_new_type_public_id was never called

    def test_authorship_is_rewritten_onto_the_importer(self) -> None:
        """The uploaded author/editor ids are replaced, so no id from the source system survives."""
        entry = make_type_doc(0, 'imported-type')
        entry[TypeSchemaKey.AUTHOR_ID.value] = 777
        entry[TypeSchemaKey.EDITOR_ID.value] = 888

        assert create_type_from_entry(entry, _StubTypesManager(), IMPORTER_ID) is None
        assert entry[TypeSchemaKey.AUTHOR_ID.value] == IMPORTER_ID
        assert entry[TypeSchemaKey.EDITOR_ID.value] is None
        assert entry[TypeSchemaKey.LAST_EDIT_TIME.value] is None

    def test_inserts_type_and_returns_none(self) -> None:
        """A valid entry is inserted with a freshly assigned public_id and reports no error."""
        entry = make_type_doc(0, 'imported-type')
        entry.pop('public_id')
        types_manager = _StubTypesManager()

        assert create_type_from_entry(entry, types_manager, IMPORTER_ID) is None
        assert entry['public_id'] == NEW_PUBLIC_ID
        assert len(types_manager.inserted) == 1

    def test_public_id_from_upload_is_overwritten(self) -> None:
        """A public_id present in the upload is replaced by the server-assigned one."""
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-type')
        types_manager = _StubTypesManager()

        assert create_type_from_entry(entry, types_manager, IMPORTER_ID) is None
        assert entry['public_id'] == NEW_PUBLIC_ID

    def test_public_id_assignment_failure_is_reported(self) -> None:
        """A failing public_id assignment is reported instead of aborting the batch."""
        entry = make_type_doc(0, 'imported-type')
        types_manager = _StubTypesManager(new_public_id=RuntimeError(BOOM))

        result = create_type_from_entry(entry, types_manager, IMPORTER_ID)

        assert result == TypeImportError.PUBLIC_ID_ASSIGNMENT_FAILED.format(detail=BOOM)
        assert types_manager.inserted == []

    def test_non_dict_entry_is_reported(self) -> None:
        """A malformed (non dictionary) entry is reported instead of raising."""
        result = create_type_from_entry('not-a-dict', _StubTypesManager(), IMPORTER_ID)

        assert result.startswith('Failed to assign a public_id to this Type:')

    def test_invalid_type_data_is_reported(self) -> None:
        """An entry that cannot be built into a CmdbType is reported with the underlying detail."""
        result = create_type_from_entry({}, _StubTypesManager(), IMPORTER_ID)

        assert result.startswith('Failed to import this Type:')

    def test_insert_failure_is_reported(self) -> None:
        """A failing insert is reported with the underlying detail."""
        entry = make_type_doc(0, 'imported-type')
        types_manager = _StubTypesManager(insert_error=RuntimeError(BOOM))

        assert create_type_from_entry(entry, types_manager, IMPORTER_ID) == TypeImportError.IMPORT_FAILED.format(detail=BOOM)


class TestUpdateTypeFromEntry:
    """update_type_from_entry writes once and reads the outcome off the returned UpdateResult."""

    def test_updates_existing_type_and_returns_none(self) -> None:
        """An entry whose update matches a document reports no error."""
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-type')
        types_manager = _StubTypesManager(matched_count=1)

        assert update_type_from_entry(entry, types_manager, IMPORTER_ID) is None
        assert len(types_manager.updated) == 1

    def test_writes_once_without_a_separate_existence_query(self) -> None:
        """Only the update is issued - the outcome comes from matched_count, not a preceding read."""
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-type')
        types_manager = _StubTypesManager(matched_count=1)

        update_type_from_entry(entry, types_manager, IMPORTER_ID)

        # a get_type call would raise AttributeError on this stub, which deliberately has no such method
        assert not hasattr(types_manager, 'get_type')

    def test_locked_special_type_is_rejected_without_writing(self) -> None:
        """A blocked special-type entry is reported and never reaches the update."""
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-ipam-type', special_type='VLAN')
        types_manager = _StubTypesManager(matched_count=1)

        result = update_type_from_entry(entry, types_manager, IMPORTER_ID, ipam_locked=True)

        assert result == TypeImportError.SPECIAL_TYPE_NOT_LICENSED.format(special_type='VLAN')
        assert types_manager.updated == []

    def test_importer_is_recorded_as_the_editor(self) -> None:
        """The importing user becomes the editor and the edit time is stamped server-side."""
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-type')
        entry[TypeSchemaKey.EDITOR_ID.value] = 888
        types_manager = _StubTypesManager(matched_count=1)

        assert update_type_from_entry(entry, types_manager, IMPORTER_ID) is None

        (_, written), = types_manager.updated
        assert written[TypeSchemaKey.EDITOR_ID.value] == IMPORTER_ID
        assert written[TypeSchemaKey.LAST_EDIT_TIME.value] is not None

    def test_author_and_creation_time_are_never_written(self) -> None:
        """The stored author/creation time survive: an update payload simply omits both fields."""
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-type')
        entry[TypeSchemaKey.AUTHOR_ID.value] = 777
        types_manager = _StubTypesManager(matched_count=1)

        update_type_from_entry(entry, types_manager, IMPORTER_ID)

        (_, written), = types_manager.updated
        assert TypeSchemaKey.AUTHOR_ID.value not in written
        assert TypeSchemaKey.CREATION_TIME.value not in written

    def test_unmatched_update_is_reported(self) -> None:
        """An update matching nothing is reported instead of passing as a silent success."""
        entry = make_type_doc(MISSING_PUBLIC_ID, 'imported-type')
        types_manager = _StubTypesManager(matched_count=0)

        result = update_type_from_entry(entry, types_manager, IMPORTER_ID)

        assert result == TypeImportError.TYPE_NOT_FOUND.format(public_id=MISSING_PUBLIC_ID)

    def test_invalid_type_data_is_reported(self) -> None:
        """An entry that cannot be built into a CmdbType is reported with the underlying detail."""
        result = update_type_from_entry({}, _StubTypesManager(), IMPORTER_ID)

        assert result.startswith('Failed to create a Type instance from the provided data:')

    def test_update_failure_is_reported(self) -> None:
        """A failing update is reported with the underlying detail."""
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-type')
        types_manager = _StubTypesManager(update_error=RuntimeError(BOOM))

        assert update_type_from_entry(entry, types_manager, IMPORTER_ID) == TypeImportError.UPDATE_FAILED.format(detail=BOOM)
