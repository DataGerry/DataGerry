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

from cmdb.manager.objects_propagation_helper import (
    build_add_field_update,
    build_remove_undeclared_fields_update,
)
from cmdb.errors.manager.objects_manager import ObjectsManagerUpdateError
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper import (
    render_or_native,
    build_field_value_map,
    build_mds_value_map,
    build_object_value_view,
    is_special_type_changed,
    validate_and_fill_object_fields,
    validate_required_object_fields,
    guard_object_write_license,
    guard_object_delete_license,
    to_normalized_cmdb_object,
    build_new_object_data,
    compute_object_version,
    apply_object_update,
    sync_select_field_options,
    collect_unknown_select_values,
    guard_predefined_select_options,
    guard_object_delete,
    guard_objects_delete,
    realign_objects_to_type,
    clean_type_reports,
    delete_one_cascade,
    guard_config_item_limit,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_patch_helper import (
    build_patched_object_data,
    create_patch_multi_data_rows,
    delete_patch_multi_data_rows,
    edit_patch_multi_data_rows,
    merge_patch_fields,
    validate_object_patch_payload,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_side_effects_helper import (
    RELATION_DELETE_LOG_PROJECTION,
    build_type_object_counts,
    emit_object_state_change_events,
    emit_object_update_events,
    handle_create_object_log,
    handle_delete_invalid_object_relations,
    handle_delete_object_location,
    handle_notify_webhooks,
    handle_sync_config_item_count,
    render_single_object,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import ObjectViewMode
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType, SectionType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.errors.manager.reports_manager import ReportsManagerUpdateError
from tests.utils.ipam_doc_builders import make_type_doc
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

    def test_values_returns_name_keyed_maps(self) -> None:
        """The values view reshapes each object's fields into a name-keyed map."""
        objects = [SimpleNamespace(public_id=1,
                                   fields=[{'name': 'hostname', 'value': 'srv-01', 'type': 'text'}],
                                   multi_data_sections=[])]

        result = render_or_native(ObjectViewMode.VALUES, objects, MagicMock())

        assert result == [{'public_id': 1, 'fields': {'hostname': 'srv-01'}, 'multi_data_sections': {}}]

    def test_values_never_renders(self) -> None:
        """
        The values view is built from the stored document, never from a render

        Its whole purpose is to skip the renderer, so RenderList must not be constructed - that is
        what makes it cheaper than the render view rather than a reshape on top of it.
        """
        objects = [SimpleNamespace(public_id=1, fields=[], multi_data_sections=[])]

        with patch(f'{HELPER_PATH}.RenderList') as render_list_ctor:
            render_or_native(ObjectViewMode.VALUES, objects, MagicMock())

        render_list_ctor.assert_not_called()

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
#                                          validate_required_object_fields                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestValidateRequiredObjectFields:
    """validate_required_object_fields refuses a write that leaves a required field of the type empty."""

    REQUIRED_FIELD: str = 'req-name'
    OPTIONAL_FIELD: str = 'opt-note'
    ROW_FIELD: str = 'req-row'
    MDS_SECTION: str = 'rows'

    @classmethod
    def _type(cls, required: bool = True) -> CmdbType:
        """A CmdbType with one (optionally required) plain field and one required MDS row field"""
        fields: list[dict[str, Any]] = [
            {'type': FieldType.TEXT.value, 'name': cls.REQUIRED_FIELD, 'label': 'Name', 'required': required},
            {'type': FieldType.TEXT.value, 'name': cls.OPTIONAL_FIELD, 'label': 'Note'},
            {'type': FieldType.TEXT.value, 'name': cls.ROW_FIELD, 'label': 'Row', 'required': required},
        ]
        sections: list[dict[str, Any]] = [
            {
                'type': SectionType.SECTION.value,
                'name': 'information',
                'label': 'Information',
                'fields': [cls.REQUIRED_FIELD, cls.OPTIONAL_FIELD],
            },
            {
                'type': SectionType.MDS_SECTION.value,
                'name': cls.MDS_SECTION,
                'label': 'Rows',
                'fields': [cls.ROW_FIELD],
            },
        ]

        return CmdbType.from_data(make_type_doc(5, 'required-demo', fields=fields, sections=sections))

    def test_a_complete_object_passes(self) -> None:
        """Every required field carrying a value is accepted."""
        object_data = {
            'fields': [{'name': self.REQUIRED_FIELD, 'value': 'x'}],
            'multi_data_sections': [{
                'section_id': self.MDS_SECTION,
                'values': [{'multi_data_id': 1, 'data': [{'name': self.ROW_FIELD, 'value': 'y'}]}],
            }],
        }

        validate_required_object_fields(object_data, self._type())

    def test_a_type_without_required_fields_is_never_rejected(self) -> None:
        """Nothing being required short-circuits the check, whatever the payload carries."""
        validate_required_object_fields({'fields': [{'name': self.REQUIRED_FIELD, 'value': ''}]},
                                        self._type(required=False))

    @pytest.mark.parametrize('fields', [
        [],
        [{'name': 'req-name', 'value': ''}],
        [{'name': 'req-name', 'value': None}],
    ])
    def test_an_empty_or_absent_required_field_aborts_400(self, fields: list[dict[str, Any]]) -> None:
        """A required field the payload leaves empty - or does not carry at all - is a 400."""
        with pytest.raises(HTTPException) as exc_info:
            validate_required_object_fields({'fields': fields}, self._type())

        assert exc_info.value.code == 400
        assert self.REQUIRED_FIELD in exc_info.value.description

    def test_an_empty_required_row_field_aborts_400(self) -> None:
        """A multi-data row leaving its required field empty is a 400 naming the section."""
        object_data = {
            'fields': [{'name': self.REQUIRED_FIELD, 'value': 'x'}],
            'multi_data_sections': [{
                'section_id': self.MDS_SECTION,
                'values': [{'multi_data_id': 1, 'data': [{'name': self.ROW_FIELD, 'value': ''}]}],
            }],
        }

        with pytest.raises(HTTPException) as exc_info:
            validate_required_object_fields(object_data, self._type())

        assert exc_info.value.code == 400
        assert self.MDS_SECTION in exc_info.value.description

    def test_both_scopes_are_reported_in_one_message(self) -> None:
        """A payload failing on both scopes is rejected once, with both messages joined."""
        object_data = {
            'fields': [],
            'multi_data_sections': [{
                'section_id': self.MDS_SECTION,
                'values': [{'multi_data_id': 1, 'data': []}],
            }],
        }

        with pytest.raises(HTTPException) as exc_info:
            validate_required_object_fields(object_data, self._type())

        assert exc_info.value.description.count('Missing value for required field(s)') == 2


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
class TestGuardObjectDelete:
    """guard_object_delete is the one-target form of the shared delete guard."""

    def test_passes_when_no_license_gate_and_no_invariant_errors(self) -> None:
        """A non-gated object with no dangling references is a no-op (no abort)."""
        with patch(f'{HELPER_PATH}.guard_object_delete_license') as license_guard, \
             patch(f'{HELPER_PATH}.guard_cable_objects_delete'), \
             patch(f'{HELPER_PATH}.enforce_delete_guards', return_value=[]) as delete_guards:
            guard_object_delete(MagicMock(), MagicMock(), MagicMock(), {'public_id': 1})

        license_guard.assert_called_once()
        delete_guards.assert_called_once()

    def test_aborts_400_on_invariant_violation(self) -> None:
        """A non-empty delete-guard error list aborts with 400."""
        with patch(f'{HELPER_PATH}.guard_object_delete_license'), \
             patch(f'{HELPER_PATH}.guard_cable_objects_delete'), \
             patch(f'{HELPER_PATH}.enforce_delete_guards', return_value=[{'error': 'still referenced'}]), \
             patch(f'{HELPER_PATH}.format_errors_for_abort', return_value='still referenced'):
            with pytest.raises(HTTPException) as exc_info:
                guard_object_delete(MagicMock(), MagicMock(), MagicMock(), {'public_id': 1})

        assert exc_info.value.code == 400

    def test_delegates_to_the_batched_guard_with_one_target(self) -> None:
        """The rules live in the batched function, so the two delete routes cannot drift apart."""
        objects_manager, types_manager, request_user = MagicMock(), MagicMock(), MagicMock()
        target = {'public_id': 1}

        with patch(f'{HELPER_PATH}.guard_objects_delete') as batched:
            guard_object_delete(objects_manager, types_manager, request_user, target)

        batched.assert_called_once_with(objects_manager, types_manager, request_user, [target])

    def test_the_cable_guard_runs_for_the_single_delete_too(self) -> None:
        """A Cable CI is refused whichever route deletes it."""
        types_manager, request_user = MagicMock(), MagicMock()
        target = {'public_id': 1}

        with patch(f'{HELPER_PATH}.guard_object_delete_license'), \
             patch(f'{HELPER_PATH}.enforce_delete_guards', return_value=[]), \
             patch(f'{HELPER_PATH}.guard_cable_objects_delete') as cable_guard:
            guard_object_delete(MagicMock(), types_manager, request_user, target)

        cable_guard.assert_called_once_with(request_user, types_manager, [target])


# -------------------------------------------------------------------------------------------------------------------- #
#                                              guard_objects_delete                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGuardObjectsDelete:
    """guard_objects_delete evaluates the delete rules for a whole selection, before anything is deleted."""

    TARGETS: list[dict[str, Any]] = [{'public_id': 1}, {'public_id': 2}, {'public_id': 3}]

    def test_the_ipam_rules_are_evaluated_for_every_target(self) -> None:
        """A bulk delete is refused as a whole, so every target has to be asked up front."""
        with patch(f'{HELPER_PATH}.guard_object_delete_license') as license_guard, \
             patch(f'{HELPER_PATH}.guard_cable_objects_delete'), \
             patch(f'{HELPER_PATH}.enforce_delete_guards', return_value=[]) as delete_guards:
            guard_objects_delete(MagicMock(), MagicMock(), MagicMock(), self.TARGETS)

        assert license_guard.call_count == len(self.TARGETS)
        assert delete_guards.call_count == len(self.TARGETS)

    def test_the_cable_rule_is_evaluated_once_for_the_selection(self) -> None:
        """One batched read for all targets is what keeps the guard affordable on a bulk delete."""
        types_manager, request_user = MagicMock(), MagicMock()

        with patch(f'{HELPER_PATH}.guard_object_delete_license'), \
             patch(f'{HELPER_PATH}.enforce_delete_guards', return_value=[]), \
             patch(f'{HELPER_PATH}.guard_cable_objects_delete') as cable_guard:
            guard_objects_delete(MagicMock(), types_manager, request_user, self.TARGETS)

        cable_guard.assert_called_once_with(request_user, types_manager, self.TARGETS)

    def test_an_ipam_violation_refuses_before_the_cable_read(self) -> None:
        """The first violation aborts; nothing after it needs to be read."""
        with patch(f'{HELPER_PATH}.guard_object_delete_license'), \
             patch(f'{HELPER_PATH}.enforce_delete_guards', return_value=[{'error': 'still referenced'}]), \
             patch(f'{HELPER_PATH}.format_errors_for_abort', return_value='still referenced'), \
             patch(f'{HELPER_PATH}.guard_cable_objects_delete') as cable_guard:
            with pytest.raises(HTTPException) as exc_info:
                guard_objects_delete(MagicMock(), MagicMock(), MagicMock(), self.TARGETS)

        assert exc_info.value.code == 400
        cable_guard.assert_not_called()

    def test_an_empty_selection_is_a_no_op(self) -> None:
        """Nothing to delete has nothing to refuse."""
        with patch(f'{HELPER_PATH}.guard_object_delete_license') as license_guard, \
             patch(f'{HELPER_PATH}.enforce_delete_guards') as delete_guards, \
             patch(f'{HELPER_PATH}.guard_cable_objects_delete') as cable_guard:
            guard_objects_delete(MagicMock(), MagicMock(), MagicMock(), [])

        license_guard.assert_not_called()
        delete_guards.assert_not_called()
        cable_guard.assert_called_once()


# -------------------------------------------------------------------------------------------------------------------- #
#                                        emit_object_state_change_events                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRealignObjectsToType:
    """
    realign_objects_to_type hands the objects manager server-side statements - it reads no object

    One pull of every name the type does not declare, then one push per declared field that only
    matches the objects lacking it, seeded with the field's default.
    """

    @staticmethod
    def _type(fields: list[dict[str, Any]], public_id: int = 1) -> SimpleNamespace:
        """A CmdbType stand-in exposing only .fields and .public_id."""
        return SimpleNamespace(fields=fields, public_id=public_id)

    def test_pulls_the_undeclared_names_and_pushes_every_declared_field(self) -> None:
        """The statements cover both halves of the drift, whatever the objects hold"""
        objects_manager = MagicMock()
        type_instance = self._type([
            {'name': 'keep', 'type': 'text'},
            {'name': 'added', 'type': 'date', 'value': 'def'},
        ], public_id=5)

        realign_objects_to_type(objects_manager, type_instance)

        objects_manager.apply_raw_updates.assert_called_once_with([
            build_remove_undeclared_fields_update(5, ['added', 'keep']),
            build_add_field_update(5, {'name': 'keep', 'type': 'text', 'value': None}),
            build_add_field_update(5, {'name': 'added', 'type': 'date', 'value': 'def'}),
        ])

    def test_reads_no_object(self) -> None:
        """Nothing is loaded to decide the drift - the statements match what needs changing"""
        objects_manager = MagicMock()

        realign_objects_to_type(objects_manager, self._type([{'name': 'keep', 'type': 'text'}]))

        objects_manager.get_objects_by.assert_not_called()

    def test_a_type_without_fields_only_pulls(self) -> None:
        """With nothing declared every flat entry is stale"""
        objects_manager = MagicMock()

        realign_objects_to_type(objects_manager, self._type([], public_id=6))

        objects_manager.apply_raw_updates.assert_called_once_with([build_remove_undeclared_fields_update(6, [])])

    def test_a_failing_statement_aborts_500(self) -> None:
        """A write failure surfaces as a 500, the route's answer for a broken re-alignment"""
        objects_manager = MagicMock()
        objects_manager.apply_raw_updates.side_effect = ObjectsManagerUpdateError('boom')

        with pytest.raises(HTTPException) as exc_info:
            realign_objects_to_type(objects_manager, self._type([{'name': 'keep', 'type': 'text'}]))

        assert exc_info.value.code == HTTP_INTERNAL_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                               clean_type_reports                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCleanTypeReports:
    """clean_type_reports is the route-layer wrapper: it delegates and maps failures to 500.

    The stripping itself lives on ReportsManager, so the section-template removal and the database
    updaters can reuse it; its own tests pin what it strips.
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
        # A real CmdbObject: the shared to_json type-checks its instance and reads the document keys
        # as attributes, so a MagicMock is refused - which is the guard working, not a test-only quirk
        deleted = _make_object([])

        with flask_app.test_request_context('/'):
            with patch(f'{HELPER_PATH}.handle_delete_from_object_groups'), \
                 patch(f'{HELPER_PATH}.handle_delete_invalid_object_relations'), \
                 patch(f'{HELPER_PATH}.handle_notify_webhooks'), \
                 patch(f'{HELPER_PATH}.handle_create_object_log'), \
                 patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
                 patch(f'{HELPER_PATH}.handle_sync_config_item_count') as sync:
                delete_one_cascade(MagicMock(), deleted, MagicMock(), LogAction.DELETE)

        # no count is forwarded - the sync derives the total from its own aggregation
        sync.assert_called_once_with(sync.call_args.args[0])

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


# -------------------------------------------------------------------------------------------------------------------- #
#                                              build_field_value_map                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildFieldValueMap:
    """build_field_value_map turns a stored fields list into a name-keyed value map."""

    def test_maps_every_name_to_its_value(self) -> None:
        """Each entry contributes one key, and only its value survives."""
        fields = [
            {'name': 'hostname', 'value': 'srv-01', 'type': 'text'},
            {'name': 'cpus', 'value': 8, 'type': 'number'},
        ]

        assert build_field_value_map(fields) == {'hostname': 'srv-01', 'cpus': 8}

    def test_drops_the_type(self) -> None:
        """
        The type is deliberately not carried over

        This is what makes the view read-only: a stored entry must always be a complete
        {name, value, type} triple, so a map built from this can never be written back.
        """
        result = build_field_value_map([{'name': 'a', 'value': 1, 'type': 'text'}])

        assert result == {'a': 1}
        assert 'type' not in result

    @pytest.mark.parametrize('value', [None, '', 0, False, []])
    def test_keeps_falsy_values(self, value: Any) -> None:
        """A falsy value is a value: the key is present, not skipped."""
        result = build_field_value_map([{'name': 'a', 'value': value}])

        assert result == {'a': value}
        assert 'a' in result

    def test_a_field_without_a_value_key_maps_to_none(self) -> None:
        """An entry missing 'value' entirely still gets its key, holding None."""
        assert build_field_value_map([{'name': 'a', 'type': 'text'}]) == {'a': None}

    def test_an_empty_name_is_kept(self) -> None:
        """
        An empty field name is stored as a key rather than dropped

        The type schema does not forbid it, and silently losing a field would be
        worse than an awkward key.
        """
        assert build_field_value_map([{'name': '', 'value': 1}]) == {'': 1}

    @pytest.mark.parametrize('name', [None, 1, ['a'], {'a': 1}])
    def test_a_non_string_name_is_skipped(self, name: Any) -> None:
        """A name that cannot be a JSON key is skipped instead of raising."""
        assert build_field_value_map([{'name': name, 'value': 1}]) == {}

    def test_a_duplicate_name_resolves_to_the_last_entry(self) -> None:
        """
        Only reachable on corrupted data - a field name is unique within its CmdbType

        Pinned so the behaviour is a decision rather than an accident.
        """
        fields = [{'name': 'a', 'value': 'first'}, {'name': 'a', 'value': 'second'}]

        assert build_field_value_map(fields) == {'a': 'second'}

    def test_a_malformed_entry_does_not_cost_the_rest(self) -> None:
        """One unusable row is skipped; the usable ones around it still map."""
        fields = [{'name': 'a', 'value': 1}, 'not-a-dict', None, {'name': 'b', 'value': 2}]

        assert build_field_value_map(fields) == {'a': 1, 'b': 2}

    @pytest.mark.parametrize('fields', [None, 'text', 42, {'name': 'a'}])
    def test_a_non_list_input_maps_to_empty(self, fields: Any) -> None:
        """Anything that is not a list answers with an empty map rather than raising."""
        assert build_field_value_map(fields) == {}

    def test_an_empty_list_maps_to_empty(self) -> None:
        """An object with no fields is a normal state."""
        assert build_field_value_map([]) == {}


# -------------------------------------------------------------------------------------------------------------------- #
#                                               build_mds_value_map                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildMdsValueMap:
    """build_mds_value_map turns stored MDS sections into a section-keyed map of row value maps."""

    def test_maps_each_section_to_its_rows(self) -> None:
        """A section becomes its section_id key, holding one value map per row in stored order."""
        sections = [{
            'section_id': 'mds-interfaces',
            'highest_id': 2,
            'values': [
                {'multi_data_id': 1, 'data': [{'name': 'ip', 'value': '10.0.0.1', 'type': 'text'}]},
                {'multi_data_id': 2, 'data': [{'name': 'ip', 'value': '10.0.0.2', 'type': 'text'}]},
            ],
        }]

        assert build_mds_value_map(sections) == {
            'mds-interfaces': [{'ip': '10.0.0.1'}, {'ip': '10.0.0.2'}],
        }

    def test_drops_the_row_identity_and_the_counter(self) -> None:
        """
        multi_data_id and highest_id are both absent from the result

        A row's identity IS its multi_data_id and never its position, so this view cannot be used to
        write rows back - the positional index must not be mistaken for the id.
        """
        sections = [{
            'section_id': 's1',
            'highest_id': 7,
            'values': [{'multi_data_id': 7, 'data': [{'name': 'a', 'value': 1}]}],
        }]

        result = build_mds_value_map(sections)

        assert result == {'s1': [{'a': 1}]}
        assert 'multi_data_id' not in result['s1'][0]

    def test_several_sections_stay_separate(self) -> None:
        """Each section keeps its own rows, keyed by its own name."""
        sections = [
            {'section_id': 's1', 'values': [{'multi_data_id': 1, 'data': [{'name': 'a', 'value': 1}]}]},
            {'section_id': 's2', 'values': [{'multi_data_id': 1, 'data': [{'name': 'b', 'value': 2}]}]},
        ]

        assert build_mds_value_map(sections) == {'s1': [{'a': 1}], 's2': [{'b': 2}]}

    def test_a_row_id_repeating_across_sections_is_not_a_conflict(self) -> None:
        """
        A multi_data_id is unique only WITHIN its section

        Two sections both holding a row 1 must map to two independent lists.
        """
        sections = [
            {'section_id': 's1', 'values': [{'multi_data_id': 1, 'data': [{'name': 'a', 'value': 'x'}]}]},
            {'section_id': 's2', 'values': [{'multi_data_id': 1, 'data': [{'name': 'a', 'value': 'y'}]}]},
        ]

        assert build_mds_value_map(sections) == {'s1': [{'a': 'x'}], 's2': [{'a': 'y'}]}

    def test_a_section_with_no_rows_maps_to_an_empty_list(self) -> None:
        """
        Kept rather than omitted

        A consumer must be able to tell "this section exists and is empty" from "no such section".
        """
        assert build_mds_value_map([{'section_id': 's1', 'highest_id': 0, 'values': []}]) == {'s1': []}

    def test_a_section_without_a_values_key_maps_to_an_empty_list(self) -> None:
        """A section missing 'values' is treated as an empty section, not skipped."""
        assert build_mds_value_map([{'section_id': 's1'}]) == {'s1': []}

    @pytest.mark.parametrize('section_id', [None, 1, ['s']])
    def test_a_section_without_a_usable_id_is_skipped(self, section_id: Any) -> None:
        """A section id that cannot be a JSON key is skipped instead of raising."""
        assert build_mds_value_map([{'section_id': section_id, 'values': []}]) == {}

    def test_a_malformed_section_is_skipped(self) -> None:
        """An entry of the sections list that is not a dict is skipped, not raised on."""
        sections = ['not-a-dict', None, 42, {'section_id': 's1', 'values': []}]

        assert build_mds_value_map(sections) == {'s1': []}

    def test_a_malformed_row_is_skipped(self) -> None:
        """One unusable row does not cost the section its other rows."""
        sections = [{
            'section_id': 's1',
            'values': ['not-a-dict', {'multi_data_id': 1, 'data': [{'name': 'a', 'value': 1}]}],
        }]

        assert build_mds_value_map(sections) == {'s1': [{'a': 1}]}

    @pytest.mark.parametrize('sections', [None, 'text', 42, {'section_id': 's1'}])
    def test_a_non_list_input_maps_to_empty(self, sections: Any) -> None:
        """Anything that is not a list answers with an empty map rather than raising."""
        assert build_mds_value_map(sections) == {}


# -------------------------------------------------------------------------------------------------------------------- #
#                                            build_object_value_view                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildObjectValueView:
    """build_object_value_view reshapes only the two field-carrying keys of a stored document."""

    @staticmethod
    def _document() -> dict[str, Any]:
        """One stored CmdbObject document with both field-carrying keys populated."""
        return {
            'public_id': 8802,
            'type_id': 42,
            'active': True,
            'author_id': 1,
            'version': '1.0.0',
            'fields': [{'name': 'hostname', 'value': 'srv-01', 'type': 'text'}],
            'multi_data_sections': [{
                'section_id': 'mds-interfaces',
                'highest_id': 1,
                'values': [{'multi_data_id': 1, 'data': [{'name': 'ip', 'value': '10.0.0.1'}]}],
            }],
        }

    def test_reshapes_both_field_carrying_keys(self) -> None:
        """fields and multi_data_sections both come back as name-keyed maps."""
        result = build_object_value_view(self._document())

        assert result['fields'] == {'hostname': 'srv-01'}
        assert result['multi_data_sections'] == {'mds-interfaces': [{'ip': '10.0.0.1'}]}

    def test_passes_every_other_key_through_untouched(self) -> None:
        """
        Only the two field-carrying keys change

        Everything else the native view returns is carried over as-is, so the two views differ in
        those two keys and nowhere else.
        """
        document = self._document()

        result = build_object_value_view(document)

        for key in ('public_id', 'type_id', 'active', 'author_id', 'version'):
            assert result[key] == document[key]

    def test_adds_and_removes_no_top_level_key(self) -> None:
        """The key set of the response is exactly the key set of the stored document."""
        document = self._document()

        assert set(build_object_value_view(document)) == set(document)

    def test_does_not_mutate_the_stored_document(self) -> None:
        """
        The source document must survive untouched

        On the list route the input is the live CmdbObject's __dict__, so reshaping in place would
        corrupt the object the caller still holds.
        """
        document = self._document()

        build_object_value_view(document)

        assert document['fields'] == [{'name': 'hostname', 'value': 'srv-01', 'type': 'text'}]
        assert isinstance(document['multi_data_sections'], list)

    def test_a_document_without_the_two_keys_maps_to_empty_maps(self) -> None:
        """A document carrying neither key still answers with both, empty."""
        result = build_object_value_view({'public_id': 1})

        assert result == {'public_id': 1, 'fields': {}, 'multi_data_sections': {}}

    def test_an_mds_field_appears_in_both_blocks(self) -> None:
        """
        The flat fields map keeps MDS field names as stored (decided, not an oversight)

        A CmdbObject's fields[] deliberately carries an entry for every field including MDS ones, and
        this view does not strip them - so an MDS field name is present in both blocks, with the
        per-row values under multi_data_sections being the authoritative ones.
        """
        document = {
            'public_id': 1,
            'fields': [{'name': 'ip', 'value': '', 'type': 'text'}],
            'multi_data_sections': [{
                'section_id': 's1',
                'values': [{'multi_data_id': 1, 'data': [{'name': 'ip', 'value': '10.0.0.1'}]}],
            }],
        }

        result = build_object_value_view(document)

        assert result['fields'] == {'ip': ''}
        assert result['multi_data_sections'] == {'s1': [{'ip': '10.0.0.1'}]}
