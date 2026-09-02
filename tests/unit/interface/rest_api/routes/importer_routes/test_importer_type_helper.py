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

The orchestration layer: parsing the multipart upload, the authorship stamps, the update payload, the
batch runner that assembles the partial report, the two per-entry steps and the persistence side
effects that follow the write. The rules and repairs the steps call are covered by their own modules -
here they are only checked to run, in the right order, with their findings reported. The manager is
stubbed throughout.
"""
import json
from typing import Any

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, request
from werkzeug.exceptions import HTTPException

from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.interface.rest_api.routes.importer_routes.importer_type_constants import (
    DEFAULT_TYPE_ICON,
    TypeImportError,
)
from cmdb.interface.rest_api.routes.importer_routes.importer_type_helper import (
    parse_uploaded_types,
    stamp_import_authorship,
    stamp_import_edit,
    build_import_update_payload,
    run_type_import_batch,
    apply_import_create_side_effects,
    apply_import_update_side_effects,
    _templates_the_update_still_claims,
    repaired_structure_error,
    create_type_from_entry,
    update_type_from_entry,
)
from tests.utils.ipam_doc_builders import make_type_doc
from tests.utils.type_import_builders import (
    BOOM,
    EXISTING_PUBLIC_ID,
    MISSING_PUBLIC_ID,
    NEW_PUBLIC_ID,
    IMPORTER,
    IMPORTER_ID,
    HELPER,
    StubTypesManager,
    StubSectionTemplatesManager,
    no_templates,
    raise_boom,
    ref_section_entry,
    unreachable,
)
# -------------------------------------------------------------------------------------------------------------------- #

TYPES_HELPER_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper'


@pytest.fixture(autouse=True)
def _no_section_dependents():
    """
    Stubs the CmdbType lookup the import's update rules perform, keeping these tests DB-free

    `stored_type_update_blocker` delegates to the same blockers the PUT route aborts with, and two of
    them ask the types collection whether another CmdbType references a section this entry removes.
    That lookup goes through ManagerProvider, which needs an application context; these tests hand
    their managers in explicitly and have none. Patched to "nothing references it", so the rules the
    module is actually about are what gets exercised - the reference guard has its own suites.
    """
    manager = MagicMock(name='types_manager')
    manager.find.return_value = []

    with patch(f'{TYPES_HELPER_PATH}.ManagerProvider.get_manager', return_value=manager):
        yield


app = Flask(__name__)


def _raise_on_read(_public_id: int) -> None:
    """Stands in for a manager whose existence read fails."""
    raise RuntimeError(BOOM)


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

    def test_malformed_json_aborts_400(self) -> None:
        """An upload that is not valid JSON is a bad request, not an internal error."""
        with app.test_request_context(
            '/', method='POST',
            data={'uploadFile': '[{"name": '},
            content_type='multipart/form-data',
        ):
            with pytest.raises(HTTPException) as exc:
                parse_uploaded_types(request)

            assert exc.value.code == 400
            assert exc.value.description.startswith('The uploaded data is not valid JSON:')

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


class TestRunTypeImportBatch:
    """run_type_import_batch reports every entry in the shape the object import answers with."""

    def test_counts_the_imported_entries(self) -> None:
        """A batch nothing failed in reports the imported count, not the imported types."""
        entries: list[Any] = [
            {TypeSchemaKey.PUBLIC_ID.value: EXISTING_PUBLIC_ID},
            {TypeSchemaKey.PUBLIC_ID.value: NEW_PUBLIC_ID},
        ]

        report = run_type_import_batch(entries, lambda _entry: None)

        assert report.message == 'Imported 2 of 2 types, 0 failed'
        assert report.success_imports == 2
        assert report.failed_imports == []

    def test_failure_carries_the_uploaded_data_and_the_reason(self) -> None:
        """A rejected entry is reported with the data the user uploaded, not with the mutated entry."""
        uploaded: dict[str, Any] = {
            TypeSchemaKey.NAME.value: 'uploaded',
            TypeSchemaKey.PUBLIC_ID.value: EXISTING_PUBLIC_ID,
        }

        def repair_then_fail(type_entry: dict[str, Any]) -> str:
            del type_entry[TypeSchemaKey.PUBLIC_ID.value]
            type_entry[TypeSchemaKey.NAME.value] = 'repaired'

            return BOOM

        report = run_type_import_batch([dict(uploaded)], repair_then_fail)
        (failure,) = report.failed_imports

        assert failure.failed_type == uploaded
        assert failure.errors == [BOOM]

    def test_a_rejected_entry_does_not_discard_its_siblings(self) -> None:
        """Both outcomes end up in the report and the summary states the split."""
        report = run_type_import_batch(
            [{TypeSchemaKey.NAME.value: 'bad'}, {TypeSchemaKey.NAME.value: 'good'}],
            lambda type_entry: BOOM if type_entry[TypeSchemaKey.NAME.value] == 'bad' else None,
        )

        assert report.message == 'Imported 1 of 2 types, 1 failed'
        assert report.success_imports == 1
        assert [failure.failed_type[TypeSchemaKey.NAME.value] for failure in report.failed_imports] == ['bad']

    def test_an_unexpected_error_fails_only_that_entry(self) -> None:
        """An error the per-entry step did not anticipate is reported like any other rejection."""
        def raise_for_the_first(type_entry: dict[str, Any]) -> None:
            if type_entry[TypeSchemaKey.NAME.value] == 'bad':
                raise RuntimeError(BOOM)

            return None

        report = run_type_import_batch(
            [{TypeSchemaKey.NAME.value: 'bad'}, {TypeSchemaKey.NAME.value: 'good'}],
            raise_for_the_first,
        )

        assert report.success_imports == 1
        assert report.failed_imports[0].errors == [
            TypeImportError.UNEXPECTED_IMPORT_ERROR.format(detail=BOOM),
        ]

    @pytest.mark.parametrize('entry', ['not-a-dict', None, 42], ids=['string', 'none', 'number'])
    def test_an_unusable_entry_is_reported_as_provided(self, entry: Any) -> None:
        """An entry that is not a type dictionary is still reported back with its value."""
        report = run_type_import_batch([entry], lambda _entry: TypeImportError.NOT_A_TYPE_ENTRY.value)
        (failure,) = report.failed_imports

        assert failure.failed_type == entry
        assert failure.errors == [TypeImportError.NOT_A_TYPE_ENTRY.value]

    def test_an_empty_upload_reports_nothing(self) -> None:
        """An empty list is a completed batch with no outcomes, not an error."""
        report = run_type_import_batch([], unreachable)

        assert report.message == 'Imported 0 of 0 types, 0 failed'
        assert report.success_imports == 0
        assert report.failed_imports == []

    def test_a_failure_serializes_with_the_type_named_key(self) -> None:
        """The wire contract: a rejected entry is `failed_type`, not the object import's `failed_object`."""
        entry: dict[str, Any] = {TypeSchemaKey.PUBLIC_ID.value: NEW_PUBLIC_ID}

        report = run_type_import_batch(
            [entry, {TypeSchemaKey.NAME.value: 'bad'}],
            lambda type_entry: BOOM if TypeSchemaKey.NAME.value in type_entry else None,
        )
        (failure,) = report.failed_imports

        assert report.success_imports == 1
        assert failure.__dict__ == {'failed_type': {TypeSchemaKey.NAME.value: 'bad'}, 'errors': [BOOM]}


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
        """The stored-fact fields are absent, so the $set leaves the stored values untouched."""
        instance = CmdbType.from_data(make_type_doc(EXISTING_PUBLIC_ID, 'imported-type'))

        payload = build_import_update_payload(instance)

        assert TypeSchemaKey.AUTHOR_ID.value not in payload
        assert TypeSchemaKey.CREATION_TIME.value not in payload
        assert TypeSchemaKey.VERSION.value not in payload
        assert TypeSchemaKey.SPECIAL_TYPE.value not in payload

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
        types_manager = StubTypesManager()

        result = create_type_from_entry(entry, types_manager, no_templates(), IMPORTER, ipam_locked=True)

        assert result == TypeImportError.SPECIAL_TYPE_NOT_LICENSED.format(special_type='SUBNET')
        assert not types_manager.inserted
        # the uploaded id is dropped up front and no fresh one was assigned - the counter never moved
        assert TypeSchemaKey.PUBLIC_ID.value not in entry

    def test_authorship_is_rewritten_onto_the_importer(self) -> None:
        """The uploaded author/editor ids are replaced, so no id from the source system survives."""
        entry = make_type_doc(0, 'imported-type')
        entry[TypeSchemaKey.AUTHOR_ID.value] = 777
        entry[TypeSchemaKey.EDITOR_ID.value] = 888

        assert create_type_from_entry(entry, StubTypesManager(), no_templates(), IMPORTER) is None
        assert entry[TypeSchemaKey.AUTHOR_ID.value] == IMPORTER_ID
        assert entry[TypeSchemaKey.EDITOR_ID.value] is None
        assert entry[TypeSchemaKey.LAST_EDIT_TIME.value] is None

    def test_inserts_type_and_returns_none(self) -> None:
        """A valid entry is inserted with a freshly assigned public_id and reports no error."""
        entry = make_type_doc(0, 'imported-type')
        entry.pop('public_id')
        types_manager = StubTypesManager()

        assert create_type_from_entry(entry, types_manager, no_templates(), IMPORTER) is None
        assert entry['public_id'] == NEW_PUBLIC_ID
        assert len(types_manager.inserted) == 1

    def test_public_id_from_upload_is_overwritten(self) -> None:
        """A public_id present in the upload is replaced by the server-assigned one."""
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-type')
        types_manager = StubTypesManager()

        assert create_type_from_entry(entry, types_manager, no_templates(), IMPORTER) is None
        assert entry['public_id'] == NEW_PUBLIC_ID

    def test_public_id_assignment_failure_is_reported(self) -> None:
        """A failing public_id assignment is reported instead of aborting the batch."""
        entry = make_type_doc(0, 'imported-type')
        types_manager = StubTypesManager(new_public_id=RuntimeError(BOOM))

        result = create_type_from_entry(entry, types_manager, no_templates(), IMPORTER)

        assert result == TypeImportError.PUBLIC_ID_ASSIGNMENT_FAILED.format(detail=BOOM)
        assert not types_manager.inserted

    def test_non_dict_entry_is_reported_without_consuming_an_id(self) -> None:
        """A malformed entry is reported as such, and the public_id counter never moves."""
        types_manager = StubTypesManager()

        assert create_type_from_entry('not-a-dict', types_manager, no_templates(), IMPORTER) \
            == TypeImportError.NOT_A_TYPE_ENTRY.value
        assert not types_manager.inserted

    def test_invalid_type_data_is_reported(self) -> None:
        """An entry that cannot be built into a CmdbType is reported like on the update path."""
        # named (so the name rules pass) but with an unusable acl, which CmdbType.from_data rejects
        result = create_type_from_entry(
            {'name': 'broken', 'acl': 'not-a-dict'}, StubTypesManager(), no_templates(), IMPORTER,
        )

        assert result.startswith('Failed to create a Type instance from the provided data:')

    def test_entry_without_a_name_is_reported(self) -> None:
        """A type carrying no name is rejected before anything is assigned or written."""
        types_manager = StubTypesManager()

        assert create_type_from_entry({}, types_manager, no_templates(), IMPORTER) \
            == TypeImportError.MISSING_TYPE_NAME.value
        assert not types_manager.inserted

    def test_insert_failure_is_reported(self) -> None:
        """A failing insert is reported with the underlying detail."""
        entry = make_type_doc(0, 'imported-type')
        types_manager = StubTypesManager(insert_error=RuntimeError(BOOM))

        assert create_type_from_entry(entry, types_manager, no_templates(), IMPORTER) \
            == TypeImportError.IMPORT_FAILED.format(detail=BOOM)


