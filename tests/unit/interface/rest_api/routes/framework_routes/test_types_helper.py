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
Unit tests for the CmdbType route helpers extracted from the update / clean-status routes

Covers the pure / orchestration helpers in types_helper: the location-field removal guard, the
removed-global-template computation + cleanup, the clean-status item builder and the post-update
side-effect orchestrator. DB-touching collaborators are patched at the module path; CmdbTypes are
lightweight SimpleNamespace stand-ins exposing only the attributes the helpers read. Schema dict
keys are referenced via the model key enums per the no-magic-values rule
"""
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import BadRequest, HTTPException

from cmdb.models.type_model import (
    CmdbType,
    DEFAULT_PORT_SECTION_INDEX,
    FieldKey,
    FieldType,
    SectionType,
    TypeSchemaKey,
)
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.object_model import CmdbObjectKey
from cmdb.manager.manager_provider_model import ManagerType
from cmdb.manager.types_mds_helper import MdsChangePlan, build_mds_updates
from cmdb.errors.database import DocumentTooLargeError
from cmdb.errors.manager.objects_manager import ObjectsManagerUpdateError
from cmdb.interface.request_limits_constants import DOCUMENT_TOO_LARGE_RESPONSE_MESSAGE
from cmdb.errors.manager.types_manager import TypesManagerAlignmentError, TypesManagerUpdateMDSError
from cmdb.models.location_model.location_constants import LocationKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types import types_helper
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    TypeOverviewKey,
    TypeUserDataKey,
    TypeAlignmentStep,
    TYPE_ACCESS_DENIED_MESSAGE,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper import (
    get_types_user_data,
    get_type_or_404,
    get_type_instance_or_404,
    is_type_readable,
    abort_unless_type_readable,
    compute_removed_global_templates,
    strip_removed_global_templates,
    run_alignment_step,
    realign_type_object_fields,
    clean_type_reports_after_update,
    undeclared_report_field_names,
    align_type_mds,
    build_types_overview_items,
    realign_type_objects_if_fields_changed,
    apply_type_update_side_effects,
    verify_type_is_unique,
    normalize_type_acl,
    type_deletion_followup,
    apply_type_changes_to_locations,
    apply_type_changes_to_mds,
    enforce_special_type_license,
    enforce_rack_selectable_as_parent,
    normalize_port_section_index,
    normalize_ci_explorer_label,
    enforce_uses_ports_license,
)
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.security.license.license_constants import LicenseFeature
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper'

HTTP_BAD_REQUEST: int = 400
HTTP_NOT_FOUND: int = 404


# ---------------------------------------- is_type_readable / abort_unless_type_readable ---------------------------- #

READER_GROUP_ID: int = 5
OTHER_GROUP_ID: int = 6
ACL_TYPE_ID: int = 4712


def _acl_type_doc(acl: dict[str, Any] | None) -> dict[str, Any]:
    """A stored type document carrying the given ``acl`` (None: no ``acl`` key at all)."""
    doc: dict[str, Any] = {TypeSchemaKey.PUBLIC_ID.value: ACL_TYPE_ID}

    if acl is not None:
        doc[TypeSchemaKey.ACL.value] = acl

    return doc


def _grants(group_id: int, permissions: list[str]) -> dict[str, Any]:
    """An activated ACL granting the group those permissions."""
    return {'activated': True, 'groups': {'includes': {str(group_id): permissions}}}


READER: SimpleNamespace = SimpleNamespace(group_id=READER_GROUP_ID)


@pytest.mark.parametrize('acl, readable', [
    (None, True),
    ({'activated': False, 'groups': {'includes': {}}}, True),
    (_grants(READER_GROUP_ID, ['READ']), True),
    (_grants(READER_GROUP_ID, ['UPDATE', 'DELETE']), False),
    (_grants(OTHER_GROUP_ID, ['READ']), False),
], ids=['no-acl', 'switched-off', 'granted', 'other-permissions-only', 'other-group-only'])
def test_is_type_readable_reads_the_acl_the_same_from_a_document_and_a_model(
        acl: dict[str, Any] | None, readable: bool) -> None:
    """READ is the permission asked, and the stored document and the hydrated model agree"""
    doc = _acl_type_doc(acl)
    model = CmdbType.from_data({**make_type_doc(ACL_TYPE_ID, 'acl-type'), **doc})

    assert is_type_readable(doc, READER) is readable
    assert is_type_readable(model, READER) is readable


@pytest.mark.parametrize('as_model', [False, True], ids=['document', 'model'])
def test_abort_unless_type_readable_refuses_with_403_naming_the_type(as_model: bool) -> None:
    """A 403 carrying the type's public_id, from either shape"""
    doc = _acl_type_doc(_grants(OTHER_GROUP_ID, ['READ']))
    target = CmdbType.from_data({**make_type_doc(ACL_TYPE_ID, 'acl-type'), **doc}) if as_model else doc

    with pytest.raises(HTTPException) as exc:
        abort_unless_type_readable(target, READER)

    assert exc.value.code == 403
    assert exc.value.description == TYPE_ACCESS_DENIED_MESSAGE.format(public_id=ACL_TYPE_ID)


def test_abort_unless_type_readable_lets_a_readable_type_pass() -> None:
    """Nothing is raised"""
    assert abort_unless_type_readable(_acl_type_doc(_grants(READER_GROUP_ID, ['READ'])), READER) is None


# ------------------------------------------ get_type_or_404 / get_type_instance_or_404 ------------------------------ #

def test_get_type_or_404_returns_the_document() -> None:
    """An existing type is returned as the raw document from the dict-mode lookup."""
    types_manager = MagicMock()
    types_manager.get_type.return_value = {TypeSchemaKey.PUBLIC_ID.value: 1}

    assert get_type_or_404(types_manager, 1) == {TypeSchemaKey.PUBLIC_ID.value: 1}
    types_manager.get_type.assert_called_once_with(1)


def test_get_type_instance_or_404_returns_the_instance() -> None:
    """An existing type is returned hydrated from the instance-mode lookup."""
    types_manager = MagicMock()
    types_manager.get_type_instance.return_value = 'hydrated'

    assert get_type_instance_or_404(types_manager, 1) == 'hydrated'
    types_manager.get_type_instance.assert_called_once_with(1)


@pytest.mark.parametrize(
    'helper, manager_method',
    [(get_type_or_404, 'get_type'), (get_type_instance_or_404, 'get_type_instance')],
    ids=['dict', 'instance'],
)
def test_missing_type_aborts_404_in_both_modes(helper: Any, manager_method: str) -> None:
    """Both helpers abort 404 with the same message when the type does not exist."""
    types_manager = MagicMock()
    getattr(types_manager, manager_method).return_value = None

    with pytest.raises(HTTPException) as exc:
        helper(types_manager, 4711)

    assert exc.value.code == 404
    assert '4711' in exc.value.description


