# DATAGERRY - OpenSource Enterprise CMDB
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
Unit tests for cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper

Pure tests: no Mongo. The render path patches RenderList at the helper module path; the
validation helper drives a MagicMock ObjectsManager. Only the helpers' own branch logic is
exercised (view dispatch, the type-schema / field-name guards, the special_type comparison)
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper import (
    render_or_native,
    is_special_type_changed,
    validate_and_fill_object_fields,
    guard_object_write_license,
    guard_object_delete_license,
    to_normalized_cmdb_object,
    build_new_object_data,
    compute_object_version,
    emit_object_update_events,
    apply_object_update,
    sync_select_field_options,
    handle_delete_object_location,
    handle_delete_location_and_child_locations,
    build_type_object_counts,
    handle_sync_config_item_count,
    validate_object_patch_payload,
    merge_patch_fields,
    create_patch_multi_data_rows,
    edit_patch_multi_data_rows,
    delete_patch_multi_data_rows,
    build_patched_object_data,
    guard_object_delete,
    emit_object_state_change_events,
    realign_objects_to_type,
    clean_type_reports,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import ObjectViewMode
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper'


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


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 render_or_native                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRenderOrNative:
    """render_or_native dispatches on the view mode and rejects unknown views with 400."""

    def test_native_returns_object_dicts(self) -> None:
        """The native view returns each object's __dict__ unchanged."""
        objects = [SimpleNamespace(public_id=1), SimpleNamespace(public_id=2)]

        result = render_or_native(ObjectViewMode.NATIVE, objects, MagicMock())

        assert result == [{'public_id': 1}, {'public_id': 2}]

    def test_render_delegates_to_render_list(self) -> None:
        """The render view delegates to RenderList(...).render_result_list(raw=True)."""
        objects = [SimpleNamespace()]

        with patch(f'{HELPER_PATH}.RenderList') as render_list_ctor:
            render_list_ctor.return_value.render_result_list.return_value = ['rendered']

            result = render_or_native(ObjectViewMode.RENDER, objects, MagicMock())

        assert result == ['rendered']
        render_list_ctor.return_value.render_result_list.assert_called_once_with(raw=True)

    def test_unknown_view_aborts_400(self) -> None:
        """An unrecognised view mode aborts with HTTP 400."""
        with pytest.raises(HTTPException) as exc_info:
            render_or_native('something-else', [], MagicMock())

        assert exc_info.value.code == 400


# -------------------------------------------------------------------------------------------------------------------- #
#                                              is_special_type_changed                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIsSpecialTypeChanged:
    """is_special_type_changed reports a difference between two special_type values."""

    @pytest.mark.parametrize('old,new,expected', [
        (None, None, False),
        ('SUBNET', 'SUBNET', False),
        (None, 'SUBNET', True),
        ('SUBNET', None, True),
        ('SUBNET', 'VLAN', True),
        # Falsy values all mean "no special type" and must be treated as equivalent
        ('', None, False),   # stored empty-string vs omitted payload key (the Update-Error report)
        (None, '', False),
        ('', '', False),
        ('', 'SUBNET', True),
        ('SUBNET', '', True),
    ])
    def test_difference_detection(self, old: Any, new: Any, expected: bool) -> None:
        """Returns True only when the two values differ (falsy values normalised to 'no special type')."""
        assert is_special_type_changed(old, new) is expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                          validate_and_fill_object_fields                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestValidateAndFillObjectFields:
    """validate_and_fill_object_fields guards type / field validity and backfills the field type."""

    @staticmethod
    def _manager(type_schema: dict[str, Any] | None) -> MagicMock:
        """A MagicMock ObjectsManager whose get_object_type returns the given schema."""
        manager = MagicMock()
        manager.get_object_type.return_value = type_schema
        return manager

    def test_missing_type_id_aborts_400(self) -> None:
        """An object payload without type_id is rejected with 400."""
        with pytest.raises(HTTPException) as exc_info:
            validate_and_fill_object_fields(self._manager({'fields': []}), {'fields': []})

        assert exc_info.value.code == 400

    def test_missing_type_schema_aborts_400(self) -> None:
        """When the type cannot be resolved the request is rejected with 400 (not a 500 crash)."""
        with pytest.raises(HTTPException) as exc_info:
            validate_and_fill_object_fields(self._manager(None), {'type_id': 5, 'fields': []})

        assert exc_info.value.code == 400

    def test_unknown_field_aborts_400(self) -> None:
        """A field not declared by the type is rejected with 400."""
        manager = self._manager({'fields': [{'name': 'known', 'type': 'text'}]})

        with pytest.raises(HTTPException) as exc_info:
            validate_and_fill_object_fields(manager, {'type_id': 5, 'fields': [{'name': 'ghost', 'value': 'x'}]})

        assert exc_info.value.code == 400

    def test_backfills_missing_field_type(self) -> None:
        """A field present in the type but missing its 'type' key gets the type backfilled in place."""
        manager = self._manager({'fields': [{'name': 'known', 'type': 'text'}]})
        object_data = {'type_id': 5, 'fields': [{'name': 'known', 'value': 'x'}]}

        validate_and_fill_object_fields(manager, object_data)

        assert object_data['fields'][0]['type'] == 'text'

    def test_validates_multi_data_section_rows(self) -> None:
        """MDS row fields are validated too: an unknown MDS field aborts with 400."""
        manager = self._manager({'fields': [{'name': 'known', 'type': 'text'}]})
        object_data = {
            'type_id': 5,
            'fields': [{'name': 'known', 'type': 'text', 'value': 'x'}],
            'multi_data_sections': [{'values': [{'data': [{'name': 'ghost', 'value': 'y'}]}]}],
        }

        with pytest.raises(HTTPException) as exc_info:
            validate_and_fill_object_fields(manager, object_data)

        assert exc_info.value.code == 400


# -------------------------------------------------------------------------------------------------------------------- #
#                                          guard_object_write_license                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGuardObjectWriteLicense:
    """guard_object_write_license delegates to the IPAM license guard only for gated writes."""

    def test_aborts_when_write_requires_license(self) -> None:
        """A gated write (special-type / interface-subnet) is handed to the license guard."""
        request_user = MagicMock()

        with patch(f'{HELPER_PATH}.object_write_requires_ipam_license', return_value=True), \
             patch(f'{HELPER_PATH}.abort_if_feature_locked') as guard:
            guard_object_write_license(MagicMock(), request_user, {}, None)

        guard.assert_called_once_with(LicenseFeature.IPAM, request_user)

    def test_noop_when_write_not_gated(self) -> None:
        """A write that touches no IPAM surface never consults the license guard."""
        with patch(f'{HELPER_PATH}.object_write_requires_ipam_license', return_value=False), \
             patch(f'{HELPER_PATH}.abort_if_feature_locked') as guard:
            guard_object_write_license(MagicMock(), MagicMock(), {}, None)

        guard.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                          guard_object_delete_license                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGuardObjectDeleteLicense:
    """guard_object_delete_license delegates to the IPAM license guard only for special-type targets."""

    def test_aborts_when_delete_requires_license(self) -> None:
        """Deleting a special-type object is handed to the license guard."""
        request_user = MagicMock()

        with patch(f'{HELPER_PATH}.object_delete_requires_ipam_license', return_value=True), \
             patch(f'{HELPER_PATH}.abort_if_feature_locked') as guard:
            guard_object_delete_license(MagicMock(), request_user, {})

        guard.assert_called_once_with(LicenseFeature.IPAM, request_user)

    def test_noop_when_delete_not_gated(self) -> None:
        """Deleting an ordinary object never consults the license guard."""
        with patch(f'{HELPER_PATH}.object_delete_requires_ipam_license', return_value=False), \
             patch(f'{HELPER_PATH}.abort_if_feature_locked') as guard:
            guard_object_delete_license(MagicMock(), MagicMock(), {})

        guard.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                              to_normalized_cmdb_object                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestToNormalizedCmdbObject:
    """to_normalized_cmdb_object rebuilds a CmdbObject from a payload via a BSON-safe round-trip."""

    def test_builds_cmdb_object_preserving_core_fields(self) -> None:
        """The returned CmdbObject carries the payload's type_id and fields (datetimes survive)."""
        payload = {
            'public_id': 4,
            'type_id': 7,
            'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc),
            'author_id': 3,
            'active': True,
            'fields': [{'name': 'a', 'value': 1, 'type': 'text'}],
        }

        result = to_normalized_cmdb_object(payload)

        assert isinstance(result, CmdbObject)
        assert result.type_id == 7
        assert result.fields == [{'name': 'a', 'value': 1, 'type': 'text'}]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                build_new_object_data                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildNewObjectData:
    """build_new_object_data normalises the insert payload (id / type / defaults / version)."""

    @staticmethod
    def _manager(new_id: int = 111, existing: Any = None, object_type: Any = 'a-type') -> MagicMock:
        """A MagicMock ObjectsManager driving the id / existence / type-resolution branches."""
        manager = MagicMock()
        manager.get_new_object_public_id.return_value = new_id
        manager.get_object.return_value = existing
        manager.get_object_type.return_value = object_type
        return manager

    def test_assigns_new_public_id_and_defaults(self) -> None:
        """Without a supplied public_id a fresh id is assigned and active / version / time defaulted."""
        manager = self._manager(new_id=111)

        with patch(f'{HELPER_PATH}.validate_and_fill_object_fields') as validate:
            new_data, object_type = build_new_object_data(manager, {'type_id': 5, 'fields': []})

        assert new_data['public_id'] == 111
        assert new_data['active'] is True
        assert new_data['version'] == '1.0.0'
        assert 'creation_time' in new_data
        assert object_type == 'a-type'
        validate.assert_called_once()

    def test_supplied_existing_public_id_aborts_400(self) -> None:
        """A supplied public_id that already exists is rejected with 400."""
        manager = self._manager(existing={'public_id': 9})

        with patch(f'{HELPER_PATH}.validate_and_fill_object_fields'):
            with pytest.raises(HTTPException) as exc_info:
                build_new_object_data(manager, {'public_id': 9, 'type_id': 5, 'fields': []})

        assert exc_info.value.code == 400

    def test_unknown_type_aborts_404(self) -> None:
        """When the referenced type does not exist the request is rejected with 404."""
        manager = self._manager(object_type=None)

        with patch(f'{HELPER_PATH}.validate_and_fill_object_fields'):
            with pytest.raises(HTTPException) as exc_info:
                build_new_object_data(manager, {'type_id': 5, 'fields': []})

        assert exc_info.value.code == 404

    def test_preserves_supplied_active_flag(self) -> None:
        """An explicit active flag in the payload is preserved (not overwritten to True)."""
        manager = self._manager()

        with patch(f'{HELPER_PATH}.validate_and_fill_object_fields'):
            new_data, _ = build_new_object_data(manager, {'type_id': 5, 'active': False, 'fields': []})

        assert new_data['active'] is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                               compute_object_version                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestComputeObjectVersion:
    """compute_object_version picks the version bump from the field-level diff size."""

    @pytest.mark.parametrize('field_count,changed_count,expected_attr', [
        (3, 1, 'VERSIONING_PATCH'),   # a single changed field is a patch
        (3, 3, 'VERSIONING_MAJOR'),   # all fields changed is a major
        (4, 3, 'VERSIONING_MINOR'),   # more than half (but not all) is a minor
        (4, 2, 'VERSIONING_PATCH'),   # not >half, not all, not one -> patch
    ])
    def test_bump_selection(self, field_count: int, changed_count: int, expected_attr: str) -> None:
        """The correct VERSIONING_* constant is passed to update_version for each diff size."""
        base_fields = [{'name': f'f{i}', 'value': i} for i in range(field_count)]
        current = _make_object(base_fields)

        updated_fields = [dict(field) for field in base_fields]
        for i in range(changed_count):
            updated_fields[i] = {'name': f'f{i}', 'value': 1000 + i}
        updated = _make_object(updated_fields)

        updated.update_version = MagicMock(return_value='bumped')

        new_version, changes = compute_object_version(current, updated)

        assert new_version == 'bumped'
        assert len(changes['new']) == changed_count
        updated.update_version.assert_called_once_with(getattr(CmdbObject, expected_attr))


# -------------------------------------------------------------------------------------------------------------------- #
#                                             emit_object_update_events                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestEmitObjectUpdateEvents:
    """emit_object_update_events fires the webhook and writes the edit log, each best-effort."""

    def test_emits_webhook_and_log(self) -> None:
        """Both the update webhook and the edit log are produced on the happy path."""
        logs_manager = MagicMock()
        before = _make_object([{'name': 'a', 'value': 1}])
        after = _make_object([{'name': 'a', 'value': 2}])
        updated = _make_object([{'name': 'a', 'value': 2}])

        with patch(f'{HELPER_PATH}.send_webhook_event') as webhook:
            emit_object_update_events(MagicMock(), logs_manager, before, after, updated, {'new': []}, "note")

        webhook.assert_called_once()
        logs_manager.insert_log.assert_called_once()

    def test_webhook_failure_does_not_block_log(self) -> None:
        """A webhook error is swallowed and the edit log is still written."""
        logs_manager = MagicMock()
        obj = _make_object([{'name': 'a', 'value': 1}])

        with patch(f'{HELPER_PATH}.send_webhook_event', side_effect=RuntimeError("boom")):
            emit_object_update_events(MagicMock(), logs_manager, obj, obj, obj, {'new': []}, "")

        logs_manager.insert_log.assert_called_once()

    def test_log_failure_is_swallowed(self) -> None:
        """A logging error never propagates out of the helper."""
        logs_manager = MagicMock()
        logs_manager.insert_log.side_effect = RuntimeError("boom")
        obj = _make_object([{'name': 'a', 'value': 1}])

        with patch(f'{HELPER_PATH}.send_webhook_event'):
            emit_object_update_events(MagicMock(), logs_manager, obj, obj, obj, {'new': []}, "")  # must not raise


# -------------------------------------------------------------------------------------------------------------------- #
#                                              sync_select_field_options                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSyncSelectFieldOptions:
    """sync_select_field_options appends new free-text select values back onto the CmdbType."""

    @staticmethod
    def _object_type() -> MagicMock:
        """A type carrying one select field 'os' whose only known option is 'Windows'."""
        object_type = MagicMock()
        object_type.public_id = 1
        object_type.get_fields_with_type.return_value = {
            'os': {'name': 'os', 'type': FieldType.SELECT, 'options': [{'name': 'Windows', 'label': 'Windows'}]}
        }
        object_type.fields = [
            {'name': 'os', 'type': FieldType.SELECT, 'options': [{'name': 'Windows', 'label': 'Windows'}]}
        ]
        return object_type

    def test_new_value_is_appended_and_type_persisted(self) -> None:
        """An object select value unknown to the type is added as a new option and the type saved."""
        object_type = self._object_type()
        target_object = SimpleNamespace(
            fields=[{'name': 'os', 'type': FieldType.SELECT, 'value': 'Linux'}],
            multi_data_sections=[],
        )
        types_manager = MagicMock()

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=types_manager):
            sync_select_field_options(MagicMock(), target_object, object_type)

        types_manager.update_type.assert_called_once()
        assert {opt['name'] for opt in object_type.fields[0]['options']} == {'Windows', 'Linux'}

    def test_known_value_does_not_persist(self) -> None:
        """When every select value is already a known option the type is not written."""
        object_type = self._object_type()
        target_object = SimpleNamespace(
            fields=[{'name': 'os', 'type': FieldType.SELECT, 'value': 'Windows'}],
            multi_data_sections=[],
        )
        types_manager = MagicMock()

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=types_manager):
            sync_select_field_options(MagicMock(), target_object, object_type)

        types_manager.update_type.assert_not_called()

    def test_new_value_from_mds_row_is_appended(self) -> None:
        """A new select value carried inside a multi-data-section row is also captured."""
        object_type = self._object_type()
        target_object = SimpleNamespace(
            fields=[],
            multi_data_sections=[{'values': [{'data': [{'name': 'os', 'type': FieldType.SELECT, 'value': 'Linux'}]}]}],
        )
        types_manager = MagicMock()

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=types_manager):
            sync_select_field_options(MagicMock(), target_object, object_type)

        types_manager.update_type.assert_called_once()


