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
Unit tests for cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_patch_helper

Pure tests, no Mongo: the PATCH path is a payload transformation. What is pinned here is what a body
may contain, how each multi-data row operation behaves, and that the merge produces a COMPLETE object -
because the result is handed to the shared update pipeline, which treats what it receives as the whole
object. A key the merge drops is a value the object loses.
"""
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import BadRequest, HTTPException

from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_patch_helper import (
    build_patched_object_data,
    create_patch_multi_data_rows,
    delete_patch_multi_data_rows,
    edit_patch_multi_data_rows,
    merge_patch_fields,
    validate_object_patch_payload,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper import (
    # The merge hands a COMPLETE object to the shared update pipeline, so one class here deliberately
    # crosses the seam to prove the pipeline backfills what the merge leaves untyped
    validate_and_fill_object_fields,
)
from cmdb.models.object_model import CmdbObject
# -------------------------------------------------------------------------------------------------------------------- #


def _make_object(fields: list[dict[str, Any]], special_type: Any = None, public_id: int = 1) -> CmdbObject:
    """Builds a minimal valid CmdbObject for the helper unit tests."""
    return CmdbObject(
        public_id=public_id,
        type_id=1,
        version='1.0.0',
        creation_time=datetime.now(timezone.utc),
        author_id=1,
        active=True,
        fields=fields,
        special_type=special_type,
    )


class TestValidateObjectPatchPayload:
    """validate_object_patch_payload guards the PATCH body: allowed keys, non-empty, right shape."""

    def test_non_dict_aborts_400(self) -> None:
        """A body that is not a JSON object (e.g. None from invalid JSON) is rejected with 400."""
        with pytest.raises(HTTPException) as exc_info:
            validate_object_patch_payload(None)

        assert exc_info.value.code == 400

    def test_disallowed_key_aborts_400_naming_it(self) -> None:
        """An immutable / server-managed key in the body is rejected with 400 that names the key."""
        with pytest.raises(HTTPException) as exc_info:
            validate_object_patch_payload({'type_id': 5, 'fields': [{'name': 'a', 'value': 1}]})

        assert exc_info.value.code == 400
        assert 'type_id' in exc_info.value.description

    def test_empty_patch_aborts_400(self) -> None:
        """A body with neither fields nor multi_data_sections changes nothing and is rejected."""
        with pytest.raises(HTTPException) as exc_info:
            validate_object_patch_payload({'comment': 'nothing to change'})

        assert exc_info.value.code == 400

    def test_invalid_shape_aborts_400(self) -> None:
        """A field entry missing its required 'name' fails schema validation with 400."""
        with pytest.raises(HTTPException) as exc_info:
            validate_object_patch_payload({'fields': [{'value': 1}]})

        assert exc_info.value.code == 400

    def test_valid_payload_returns_document(self) -> None:
        """A well-formed patch is returned as the normalized document."""
        result = validate_object_patch_payload({'fields': [{'name': 'a', 'value': 1}]})

        assert result == {'fields': [{'name': 'a', 'value': 1}]}

    def test_delete_only_payload_is_accepted(self) -> None:
        """A patch that only deletes MDS rows is a real change and passes validation."""
        payload = {'deleted_mds_rows': [{'section_id': 's1', 'multi_data_id': 3}]}

        assert validate_object_patch_payload(payload) == payload


# -------------------------------------------------------------------------------------------------------------------- #
#                                                merge_patch_fields                                                   #
# -------------------------------------------------------------------------------------------------------------------- #


class TestMergePatchFields:
    """merge_patch_fields overlays patched values by name, appends unknowns, keeps the rest."""

    def test_overwrites_existing_value_and_keeps_type(self) -> None:
        """A patched field's value replaces the stored one while its stored type is preserved."""
        stored = [{'name': 'a', 'value': 1, 'type': 'text'}, {'name': 'b', 'value': 2, 'type': 'text'}]

        result = merge_patch_fields(stored, [{'name': 'a', 'value': 99}])

        assert result[0] == {'name': 'a', 'value': 99, 'type': 'text'}
        assert result[1] == {'name': 'b', 'value': 2, 'type': 'text'}

    def test_appends_unknown_field(self) -> None:
        """A patched name absent from the stored list is appended as a new entry."""
        result = merge_patch_fields([{'name': 'a', 'value': 1, 'type': 'text'}], [{'name': 'c', 'value': 5}])

        assert result[-1] == {'name': 'c', 'value': 5}

    def test_does_not_mutate_input(self) -> None:
        """The stored field list is not modified in place."""
        stored = [{'name': 'a', 'value': 1, 'type': 'text'}]

        merge_patch_fields(stored, [{'name': 'a', 'value': 99}])

        assert stored[0]['value'] == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                         create_patch_multi_data_rows                                                #