# ------------------------------------------------- compute_removed_global_templates --------------------------------- #

def test_compute_removed_global_templates_snapshots_present_sections() -> None:
    """Removed templates are the old-minus-incoming set; hints are captured only for present sections."""
    section = SimpleNamespace(type=SectionType.MDS_SECTION.value, get_fields=lambda: ['a', 'b'])
    old_type = SimpleNamespace(
        global_template_ids=['t1', 'gone'],
        get_section=lambda name: section if name == 't1' else None,
    )

    removed_ids, hints = compute_removed_global_templates(old_type, {'t-keep'})

    assert removed_ids == {'t1', 'gone'}
    assert hints == {'t1': (['a', 'b'], SectionType.MDS_SECTION.value)}


# ------------------------------------------------- strip_removed_global_templates ----------------------------------- #

def _templated_document() -> dict[str, Any]:
    """A type document carrying a global template 'tpl' (section + two fields) beside its own field 'own'."""
    return {
        TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value: ['tpl', 'kept'],
        TypeSchemaKey.FIELDS.value: [{'name': 'own'}, {'name': 'tpl-a'}, {'name': 'tpl-b'}],
        TypeSchemaKey.RENDER_META.value: {
            TypeSchemaKey.SECTIONS.value: [{'name': 'main', 'fields': ['own']}, {'name': 'tpl', 'fields': ['tpl-a']}],
            TypeSchemaKey.SUMMARY.value: {TypeSchemaKey.FIELDS.value: ['own', 'tpl-a']},
        },
    }


def test_strip_removed_global_templates_takes_the_template_out_of_the_document() -> None:
    """Its name, its section, its fields and their summary entries go - from the document that is written"""
    document = _templated_document()
    removed = ({'tpl'}, {'tpl': (['tpl-a', 'tpl-b'], SectionType.SECTION.value)})

    cleaned = strip_removed_global_templates(document, removed)

    assert cleaned[TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value] == ['kept']
    assert [field['name'] for field in cleaned[TypeSchemaKey.FIELDS.value]] == ['own']
    render_meta = cleaned[TypeSchemaKey.RENDER_META.value]
    assert [section['name'] for section in render_meta[TypeSchemaKey.SECTIONS.value]] == ['main']
    assert render_meta[TypeSchemaKey.SUMMARY.value][TypeSchemaKey.FIELDS.value] == ['own']


def test_strip_removed_global_templates_leaves_the_input_untouched() -> None:
    """A new document; the caller's is not modified"""
    document = _templated_document()

    strip_removed_global_templates(document, ({'tpl'}, {'tpl': (['tpl-a'], SectionType.SECTION.value)}))

    assert document == _templated_document()


def test_strip_removed_global_templates_with_nothing_removed_is_the_same_document() -> None:
    """No copy, no change"""
    document = _templated_document()

    assert strip_removed_global_templates(document, (set(), {})) is document


def test_strip_removed_global_templates_without_a_hint_still_drops_the_claim_and_section() -> None:
    """A template whose section was already gone contributes no field names, but its claim goes"""
    cleaned = strip_removed_global_templates(_templated_document(), ({'tpl'}, {}))

    assert cleaned[TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value] == ['kept']
    assert len(cleaned[TypeSchemaKey.FIELDS.value]) == 3


def test_strip_removed_global_templates_adds_no_render_meta_the_document_lacks() -> None:
    """Without sections or summary fields only the claim and the fields go; no empty key is invented"""
    document = {
        TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value: ['tpl'],
        TypeSchemaKey.FIELDS.value: [{'name': 'own'}, {'name': 'tpl-a'}],
        TypeSchemaKey.RENDER_META.value: {TypeSchemaKey.SUMMARY.value: {}},
    }

    cleaned = strip_removed_global_templates(document, ({'tpl'}, {'tpl': (['tpl-a'], SectionType.SECTION.value)}))

    assert cleaned[TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value] == []
    assert [field['name'] for field in cleaned[TypeSchemaKey.FIELDS.value]] == ['own']
    assert cleaned[TypeSchemaKey.RENDER_META.value] == {TypeSchemaKey.SUMMARY.value: {}}


def _type_doc(public_id: int, field_names: list[str]) -> dict[str, Any]:
    """Builds a CmdbType document with the given field names."""
    return {
        TypeSchemaKey.PUBLIC_ID.value: public_id,
        TypeSchemaKey.FIELDS.value: [{FieldKey.NAME.value: name} for name in field_names],
    }


def test_build_types_overview_items_bundles_type_and_user_data() -> None:
    """Each item bundles the type document with a resolved user-data block (no clean status)."""
    items = build_types_overview_items([_type_doc(1, ['a', 'b'])], {})

    assert items[0][TypeOverviewKey.TYPE_DATA][TypeSchemaKey.PUBLIC_ID.value] == 1
    assert isinstance(items[0][TypeOverviewKey.USER_DATA], dict)
    assert 'clean_status' not in items[0]


def test_build_types_overview_items_one_item_per_type() -> None:
    """One overview item is produced per input type, in order."""
    items = build_types_overview_items([_type_doc(1, ['a']), _type_doc(2, ['b'])], {})

    assert [item[TypeOverviewKey.TYPE_DATA][TypeSchemaKey.PUBLIC_ID.value] for item in items] == [1, 2]


# --------------------------------------------- realign_type_objects_if_fields_changed ------------------------------- #

def _type_with_field_names(public_id: int, field_names: list[str]) -> SimpleNamespace:
    """A minimal CmdbType stub exposing .fields (name dicts) and .public_id for the realign gate."""
    return SimpleNamespace(
        public_id=public_id,
        fields=[{FieldKey.NAME.value: name} for name in field_names],
    )


def test_realign_skips_when_field_names_unchanged() -> None:
    """A metadata-only edit (same field names) triggers no object/report reconciliation."""
    old_type = _type_with_field_names(1, ['a', 'b'])
    updated_type = _type_with_field_names(1, ['a', 'b'])

    with patch(f'{PATH}.ManagerProvider.get_manager') as mock_get, \
         patch(f'{PATH}.align_objects_to_type') as mock_align:
        realign_type_objects_if_fields_changed(MagicMock(), old_type, updated_type)

    mock_get.assert_not_called()
    mock_align.assert_not_called()


