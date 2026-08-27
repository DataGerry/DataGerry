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
from flask import Flask
from werkzeug.exceptions import BadRequest, HTTPException

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
    collect_unknown_select_values,
    guard_predefined_select_options,
    handle_delete_object_location,
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
    delete_one_cascade,
    RELATION_DELETE_LOG_PROJECTION,
    guard_config_item_limit,
    handle_create_object_log,
    handle_delete_invalid_object_relations,
    handle_notify_webhooks,
    render_single_object,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import ObjectViewMode
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.errors.manager.reports_manager import ReportsManagerUpdateError
# -------------------------------------------------------------------------------------------------------------------- #

HTTP_INTERNAL_SERVER_ERROR: int = 500

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper'


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """Minimal app carrying the cloud_mode flag the cloud-only guards branch on."""
    app = Flask(__name__)
    app.cloud_mode = False

    return app

# A select field owned by a predefined section template: its options may not be extended by a write
PREDEFINED_TEMPLATE: str = 'dg-ipam-interface'
PROTECTED_SELECT_FIELD: str = 'dg-interface-type'


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
        object_type.global_template_ids = []  # no global section template -> nothing is protected
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

    def test_a_predefined_template_select_field_is_never_extended(self) -> None:
        """A select field owned by a predefined section template is skipped, so the type is not written."""
        object_type = self._object_type()
        target_object = SimpleNamespace(
            fields=[{'name': 'os', 'type': FieldType.SELECT, 'value': 'Linux'}],
            multi_data_sections=[],
        )
        types_manager = MagicMock()

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=types_manager), \
             patch(f'{HELPER_PATH}.resolve_predefined_select_fields', return_value={'os': PREDEFINED_TEMPLATE}):
            sync_select_field_options(MagicMock(), target_object, object_type)

        types_manager.update_type.assert_not_called()
        assert {opt['name'] for opt in object_type.fields[0]['options']} == {'Windows'}


# -------------------------------------------------------------------------------------------------------------------- #
#                                            collect_unknown_select_values                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCollectUnknownSelectValues:
    """collect_unknown_select_values reports the select values a type does not offer yet."""

    TYPE_SELECT_FIELDS: dict[str, Any] = {
        'os': {'name': 'os', 'type': FieldType.SELECT, 'options': [{'name': 'Windows', 'label': 'Windows'}]},
    }

    def test_unknown_top_level_value_is_collected(self) -> None:
        """A regular field's unknown value is reported under its field name."""
        fields = [{'name': 'os', 'type': FieldType.SELECT, 'value': 'Linux'}]

        assert collect_unknown_select_values(fields, None, self.TYPE_SELECT_FIELDS) == {'os': {'Linux'}}

    def test_unknown_mds_row_value_is_collected(self) -> None:
        """An MDS row's unknown value is reported the same way."""
        mds = [{'values': [{'data': [{'name': 'os', 'type': FieldType.SELECT, 'value': 'Linux'}]}]}]

        assert collect_unknown_select_values([], mds, self.TYPE_SELECT_FIELDS) == {'os': {'Linux'}}

    def test_known_value_is_ignored(self) -> None:
        """A value the type already offers is not reported."""
        fields = [{'name': 'os', 'type': FieldType.SELECT, 'value': 'Windows'}]

        assert collect_unknown_select_values(fields, [], self.TYPE_SELECT_FIELDS) == {}

    @pytest.mark.parametrize('value', [None, '', [], {}])
    def test_empty_value_is_ignored(self, value: Any) -> None:
        """An empty value never becomes an option."""
        fields = [{'name': 'os', 'type': FieldType.SELECT, 'value': value}]

        assert collect_unknown_select_values(fields, [], self.TYPE_SELECT_FIELDS) == {}

    def test_field_the_type_does_not_define_is_ignored(self) -> None:
        """A select entry naming a field the type has no select definition for is skipped."""
        fields = [{'name': 'other', 'type': FieldType.SELECT, 'value': 'x'}]

        assert collect_unknown_select_values(fields, [], self.TYPE_SELECT_FIELDS) == {}

    def test_non_select_entry_is_ignored(self) -> None:
        """Only select entries are inspected."""
        fields = [{'name': 'os', 'type': FieldType.TEXT, 'value': 'Linux'}]

        assert collect_unknown_select_values(fields, [], self.TYPE_SELECT_FIELDS) == {}

    def test_missing_field_list_is_tolerated(self) -> None:
        """A payload without fields / multi_data_sections yields nothing."""
        assert collect_unknown_select_values(None, None, self.TYPE_SELECT_FIELDS) == {}