# -------------------------------------------------------------------------------------------------------------------- #


class TestCreatePatchMultiDataRows:
    """create_patch_multi_data_rows appends rows and assigns multi_data_id server-side."""

    @staticmethod
    def _stored() -> list[dict[str, Any]]:
        """One section 's1' (highest_id 2) with a single row multi_data_id 1."""
        return [{
            'section_id': 's1',
            'highest_id': 2,
            'values': [{'multi_data_id': 1, 'data': [{'name': 'a', 'value': 1, 'type': 'text'}]}],
        }]

    def test_assigns_next_id_and_bumps_counter(self) -> None:
        """A created row gets highest_id+1 as its multi_data_id and the counter advances."""
        created = [{'section_id': 's1', 'data': [{'name': 'a', 'value': 7}]}]

        result = create_patch_multi_data_rows(self._stored(), created, {'s1'})

        assert result[0]['highest_id'] == 3
        new_row = next(row for row in result[0]['values'] if row['multi_data_id'] == 3)
        assert new_row['data'] == [{'name': 'a', 'value': 7}]

    def test_multiple_creates_get_consecutive_ids(self) -> None:
        """Several creates in one section receive consecutive ids and the counter ends at the last."""
        created = [
            {'section_id': 's1', 'data': [{'name': 'a', 'value': 7}]},
            {'section_id': 's1', 'data': [{'name': 'a', 'value': 8}]},
        ]

        result = create_patch_multi_data_rows(self._stored(), created, {'s1'})

        assert result[0]['highest_id'] == 4
        assert {row['multi_data_id'] for row in result[0]['values']} == {1, 3, 4}

    def test_first_row_add_seeds_container_for_declared_section(self) -> None:
        """A section the type declares but the object lacks gets a fresh container + row 1."""
        created = [{'section_id': 's2', 'data': [{'name': 'a', 'value': 7}]}]

        result = create_patch_multi_data_rows(self._stored(), created, {'s1', 's2'})

        new_section = next(section for section in result if section['section_id'] == 's2')
        assert new_section['highest_id'] == 1
        assert new_section['values'][0]['multi_data_id'] == 1
        assert new_section['values'][0]['data'] == [{'name': 'a', 'value': 7}]

    def test_undeclared_section_aborts_400(self) -> None:
        """Creating a row in a section the type does not declare is refused with 400."""
        with pytest.raises(HTTPException) as exc_info:
            create_patch_multi_data_rows(self._stored(), [{'section_id': 'sX', 'data': []}], {'s1'})

        assert exc_info.value.code == 400

    def test_does_not_mutate_input(self) -> None:
        """The stored sections are not modified in place."""
        stored = self._stored()

        create_patch_multi_data_rows(stored, [{'section_id': 's1', 'data': [{'name': 'a', 'value': 7}]}], {'s1'})

        assert stored[0]['highest_id'] == 2
        assert {row['multi_data_id'] for row in stored[0]['values']} == {1}


# -------------------------------------------------------------------------------------------------------------------- #
#                                          edit_patch_multi_data_rows                                                 #
# -------------------------------------------------------------------------------------------------------------------- #