class TestUpdateTypeFromEntry:
    """update_type_from_entry writes once and reads the outcome off the returned UpdateResult."""

    def test_updates_existing_type_and_returns_none(self) -> None:
        """An entry whose update matches a document reports no error."""
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-type')
        types_manager = StubTypesManager(matched_count=1)

        assert update_type_from_entry(entry, types_manager, no_templates(), IMPORTER) is None
        assert len(types_manager.updated) == 1

    def test_writes_once_without_a_separate_existence_query(self) -> None:
        """Only the update is issued - the outcome comes from matched_count, not a preceding read."""
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-type')
        types_manager = StubTypesManager(matched_count=1)

        update_type_from_entry(entry, types_manager, no_templates(), IMPORTER)

        # a get_type call would raise AttributeError on this stub, which deliberately has no such method
        assert not hasattr(types_manager, 'get_type')

    def test_locked_special_type_is_rejected_without_writing(self) -> None:
        """A blocked special-type entry is reported and never reaches the update."""
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-ipam-type', special_type='VLAN')
        types_manager = StubTypesManager(matched_count=1)

        result = update_type_from_entry(entry, types_manager, no_templates(), IMPORTER, ipam_locked=True)

        assert result == TypeImportError.SPECIAL_TYPE_NOT_LICENSED.format(special_type='VLAN')
        assert not types_manager.updated

    def test_importer_is_recorded_as_the_editor(self) -> None:
        """The importing user becomes the editor and the edit time is stamped server-side."""
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-type')
        entry[TypeSchemaKey.EDITOR_ID.value] = 888
        types_manager = StubTypesManager(matched_count=1)

        assert update_type_from_entry(entry, types_manager, no_templates(), IMPORTER) is None

        (_, written), = types_manager.updated
        assert written[TypeSchemaKey.EDITOR_ID.value] == IMPORTER_ID
        assert written[TypeSchemaKey.LAST_EDIT_TIME.value] is not None

    def test_author_and_creation_time_are_never_written(self) -> None:
        """The stored author/creation time survive: an update payload simply omits both fields."""
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-type')
        entry[TypeSchemaKey.AUTHOR_ID.value] = 777
        types_manager = StubTypesManager(matched_count=1)

        update_type_from_entry(entry, types_manager, no_templates(), IMPORTER)

        (_, written), = types_manager.updated
        assert TypeSchemaKey.AUTHOR_ID.value not in written
        assert TypeSchemaKey.CREATION_TIME.value not in written

    def test_a_type_deleted_between_the_read_and_the_write_is_reported(self) -> None:
        """The read found it, the write matched nothing - reported instead of a silent success."""
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-type')
        types_manager = StubTypesManager(matched_count=0)

        result = update_type_from_entry(entry, types_manager, no_templates(), IMPORTER)

        assert result == TypeImportError.TYPE_NOT_FOUND.format(public_id=EXISTING_PUBLIC_ID)

    def test_invalid_type_data_is_reported(self) -> None:
        """An entry that cannot be built into a CmdbType is reported with the underlying detail."""
        # the type exists, but the entry carries an unusable acl, which CmdbType.from_data rejects
        entry = {'name': 'broken', TypeSchemaKey.PUBLIC_ID.value: EXISTING_PUBLIC_ID, 'acl': 'not-a-dict'}
        result = update_type_from_entry(entry, StubTypesManager(), no_templates(), IMPORTER)

        assert result.startswith('Failed to create a Type instance from the provided data:')

    def test_an_entry_without_a_public_id_cannot_identify_a_type(self) -> None:
        """The update is applied by public_id, so an entry without one has nothing to update."""
        types_manager = StubTypesManager()

        assert update_type_from_entry({'name': 'nameless'}, types_manager, no_templates(), IMPORTER) \
            == TypeImportError.TYPE_NOT_FOUND.format(public_id=None)
        assert not types_manager.instance_reads  # not even looked up

    def test_entry_without_a_name_is_reported(self) -> None:
        """A type carrying no name is rejected before anything is written."""
        types_manager = StubTypesManager()
        entry = {TypeSchemaKey.PUBLIC_ID.value: EXISTING_PUBLIC_ID}

        assert update_type_from_entry(entry, types_manager, no_templates(), IMPORTER) \
            == TypeImportError.MISSING_TYPE_NAME.value
        assert not types_manager.updated

    def test_update_failure_is_reported(self) -> None:
        """A failing update is reported with the underlying detail."""
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-type')
        types_manager = StubTypesManager(update_error=RuntimeError(BOOM))

        assert update_type_from_entry(entry, types_manager, no_templates(), IMPORTER) \
            == TypeImportError.UPDATE_FAILED.format(detail=BOOM)


