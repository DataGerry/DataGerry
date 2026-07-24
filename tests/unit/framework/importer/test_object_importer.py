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
Unit tests for cmdb.framework.importer.importers.object_importer

DB-free: the importer methods run on a MagicMock-typed ``self`` with ``current_app`` / the portal-sync
helper patched at the module path. Covers the batch loop (``_import``: success/reject/failure routing,
start_element + max_elements bounds, one-sync-per-batch) and the per-object write (``_import_single_object``:
new-id assignment, overwrite of an existing object, and the cloud ConfigItem limit).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cmdb.framework.importer.importers.object_importer import ObjectImporter
from cmdb.framework.importer.helper.object_import_validator import ImportTypeContext
from cmdb.errors.manager.objects_manager import (
    ObjectsManagerGetError,
    ObjectsManagerInsertError,
    ObjectsManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #
# The suite drives the class-under-test's protected methods directly on a MagicMock ``self``
# pylint: disable=protected-access

PATH: str = 'cmdb.framework.importer.importers.object_importer'


def _run_config(start_element: int = 0, max_elements: int = 0, overwrite_public: bool = True) -> SimpleNamespace:
    """A minimal run config for the import loop."""
    return SimpleNamespace(
        start_element=start_element,
        max_elements=max_elements,
        overwrite_public=overwrite_public,
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     _import                                                         #
# -------------------------------------------------------------------------------------------------------------------- #

def _candidates(count: int) -> list:
    """A list of (provided, generated) candidate pairs of empty objects (pass validation as-is)."""
    return [({}, {}) for _ in range(count)]


class TestToProvidedJson:
    """The base provided-data snapshot (used by JSON, whose entry is already the object)."""

    def test_deep_copies_the_entry(self) -> None:
        """It returns a deep copy so later coercion of the entry can't mutate the report snapshot."""
        entry = {'active': True, 'fields': [{'name': 'f', 'value': 'v'}]}

        result = ObjectImporter._to_provided_json(MagicMock(), entry)  # pylint: disable=protected-access

        assert result == entry
        assert result is not entry
        assert result['fields'] is not entry['fields']


class TestGenerateObjects:
    """The base _generate_objects pairs each parsed entry's provided snapshot with its generated object."""

    def test_pairs_provided_and_generated_per_entry(self) -> None:
        """One (provided, generated) candidate is produced per parsed entry, in order."""
        mock_self = MagicMock()
        mock_self._to_provided_json.side_effect = lambda entry, **kwargs: ('p', entry)
        mock_self.generate_object.side_effect = lambda entry, *a, **k: ('g', entry)
        parsed = SimpleNamespace(entries=['e1', 'e2'])

        result = ObjectImporter._generate_objects(mock_self, parsed)  # pylint: disable=protected-access

        assert result == [(('p', 'e1'), ('g', 'e1')), (('p', 'e2'), ('g', 'e2'))]


class TestImportBatch:
    """The batch loop routes each candidate's outcome to success/failure and syncs once."""

    def test_aggregates_successes_and_failures(self) -> None:
        """Each (success, failure) from _process_candidate is routed; the message counts successes."""
        mock_self = MagicMock()
        mock_self.get_config.return_value = _run_config()
        mock_self._process_candidate.side_effect = [('s1', None), (None, 'f1'), ('s2', None)]

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = False
            result = ObjectImporter._import(mock_self, _candidates(3), None)  # pylint: disable=protected-access

        assert result.success_imports == ['s1', 's2']
        assert result.failed_imports == ['f1']
        assert result.message == 'Import of 2 objects'

    def test_syncs_once_when_anything_was_written(self) -> None:
        """In cloud mode a single config-item sync runs when at least one object was written."""
        mock_self = MagicMock()
        mock_self.get_config.return_value = _run_config()
        mock_self._process_candidate.side_effect = [('s1', None), (None, 'f1')]

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = True
            ObjectImporter._import(mock_self, _candidates(2), None)  # pylint: disable=protected-access

        mock_self._sync_config_item_count.assert_called_once()  # pylint: disable=protected-access

    def test_no_sync_when_nothing_was_written(self) -> None:
        """No config-item sync runs when every candidate failed."""
        mock_self = MagicMock()
        mock_self.get_config.return_value = _run_config()
        mock_self._process_candidate.side_effect = [(None, 'f1')]

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = True
            ObjectImporter._import(mock_self, _candidates(1), None)  # pylint: disable=protected-access

        mock_self._sync_config_item_count.assert_not_called()  # pylint: disable=protected-access

    def test_start_element_skips_leading_objects(self) -> None:
        """start_element offsets the first processed object."""
        mock_self = MagicMock()
        mock_self.get_config.return_value = _run_config(start_element=2)
        mock_self._process_candidate.return_value = ('s', None)

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = False
            result = ObjectImporter._import(mock_self, _candidates(3), None)  # pylint: disable=protected-access

        assert len(result.success_imports) == 1
        assert mock_self._process_candidate.call_count == 1  # pylint: disable=protected-access

    def test_max_elements_limits_the_batch(self) -> None:
        """max_elements caps the number of processed candidates (count, not absolute index)."""
        mock_self = MagicMock()
        mock_self.get_config.return_value = _run_config(start_element=1, max_elements=2)
        mock_self._process_candidate.return_value = ('s', None)

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = False
            result = ObjectImporter._import(mock_self, _candidates(5), None)  # pylint: disable=protected-access

        assert len(result.success_imports) == 2
        assert mock_self._process_candidate.call_count == 2  # pylint: disable=protected-access


class TestProcessCandidate:
    """_process_candidate normalizes, resolves the public_id and inserts one candidate."""

    def test_valid_object_is_inserted(self) -> None:
        """A valid object with no public_id issue is inserted and returned as a success."""
        mock_self = MagicMock()
        mock_self._provided_field_names.return_value = set()
        mock_self._resolve_public_id.return_value = None
        mock_self._import_single_object.return_value = 42

        with patch(f'{PATH}.normalize_and_validate_object', return_value=[]):
            success, failure = ObjectImporter._process_candidate(  # pylint: disable=protected-access
                mock_self, {'p': 1}, {'o': 1}, None, None)

        assert failure is None and success is not None
        mock_self._import_single_object.assert_called_once_with({'o': 1})  # pylint: disable=protected-access

    def test_validation_error_is_rejected(self) -> None:
        """A validation error rejects the object and skips the write."""
        mock_self = MagicMock()
        mock_self._provided_field_names.return_value = set()

        with patch(f'{PATH}.normalize_and_validate_object', return_value=['bad']):
            success, failure = ObjectImporter._process_candidate(  # pylint: disable=protected-access
                mock_self, {'p': 1}, {}, None, None)

        assert success is None
        assert failure.errors == ['bad']
        mock_self._import_single_object.assert_not_called()  # pylint: disable=protected-access

    def test_public_id_error_is_rejected(self) -> None:
        """An overwrite-incompatibility error from _resolve_public_id rejects the object."""
        mock_self = MagicMock()
        mock_self._provided_field_names.return_value = {'x'}
        mock_self._resolve_public_id.return_value = 'incompatible'

        with patch(f'{PATH}.normalize_and_validate_object', return_value=[]):
            success, failure = ObjectImporter._process_candidate(  # pylint: disable=protected-access
                mock_self, {'p': 1}, {}, None, None)

        assert success is None
        assert failure.errors == ['incompatible']
        mock_self._import_single_object.assert_not_called()  # pylint: disable=protected-access

    def test_write_error_is_rejected(self) -> None:
        """An ObjectsManager* error from the write becomes a failed import."""
        mock_self = MagicMock()
        mock_self._provided_field_names.return_value = set()
        mock_self._resolve_public_id.return_value = None
        mock_self._import_single_object.side_effect = ObjectsManagerInsertError("boom")

        with patch(f'{PATH}.normalize_and_validate_object', return_value=[]):
            success, failure = ObjectImporter._process_candidate(  # pylint: disable=protected-access
                mock_self, {'p': 1}, {}, None, None)

        assert success is None
        assert failure.errors == ['boom']


class TestProvidedFieldNames:
    """_provided_field_names collects the field names the file provided (top-level + MDS)."""

    def test_collects_top_level_and_mds_names(self) -> None:
        """Top-level field names and MDS-row field names are both collected."""
        obj = {
            'fields': [{'name': 'a'}, {'name': 'b'}],
            'multi_data_sections': [{'section_id': 's', 'values': [{'data': [{'name': 'c'}]}]}],
        }

        assert ObjectImporter._provided_field_names(obj) == {'a', 'b', 'c'}  # pylint: disable=protected-access


class TestResolvePublicId:
    """_resolve_public_id strips the id when overwrite is off, else checks overwrite compatibility."""

    def test_no_public_id_is_a_new_object(self) -> None:
        """An object without a public_id resolves to None (new object) with no compat check."""
        mock_self = MagicMock()

        assert ObjectImporter._resolve_public_id(mock_self, {'fields': []}, set()) is None  # pylint: disable=protected-access
        mock_self._check_overwrite_compatibility.assert_not_called()  # pylint: disable=protected-access

    def test_overwrite_off_strips_the_public_id(self) -> None:
        """With overwrite disabled the public_id is dropped so the object imports as new."""
        mock_self = MagicMock()
        mock_self.get_config.return_value = _run_config(overwrite_public=False)
        obj = {'public_id': 5, 'fields': []}

        assert ObjectImporter._resolve_public_id(mock_self, obj, set()) is None  # pylint: disable=protected-access
        assert 'public_id' not in obj  # stripped

    def test_overwrite_on_delegates_to_compatibility_check(self) -> None:
        """With overwrite enabled the public_id is kept and the compatibility check drives the result."""
        mock_self = MagicMock()
        mock_self.get_config.return_value = _run_config(overwrite_public=True)
        mock_self._check_overwrite_compatibility.return_value = 'ERR'
        obj = {'public_id': 5}

        result = ObjectImporter._resolve_public_id(mock_self, obj, {'a'})  # pylint: disable=protected-access

        assert result == 'ERR'
        assert obj['public_id'] == 5  # kept for the overwrite
        mock_self._check_overwrite_compatibility.assert_called_once_with(5, {'a'})  # pylint: disable=protected-access


class TestOverwriteCompatibility:
    """_check_overwrite_compatibility guards overwriting an object whose type lacks provided fields."""

    def test_unused_public_id_is_allowed(self) -> None:
        """No existing object at that id -> nothing to overwrite, allowed."""
        mock_self = MagicMock()
        mock_self.objects_manager.get_object.return_value = None

        assert ObjectImporter._check_overwrite_compatibility(mock_self, 5, {'a'}) is None  # pylint: disable=protected-access

    def test_existing_type_supporting_fields_is_allowed(self) -> None:
        """An existing object whose type defines all provided fields may be overwritten."""
        mock_self = MagicMock()
        existing = MagicMock()
        existing.get_type_id.return_value = 9
        mock_self.objects_manager.get_object.return_value = existing
        mock_self.objects_manager.get_object_type.return_value.get_fields.return_value = [
            {'name': 'a'}, {'name': 'b'}]

        assert ObjectImporter._check_overwrite_compatibility(mock_self, 5, {'a'}) is None  # pylint: disable=protected-access

    def test_existing_type_missing_a_field_is_rejected(self) -> None:
        """An existing object whose type lacks a provided field rejects the overwrite."""
        mock_self = MagicMock()
        existing = MagicMock()
        existing.get_type_id.return_value = 9
        mock_self.objects_manager.get_object.return_value = existing
        mock_self.objects_manager.get_object_type.return_value.get_fields.return_value = [{'name': 'a'}]

        result = ObjectImporter._check_overwrite_compatibility(mock_self, 5, {'a', 'b'})  # pylint: disable=protected-access

        assert result is not None and 'b' in result


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _import_single_object                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

class TestImportSingleObject:
    """The per-object write: new-id assignment, overwrite, and the cloud limit."""

    def test_new_object_gets_a_fresh_id_and_is_inserted(self) -> None:
        """An object without a public_id is assigned a new id, then inserted."""
        mock_self = MagicMock()
        mock_self.objects_manager.get_new_object_public_id.return_value = 500
        obj: dict = {}

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = False
            result = ObjectImporter._import_single_object(mock_self, obj)  # pylint: disable=protected-access

        assert result == 500
        assert obj['public_id'] == 500
        # A new object never probes for an existing one
        mock_self.objects_manager.get_object.assert_not_called()
        mock_self.objects_manager.insert_object.assert_called_once_with(obj)

    def test_existing_object_is_overwritten(self) -> None:
        """An object with an existing public_id is deleted then re-inserted (lifecycle fields owned upstream)."""
        mock_self = MagicMock()
        mock_self.objects_manager.get_object.return_value = {'creation_time': 'ORIGINAL'}
        obj: dict = {'public_id': 7}

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = False
            result = ObjectImporter._import_single_object(mock_self, obj)  # pylint: disable=protected-access

        assert result == 7
        # creation_time is forced by the normalization step, not preserved here
        assert 'creation_time' not in obj
        mock_self.objects_manager.delete_with_follow_up.assert_called_once_with(7, mock_self.request_user)
        mock_self.objects_manager.get_new_object_public_id.assert_not_called()
        mock_self.objects_manager.insert_object.assert_called_once_with(obj)

    def test_given_id_that_does_not_exist_is_inserted_as_is(self) -> None:
        """A supplied public_id with no existing object is inserted without deletion."""
        mock_self = MagicMock()
        mock_self.objects_manager.get_object.return_value = None
        obj: dict = {'public_id': 9}

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = False
            result = ObjectImporter._import_single_object(mock_self, obj)  # pylint: disable=protected-access

        assert result == 9
        mock_self.objects_manager.delete_with_follow_up.assert_not_called()
        mock_self.objects_manager.get_new_object_public_id.assert_not_called()
        mock_self.objects_manager.insert_object.assert_called_once_with(obj)

    def test_cloud_limit_reached_raises_before_insert(self) -> None:
        """In cloud mode a reached ConfigItem limit raises and skips the insert."""
        mock_self = MagicMock()
        mock_self.objects_manager.get_new_object_public_id.return_value = 1
        mock_self.check_config_item_limit_reached.return_value = True

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = True
            with pytest.raises(ObjectsManagerInsertError):
                ObjectImporter._import_single_object(mock_self, {})  # pylint: disable=protected-access

        mock_self.objects_manager.insert_object.assert_not_called()

    def test_get_error_propagates(self) -> None:
        """A DB error probing for the existing object propagates (caught as a failed import upstream)."""
        mock_self = MagicMock()
        mock_self.objects_manager.get_object.side_effect = ObjectsManagerGetError("db down")

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = False
            with pytest.raises(ObjectsManagerGetError):
                ObjectImporter._import_single_object(mock_self, {'public_id': 3})  # pylint: disable=protected-access

    def test_delete_error_propagates(self) -> None:
        """A delete failure while overwriting propagates."""
        mock_self = MagicMock()
        mock_self.objects_manager.get_object.return_value = {'creation_time': 'X'}
        mock_self.objects_manager.delete_with_follow_up.side_effect = ObjectsManagerDeleteError("nope")

        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = False
            with pytest.raises(ObjectsManagerDeleteError):
                ObjectImporter._import_single_object(mock_self, {'public_id': 3})  # pylint: disable=protected-access


# -------------------------------------------------------------------------------------------------------------------- #
#                                          _sync_config_item_count                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

class TestImportForType:
    """_import_for_type derives the normalization context from the type and delegates to _import."""

    def test_derives_context_and_delegates(self) -> None:
        """It passes the type's special_type and the derived ImportTypeContext to _import."""
        mock_self = MagicMock()
        type_instance = MagicMock()
        type_instance.get_fields.return_value = [
            {'name': 'owner', 'type': 'ref', 'required': True},   # ref -> exempt from required
            {'name': 'host', 'type': 'text', 'required': True},
            {'name': 'note', 'type': 'text'},
        ]
        type_instance.get_sections.return_value = []
        type_instance.special_type = 'SUBNET'
        mock_self._import.return_value = 'RESULT'

        result = ObjectImporter._import_for_type(mock_self, ['cand'], type_instance)

        expected_context = ImportTypeContext(
            clearable_reference_fields={'owner'},
            field_type_map={'owner': 'ref', 'host': 'text', 'note': 'text'},
            required_top_level={'host'},
            required_mds_by_section={},
            top_level_field_defaults={'owner': None, 'host': None, 'note': None},
            mds_field_defaults_by_section={},
            field_options={},
            new_select_options={},
        )
        mock_self._import.assert_called_once_with(['cand'], 'SUBNET', expected_context)
        assert result == 'RESULT'

    def test_persists_new_select_options_when_the_import_records_them(self) -> None:
        """When the batch records new select options, _import_for_type delegates to the persist step."""
        mock_self = MagicMock()
        type_instance = MagicMock()
        type_instance.get_fields.return_value = [{'name': 'kind', 'type': 'select'}]
        type_instance.get_sections.return_value = []
        type_instance.special_type = None
        # simulate _import filling the context's new_select_options during the batch
        mock_self._import.side_effect = lambda candidates, special_type, ctx: ctx.new_select_options.update(
            {'kind': ['x']}) or 'RESULT'

        result = ObjectImporter._import_for_type(mock_self, ['cand'], type_instance)

        assert result == 'RESULT'
        mock_self._persist_new_select_options.assert_called_once_with(type_instance, {'kind': ['x']})

    def test_persist_new_select_options_applies_and_updates_the_type(self) -> None:
        """_persist_new_select_options adds the options to the type and saves it once via TypesManager."""
        mock_self = MagicMock()
        field = {'name': 'kind', 'type': 'select', 'extras': {'options': [{'name': 'a', 'label': 'a'}]}}
        type_instance = MagicMock()
        type_instance.get_fields.return_value = [field]
        type_instance.public_id = 5

        with patch(f'{PATH}.TypesManager') as types_manager_cls:
            ObjectImporter._persist_new_select_options(mock_self, type_instance, {'kind': ['b']})

        assert {'name': 'b', 'label': 'b'} in field['extras']['options']
        types_manager_cls.return_value.update_type.assert_called_once_with(5, type_instance)


class TestAbstractMethods:
    """generate_object and start_import must be implemented by concrete importers."""

    def test_generate_object_is_abstract(self) -> None:
        """The base generate_object raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            ObjectImporter.generate_object(MagicMock(), {})

    def test_start_import_is_abstract(self) -> None:
        """The base start_import raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            ObjectImporter.start_import(MagicMock())


class TestConfigItemLimit:
    """The cloud ConfigItem limit check compares the object count against the user's limit."""

    def test_limit_reached_when_count_at_limit(self) -> None:
        """At or above the user's limit the check reports True."""
        mock_self = MagicMock()
        mock_self.objects_manager.count_documents.return_value = 10
        user = SimpleNamespace(config_items_limit=10)

        assert ObjectImporter.check_config_item_limit_reached(mock_self, user) is True

    def test_limit_not_reached_below_limit(self) -> None:
        """Below the user's limit the check reports False."""
        mock_self = MagicMock()
        mock_self.objects_manager.count_documents.return_value = 3
        user = SimpleNamespace(config_items_limit=10)

        assert ObjectImporter.check_config_item_limit_reached(mock_self, user) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                          _sync_config_item_count                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

class TestSyncConfigItemCount:
    """The batch-sync helper reports the current total once and is best-effort."""

    def test_reports_current_count_once(self) -> None:
        """It forwards a single fresh count_documents() total to the portal helper."""
        mock_self = MagicMock()
        mock_self.objects_manager.count_documents.return_value = 42

        with patch(f'{PATH}.handle_sync_config_item_count') as sync:
            ObjectImporter._sync_config_item_count(mock_self)  # pylint: disable=protected-access

        sync.assert_called_once_with(mock_self.request_user, 42)

    def test_swallows_sync_errors(self) -> None:
        """A portal/transport failure is logged and swallowed, never raised into the import."""
        mock_self = MagicMock()

        with patch(f'{PATH}.handle_sync_config_item_count', side_effect=RuntimeError("boom")):
            ObjectImporter._sync_config_item_count(mock_self)  # pylint: disable=protected-access  # must not raise