# -------------------------------------------------------------------------------------------------------------------- #
#                                           guard_predefined_select_options                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGuardPredefinedSelectOptions:
    """guard_predefined_select_options refuses a write that would edit a predefined template's field."""

    @staticmethod
    def _object_type() -> MagicMock:
        """A type whose select field 'dg-interface-type' only offers 'ipv4' / 'ipv6'."""
        object_type = MagicMock()
        object_type.public_id = 1
        object_type.global_template_ids = [PREDEFINED_TEMPLATE]
        object_type.get_fields_with_type.return_value = {
            PROTECTED_SELECT_FIELD: {
                'name': PROTECTED_SELECT_FIELD,
                'type': FieldType.SELECT,
                'options': [{'name': 'ipv4', 'label': 'IPv4'}, {'name': 'ipv6', 'label': 'IPv6'}],
            },
        }
        return object_type

    def test_unknown_value_aborts_400(self) -> None:
        """An unknown value on the protected field is rejected before the object is written."""
        fields = [{'name': PROTECTED_SELECT_FIELD, 'type': FieldType.SELECT, 'value': 'IPv4'}]

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
             patch(f'{HELPER_PATH}.resolve_predefined_select_fields',
                   return_value={PROTECTED_SELECT_FIELD: PREDEFINED_TEMPLATE}):
            with pytest.raises(HTTPException) as err:
                guard_predefined_select_options(MagicMock(), fields, None, self._object_type())

        assert err.value.code == 400
        assert PREDEFINED_TEMPLATE in err.value.description
        assert 'IPv4' in err.value.description

    def test_unknown_value_in_an_mds_row_aborts_400(self) -> None:
        """The MDS rows of the predefined section are checked too."""
        mds = [{'values': [{'data': [{'name': PROTECTED_SELECT_FIELD,
                                     'type': FieldType.SELECT, 'value': 'IPv6'}]}]}]

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
             patch(f'{HELPER_PATH}.resolve_predefined_select_fields',
                   return_value={PROTECTED_SELECT_FIELD: PREDEFINED_TEMPLATE}):
            with pytest.raises(HTTPException) as err:
                guard_predefined_select_options(MagicMock(), [], mds, self._object_type())

        assert err.value.code == 400

    def test_known_value_passes(self) -> None:
        """A value the predefined template offers is written without complaint."""
        fields = [{'name': PROTECTED_SELECT_FIELD, 'type': FieldType.SELECT, 'value': 'ipv6'}]

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
             patch(f'{HELPER_PATH}.resolve_predefined_select_fields',
                   return_value={PROTECTED_SELECT_FIELD: PREDEFINED_TEMPLATE}):
            guard_predefined_select_options(MagicMock(), fields, None, self._object_type())  # must not raise

    def test_unprotected_field_passes(self) -> None:
        """An unknown value of a normal select field is left to sync_select_field_options."""
        fields = [{'name': PROTECTED_SELECT_FIELD, 'type': FieldType.SELECT, 'value': 'IPv4'}]

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
             patch(f'{HELPER_PATH}.resolve_predefined_select_fields', return_value={}):
            guard_predefined_select_options(MagicMock(), fields, None, self._object_type())  # must not raise

    def test_known_values_only_skips_the_template_lookup(self) -> None:
        """With nothing to add there is nothing to protect - the section templates are not read."""
        fields = [{'name': PROTECTED_SELECT_FIELD, 'type': FieldType.SELECT, 'value': 'ipv4'}]

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager') as get_manager, \
             patch(f'{HELPER_PATH}.resolve_predefined_select_fields') as resolver:
            guard_predefined_select_options(MagicMock(), fields, None, self._object_type())

        get_manager.assert_not_called()
        resolver.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                             handle_delete_object_location                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestHandleDeleteObjectLocation:
    """handle_delete_object_location deletes the object's location, promoting its direct children."""

    def test_deletes_location_via_reparenting_helper(self) -> None:
        """The object's location is handed to the re-parenting delete helper."""
        location = {'public_id': 50, 'parent': 1}
        locations_manager = MagicMock()
        locations_manager.get_location_for_object.return_value = location

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=locations_manager), \
             patch(f'{HELPER_PATH}.delete_location_with_reparenting') as reparent:
            handle_delete_object_location(MagicMock(), 5)

        reparent.assert_called_once()
        assert reparent.call_args.args[0] == location

    def test_no_location_is_noop(self) -> None:
        """When the object has no location nothing is deleted."""
        locations_manager = MagicMock()
        locations_manager.get_location_for_object.return_value = None

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=locations_manager), \
             patch(f'{HELPER_PATH}.delete_location_with_reparenting') as reparent:
            handle_delete_object_location(MagicMock(), 5)

        reparent.assert_not_called()

    def test_passed_in_managers_skip_the_provider_lookup(self) -> None:
        """When both managers are supplied (e.g. a bulk loop) no ManagerProvider lookup happens."""
        location = {'public_id': 50, 'parent': 1}
        locations_manager = MagicMock()
        locations_manager.get_location_for_object.return_value = location
        objects_manager = MagicMock()

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager') as get_manager, \
             patch(f'{HELPER_PATH}.delete_location_with_reparenting') as reparent:
            handle_delete_object_location(MagicMock(), 5, locations_manager, objects_manager)

        get_manager.assert_not_called()
        reparent.assert_called_once_with(location, locations_manager, objects_manager)


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

        assert exc_info.value.code == HTTP_INTERNAL_SERVER_ERROR
        objects_manager.update_object.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                             build_type_object_counts                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildTypeObjectCounts:
    """build_type_object_counts joins the per-type object counts with each CmdbType's label."""

    def test_maps_counts_to_type_labels(self) -> None:
        """Each counted type_id is resolved to its label and paired with the object count."""
        objects_manager = MagicMock()
        objects_manager.count_objects_grouped_by_type_with_total.return_value = ({1: 30, 2: 12}, 42)
        types_manager = MagicMock()
        types_manager.get_types_lookup.return_value = {
            1: SimpleNamespace(label='Server'),
            2: SimpleNamespace(label='Client'),
        }

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=[objects_manager, types_manager]):
            type_counts, total = build_type_object_counts(MagicMock())

        assert type_counts == [{'name': 'Server', 'count': 30}, {'name': 'Client', 'count': 12}]
        assert total == 42

    def test_no_objects_returns_empty_without_type_lookup(self) -> None:
        """With no objects the helper returns [] and never queries the type lookup."""
        objects_manager = MagicMock()
        objects_manager.count_objects_grouped_by_type_with_total.return_value = ({}, 0)
        types_manager = MagicMock()

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=[objects_manager, types_manager]):
            type_counts, total = build_type_object_counts(MagicMock())

        assert not type_counts
        assert total == 0
        types_manager.get_types_lookup.assert_not_called()

    def test_skips_type_missing_from_lookup(self) -> None:
        """A counted type_id whose CmdbType no longer exists is skipped, not emitted with no label."""
        objects_manager = MagicMock()
        objects_manager.count_objects_grouped_by_type_with_total.return_value = ({1: 30, 99: 5}, 35)
        types_manager = MagicMock()
        types_manager.get_types_lookup.return_value = {1: SimpleNamespace(label='Server')}

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=[objects_manager, types_manager]):
            type_counts, total = build_type_object_counts(MagicMock())

        # the skipped type still counts toward the total the portal is told about
        assert type_counts == [{'name': 'Server', 'count': 30}]
        assert total == 35


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

        with patch(f'{HELPER_PATH}.build_type_object_counts', return_value=(type_counts, 30)), \
             patch(f'{HELPER_PATH}.DgServicePortalManager', return_value=manager_instance):
            handle_sync_config_item_count(request_user, 42)

        # an explicitly supplied count wins over the aggregation's total
        manager_instance.sync_config_items.assert_called_once_with(request_user, 42, type_counts)

    def test_derives_the_total_from_the_breakdown_when_no_count_is_given(self) -> None:
        """Omitting the count takes the total from the same aggregation - no extra full-collection count."""
        request_user = MagicMock()
        manager_instance = MagicMock()
        type_counts = [{'name': 'Server', 'count': 30}]

        with patch(f'{HELPER_PATH}.build_type_object_counts', return_value=(type_counts, 31)), \
             patch(f'{HELPER_PATH}.DgServicePortalManager', return_value=manager_instance):
            handle_sync_config_item_count(request_user)

        manager_instance.sync_config_items.assert_called_once_with(request_user, 31, type_counts)


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

        assert exc_info.value.code == HTTP_INTERNAL_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                               clean_type_reports                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCleanTypeReports:
    """clean_type_reports is the route-layer wrapper: it delegates and maps failures to 500.

    The stripping itself lives on ReportsManager (so the section-template removal and the database
    updaters can reuse it) and is covered in tests/unit/manager/test_reports_manager.py.
    """

    def test_delegates_to_the_reports_manager(self) -> None:
        """The arguments are handed straight to the manager operation."""
        reports_manager = MagicMock()
        reports = [{'public_id': 1}]
        type_instance = MagicMock()

        clean_type_reports(reports_manager, reports, {'gone'}, type_instance)

        reports_manager.strip_removed_fields_from_reports.assert_called_once_with(
            reports, {'gone'}, type_instance,
        )

    def test_noop_when_nothing_removed(self) -> None:
        """No removed field names means no report write (the manager short-circuits)."""
        reports_manager = MagicMock()

        clean_type_reports(reports_manager, [{'public_id': 1}], set(), MagicMock())

        reports_manager.bulk_write.assert_not_called()

    def test_manager_failure_maps_to_500(self) -> None:
        """A failed report write surfaces as an internal server error, not as a manager exception."""
        reports_manager = MagicMock()
        reports_manager.strip_removed_fields_from_reports.side_effect = ReportsManagerUpdateError('boom')

        with pytest.raises(HTTPException) as exc_info:
            clean_type_reports(reports_manager, [{'public_id': 1}], {'gone'}, MagicMock())

        assert exc_info.value.code == HTTP_INTERNAL_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                              render_single_object                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRenderSingleObject:
    """render_single_object collapses CmdbMultiRender's union down to RenderResult | None."""

    def test_returns_the_rendered_result(self) -> None:
        """A real RenderResult is handed straight back."""
        rendered = MagicMock(spec=RenderResult)

        with patch(f'{HELPER_PATH}.CmdbMultiRender') as multi_render:
            multi_render.return_value.result.return_value = rendered

            assert render_single_object(MagicMock(), MagicMock()) is rendered

    @pytest.mark.parametrize('produced', [None, [], ['not-a-render-result']])
    def test_anything_that_is_not_a_render_result_becomes_none(self, produced: Any) -> None:
        """None (type gone) and the list shape both collapse to None instead of leaking out."""
        with patch(f'{HELPER_PATH}.CmdbMultiRender') as multi_render:
            multi_render.return_value.result.return_value = produced

            assert render_single_object(MagicMock(), MagicMock()) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                              handle_notify_webhooks                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestHandleNotifyWebhooks:
    """handle_notify_webhooks emits the event and never lets a webhook failure escape."""

    @pytest.mark.parametrize('event_type, expected_kwarg', [
        (WebhookEventType.CREATE, 'object_after'),
        (WebhookEventType.DELETE, 'object_before'),
    ])
    def test_sends_the_event_under_the_right_keyword(self, event_type: Any, expected_kwarg: str) -> None:
        """A create reports the object as 'after', a delete as 'before'."""
        target = MagicMock()

        with patch(f'{HELPER_PATH}.send_webhook_event') as send, \
             patch(f'{HELPER_PATH}.CmdbObject.to_json', return_value={'public_id': 5}):
            handle_notify_webhooks(MagicMock(), target, event_type)

        assert expected_kwarg in send.call_args.kwargs

    def test_a_failing_webhook_is_swallowed(self) -> None:
        """A webhook problem must never roll back or fail the surrounding object operation."""
        with patch(f'{HELPER_PATH}.send_webhook_event', side_effect=RuntimeError('webhook down')), \
             patch(f'{HELPER_PATH}.CmdbObject.to_json', return_value={}):
            handle_notify_webhooks(MagicMock(), MagicMock(), WebhookEventType.CREATE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                             handle_create_object_log                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestHandleCreateObjectLog:
    """handle_create_object_log writes the audit entry, best-effort (discussion-backlog #160)."""

    def test_writes_the_log_entry(self) -> None:
        """The rendered object's id and version land on the persisted log document."""
        logs_manager = MagicMock()
        rendered = MagicMock(spec=RenderResult)
        rendered.object_information = {'object_id': 5, 'version': '1.0.1'}

        with patch(f'{HELPER_PATH}.render_single_object', return_value=rendered), \
             patch(f'{HELPER_PATH}.json.dumps', return_value='{}'), \
             patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=logs_manager):
            handle_create_object_log(MagicMock(), MagicMock(), LogAction.CREATE)

        assert logs_manager.insert_log.call_args.kwargs['object_id'] == 5
        assert logs_manager.insert_log.call_args.kwargs['comment'] == 'Object created'

    def test_a_delete_is_labelled_as_one(self) -> None:
        """The DELETE action gets its own comment."""
        logs_manager = MagicMock()
        rendered = MagicMock(spec=RenderResult)
        rendered.object_information = {'object_id': 5, 'version': '1.0.1'}

        with patch(f'{HELPER_PATH}.render_single_object', return_value=rendered), \
             patch(f'{HELPER_PATH}.json.dumps', return_value='{}'), \
             patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=logs_manager):
            handle_create_object_log(MagicMock(), MagicMock(), LogAction.DELETE)

        assert logs_manager.insert_log.call_args.kwargs['comment'] == 'Object was deleted'

    def test_an_unrenderable_object_writes_no_log(self) -> None:
        """A render that yields nothing is reported and skipped, not dereferenced into an AttributeError."""
        logs_manager = MagicMock()

        with patch(f'{HELPER_PATH}.render_single_object', return_value=None), \
             patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=logs_manager):
            handle_create_object_log(MagicMock(), MagicMock(), LogAction.CREATE)

        logs_manager.insert_log.assert_not_called()

    def test_a_failing_log_write_is_swallowed(self) -> None:
        """A logging problem must never fail the surrounding object operation."""
        logs_manager = MagicMock()
        logs_manager.insert_log.side_effect = RuntimeError('logs collection down')
        rendered = MagicMock(spec=RenderResult)
        rendered.object_information = {'object_id': 5, 'version': '1.0.1'}

        with patch(f'{HELPER_PATH}.render_single_object', return_value=rendered), \
             patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=logs_manager):
            handle_create_object_log(MagicMock(), MagicMock(), LogAction.CREATE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                       handle_delete_invalid_object_relations                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestHandleDeleteInvalidObjectRelations:
    """The relation half of the object-delete cascade: bulk delete plus one log per relation."""

    @staticmethod
    def _managers(relations: list[dict[str, Any]]) -> tuple[MagicMock, MagicMock]:
        """Builds the relation + relation-log managers with the given relations found."""
        relations_manager = MagicMock()
        relations_manager.find.return_value = relations
        relations_manager.get_related_relations_query.return_value = {'$or': []}
        logs_manager = MagicMock()

        return relations_manager, logs_manager

    def test_no_relations_writes_nothing(self) -> None:
        """An object with no relations short-circuits before the delete and the log work."""
        relations_manager, logs_manager = self._managers([])

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=[relations_manager, logs_manager]):
            handle_delete_invalid_object_relations(MagicMock(), 5)

        relations_manager.delete_many_raw.assert_not_called()
        logs_manager.insert_many.assert_not_called()

    def test_reads_back_only_the_keys_the_log_needs(self) -> None:
        """The relations are read with a projection - the full documents are never loaded."""
        relations_manager, logs_manager = self._managers([{'public_id': 1}])
        logs_manager.format_object_relation_log_data.side_effect = [{'a': 1}]
        logs_manager.reserve_public_ids.return_value = [10]

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=[relations_manager, logs_manager]):
            handle_delete_invalid_object_relations(MagicMock(), 5)

        assert relations_manager.find.call_args.kwargs['projection'] == RELATION_DELETE_LOG_PROJECTION

    def test_deletes_and_logs_every_affected_relation(self) -> None:
        """One bulk delete, one reserved id per log, then a single insert_many."""
        relations = [{'public_id': 1}, {'public_id': 2}]
        relations_manager, logs_manager = self._managers(relations)
        logs_manager.format_object_relation_log_data.side_effect = [{'a': 1}, {'b': 2}]
        logs_manager.reserve_public_ids.return_value = [10, 11]

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=[relations_manager, logs_manager]):
            handle_delete_invalid_object_relations(MagicMock(), 5)

        relations_manager.delete_many_raw.assert_called_once_with({'$or': []})
        logs_manager.reserve_public_ids.assert_called_once_with(2)
        logs_manager.insert_many.assert_called_once_with(
            [{'a': 1, 'public_id': 10}, {'b': 2, 'public_id': 11}], skip_public=True,
        )

    def test_a_failing_log_prep_skips_only_that_relation(self) -> None:
        """One unformattable relation must not cost the others their log entry."""
        relations_manager, logs_manager = self._managers([{'public_id': 1}, {'public_id': 2}])
        logs_manager.format_object_relation_log_data.side_effect = [RuntimeError('bad relation'), {'b': 2}]
        logs_manager.reserve_public_ids.return_value = [11]

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=[relations_manager, logs_manager]):
            handle_delete_invalid_object_relations(MagicMock(), 5)

        logs_manager.insert_many.assert_called_once_with([{'b': 2, 'public_id': 11}], skip_public=True)

    def test_every_log_prep_failing_writes_no_logs(self) -> None:
        """The relations are still deleted, but there is nothing to insert."""
        relations_manager, logs_manager = self._managers([{'public_id': 1}])
        logs_manager.format_object_relation_log_data.side_effect = RuntimeError('bad relation')

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=[relations_manager, logs_manager]):
            handle_delete_invalid_object_relations(MagicMock(), 5)

        relations_manager.delete_many_raw.assert_called_once()
        logs_manager.reserve_public_ids.assert_not_called()
        logs_manager.insert_many.assert_not_called()

    def test_a_short_id_reservation_fails_loudly(self) -> None:
        """
        insert_many(skip_public=True) needs a public_id on EVERY document

        Without strict pairing the surplus logs would be inserted with the key missing, which the
        unique index answers with a duplicate-key error on the second null - so the mismatch has to
        surface here instead.
        """
        relations_manager, logs_manager = self._managers([{'public_id': 1}, {'public_id': 2}])
        logs_manager.format_object_relation_log_data.side_effect = [{'a': 1}, {'b': 2}]
        logs_manager.reserve_public_ids.return_value = [10]

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=[relations_manager, logs_manager]):
            with pytest.raises(ValueError):
                handle_delete_invalid_object_relations(MagicMock(), 5)

        logs_manager.insert_many.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                              guard_config_item_limit                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGuardConfigItemLimit:
    """guard_config_item_limit only applies in cloud mode, where subscriptions have a budget."""

    def test_outside_cloud_mode_nothing_is_counted(self, flask_app: Flask) -> None:
        """On-premise has no ConfigItem limit, so the count is never even taken."""
        objects_manager = MagicMock()
        flask_app.cloud_mode = False

        with flask_app.test_request_context('/'):
            guard_config_item_limit(MagicMock(), objects_manager)

        objects_manager.count_documents.assert_not_called()

    def test_below_the_limit_passes(self, flask_app: Flask) -> None:
        """A subscription with budget left is allowed to create another object."""
        flask_app.cloud_mode = True
        request_user = MagicMock()
        request_user.is_config_item_limit_reached.return_value = False

        with flask_app.test_request_context('/'):
            guard_config_item_limit(request_user, MagicMock())

    def test_at_the_limit_aborts_400(self, flask_app: Flask) -> None:
        """A subscription at its ConfigItem limit is refused before the write."""
        flask_app.cloud_mode = True
        request_user = MagicMock()
        request_user.is_config_item_limit_reached.return_value = True

        with flask_app.test_request_context('/'):
            with pytest.raises(HTTPException) as exc_info:
                guard_config_item_limit(request_user, MagicMock())

        assert exc_info.value.code == 400
        assert 'amount' in exc_info.value.description