class TestNormalizationDuringImport:
    """Both per-entry steps repair the entry before it is written."""

    def test_create_stamps_the_default_icon(self) -> None:
        """A created type without an icon is stored with the placeholder."""
        entry = make_type_doc(0, 'imported-type')
        entry['render_meta'].pop('icon')
        types_manager = StubTypesManager()

        assert create_type_from_entry(entry, types_manager, no_templates(), IMPORTER) is None
        assert types_manager.inserted[0].render_meta.icon == DEFAULT_TYPE_ICON

    def test_create_clears_a_dangling_reference(self) -> None:
        """A reference the target system does not know is cleared instead of failing the entry."""
        entry = ref_section_entry(7)
        types_manager = StubTypesManager()

        assert create_type_from_entry(entry, types_manager, no_templates(), IMPORTER) is None
        assert types_manager.inserted[0].render_meta.sections[0].reference.type_id is None

    def test_update_clears_a_dangling_reference(self) -> None:
        """The update path repairs the replacement the same way the create path does."""
        entry = ref_section_entry(7)
        entry[TypeSchemaKey.PUBLIC_ID.value] = EXISTING_PUBLIC_ID
        entry[TypeSchemaKey.AUTHOR_ID.value] = 1
        types_manager = StubTypesManager()

        assert update_type_from_entry(entry, types_manager, no_templates(), IMPORTER) is None

        _, payload = types_manager.updated[0]

        assert payload['render_meta']['sections'][0]['reference']['type_id'] is None

    def test_failing_reference_lookup_is_reported_per_entry(self) -> None:
        """A failing existence lookup fails this entry, not the whole batch."""
        entry = ref_section_entry(7)
        types_manager = StubTypesManager(existence_error=RuntimeError(BOOM))

        assert create_type_from_entry(entry, types_manager, no_templates(), IMPORTER) \
            == TypeImportError.NORMALIZATION_FAILED.format(detail=BOOM)
        assert not types_manager.inserted