@pytest.mark.parametrize('old_names, new_names', [
    (['a'], ['a', 'b']),        # field added
    (['a', 'b'], ['a']),        # field removed
])
def test_realign_runs_when_field_set_changed(old_names: list[str], new_names: list[str]) -> None:
    """Adding or removing a field name reconciles the type's objects and reports."""
    old_type = _type_with_field_names(1, old_names)
    updated_type = _type_with_field_names(1, new_names)
    reports_manager = MagicMock(name='reports_manager')

    with patch(f'{PATH}.ManagerProvider.get_manager', return_value=reports_manager), \
         patch(f'{PATH}.align_objects_to_type') as mock_align:
        realign_type_objects_if_fields_changed(MagicMock(), old_type, updated_type)

    mock_align.assert_called_once()
    removed: set[str] = set(old_names) - set(new_names)

    if removed:
        # The reports lose exactly the names the edit removed - read off the two type states
        assert reports_manager.strip_removed_fields_from_reports.call_args.args[1] == removed
    else:
        # An edit that only added fields leaves the reports alone, and does not even read them
        reports_manager.strip_removed_fields_from_reports.assert_not_called()


def test_a_forced_realign_runs_although_the_names_are_unchanged() -> None:
    """alignment_pending: what the failed save changed is not known any more, so the objects are re-aligned"""
    same = _type_with_field_names(1, ['a'])

    with patch(f'{PATH}.ManagerProvider.get_manager'), patch(f'{PATH}.align_objects_to_type') as mock_align:
        realign_type_object_fields(MagicMock(), same, same, force=True)

    mock_align.assert_called_once()


def test_a_forced_report_cleanup_strips_every_undeclared_name() -> None:
    """The names the reports still reference that the type no longer declares - not the object's own keys"""
    same = _type_with_field_names(1, ['a'])
    manager = MagicMock(name='manager')
    manager.get_many_from_other_collection.return_value = [{'report': 1}]
    report = MagicMock(name='report')
    report.referenced_field_names.return_value = {'a', 'gone', CmdbObjectKey.PUBLIC_ID.value}

    with patch(f'{PATH}.ManagerProvider.get_manager', return_value=manager), \
         patch(f'{PATH}.CmdbReport.from_data', return_value=report):
        clean_type_reports_after_update(MagicMock(), same, same, force=True)

    assert manager.strip_removed_fields_from_reports.call_args.args[1] == {'gone'}


def test_an_unforced_report_cleanup_with_nothing_removed_reads_nothing() -> None:
    """A metadata edit costs no report read"""
    same = _type_with_field_names(1, ['a'])

    with patch(f'{PATH}.ManagerProvider.get_manager') as mock_get:
        clean_type_reports_after_update(MagicMock(), same, same)

    mock_get.assert_not_called()


def test_undeclared_report_field_names_are_the_stale_ones_across_reports() -> None:
    """Union over the reports, minus the declared names and the object's own keys"""
    reports = [MagicMock(), MagicMock()]
    reports[0].referenced_field_names.return_value = {'a', 'x'}
    reports[1].referenced_field_names.return_value = {'y', CmdbObjectKey.TYPE_ID.value}

    with patch(f'{PATH}.CmdbReport.from_data', side_effect=reports):
        assert undeclared_report_field_names([{}, {}], _type_with_field_names(1, ['a'])) == {'x', 'y'}


# ------------------------------------------------- apply_type_update_side_effects ----------------------------------- #

STEP_PATCHES: tuple[str, ...] = (
    'apply_type_changes_to_locations', 'apply_type_changes_to_mds', 'align_type_mds',
    'realign_type_object_fields', 'clean_type_reports_after_update',
)


def _run_side_effects(old_type: Any, updated_type: Any, types_manager: Any = None) -> dict[str, MagicMock]:
    """Runs apply_type_update_side_effects with every step patched; answers the patches by name"""
    mocks: dict[str, MagicMock] = {}

    with patch(f'{PATH}.ManagerProvider.get_manager'), \
         patch(f'{PATH}.handle_special_types') as mock_special, \
         patch.object(types_helper.CmdbType, 'to_json', return_value={}):
        patches = [patch(f'{PATH}.{name}') for name in STEP_PATCHES]
        for name, started in zip(STEP_PATCHES, (p.start() for p in patches)):
            mocks[name] = started
        try:
            apply_type_update_side_effects(MagicMock(), types_manager or MagicMock(), old_type, updated_type)
        finally:
            for started_patch in patches:
                started_patch.stop()
        mocks['handle_special_types'] = mock_special

    return mocks


def test_apply_type_update_side_effects_skips_special_wiring_without_marker() -> None:
    """A non-special type runs location / MDS / field / report alignment but no special wiring."""
    mocks = _run_side_effects(SimpleNamespace(alignment_pending=False), SimpleNamespace(public_id=7, special_type=None))

    for name in ('apply_type_changes_to_locations', 'apply_type_changes_to_mds', 'realign_type_object_fields',
                 'clean_type_reports_after_update'):
        mocks[name].assert_called_once()
    mocks['handle_special_types'].assert_not_called()
    mocks['align_type_mds'].assert_not_called()


def test_apply_type_update_side_effects_runs_special_wiring_with_marker() -> None:
    """A special type additionally runs the special-type ref_types wiring."""
    mocks = _run_side_effects(SimpleNamespace(alignment_pending=False),
                              SimpleNamespace(public_id=7, special_type='SUBNET'))

    mocks['handle_special_types'].assert_called_once()


def test_the_marker_is_cleared_last() -> None:
    """Only after every step: one targeted write of the flag"""
    types_manager = MagicMock(name='types_manager')

    _run_side_effects(SimpleNamespace(alignment_pending=False), SimpleNamespace(public_id=7, special_type=None),
                      types_manager)

    types_manager.update_type_field.assert_called_once_with(7, TypeSchemaKey.ALIGNMENT_PENDING.value, False)


def test_a_pending_type_aligns_by_state() -> None:
    """The stored type carried the marker: every step forced, the MDS aligned to the type as it is"""
    mocks = _run_side_effects(SimpleNamespace(alignment_pending=True), SimpleNamespace(public_id=7, special_type=None))

    mocks['align_type_mds'].assert_called_once()
    mocks['apply_type_changes_to_mds'].assert_not_called()
    assert mocks['apply_type_changes_to_locations'].call_args.args[3] is True
    assert mocks['realign_type_object_fields'].call_args.args[3] is True
    assert mocks['clean_type_reports_after_update'].call_args.args[3] is True