# -------------------------------------------------------------------------------------------------------------------- #
#                                             handle_delete_object_location                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestHandleDeleteObjectLocation:
    """handle_delete_object_location deletes a childless location and refuses a parent one with 400."""

    def test_deletes_childless_location(self) -> None:
        """A location with no children is removed."""
        locations_manager = MagicMock()
        locations_manager.get_location_for_object.return_value = {'public_id': 50}
        locations_manager.get_one_by.return_value = None

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=locations_manager):
            handle_delete_object_location(MagicMock(), 5)

        locations_manager.delete_location.assert_called_once_with(50)

    def test_parent_location_aborts_400(self) -> None:
        """A location that still parents other locations is refused with 400 (business rule)."""
        locations_manager = MagicMock()
        locations_manager.get_location_for_object.return_value = {'public_id': 50}
        locations_manager.get_one_by.return_value = [{'public_id': 60}]

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=locations_manager):
            with pytest.raises(HTTPException) as exc_info:
                handle_delete_object_location(MagicMock(), 5)

        assert exc_info.value.code == 400
        locations_manager.delete_location.assert_not_called()

    def test_no_location_is_noop(self) -> None:
        """When the object has no location nothing is deleted."""
        locations_manager = MagicMock()
        locations_manager.get_location_for_object.return_value = None

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=locations_manager):
            handle_delete_object_location(MagicMock(), 5)

        locations_manager.delete_location.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                     handle_delete_location_and_child_locations                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestHandleDeleteLocationAndChildLocations:
    """The helper deletes the location subtree and returns the surviving child objects' ids."""

    def test_returns_descendant_object_ids_and_deletes_subtree(self) -> None:
        """Descendant location object_ids are returned; child locations and own location are deleted."""
        locations_manager = MagicMock()
        locations_manager.get_location_for_object.return_value = {'public_id': 50, 'object_id': 5}
        descendants = [
            {'public_id': 51, 'object_id': 6},
            {'public_id': 52, 'object_id': 7},
        ]
        locations_manager.get_all_descendant_locations.return_value = descendants

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=locations_manager):
            result = handle_delete_location_and_child_locations(MagicMock(), 5)

        assert result == [6, 7]
        locations_manager.delete_locations.assert_called_once_with(descendants)
        locations_manager.delete_location.assert_called_once_with(50)

    def test_no_location_returns_empty_list(self) -> None:
        """When the object has no location the helper returns [] and deletes nothing."""
        locations_manager = MagicMock()
        locations_manager.get_location_for_object.return_value = None

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=locations_manager):
            result = handle_delete_location_and_child_locations(MagicMock(), 5)

        assert result == []
        locations_manager.delete_location.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                apply_object_update                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestApplyObjectUpdate:
    """apply_object_update guards the per-object update before touching the write path."""

    def test_missing_object_aborts_404(self) -> None:
        """A target object that no longer exists aborts with 404 before any write."""
        objects_manager = MagicMock()
        objects_manager.get_object.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            apply_object_update(5, {'fields': []}, None, MagicMock(),
                                objects_manager, MagicMock(), MagicMock())

        assert exc_info.value.code == 404
        objects_manager.update_object.assert_not_called()

    def test_special_type_change_aborts_400(self) -> None:
        """Changing an object's special_type is refused with 400."""
        objects_manager = MagicMock()
        objects_manager.get_object.return_value = _make_object([{'name': 'a', 'value': 1}], special_type='SUBNET')

        with pytest.raises(HTTPException) as exc_info:
            apply_object_update(5, {'fields': [], 'special_type': 'VLAN'}, None, MagicMock(),
                                objects_manager, MagicMock(), MagicMock())

        assert exc_info.value.code == 400
        objects_manager.update_object.assert_not_called()

    def test_missing_type_aborts_500(self) -> None:
        """When the object's type cannot be resolved the update aborts with 500."""
        objects_manager = MagicMock()
        objects_manager.get_object.return_value = _make_object([{'name': 'a', 'value': 1}])
        objects_manager.get_object_type.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            apply_object_update(5, {'fields': []}, None, MagicMock(),
                                objects_manager, MagicMock(), MagicMock())

        assert exc_info.value.code == 500
        objects_manager.update_object.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                             build_type_object_counts                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildTypeObjectCounts:
    """build_type_object_counts joins the per-type object counts with each CmdbType's label."""

    def test_maps_counts_to_type_labels(self) -> None:
        """Each counted type_id is resolved to its label and paired with the object count."""
        objects_manager = MagicMock()
        objects_manager.count_objects_grouped_by_type.return_value = {1: 30, 2: 12}
        types_manager = MagicMock()
        types_manager.get_types_lookup.return_value = {
            1: SimpleNamespace(label='Server'),
            2: SimpleNamespace(label='Client'),
        }

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=[objects_manager, types_manager]):
            result = build_type_object_counts(MagicMock())

        assert result == [{'name': 'Server', 'count': 30}, {'name': 'Client', 'count': 12}]

    def test_no_objects_returns_empty_without_type_lookup(self) -> None:
        """With no objects the helper returns [] and never queries the type lookup."""
        objects_manager = MagicMock()
        objects_manager.count_objects_grouped_by_type.return_value = {}
        types_manager = MagicMock()

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=[objects_manager, types_manager]):
            result = build_type_object_counts(MagicMock())

        assert not result
        types_manager.get_types_lookup.assert_not_called()

    def test_skips_type_missing_from_lookup(self) -> None:
        """A counted type_id whose CmdbType no longer exists is skipped, not emitted with no label."""
        objects_manager = MagicMock()
        objects_manager.count_objects_grouped_by_type.return_value = {1: 30, 99: 5}
        types_manager = MagicMock()
        types_manager.get_types_lookup.return_value = {1: SimpleNamespace(label='Server')}

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=[objects_manager, types_manager]):
            result = build_type_object_counts(MagicMock())

        assert result == [{'name': 'Server', 'count': 30}]