class TestApplyImportCreateSideEffects:
    """A created type is wired up exactly like a hand-created one - today that is the SpecialType."""

    @pytest.mark.parametrize('entry', [{'name': 'plain'}, {'name': 'plain', 'special_type': ''}],
                             ids=['absent', 'empty'])
    def test_an_ordinary_type_has_no_side_effects(self, entry: dict[str, Any], monkeypatch) -> None:
        """Nothing to wire for an ordinary type."""
        monkeypatch.setattr(f'{HELPER}.handle_special_types', unreachable)

        apply_import_create_side_effects(StubTypesManager(), no_templates(), entry)

    def test_a_special_type_is_cross_wired(self, monkeypatch) -> None:
        """handle_special_types runs for the freshly assigned public_id, as the create route does."""
        wired: list[tuple] = []
        monkeypatch.setattr(f'{HELPER}.handle_special_types', lambda *args: wired.append(args))

        types_manager = StubTypesManager()
        section_templates = no_templates()
        entry = {'name': 'subnet', 'special_type': SpecialType.SUBNET.value,
                 TypeSchemaKey.PUBLIC_ID.value: NEW_PUBLIC_ID}

        apply_import_create_side_effects(types_manager, section_templates, entry)

        assert wired == [(types_manager, SpecialType.SUBNET.value, section_templates, NEW_PUBLIC_ID)]