def test_a_failed_step_stops_the_rest_and_keeps_the_marker() -> None:
    """The step is named; nothing after it runs, the marker is not cleared"""
    types_manager = MagicMock(name='types_manager')

    with patch(f'{PATH}.ManagerProvider.get_manager'), \
         patch(f'{PATH}.apply_type_changes_to_locations'), \
         patch(f'{PATH}.apply_type_changes_to_mds', side_effect=TypesManagerUpdateMDSError('boom')), \
         patch(f'{PATH}.realign_type_object_fields') as mock_fields, \
         patch.object(types_helper.CmdbType, 'to_json', return_value={}):
        with pytest.raises(TypesManagerAlignmentError) as exc_info:
            apply_type_update_side_effects(MagicMock(), types_manager, SimpleNamespace(alignment_pending=False),
                                           SimpleNamespace(public_id=7, special_type=None))

    assert exc_info.value.step == TypeAlignmentStep.MULTI_DATA_SECTIONS.value
    mock_fields.assert_not_called()
    types_manager.update_type_field.assert_not_called()


def test_run_alignment_step_wraps_with_the_error_itself() -> None:
    """args[0] and __cause__ are the step's own error"""
    cause = RuntimeError('boom')

    def _fail() -> None:
        raise cause

    with pytest.raises(TypesManagerAlignmentError) as exc_info:
        run_alignment_step(TypeAlignmentStep.LOCATIONS, _fail)

    assert exc_info.value.args[0] is cause
    assert exc_info.value.__cause__ is cause
    assert exc_info.value.step == TypeAlignmentStep.LOCATIONS.value


def test_run_alignment_step_lets_a_steps_own_answer_through() -> None:
    """An abort inside a step (the size-limit 400) is answered as it is, not turned into the 500"""
    def _abort() -> None:
        raise BadRequest('too large')

    with pytest.raises(BadRequest):
        run_alignment_step(TypeAlignmentStep.MULTI_DATA_SECTIONS, _abort)


@pytest.mark.parametrize('propagate', ['align_type_mds', 'apply_type_changes_to_mds'])
def test_an_mds_statement_over_the_size_limit_answers_400(propagate: str) -> None:
    """A row added past MongoDB's 16 MB limit answers the shared size-limit 400, like every other write"""
    objects_manager = MagicMock(name='objects_manager')
    objects_manager.apply_raw_updates.side_effect = _too_large_update_error()
    old_type = SimpleNamespace(public_id=7)

    with patch(f'{PATH}.ManagerProvider.get_manager', return_value=objects_manager), \
         patch(f'{PATH}.build_mds_alignment_updates', return_value=['stmt']), \
         patch(f'{PATH}.plan_mds_changes', return_value=SimpleNamespace(is_empty=False)), \
         patch(f'{PATH}.build_mds_updates', return_value=['stmt']):
        with pytest.raises(BadRequest) as exc_info:
            if propagate == 'align_type_mds':
                align_type_mds(MagicMock(), MagicMock())
            else:
                apply_type_changes_to_mds(MagicMock(), old_type, MagicMock())

    assert exc_info.value.description == DOCUMENT_TOO_LARGE_RESPONSE_MESSAGE


def _too_large_update_error() -> ObjectsManagerUpdateError:
    """An objects-manager update error caused by the document size limit"""
    cause = DocumentTooLargeError('16 MB')

    try:
        raise ObjectsManagerUpdateError(cause) from cause
    except ObjectsManagerUpdateError as err:
        return err


def test_align_type_mds_runs_the_state_based_statements() -> None:
    """build_mds_alignment_updates of the type, run by the objects manager"""
    objects_manager = MagicMock(name='objects_manager')
    updated_type = MagicMock(name='updated_type')

    with patch(f'{PATH}.ManagerProvider.get_manager', return_value=objects_manager), \
         patch(f'{PATH}.build_mds_alignment_updates', return_value=['stmt']) as build:
        align_type_mds(MagicMock(), updated_type)

    build.assert_called_once_with(updated_type)
    objects_manager.apply_raw_updates.assert_called_once_with(['stmt'])


def test_align_type_mds_reports_a_failing_statement_as_its_own_error() -> None:
    """Any other update failure becomes TypesManagerUpdateMDSError carrying the error itself"""
    failure = ObjectsManagerUpdateError('write refused')
    objects_manager = MagicMock(name='objects_manager')
    objects_manager.apply_raw_updates.side_effect = failure

    with patch(f'{PATH}.ManagerProvider.get_manager', return_value=objects_manager), \
         patch(f'{PATH}.build_mds_alignment_updates', return_value=['stmt']):
        with pytest.raises(TypesManagerUpdateMDSError) as exc_info:
            align_type_mds(MagicMock(), MagicMock())

    assert exc_info.value.args[0] is failure
    assert exc_info.value.__cause__ is failure


def test_a_forced_location_update_writes_all_three_values() -> None:
    """Even the unchanged ones - a pending type cannot tell which its locations lack"""
    same = SimpleNamespace(label='L', render_meta=SimpleNamespace(icon='i'), selectable_as_parent=True,
                           get_public_id=lambda: 7)
    locations_manager = MagicMock(name='locations_manager')

    with patch(f'{PATH}.ManagerProvider.get_manager', return_value=locations_manager):
        apply_type_changes_to_locations(MagicMock(), same, same, force=True)

    assert set(locations_manager.update_locations_by_type.call_args.args[1]) == {
        LocationKey.TYPE_LABEL, LocationKey.TYPE_ICON, LocationKey.TYPE_SELECTABLE,
    }


# --------------------------------------------------- apply_type_changes_to_mds -------------------------------------- #

def test_apply_type_changes_to_mds_runs_the_plans_statements() -> None:
    """The plan becomes statements and the objects manager runs them - no object is read for it"""
    plan = MdsChangePlan(added_fields={'sec': ['b']})
    objects_manager = MagicMock(name='objects_manager')
    old_type = SimpleNamespace(public_id=7)

    with patch(f'{PATH}.plan_mds_changes', return_value=plan), \
         patch(f'{PATH}.ManagerProvider.get_manager', return_value=objects_manager):
        apply_type_changes_to_mds(MagicMock(), old_type, {})

    objects_manager.apply_raw_updates.assert_called_once_with(build_mds_updates(7, plan))


def test_apply_type_changes_to_mds_does_nothing_for_an_empty_plan() -> None:
    """A metadata edit needs no manager and issues no statement"""
    with patch(f'{PATH}.plan_mds_changes', return_value=MdsChangePlan()), \
         patch(f'{PATH}.ManagerProvider.get_manager') as mock_get:
        apply_type_changes_to_mds(MagicMock(), SimpleNamespace(public_id=7), {})

    mock_get.assert_not_called()


def test_apply_type_changes_to_mds_reports_a_failing_statement_as_its_own_error() -> None:
    """
    The route answers a propagation failure with its own message, so the error keeps its identity

    The failing write is chained, not flattened into a string.
    """
    objects_manager = MagicMock(name='objects_manager')
    cause = ObjectsManagerUpdateError('boom')
    objects_manager.apply_raw_updates.side_effect = cause

    with patch(f'{PATH}.plan_mds_changes', return_value=MdsChangePlan(removed_sections=['sec'])), \
         patch(f'{PATH}.ManagerProvider.get_manager', return_value=objects_manager):
        with pytest.raises(TypesManagerUpdateMDSError) as exc_info:
            apply_type_changes_to_mds(MagicMock(), SimpleNamespace(public_id=7), {})

    assert exc_info.value.__cause__ is cause