# -------------------------------------------------------------------------------------------------------------------- #
#                                          handle_sync_config_item_count                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestHandleSyncConfigItemCount:
    """handle_sync_config_item_count forwards the count plus the per-type breakdown to the portal."""

    def test_passes_count_and_type_breakdown_to_manager(self) -> None:
        """The built type-count list is passed straight into DgServicePortalManager.sync_config_items."""
        request_user = MagicMock()
        manager_instance = MagicMock()
        type_counts = [{'name': 'Server', 'count': 30}]

        with patch(f'{HELPER_PATH}.build_type_object_counts', return_value=type_counts), \
             patch(f'{HELPER_PATH}.DgServicePortalManager', return_value=manager_instance):
            handle_sync_config_item_count(request_user, 42)

        manager_instance.sync_config_items.assert_called_once_with(request_user, 42, type_counts)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          validate_object_patch_payload                                              #
# -------------------------------------------------------------------------------------------------------------------- #
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
class TestGuardObjectDelete:
    """guard_object_delete combines the IPAM license guard and the IPAM delete invariants."""

    def test_passes_when_no_license_gate_and_no_invariant_errors(self) -> None:
        """A non-gated object with no dangling references is a no-op (no abort)."""
        with patch(f'{HELPER_PATH}.guard_object_delete_license') as license_guard, \
             patch(f'{HELPER_PATH}.enforce_delete_guards', return_value=[]) as delete_guards:
            guard_object_delete(MagicMock(), MagicMock(), MagicMock(), {'public_id': 1})

        license_guard.assert_called_once()
        delete_guards.assert_called_once()

    def test_aborts_400_on_invariant_violation(self) -> None:
        """A non-empty delete-guard error list aborts with 400."""
        with patch(f'{HELPER_PATH}.guard_object_delete_license'), \
             patch(f'{HELPER_PATH}.enforce_delete_guards', return_value=[{'error': 'still referenced'}]), \
             patch(f'{HELPER_PATH}.format_errors_for_abort', return_value='still referenced'):
            with pytest.raises(HTTPException) as exc_info:
                guard_object_delete(MagicMock(), MagicMock(), MagicMock(), {'public_id': 1})

        assert exc_info.value.code == 400