class TestApplyImportUpdateSideEffects:
    """An import update owes the stored data the same follow-up work as the normal update route."""

    @staticmethod
    def _patch(monkeypatch) -> dict[str, list]:
        """Records the two route helpers this delegates to instead of running them."""
        calls: dict[str, list] = {'removed': [], 'applied': []}

        def _removed(*args):
            calls['removed'].append(args)
            return ({'tpl'}, {})

        monkeypatch.setattr(f'{HELPER}.compute_removed_global_templates', _removed)
        monkeypatch.setattr(f'{HELPER}.apply_type_update_side_effects',
                            lambda *args: calls['applied'].append(args))

        return calls

    def test_delegates_to_the_route_helper_with_both_states(self, monkeypatch) -> None:
        """The pre-update type and the re-read post-update type are both handed over."""
        calls = self._patch(monkeypatch)
        types_manager = StubTypesManager()
        old_type = CmdbType.from_data(make_type_doc(EXISTING_PUBLIC_ID, 'old-type'))

        apply_import_update_side_effects(IMPORTER, types_manager, no_templates(), old_type, {'name': 'new-type'})

        (request_user, manager, passed_old, passed_new, removed), = calls['applied']

        assert request_user is IMPORTER
        assert manager is types_manager
        assert passed_old is old_type
        assert passed_new is types_manager.stored_type  # the re-read, not the uploaded entry
        assert removed == ({'tpl'}, {})

    def test_the_type_is_re_read_because_the_payload_omits_preserved_fields(self, monkeypatch) -> None:
        """special_type is never written by an update, so only the stored document is authoritative."""
        self._patch(monkeypatch)
        types_manager = StubTypesManager()
        old_type = CmdbType.from_data(make_type_doc(EXISTING_PUBLIC_ID, 'old-type'))

        apply_import_update_side_effects(IMPORTER, types_manager, no_templates(), old_type, {'name': 'new-type'})

        assert types_manager.instance_reads == [EXISTING_PUBLIC_ID]

    def test_removed_templates_are_computed_from_the_uploaded_ids(self, monkeypatch) -> None:
        """The dropped global templates come from the upload, not from the re-read type."""
        calls = self._patch(monkeypatch)
        old_type = CmdbType.from_data(make_type_doc(EXISTING_PUBLIC_ID, 'old-type'))
        entry = {'name': 'new-type', TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value: ['kept']}

        apply_import_update_side_effects(IMPORTER, StubTypesManager(), no_templates(), old_type, entry)

        (passed_old, incoming_ids), = calls['removed']

        assert passed_old is old_type
        assert incoming_ids == {'kept'}

    def test_a_type_deleted_after_the_update_is_skipped(self, monkeypatch) -> None:
        """Nothing left to reconcile, so the side effects are not attempted."""
        calls = self._patch(monkeypatch)
        old_type = CmdbType.from_data(make_type_doc(EXISTING_PUBLIC_ID, 'old-type'))

        apply_import_update_side_effects(
            IMPORTER, StubTypesManager(stored_type_instance=None), no_templates(), old_type, {},
        )

        assert not calls['applied']


