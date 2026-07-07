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