# -------------------------------------------------------------------------------------------------------------------- #
#                                        emit_object_state_change_events                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestEmitObjectStateChangeEvents:
    """emit_object_state_change_events emits the UPDATE webhook and writes the ACTIVE_CHANGE log."""

    def _objects(self) -> tuple[CmdbObject, CmdbObject]:
        """Builds a before/after CmdbObject pair for the state-change events."""
        before = _make_object([{'name': 'a', 'value': 1, 'type': 'text'}], public_id=5)
        after = _make_object([{'name': 'a', 'value': 1, 'type': 'text'}], public_id=5)
        return before, after

    def test_emits_webhook_and_writes_log(self) -> None:
        """The webhook fires and an ACTIVE_CHANGE log is inserted with the old/new change dict."""
        before, after = self._objects()
        logs_manager = MagicMock()

        with patch(f'{HELPER_PATH}.send_webhook_event') as webhook:
            emit_object_state_change_events(MagicMock(), logs_manager, before, after, {'rendered': True}, True)

        webhook.assert_called_once()
        logs_manager.insert_log.assert_called_once()
        assert logs_manager.insert_log.call_args.kwargs['changes'] == {'old': False, 'new': True}

    def test_webhook_failure_does_not_block_log(self) -> None:
        """A webhook exception is swallowed; the log is still written."""
        before, after = self._objects()
        logs_manager = MagicMock()

        with patch(f'{HELPER_PATH}.send_webhook_event', side_effect=RuntimeError('boom')):
            emit_object_state_change_events(MagicMock(), logs_manager, before, after, {'rendered': True}, False)

        logs_manager.insert_log.assert_called_once()