class TestSideEffectsAreRunByTheEntrySteps:
    """Both per-entry steps end in their side effects, and report a failure without hiding the write."""

    def test_create_runs_its_side_effects(self, side_effect_calls: dict[str, list]) -> None:
        """A created type reaches apply_import_create_side_effects with the stored entry."""
        entry = make_type_doc(0, 'imported-type')
        types_manager = StubTypesManager()

        assert create_type_from_entry(entry, types_manager, no_templates(), IMPORTER) is None

        (manager, section_templates, passed_entry), = side_effect_calls['create']

        assert manager is types_manager
        assert isinstance(section_templates, StubSectionTemplatesManager)
        assert passed_entry is entry

    def test_update_runs_its_side_effects_with_the_pre_update_type(
        self, side_effect_calls: dict[str, list]
    ) -> None:
        """The type read before the write is what the side effects diff against."""
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-type')
        types_manager = StubTypesManager()

        assert update_type_from_entry(entry, types_manager, no_templates(), IMPORTER) is None

        (request_user, manager, _templates, old_type, passed_entry), = side_effect_calls['update']

        assert request_user is IMPORTER
        assert manager is types_manager
        assert old_type is types_manager.stored_type
        assert passed_entry is entry

    def test_the_update_reads_the_type_once_before_writing(self) -> None:
        """One read serves both the existence check and the side effects - not two queries."""
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-type')
        types_manager = StubTypesManager()

        update_type_from_entry(entry, types_manager, no_templates(), IMPORTER)

        assert types_manager.instance_reads == [EXISTING_PUBLIC_ID]

    def test_an_unknown_public_id_is_reported_from_the_read(self) -> None:
        """The pre-update read doubles as the existence check, so nothing is written."""
        entry = make_type_doc(MISSING_PUBLIC_ID, 'imported-type')
        types_manager = StubTypesManager(stored_type_instance=None)

        assert update_type_from_entry(entry, types_manager, no_templates(), IMPORTER) \
            == TypeImportError.TYPE_NOT_FOUND.format(public_id=MISSING_PUBLIC_ID)
        assert not types_manager.updated

    def test_failing_create_side_effects_are_reported_as_a_follow_up(self, monkeypatch) -> None:
        """The type is already stored, so the message says so instead of claiming the import failed."""
        monkeypatch.setattr(f'{HELPER}.apply_import_create_side_effects', raise_boom)
        types_manager = StubTypesManager()

        assert create_type_from_entry(make_type_doc(0, 'imported-type'), types_manager, no_templates(), IMPORTER) \
            == TypeImportError.CREATE_SIDE_EFFECTS_FAILED.format(detail=BOOM)
        assert len(types_manager.inserted) == 1  # the Type itself was written

    def test_failing_update_side_effects_are_reported_as_a_follow_up(self, monkeypatch) -> None:
        """Same for the update: the write happened, the reconciliation did not."""
        monkeypatch.setattr(f'{HELPER}.apply_import_update_side_effects', raise_boom)
        types_manager = StubTypesManager()

        assert update_type_from_entry(
            make_type_doc(EXISTING_PUBLIC_ID, 'imported-type'), types_manager, no_templates(), IMPORTER,
        ) == TypeImportError.UPDATE_SIDE_EFFECTS_FAILED.format(detail=BOOM)
        assert len(types_manager.updated) == 1  # the Type itself was written