class TestEditPatchMultiDataRows:
    """edit_patch_multi_data_rows merges field values into existing rows by (section_id, multi_data_id)."""

    @staticmethod
    def _stored() -> list[dict[str, Any]]:
        """One section 's1' with a single row multi_data_id 1."""
        return [{
            'section_id': 's1',
            'highest_id': 2,
            'values': [{'multi_data_id': 1, 'data': [{'name': 'a', 'value': 1, 'type': 'text'}]}],
        }]

    def test_merges_row_data_by_name(self) -> None:
        """A matched row has its field values merged; the stored type is preserved."""
        edited = [{'section_id': 's1', 'multi_data_id': 1, 'data': [{'name': 'a', 'value': 9}]}]

        result = edit_patch_multi_data_rows(self._stored(), edited)

        assert result[0]['values'][0]['data'][0] == {'name': 'a', 'value': 9, 'type': 'text'}

    def test_unknown_section_aborts_400(self) -> None:
        """Editing a row in a section the object does not have is refused with 400."""
        with pytest.raises(HTTPException) as exc_info:
            edit_patch_multi_data_rows(self._stored(), [{'section_id': 'sX', 'multi_data_id': 1, 'data': []}])

        assert exc_info.value.code == 400

    def test_unknown_row_aborts_400(self) -> None:
        """Editing a multi_data_id not present in the section is refused with 400 (use create)."""
        with pytest.raises(HTTPException) as exc_info:
            edit_patch_multi_data_rows(self._stored(), [{'section_id': 's1', 'multi_data_id': 99, 'data': []}])

        assert exc_info.value.code == 400

    def test_does_not_mutate_input(self) -> None:
        """The stored sections are not modified in place."""
        stored = self._stored()

        edited = [{'section_id': 's1', 'multi_data_id': 1, 'data': [{'name': 'a', 'value': 9}]}]
        edit_patch_multi_data_rows(stored, edited)

        assert stored[0]['values'][0]['data'][0]['value'] == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                        delete_patch_multi_data_rows                                                 #
# -------------------------------------------------------------------------------------------------------------------- #


class TestDeletePatchMultiDataRows:
    """delete_patch_multi_data_rows removes rows by (section_id, multi_data_id), keeping empty sections."""

    @staticmethod
    def _stored() -> list[dict[str, Any]]:
        """One section 's1' (highest_id 2) with two rows: multi_data_id 1 and 2."""
        return [{
            'section_id': 's1',
            'highest_id': 2,
            'values': [
                {'multi_data_id': 1, 'data': [{'name': 'a', 'value': 1, 'type': 'text'}]},
                {'multi_data_id': 2, 'data': [{'name': 'a', 'value': 2, 'type': 'text'}]},
            ],
        }]

    def test_removes_named_row_only(self) -> None:
        """The named row is removed; the other row and section are kept."""
        result = delete_patch_multi_data_rows(self._stored(), [{'section_id': 's1', 'multi_data_id': 2}])

        assert {row['multi_data_id'] for row in result[0]['values']} == {1}

    def test_deleting_last_row_keeps_empty_section(self) -> None:
        """Deleting every row leaves the section present with an empty values list and its highest_id."""
        result = delete_patch_multi_data_rows(
            self._stored(),
            [{'section_id': 's1', 'multi_data_id': 1}, {'section_id': 's1', 'multi_data_id': 2}],
        )

        assert result[0]['values'] == []
        assert result[0]['highest_id'] == 2

    def test_unknown_section_aborts_400(self) -> None:
        """Deleting from a section the object does not have is refused with 400."""
        with pytest.raises(HTTPException) as exc_info:
            delete_patch_multi_data_rows(self._stored(), [{'section_id': 'sX', 'multi_data_id': 1}])

        assert exc_info.value.code == 400

    def test_unknown_row_aborts_400(self) -> None:
        """Deleting a multi_data_id not present in the section is refused with 400."""
        with pytest.raises(HTTPException) as exc_info:
            delete_patch_multi_data_rows(self._stored(), [{'section_id': 's1', 'multi_data_id': 99}])

        assert exc_info.value.code == 400

    def test_does_not_mutate_input(self) -> None:
        """The stored sections are not modified in place."""
        stored = self._stored()

        delete_patch_multi_data_rows(stored, [{'section_id': 's1', 'multi_data_id': 2}])

        assert {row['multi_data_id'] for row in stored[0]['values']} == {1, 2}


# -------------------------------------------------------------------------------------------------------------------- #
#                                            build_patched_object_data                                                #
# -------------------------------------------------------------------------------------------------------------------- #