# ------------------------------------------------------ verify_type_is_unique --------------------------------------- #

def test_verify_type_is_unique_rejects_existing_public_id() -> None:
    """A pre-assigned public_id that already exists aborts 400."""
    mgr = MagicMock()
    mgr.get_type.return_value = {TypeSchemaKey.PUBLIC_ID.value: 5}

    with pytest.raises(HTTPException) as exc_info:
        verify_type_is_unique(mgr, 'name', public_id=5)

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_verify_type_is_unique_rejects_duplicate_name() -> None:
    """A name already used by another type aborts 400."""
    mgr = MagicMock()
    mgr.get_one_by.return_value = {TypeSchemaKey.NAME.value: 'name'}

    with pytest.raises(HTTPException) as exc_info:
        verify_type_is_unique(mgr, 'name')

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_verify_type_is_unique_rejects_missing_name() -> None:
    """A falsy name aborts 400 (the type data must carry a name)."""
    mgr = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        verify_type_is_unique(mgr, None)

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_verify_type_is_unique_rejects_taken_special_type() -> None:
    """A special_type already carried by another type aborts 400."""
    mgr = MagicMock()
    mgr.get_one_by.return_value = None
    mgr.check_special_type_exists.return_value = True

    with pytest.raises(HTTPException) as exc_info:
        verify_type_is_unique(mgr, 'name', special_type='SUBNET')

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_verify_type_is_unique_passes_when_all_clear() -> None:
    """A fresh name, free public_id and unused special_type pass without aborting."""
    mgr = MagicMock()
    mgr.get_type.return_value = None
    mgr.get_one_by.return_value = None
    mgr.check_special_type_exists.return_value = False

    verify_type_is_unique(mgr, 'name', public_id=5, special_type='SUBNET')  # must not raise


# ------------------------------------------------------ type_deletion_followup -------------------------------------- #

def test_type_deletion_followup_runs_generic_cleanup_without_special_type() -> None:
    """The generic cleanup chain runs; special-type un-wiring is skipped without a marker."""
    managers: dict = {}

    with patch(f'{PATH}.ManagerProvider.get_manager', side_effect=lambda mtype, _user: managers.setdefault(
        mtype, MagicMock())), \
         patch(f'{PATH}.cleanup_type_references_from_all_types', return_value=0) as cleanup_refs, \
         patch(f'{PATH}.cleanup_special_type_template_references') as cleanup_special:
        type_deletion_followup(MagicMock(), 7, special_type=None)

    managers[ManagerType.RELATIONS].remove_type_from_relations.assert_called_once_with(7)
    managers[ManagerType.CATEGORIES].remove_type_from_categories.assert_called_once_with(7)
    cleanup_refs.assert_called_once()
    cleanup_special.assert_not_called()


def test_type_deletion_followup_runs_special_type_cleanup_with_marker() -> None:
    """A deleted special type additionally triggers the template-only ref_types un-wiring."""
    with patch(f'{PATH}.ManagerProvider.get_manager', side_effect=lambda mtype, _user: MagicMock()), \
         patch(f'{PATH}.cleanup_type_references_from_all_types', return_value=0), \
         patch(f'{PATH}.cleanup_special_type_template_references') as cleanup_special:
        type_deletion_followup(MagicMock(), 7, special_type='SUBNET')

    cleanup_special.assert_called_once()


def test_type_deletion_followup_reports_the_siblings_it_cleaned(caplog) -> None:
    """
    The sibling cleanup is silent unless it changed something, and then it says how much

    Stripping a deleted type out of other types' `ref_types` is the one step of the chain whose scope
    is not knowable from the request, so the count is the only record that it happened at all.
    """
    with patch(f'{PATH}.ManagerProvider.get_manager', side_effect=lambda mtype, _user: MagicMock()), \
         patch(f'{PATH}.cleanup_type_references_from_all_types', return_value=3), \
         patch(f'{PATH}.cleanup_special_type_template_references'), \
         caplog.at_level(logging.INFO, logger=PATH):
        type_deletion_followup(MagicMock(), 7, special_type=None)

    assert 'Cleaned references to deleted CmdbType 7 from 3' in caplog.text


# ------------------------------------------------------- get_types_user_data ---------------------------------------- #

def _user(display_name: str, image: str) -> MagicMock:
    """A CmdbUser stand-in exposing what the overview row reads."""
    user = MagicMock()
    user.get_display_name.return_value = display_name
    user.image = image

    return user


def test_types_user_data_resolves_both_sides() -> None:
    """The overview row of an edited type names its author AND its last editor"""
    lookup = {1: _user('Author', 'author.png'), 2: _user('Editor', 'editor.png')}

    user_data = get_types_user_data(lookup, author_id=1, editor_id=2)

    assert user_data[TypeUserDataKey.AUTHOR] == 'Author'
    assert user_data[TypeUserDataKey.AUTHOR_IMAGE] == 'author.png'
    assert user_data[TypeUserDataKey.LAST_EDITOR] == 'Editor'
    assert user_data[TypeUserDataKey.LAST_EDITOR_IMAGE] == 'editor.png'


def test_types_user_data_leaves_an_unresolvable_user_null() -> None:
    """
    A never-edited type, and one whose author has been deleted, both read as null rather than raising

    The lookup is built in bulk from the ids the page carries, so a user removed since is simply absent
    from it - the row still has to render.
    """
    user_data = get_types_user_data({1: _user('Author', 'author.png')}, author_id=99, editor_id=None)

    assert user_data == {
        TypeUserDataKey.AUTHOR: None,
        TypeUserDataKey.AUTHOR_IMAGE: None,
        TypeUserDataKey.LAST_EDITOR: None,
        TypeUserDataKey.LAST_EDITOR_IMAGE: None,
    }


# ------------------------------------------------- apply_type_changes_to_locations ---------------------------------- #

def _type_for_location(label: str, icon: str, selectable: bool) -> SimpleNamespace:
    """Builds a CmdbType stand-in exposing the attributes apply_type_changes_to_locations reads."""
    return SimpleNamespace(
        label=label,
        render_meta=SimpleNamespace(icon=icon),
        selectable_as_parent=selectable,
        get_public_id=lambda: 5,
    )