class TestUpdateAppliesTheStoredTypeRules:
    """update_type_from_entry runs the stored-type rules before it writes."""

    def test_a_blocked_update_is_reported_and_nothing_is_written(self, monkeypatch) -> None:
        """The blocker's message becomes the entry's error and the write is skipped."""
        monkeypatch.setattr(f'{HELPER}.stored_type_update_blocker', lambda *_args: 'blocked')
        types_manager = StubTypesManager()

        assert update_type_from_entry(
            make_type_doc(EXISTING_PUBLIC_ID, 'imported-type'), types_manager, no_templates(), IMPORTER,
        ) == 'blocked'
        assert not types_manager.updated

    def test_the_blocker_sees_the_stored_and_the_uploaded_state(self, monkeypatch) -> None:
        """Both sides of the comparison are handed over, along with the licence state."""
        seen: list[tuple] = []
        monkeypatch.setattr(f'{HELPER}.stored_type_update_blocker',
                            lambda *args: seen.append(args) or None)
        types_manager = StubTypesManager()

        update_type_from_entry(
            make_type_doc(EXISTING_PUBLIC_ID, 'imported-type'), types_manager, no_templates(), IMPORTER,
            ipam_locked=True,
        )

        (request_user, old_type, new_type, ipam_locked), = seen

        assert request_user is IMPORTER
        assert old_type is types_manager.stored_type
        assert new_type.public_id == EXISTING_PUBLIC_ID
        assert ipam_locked is True

    @pytest.mark.parametrize('entry', ['a string', 42, ['a', 'list']], ids=['str', 'int', 'list'])
    def test_a_non_dict_entry_is_reported_not_raised(self, entry: Any) -> None:
        """An unusable entry must not escape the batch loop - it is reported like any other."""
        types_manager = StubTypesManager()

        assert update_type_from_entry(entry, types_manager, no_templates(), IMPORTER) \
            == TypeImportError.NOT_A_TYPE_ENTRY.value
        assert not types_manager.updated


class TestRepairedStructureError:
    """The structural rules are re-run on what the repairs completed."""

    def test_a_sound_entry_passes(self) -> None:
        """Nothing the repairs did broke the type."""
        assert repaired_structure_error(make_type_doc(EXISTING_PUBLIC_ID, 'imported-type')) is None

    def test_a_finding_is_worded_as_a_repair_failure(self) -> None:
        """The upload was sound, so a finding here can only come from a template's fields."""
        entry = make_type_doc(
            EXISTING_PUBLIC_ID, 'imported-type',
            fields=[{'type': 'text', 'name': 'no-label'}],
            sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['no-label']}],
        )

        result = repaired_structure_error(entry)

        assert result.startswith('Completing this Type from its global section template(s) made it invalid:')
        assert "without a label: ['no-label']" in result