class TestBuildPatchedObjectData:
    """build_patched_object_data overlays a validated patch onto the stored object's JSON."""

    def test_merges_fields_and_comment_preserving_identity(self) -> None:
        """Patched field values land on the full object dict; immutable identity is carried through."""
        current = _make_object([{'name': 'a', 'value': 1, 'type': 'text'}], public_id=7)

        result = build_patched_object_data(current, {'fields': [{'name': 'a', 'value': 42}], 'comment': 'note'}, set())

        assert result['public_id'] == 7
        assert result['type_id'] == 1
        assert result['comment'] == 'note'
        field_a = next(field for field in result['fields'] if field['name'] == 'a')
        assert field_a['value'] == 42

    def test_applies_mds_row_deletion(self) -> None:
        """A deleted_mds_rows entry removes the named row from the merged object."""
        current = _make_object([{'name': 'a', 'value': 1, 'type': 'text'}], public_id=7)
        current.multi_data_sections = [{
            'section_id': 's1',
            'highest_id': 2,
            'values': [
                {'multi_data_id': 1, 'data': [{'name': 'a', 'value': 1, 'type': 'text'}]},
                {'multi_data_id': 2, 'data': [{'name': 'a', 'value': 2, 'type': 'text'}]},
            ],
        }]

        result = build_patched_object_data(
            current, {'deleted_mds_rows': [{'section_id': 's1', 'multi_data_id': 2}]}, set()
        )

        section = result['multi_data_sections'][0]
        assert {row['multi_data_id'] for row in section['values']} == {1}


# -------------------------------------------------------------------------------------------------------------------- #
#                                    PATCH new-field type backfill (boundary)                                         #
# -------------------------------------------------------------------------------------------------------------------- #


class TestPatchNewFieldTypeBackfill:
    """A PATCH-added field the stored object lacks is a name+value pair after merge; the shared update
    pipeline then backfills its type from the type schema (or rejects an undeclared field), so no field
    with a missing type is ever persisted. This locks why the merge_patch_fields 2-tuple is safe.
    """

    @staticmethod
    def _manager(type_schema: dict[str, Any]) -> MagicMock:
        """A MagicMock ObjectsManager whose get_object_type returns the given type schema."""
        manager = MagicMock()
        manager.get_object_type.return_value = type_schema
        return manager

    def test_merge_appends_new_field_without_a_type(self) -> None:
        """build_patched_object_data appends a stored-missing field as a name+value pair (no type yet)."""
        current = _make_object([{'name': 'stored', 'value': 1, 'type': 'text'}], public_id=7)

        result = build_patched_object_data(current, {'fields': [{'name': 'fresh', 'value': 5}]}, set())

        fresh = next(field for field in result['fields'] if field['name'] == 'fresh')
        assert 'type' not in fresh

    def test_pipeline_backfills_the_new_field_type(self) -> None:
        """The merged object run through validate_and_fill_object_fields becomes a full name+value+type triple."""
        current = _make_object([{'name': 'stored', 'value': 1, 'type': 'text'}], public_id=7)
        merged = build_patched_object_data(current, {'fields': [{'name': 'fresh', 'value': 5}]}, set())
        manager = self._manager({'fields': [
            {'name': 'stored', 'type': 'text'}, {'name': 'fresh', 'type': 'number'},
        ]})

        validate_and_fill_object_fields(manager, merged)

        fresh = next(field for field in merged['fields'] if field['name'] == 'fresh')
        assert fresh == {'name': 'fresh', 'value': 5, 'type': 'number'}

    def test_pipeline_rejects_new_field_not_declared_by_the_type(self) -> None:
        """A PATCH-added field the type does not declare is rejected 400 (never persisted as a 2-tuple)."""
        current = _make_object([{'name': 'stored', 'value': 1, 'type': 'text'}], public_id=7)
        merged = build_patched_object_data(current, {'fields': [{'name': 'ghost', 'value': 5}]}, set())
        manager = self._manager({'fields': [{'name': 'stored', 'type': 'text'}]})

        with pytest.raises(HTTPException) as exc_info:
            validate_and_fill_object_fields(manager, merged)

        assert exc_info.value.code == 400


# -------------------------------------------------------------------------------------------------------------------- #
#                                              guard_object_delete                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