def test_apply_type_changes_to_locations_is_a_noop_without_changes() -> None:
    """When label/icon/selectable are unchanged, no location update is issued."""
    old_type = _type_for_location('L', 'fa-cube', True)
    new_type = _type_for_location('L', 'fa-cube', True)

    with patch(f'{PATH}.ManagerProvider.get_manager') as provider:
        apply_type_changes_to_locations(MagicMock(), old_type, new_type)

    provider.assert_not_called()


def test_apply_type_changes_to_locations_pushes_only_changed_fields() -> None:
    """A changed label propagates as a location update carrying just the changed field."""
    old_type = _type_for_location('Old', 'fa-cube', True)
    new_type = _type_for_location('New', 'fa-cube', True)
    locations = MagicMock()

    with patch(f'{PATH}.ManagerProvider.get_manager', return_value=locations):
        apply_type_changes_to_locations(MagicMock(), old_type, new_type)

    public_id, changed_data = locations.update_locations_by_type.call_args.args
    assert public_id == 5
    assert changed_data == {LocationKey.TYPE_LABEL: 'New'}


# -------------------------------------------------------------------------------------------------------------------- #
#                                          enforce_special_type_license                                                #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('markers', [
    (None,),
    ('',),
    ('NOT-A-SPECIAL-TYPE',),
    (None, None),
], ids=str)
def test_enforce_special_type_license_noop_without_an_ipam_marker(markers: tuple) -> None:
    """A write that touches no IPAM special type never consults the license guard"""
    with patch(f'{PATH}.abort_if_feature_locked') as guard:
        enforce_special_type_license(MagicMock(), *markers)

    guard.assert_not_called()


@pytest.mark.parametrize('marker', [SpecialType.SUPERNET, SpecialType.SUBNET, SpecialType.VLAN], ids=str)
def test_enforce_special_type_license_delegates_for_an_ipam_special_type(marker: SpecialType) -> None:
    """An IPAM special-type write delegates to the IPAM license guard with the request user"""
    request_user = MagicMock()

    with patch(f'{PATH}.abort_if_feature_locked') as guard:
        enforce_special_type_license(request_user, marker)

    guard.assert_called_once_with(LicenseFeature.IPAM, request_user)


def test_enforce_special_type_license_gates_a_rack_behind_ipam() -> None:
    """
    Managing a Rack type requires the IPAM license - an INTERIM policy, not a claim about IPAM

    A Rack is not an IPAM type (SpecialType.get_ipam_types still excludes it) and the Rack View is
    expected to get a LicenseFeature of its own; until then it is gated behind IPAM, so the guard
    matches it via SpecialType.get_license_gated_types.
    """
    request_user = MagicMock()

    with patch(f'{PATH}.abort_if_feature_locked') as guard:
        enforce_special_type_license(request_user, SpecialType.RACK)

    guard.assert_called_once_with(LicenseFeature.IPAM, request_user)


def test_enforce_special_type_license_fires_when_any_marker_is_ipam() -> None:
    """The update route passes stored and requested markers; either one being IPAM gates the write"""
    with patch(f'{PATH}.abort_if_feature_locked') as guard:
        enforce_special_type_license(MagicMock(), None, SpecialType.SUBNET)

    guard.assert_called_once()


# -------------------------------------------------------------------------------------------------------------------- #
#                                           enforce_uses_ports_license                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('requested', [None, False, '', 0], ids=str)
def test_enforce_uses_ports_license_noop_when_the_flag_is_not_requested(requested: Any) -> None:
    """
    A write that does not turn the flag on never consults the license guard

    The absent-key case is the important one: every ordinary type write omits 'uses_ports', and none
    of them may start requiring an IPAM license because of this feature.
    """
    with patch(f'{PATH}.abort_if_feature_locked') as guard:
        enforce_uses_ports_license(MagicMock(), requested)

    guard.assert_not_called()


def test_enforce_uses_ports_license_delegates_when_the_flag_is_turned_on() -> None:
    """Declaring a type as port-bearing delegates to the IPAM license guard with the request user"""
    request_user = MagicMock()

    with patch(f'{PATH}.abort_if_feature_locked') as guard:
        enforce_uses_ports_license(request_user, True)

    guard.assert_called_once_with(LicenseFeature.IPAM, request_user)


def test_enforce_uses_ports_license_allows_turning_the_flag_off() -> None:
    """
    Turning 'uses_ports' off is never gated - cleanup is never blocked

    The guard reads the REQUESTED value only, never the stored one, so a customer whose IPAM license
    lapsed can still switch a port-bearing type back. Same policy as the rack hooks, where leaving a
    rack stays possible unlicensed.
    """
    with patch(f'{PATH}.abort_if_feature_locked') as guard:
        enforce_uses_ports_license(MagicMock(), False)

    guard.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                        enforce_rack_selectable_as_parent                                             #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('special_type', [None, '', SpecialType.SUBNET], ids=str)
def test_enforce_rack_selectable_as_parent_leaves_other_types_untouched(special_type: Any) -> None:
    """Only a Rack has its selectable_as_parent forced; every other type keeps what was sent"""
    data: dict[str, Any] = {TypeSchemaKey.SELECTABLE_AS_PARENT.value: False}

    enforce_rack_selectable_as_parent(special_type, data)

    assert data[TypeSchemaKey.SELECTABLE_AS_PARENT.value] is False


def test_enforce_rack_selectable_as_parent_fills_in_a_missing_value() -> None:
    """A Rack payload that omits the flag gets it set, so the type can parent its members"""
    data: dict[str, Any] = {}

    enforce_rack_selectable_as_parent(SpecialType.RACK, data)

    assert data[TypeSchemaKey.SELECTABLE_AS_PARENT.value] is True


def test_enforce_rack_selectable_as_parent_keeps_an_explicit_true() -> None:
    """An explicit True is already correct and stays"""
    data: dict[str, Any] = {TypeSchemaKey.SELECTABLE_AS_PARENT.value: True}

    enforce_rack_selectable_as_parent(SpecialType.RACK, data)

    assert data[TypeSchemaKey.SELECTABLE_AS_PARENT.value] is True


def test_enforce_rack_selectable_as_parent_aborts_400_on_an_explicit_false() -> None:
    """
    Disabling it on a Rack is refused rather than silently flipped

    A Rack whose type is not selectable as a parent could never have anything placed in it, because
    validate_object_location_change refuses such a parent - so the caller gets a 400 explaining it
    instead of a coercion they cannot see.
    """
    data: dict[str, Any] = {TypeSchemaKey.SELECTABLE_AS_PARENT.value: False}

    with pytest.raises(HTTPException) as err:
        enforce_rack_selectable_as_parent(SpecialType.RACK, data)

    assert err.value.code == 400


# ------------------------------------------------------ normalize_type_acl ------------------------------------------ #

ACL_DEFAULT: dict[str, Any] = {'activated': False, 'groups': {'includes': {}}}