class TestTemplatesTheUpdateStillClaims:
    """A claim the repair dropped is not a section the user removed."""

    def test_an_unknown_template_stays_claimed_for_the_cleanup(self) -> None:
        """It does not exist here, so the repair dropped it - the section must survive."""
        old_type = CmdbType.from_data(
            make_type_doc(EXISTING_PUBLIC_ID, 'stored-type', global_template_ids=['dg-gone'])
        )

        still_claimed = _templates_the_update_still_claims(
            no_templates(), old_type, {'global_template_ids': []},
        )

        assert still_claimed == {'dg-gone'}

    def test_a_template_the_user_dropped_is_reported_as_removed(self) -> None:
        """It exists here, so the upload really took it off the Type."""
        old_type = CmdbType.from_data(
            make_type_doc(EXISTING_PUBLIC_ID, 'stored-type', global_template_ids=['dg-real'])
        )
        section_templates = StubSectionTemplatesManager([
            {'public_id': 1, 'name': 'dg-real', 'label': 'Real', 'type': 'section',
             'is_global': True, 'fields': []},
        ])

        still_claimed = _templates_the_update_still_claims(
            section_templates, old_type, {'global_template_ids': []},
        )

        assert still_claimed == set()

    def test_a_claim_kept_by_the_upload_needs_no_lookup(self) -> None:
        """Nothing disappeared, so there is nothing to tell apart."""
        old_type = CmdbType.from_data(
            make_type_doc(EXISTING_PUBLIC_ID, 'stored-type', global_template_ids=['dg-real'])
        )
        section_templates = no_templates()

        still_claimed = _templates_the_update_still_claims(
            section_templates, old_type, {'global_template_ids': ['dg-real']},
        )

        assert still_claimed == {'dg-real'}
        assert not section_templates.queries

    def test_the_update_side_effects_use_it(self, monkeypatch) -> None:
        """The removed-template set the cleanup runs on comes from this, not from the raw upload."""
        seen: list[tuple] = []
        monkeypatch.setattr(f'{HELPER}.compute_removed_global_templates',
                            lambda *args: seen.append(args) or (set(), {}))
        monkeypatch.setattr(f'{HELPER}.apply_type_update_side_effects', lambda *args: None)

        old_type = CmdbType.from_data(
            make_type_doc(EXISTING_PUBLIC_ID, 'stored-type', global_template_ids=['dg-gone'])
        )
        types_manager = StubTypesManager()

        apply_import_update_side_effects(
            IMPORTER, types_manager, no_templates(), old_type, {'global_template_ids': []},
        )

        (_passed_old, incoming), = seen

        assert incoming == {'dg-gone'}


class TestUpdateReadsTheTypeFirst:
    """The existence check runs before the rules and the repairs, not after them."""

    def test_an_unknown_public_id_costs_no_further_query(self) -> None:
        """No name lookup, no reference / group / template resolution for an id nobody has."""
        types_manager = StubTypesManager(stored_type_instance=None)
        section_templates = no_templates()
        entry = make_type_doc(MISSING_PUBLIC_ID, 'imported-type')

        assert update_type_from_entry(entry, types_manager, section_templates, IMPORTER) \
            == TypeImportError.TYPE_NOT_FOUND.format(public_id=MISSING_PUBLIC_ID)
        assert types_manager.instance_reads == [MISSING_PUBLIC_ID]
        assert not types_manager.existence_lookups
        assert not types_manager.group_lookups
        assert not section_templates.queries

    def test_a_string_public_id_identifies_the_type(self) -> None:
        """An upload may carry the id as a string; it still resolves."""
        types_manager = StubTypesManager()
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-type')
        entry[TypeSchemaKey.PUBLIC_ID.value] = str(EXISTING_PUBLIC_ID)

        assert update_type_from_entry(entry, types_manager, no_templates(), IMPORTER) is None
        assert types_manager.instance_reads == [EXISTING_PUBLIC_ID]

    def test_a_read_failure_is_reported_per_entry(self) -> None:
        """A database error on the existence read fails this entry, not the batch."""
        types_manager = StubTypesManager()
        types_manager.get_type_instance = _raise_on_read

        assert update_type_from_entry(
            make_type_doc(EXISTING_PUBLIC_ID, 'imported-type'), types_manager, no_templates(), IMPORTER,
        ) == TypeImportError.UPDATE_FAILED.format(detail=BOOM)