# -------------------------------------------------------------------------------------------------------------------- #
#                                    the remaining guard / error arms of the helpers                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestHelperErrorArms:
    """The guards and error mappings that only fire when something upstream has already gone wrong."""

    def test_delete_cascade_syncs_the_config_item_count_in_cloud_mode(self, flask_app: Flask) -> None:
        """Cloud mode reports the new total after a delete; on-premise has nothing to report."""
        flask_app.cloud_mode = True
        deleted = MagicMock()

        with flask_app.test_request_context('/'):
            with patch(f'{HELPER_PATH}.handle_delete_object_location'), \
                 patch(f'{HELPER_PATH}.handle_delete_from_object_groups'), \
                 patch(f'{HELPER_PATH}.handle_delete_invalid_object_relations'), \
                 patch(f'{HELPER_PATH}.handle_notify_webhooks'), \
                 patch(f'{HELPER_PATH}.handle_create_object_log'), \
                 patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
                 patch(f'{HELPER_PATH}.handle_sync_config_item_count') as sync:
                delete_one_cascade(MagicMock(), deleted, MagicMock(), LogAction.DELETE)

        # no count is forwarded - the sync derives the total from its own aggregation
        sync.assert_called_once_with(sync.call_args.args[0])

    def test_a_failing_location_delete_becomes_500(self) -> None:
        """An unexpected locations failure is mapped onto a 500 instead of escaping raw."""
        locations_manager = MagicMock()
        locations_manager.get_location_for_object.side_effect = RuntimeError('locations down')

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=locations_manager):
            with pytest.raises(HTTPException) as exc_info:
                handle_delete_object_location(MagicMock(), 5)

        assert exc_info.value.code == 500

    def test_an_http_error_from_the_location_delete_propagates(self) -> None:
        """A 400 raised while re-parenting reaches the client instead of being masked as a 500."""
        locations_manager = MagicMock()
        locations_manager.get_location_for_object.return_value = {'public_id': 50}

        with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=locations_manager), \
             patch(f'{HELPER_PATH}.delete_location_with_reparenting', side_effect=BadRequest('nope')):
            with pytest.raises(HTTPException) as exc_info:
                handle_delete_object_location(MagicMock(), 5)

        assert exc_info.value.code == 400

    def test_a_field_without_a_name_aborts_400(self) -> None:
        """A field entry carrying no 'name' cannot be matched against the type schema."""
        objects_manager = MagicMock()
        objects_manager.get_object_type.return_value = {'fields': [{'name': 'a', 'type': 'text'}]}

        with pytest.raises(HTTPException) as exc_info:
            validate_and_fill_object_fields(objects_manager, {'type_id': 1, 'fields': [{'value': 'x'}]})

        assert exc_info.value.code == 400

    def test_a_patch_field_carrying_a_type_keeps_it(self) -> None:
        """A client that does send a 'type' has it preserved on the appended entry."""
        merged = merge_patch_fields([], [{'name': 'b', 'value': 2, 'type': 'number'}])

        assert merged == [{'name': 'b', 'value': 2, 'type': 'number'}]

    def test_a_failing_state_change_log_is_swallowed(self) -> None:
        """A logging problem must not fail an activate / deactivate that already happened."""
        logs_manager = MagicMock()
        logs_manager.insert_log.side_effect = RuntimeError('logs collection down')
        before = MagicMock()
        before.get_public_id.return_value = 5

        with patch(f'{HELPER_PATH}.send_webhook_event'), \
             patch(f'{HELPER_PATH}.CmdbObject.to_json', return_value={}), \
             patch(f'{HELPER_PATH}.json.dumps', return_value='{}'):
            emit_object_state_change_events(MagicMock(), logs_manager, before, MagicMock(), {}, True)

        logs_manager.insert_log.assert_called_once()


    def test_an_object_that_vanishes_during_the_update_aborts_404(self) -> None:
        """
        The re-read after the write is what the response is built from

        A concurrent delete between the write and the re-read leaves nothing to report, so the update
        answers 404 rather than building a response from a half-known state.
        """
        stored = _make_object([{'name': 'a', 'value': 1, 'type': 'text'}])
        objects_manager = MagicMock()
        # first read: the object being updated; second read (after the write): gone
        objects_manager.get_object.side_effect = [stored, None]
        objects_manager.get_object_type.return_value = {'fields': [{'name': 'a', 'type': 'text'}]}

        with patch(f'{HELPER_PATH}.resolve_object_type', return_value=MagicMock()), \
             patch(f'{HELPER_PATH}.guard_object_write_license'), \
             patch(f'{HELPER_PATH}.enforce_object_write_invariants', return_value=None), \
             patch(f'{HELPER_PATH}.guard_predefined_select_options'), \
             patch(f'{HELPER_PATH}.extract_object_location_parent', return_value=(False, None)), \
             patch(f'{HELPER_PATH}.handle_rack_object_updated'), \
             patch(f'{HELPER_PATH}.to_normalized_cmdb_object', return_value=MagicMock()), \
             patch(f'{HELPER_PATH}.compute_object_version', return_value=('1.0.1', {})):
            with pytest.raises(HTTPException) as exc_info:
                apply_object_update(5, {'type_id': 1, 'fields': [{'name': 'a', 'value': 2}]}, None,
                                    MagicMock(), objects_manager, MagicMock(), MagicMock())

        assert exc_info.value.code == 404
        objects_manager.update_object.assert_called_once()