def test_normalize_type_acl_adds_the_default_when_the_key_is_absent() -> None:
    """A create that sends no acl stored a document without one; it now gets the same block as an update."""
    payload: dict[str, Any] = {'name': 'x'}

    normalize_type_acl(payload)

    assert payload[TypeSchemaKey.ACL.value] == ACL_DEFAULT


def test_normalize_type_acl_completes_an_acl_that_only_carries_groups() -> None:
    """The shape the model and the query builder used to disagree about is completed on the way in."""
    payload: dict[str, Any] = {'acl': {'groups': {'includes': {'1': ['READ']}}}}

    normalize_type_acl(payload)

    assert payload[TypeSchemaKey.ACL.value] == {
        'activated': False,
        'groups': {'includes': {'1': ['READ']}},
    }


def test_normalize_type_acl_completes_an_acl_that_only_carries_the_flag() -> None:
    """The other half: an activated acl with no groups gains the empty section."""
    payload: dict[str, Any] = {'acl': {'activated': True}}

    normalize_type_acl(payload)

    assert payload[TypeSchemaKey.ACL.value] == {'activated': True, 'groups': {'includes': {}}}


def test_normalize_type_acl_keeps_a_complete_acl_unchanged() -> None:
    """The common case is a no-op - the frontend always sends both halves."""
    stored = {'activated': True, 'groups': {'includes': {'2': ['READ', 'UPDATE']}}}
    payload: dict[str, Any] = {'acl': dict(stored)}

    normalize_type_acl(payload)

    assert payload[TypeSchemaKey.ACL.value] == stored


@pytest.mark.parametrize('acl', [None, {}, {'groups': None}, {'groups': {'includes': None}}], ids=str)
def test_normalize_type_acl_reads_every_empty_spelling_as_the_default(acl: Any) -> None:
    """
    null, {}, a null groups and a null includes all mean "no ACL"

    A null `groups` must not raise inside `GroupACL.from_data`, which on the update route surfaces as a
    500; the model tolerates it now, so completing the payload here cannot turn a create into one.
    """
    payload: dict[str, Any] = {'acl': acl}

    normalize_type_acl(payload)

    assert payload[TypeSchemaKey.ACL.value] == ACL_DEFAULT


def test_normalize_type_acl_drops_unknown_keys_inside_the_acl() -> None:
    """The model reads only 'activated' and 'groups' - which is what an update has always stored."""
    payload: dict[str, Any] = {'acl': {'activated': False, 'groups': {'includes': {}}, 'junk': 1}}

    normalize_type_acl(payload)

    assert 'junk' not in payload[TypeSchemaKey.ACL.value]


def test_normalize_type_acl_leaves_the_rest_of_the_payload_alone() -> None:
    """It completes one key and touches nothing else."""
    payload: dict[str, Any] = {'name': 'x', 'fields': [], 'public_id': 7}

    normalize_type_acl(payload)

    assert payload['name'] == 'x'
    assert not payload['fields']
    assert payload['public_id'] == 7


# -------------------------------------------------------------------------------------------------------------------- #
#                                            normalize_port_section_index                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def _port_type_payload(**overrides: Any) -> dict[str, Any]:
    """Builds the payload of a port-bearing type, where the index is actually read."""
    return {TypeSchemaKey.USES_PORTS.value: True, **overrides}


def test_normalize_port_section_index_defaults_an_absent_key() -> None:
    """
    A payload that says nothing gets the default written in

    POST /types/ stores the payload as given, so without this a created type would not carry the key
    at all and only its first edit would add it - two stored shapes for one meaning.
    """
    payload: dict[str, Any] = _port_type_payload()

    normalize_port_section_index(payload)

    assert payload[TypeSchemaKey.PORT_SECTION_INDEX.value] == DEFAULT_PORT_SECTION_INDEX


@pytest.mark.parametrize('sent', [None, ''], ids=['null', 'empty'])
def test_normalize_port_section_index_defaults_an_empty_value(sent: Any) -> None:
    """A null or an empty string is "unset", not a bad value: neither is refused"""
    payload: dict[str, Any] = _port_type_payload(**{TypeSchemaKey.PORT_SECTION_INDEX.value: sent})

    normalize_port_section_index(payload)

    assert payload[TypeSchemaKey.PORT_SECTION_INDEX.value] == DEFAULT_PORT_SECTION_INDEX


@pytest.mark.parametrize('sent, expected', [(0, 0), (1, 1), (5, 5), ('3', 3), (2.0, 2)], ids=str)
def test_normalize_port_section_index_keeps_a_usable_position(sent: Any, expected: int) -> None:
    """Whole numbers from 0 up are stored as ints, including the JSON/string spellings of one"""
    payload: dict[str, Any] = _port_type_payload(**{TypeSchemaKey.PORT_SECTION_INDEX.value: sent})

    normalize_port_section_index(payload)

    assert payload[TypeSchemaKey.PORT_SECTION_INDEX.value] == expected


@pytest.mark.parametrize('sent', [-1, -10, 1.5, 'left', [], {}, True], ids=str)
def test_normalize_port_section_index_aborts_400_on_an_unusable_value(sent: Any) -> None:
    """
    An index that cannot mean a position is reported, not silently corrected

    True is in the list on purpose: bool is an int subclass in Python, so a client sending it would
    otherwise be read as position 1. The type IMPORT is the one path that falls back to the default
    instead of refusing.
    """
    payload: dict[str, Any] = _port_type_payload(**{TypeSchemaKey.PORT_SECTION_INDEX.value: sent})

    with pytest.raises(HTTPException) as err:
        normalize_port_section_index(payload)

    assert err.value.code == 400


@pytest.mark.parametrize('uses_ports', [False, None, ''], ids=['false', 'absent', 'empty'])
def test_normalize_port_section_index_resets_a_type_without_ports(uses_ports: Any) -> None:
    """
    A type that does not use ports always stores the default

    The index is only read while the flag is on, so keeping a position here would resurface it if the
    flag were ever set again - a placement the user never made for that type.
    """
    payload: dict[str, Any] = {
        TypeSchemaKey.USES_PORTS.value: uses_ports,
        TypeSchemaKey.PORT_SECTION_INDEX.value: 4,
    }

    normalize_port_section_index(payload)

    assert payload[TypeSchemaKey.PORT_SECTION_INDEX.value] == DEFAULT_PORT_SECTION_INDEX


def test_normalize_port_section_index_validates_before_it_resets() -> None:
    """
    A broken index is refused even on a type without ports

    The value is about to be discarded either way, but reporting it is what tells a client its
    payload is wrong instead of letting the bug ride until someone turns ports on.
    """
    payload: dict[str, Any] = {
        TypeSchemaKey.USES_PORTS.value: False,
        TypeSchemaKey.PORT_SECTION_INDEX.value: -3,
    }

    with pytest.raises(HTTPException) as err:
        normalize_port_section_index(payload)

    assert err.value.code == 400