# -------------------------------------------------------------------------------------------------------------------- #
#                                            realign_objects_to_type                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRealignObjectsToType:
    """realign_objects_to_type drops stale fields, adds missing ones, returns removed names."""

    @staticmethod
    def _type(fields: list[dict[str, Any]], public_id: int = 1) -> SimpleNamespace:
        """A CmdbType stand-in exposing only .fields and .public_id."""
        return SimpleNamespace(fields=fields, public_id=public_id)

    @staticmethod
    def _object(field_names: list[str], public_id: int) -> MagicMock:
        """A CmdbObject stand-in whose get_all_fields returns name-only field dicts."""
        obj = MagicMock()
        obj.public_id = public_id
        obj.get_all_fields.return_value = [{'name': name} for name in field_names]
        return obj

    def test_removes_stale_and_adds_missing(self) -> None:
        """An object with a stale field and a missing field yields one bulk write + the removed name."""
        objects_manager = MagicMock()
        objects_manager.get_objects_by.return_value = [self._object(['keep', 'stale'], public_id=11)]

        type_instance = self._type([
            {'name': 'keep', 'type': 'text'},
            {'name': 'added', 'type': 'text', 'value': 'def'},
        ])

        removed = realign_objects_to_type(objects_manager, type_instance)

        assert removed == {'stale'}
        objects_manager.bulk_write.assert_called_once()

    def test_no_drift_writes_nothing(self) -> None:
        """An object already matching the type produces no bulk write and an empty removed set."""
        objects_manager = MagicMock()
        objects_manager.get_objects_by.return_value = [self._object(['keep'], public_id=12)]

        removed = realign_objects_to_type(objects_manager, self._type([{'name': 'keep', 'type': 'text'}]))

        assert removed == set()
        objects_manager.bulk_write.assert_not_called()

    def test_bulk_write_failure_aborts_500(self) -> None:
        """A bulk-write failure surfaces as a 500."""
        objects_manager = MagicMock()
        objects_manager.get_objects_by.return_value = [self._object(['stale'], public_id=13)]
        objects_manager.bulk_write.side_effect = RuntimeError('boom')

        with pytest.raises(HTTPException) as exc_info:
            realign_objects_to_type(objects_manager, self._type([{'name': 'keep', 'type': 'text'}]))

        assert exc_info.value.code == 500


# -------------------------------------------------------------------------------------------------------------------- #
#                                               clean_type_reports                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCleanTypeReports:
    """clean_type_reports strips removed fields from a type's reports and bulk-writes them."""

    def test_noop_when_nothing_removed(self) -> None:
        """No removed field names means no report write."""
        reports_manager = MagicMock()

        clean_type_reports(reports_manager, [{'public_id': 1}], set(), MagicMock())

        reports_manager.bulk_write.assert_not_called()

    def test_cleans_and_writes_reports(self) -> None:
        """Each report has the removed field stripped, its query rebuilt, and is bulk-written."""
        reports_manager = MagicMock()
        report = MagicMock()

        with patch(f'{HELPER_PATH}.CmdbReport') as report_cls, \
             patch(f'{HELPER_PATH}.build_report_query', return_value={}):
            report_cls.from_data.return_value = report
            clean_type_reports(reports_manager, [{'public_id': 1}], {'gone'}, MagicMock())

        report.remove_field_occurences.assert_called_once_with('gone')
        reports_manager.bulk_write.assert_called_once()