def test_normalize_port_section_index_leaves_the_rest_of_the_payload_alone() -> None:
    """It completes one key and touches nothing else"""
    payload: dict[str, Any] = _port_type_payload(name='x', fields=[], public_id=7)

    normalize_port_section_index(payload)

    assert (payload['name'], payload['fields'], payload['public_id']) == ('x', [], 7)
    assert payload[TypeSchemaKey.USES_PORTS.value] is True


# -------------------------------------------------------------------------------------------------------------------- #
#                                            normalize_ci_explorer_label                                               #
# -------------------------------------------------------------------------------------------------------------------- #
LABEL_FIELD: str = 'hostname'
LABEL_MDS_FIELD: str = 'port-name'


def _label_payload(**overrides: Any) -> dict[str, Any]:
    """A type payload with one plain field and one multi-data-section field."""
    payload: dict[str, Any] = {
        TypeSchemaKey.NAME.value: 'server',
        TypeSchemaKey.FIELDS.value: [
            {FieldKey.NAME.value: LABEL_FIELD, FieldKey.TYPE.value: FieldType.TEXT.value},
            {FieldKey.NAME.value: LABEL_MDS_FIELD, FieldKey.TYPE.value: FieldType.TEXT.value},
        ],
        TypeSchemaKey.RENDER_META.value: {
            TypeSchemaKey.SECTIONS.value: [
                {SectionKey.TYPE.value: SectionType.SECTION.value, SectionKey.NAME.value: 'info',
                 SectionKey.FIELDS.value: [LABEL_FIELD]},
                {SectionKey.TYPE.value: SectionType.MDS_SECTION.value, SectionKey.NAME.value: 'ports',
                 SectionKey.FIELDS.value: [LABEL_MDS_FIELD]},
            ],
        },
    }
    payload.update(overrides)

    return payload


def _stored_type(label_field: Any) -> SimpleNamespace:
    """The stored CmdbType an update is judged against - only two attributes are read."""
    return SimpleNamespace(ci_explorer_label=label_field, public_id=42)


def test_normalize_ci_explorer_label_keeps_a_usable_nomination() -> None:
    """The ordinary case: the nominated field is one the Type declares"""
    payload = _label_payload(**{TypeSchemaKey.CI_EXPLORER_LABEL.value: LABEL_FIELD})

    normalize_ci_explorer_label(payload)

    assert payload[TypeSchemaKey.CI_EXPLORER_LABEL.value] == LABEL_FIELD


@pytest.mark.parametrize('sent', [None, ''], ids=['null', 'empty'])
def test_normalize_ci_explorer_label_normalises_an_unset_value(sent: Any) -> None:
    """
    Both spellings of "no field chosen" become the stored one

    The frontend writes an empty string when it clears the pick and None when it starts fresh; one
    stored spelling keeps the key answerable by a single query.
    """
    payload = _label_payload(**{TypeSchemaKey.CI_EXPLORER_LABEL.value: sent})

    normalize_ci_explorer_label(payload)

    assert payload[TypeSchemaKey.CI_EXPLORER_LABEL.value] is None


def test_normalize_ci_explorer_label_fills_in_an_absent_key() -> None:
    """A create that says nothing stores the key as None rather than not at all"""
    payload = _label_payload()

    normalize_ci_explorer_label(payload)

    assert payload[TypeSchemaKey.CI_EXPLORER_LABEL.value] is None


def test_normalize_ci_explorer_label_aborts_400_on_an_unknown_field() -> None:
    """
    A display string sent where a field name belongs is refused

    Stored, it would render every node of the Type as "Label not selected" with nothing anywhere
    saying why - so the caller is told at the write instead.
    """
    payload = _label_payload(**{TypeSchemaKey.CI_EXPLORER_LABEL.value: 'Switch'})

    with pytest.raises(HTTPException) as err:
        normalize_ci_explorer_label(payload)

    assert err.value.code == 400


def test_normalize_ci_explorer_label_aborts_400_on_a_multi_data_section_field() -> None:
    """An MDS field resolves to a flat entry that carries none of the section's rows"""
    payload = _label_payload(**{TypeSchemaKey.CI_EXPLORER_LABEL.value: LABEL_MDS_FIELD})

    with pytest.raises(HTTPException) as err:
        normalize_ci_explorer_label(payload)

    assert err.value.code == 400


def test_normalize_ci_explorer_label_refuses_a_newly_chosen_bad_field_on_an_update() -> None:
    """An update that CHANGES the nomination to something unusable is still a client bug"""
    payload = _label_payload(**{TypeSchemaKey.CI_EXPLORER_LABEL.value: 'Switch'})

    with pytest.raises(HTTPException) as err:
        normalize_ci_explorer_label(payload, _stored_type(LABEL_FIELD))

    assert err.value.code == 400


def test_normalize_ci_explorer_label_clears_a_nomination_whose_field_was_removed() -> None:
    """
    Removing the nominated field clears the nomination instead of refusing the update

    The nomination is unchanged - the update did not choose it, it only stopped resolving - and
    refusing a field removal over a cosmetic key would be the wrong trade. The stale nomination has
    to go either way.
    """
    payload = _label_payload(**{
        TypeSchemaKey.CI_EXPLORER_LABEL.value: LABEL_FIELD,
        TypeSchemaKey.FIELDS.value: [],
        TypeSchemaKey.RENDER_META.value: {TypeSchemaKey.SECTIONS.value: []},
    })

    normalize_ci_explorer_label(payload, _stored_type(LABEL_FIELD))

    assert payload[TypeSchemaKey.CI_EXPLORER_LABEL.value] is None


def test_normalize_ci_explorer_label_repairs_a_nomination_that_was_already_stale() -> None:
    """A Type carrying a dangling nomination from before this rule is cleaned up on its next save"""
    payload = _label_payload(**{TypeSchemaKey.CI_EXPLORER_LABEL.value: 'Switch'})

    normalize_ci_explorer_label(payload, _stored_type('Switch'))

    assert payload[TypeSchemaKey.CI_EXPLORER_LABEL.value] is None


def test_normalize_ci_explorer_label_leaves_the_rest_of_the_payload_alone() -> None:
    """It completes one key and touches nothing else"""
    payload = _label_payload(**{TypeSchemaKey.CI_EXPLORER_LABEL.value: LABEL_FIELD, 'public_id': 7})

    normalize_ci_explorer_label(payload)

    assert payload['public_id'] == 7
    assert len(payload[TypeSchemaKey.FIELDS.value]) == 2
