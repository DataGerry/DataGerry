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
Unit tests for the shared ISMS route helpers in isms_routes_helper.

Pure tests driven against MagicMock managers: ``bulk_delete_reporting_in_use`` (delete_item reports
whether a document was removed) and ``update_multiple_items`` (the bulk-update orchestration that
resolves existing ids in one batched query and reports a per-item result), plus the RiskAssessment
required-field guard - which is where the "name every missing field at once" behaviour is asserted,
since through HTTP the Cerberus schema already rejects four of the five before the guard is reached.
"""
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    REQUIRED_RISK_ASSESSMENT_FIELDS,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_helper import (
    bulk_delete_reporting_in_use,
    get_missing_risk_assessment_fields,
    guard_required_risk_assessment_fields,
    update_multiple_items,
)
# -------------------------------------------------------------------------------------------------------------------- #

ID_A: int = 11
ID_B: int = 12
ID_C: int = 13
MISSING_ID: int = 99


class TestBulkDeleteReportingInUse:
    """``bulk_delete_reporting_in_use`` deletes the unused subset and reports both lists sorted."""

    def test_deletes_unused_skips_in_use(self) -> None:
        """In-use ids are never passed to delete_item; the rest are deleted and both lists sorted."""
        manager = MagicMock()
        manager.delete_item.return_value = True

        result = bulk_delete_reporting_in_use(manager, [ID_C, ID_A, ID_B], {ID_B})

        deleted_calls = [call.args[0] for call in manager.delete_item.call_args_list]
        assert ID_B not in deleted_calls
        assert result == {'successfully': [ID_A, ID_C], 'in_use': [ID_B]}

    def test_non_existent_id_not_reported_deleted(self) -> None:
        """delete_item returning False (missing doc) keeps that id out of the deleted list."""
        manager = MagicMock()
        manager.delete_item.side_effect = lambda public_id: public_id == ID_A

        result = bulk_delete_reporting_in_use(manager, [ID_A, MISSING_ID], set())

        assert result == {'successfully': [ID_A], 'in_use': []}

    def test_all_in_use_deletes_nothing(self) -> None:
        """When every requested id is in use, delete_item is never called."""
        manager = MagicMock()

        result = bulk_delete_reporting_in_use(manager, [ID_A, ID_B], {ID_A, ID_B})

        manager.delete_item.assert_not_called()
        assert result == {'successfully': [], 'in_use': [ID_A, ID_B]}

    def test_mixed_deleted_in_use_and_missing(self) -> None:
        """One batch with an unused-existing (A), an in-use (B) and an unused-missing (C) id partitions cleanly."""
        manager = MagicMock()
        # A exists and is deleted; C is unused but does not exist (delete_item returns False)
        manager.delete_item.side_effect = lambda public_id: public_id == ID_A

        result = bulk_delete_reporting_in_use(manager, [ID_A, ID_B, ID_C], {ID_B})

        # B (in-use) is never deleted; C (missing) is attempted but not reported; only A lands in successfully
        assert ID_B not in [call.args[0] for call in manager.delete_item.call_args_list]
        assert result == {'successfully': [ID_A], 'in_use': [ID_B]}


def _existence_manager(existing_ids: list[int]) -> MagicMock:
    """Builds a MagicMock manager whose find_all returns docs for the given existing public_ids."""
    manager = MagicMock()
    manager.find_all.return_value = [{'public_id': public_id} for public_id in existing_ids]
    return manager


class TestUpdateMultipleItems:
    """``update_multiple_items`` batches the existence check and reports a per-item result."""

    def test_non_list_body_aborts_400(self) -> None:
        """A body that is not a list is rejected with HTTP 400."""
        with pytest.raises(HTTPException) as exc_info:
            update_multiple_items(MagicMock(), MagicMock(), {'public_id': ID_A}, "RiskClass", "tag")

        assert exc_info.value.code == 400

    def test_resolves_existence_in_one_query_without_per_item_get(self) -> None:
        """Existence is checked with a single batched find_all and never a per-item get_item (N+1 fix)."""
        manager = _existence_manager([ID_A, ID_B])

        update_multiple_items(
            manager, MagicMock(), [{'public_id': ID_A}, {'public_id': ID_B}], "RiskClass", "tag"
        )

        manager.find_all.assert_called_once_with(criteria={'public_id': {'$in': [ID_A, ID_B]}})
        manager.get_item.assert_not_called()

    def test_reports_per_item_status(self) -> None:
        """Existing ids update and succeed; a missing id and an id-less item both fail."""
        manager = _existence_manager([ID_A])
        model = MagicMock()

        results = update_multiple_items(
            manager, model,
            [{'public_id': ID_A}, {'public_id': MISSING_ID}, {'name': 'no id'}],
            "RiskClass", "tag",
        )

        by_id = {entry['public_id']: entry['status'] for entry in results}
        assert by_id == {ID_A: 'success', MISSING_ID: 'failed', None: 'failed'}
        # update_item runs only for the existing id
        manager.update_item.assert_called_once_with(ID_A, model.from_data.return_value)

    def test_no_public_ids_skips_find_all(self) -> None:
        """When no item carries a public_id, the existence query is skipped entirely."""
        manager = MagicMock()

        results = update_multiple_items(manager, MagicMock(), [{'name': 'no id'}], "RiskClass", "tag")

        manager.find_all.assert_not_called()
        assert results == [{'public_id': None, 'status': 'failed', 'message': 'Missing public_id'}]

    def test_update_failure_is_isolated_per_item(self) -> None:
        """An update_item raising for one id fails only that item; the rest still succeed."""
        manager = _existence_manager([ID_A, ID_B])

        def _fail_on_a(public_id: int, _data: object) -> None:
            if public_id == ID_A:
                raise RuntimeError('boom')

        manager.update_item.side_effect = _fail_on_a

        results = update_multiple_items(
            manager, MagicMock(), [{'public_id': ID_A}, {'public_id': ID_B}], "RiskClass", "tag"
        )

        by_id = {entry['public_id']: entry['status'] for entry in results}
        assert by_id == {ID_A: 'failed', ID_B: 'success'}


# -------------------------------------------------------------------------------------------------------------------- #
#                                        RiskAssessment required-field guard                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def _complete_risk_assessment() -> dict:
    """Builds a payload carrying a value for every mandatory RiskAssessment field."""
    return {
        'risk_id': 1,
        'object_id_ref_type': 'OBJECT',
        'object_id': 2,
        'risk_owner_id': 3,
        'risk_assessment_date': {'$date': 1600000000000},
    }


class TestGetMissingRiskAssessmentFields:
    """Which mandatory fields a payload fails to supply."""

    def test_a_complete_payload_reports_nothing(self) -> None:
        """Every mandatory field filled means no complaint."""
        assert get_missing_risk_assessment_fields(_complete_risk_assessment()) == []

    def test_optional_lifecycle_fields_are_not_required(self) -> None:
        """The treatment / audit blocks may be absent or null - they belong to later stages."""
        payload = _complete_risk_assessment()
        payload.update({
            'risk_treatment_option': None,
            'implementation_status': None,
            'audit_done_date': None,
            'auditor_id': None,
            'risk_assessor_id': None,
        })

        assert get_missing_risk_assessment_fields(payload) == []

    @pytest.mark.parametrize('field_name', list(REQUIRED_RISK_ASSESSMENT_FIELDS))
    def test_an_absent_field_is_reported(self, field_name: str) -> None:
        """A key that is not sent at all is missing."""
        payload = _complete_risk_assessment()
        payload.pop(field_name)

        assert get_missing_risk_assessment_fields(payload) == [field_name]

    @pytest.mark.parametrize('field_name', list(REQUIRED_RISK_ASSESSMENT_FIELDS))
    def test_a_null_field_is_reported(self, field_name: str) -> None:
        """A key sent as null is missing too (the schema still allows null for risk_owner_id)."""
        payload = _complete_risk_assessment()
        payload[field_name] = None

        assert get_missing_risk_assessment_fields(payload) == [field_name]

    @pytest.mark.parametrize('empty_value', ['', [], {}])
    def test_an_empty_value_is_reported(self, empty_value: object) -> None:
        """An empty date object is as unusable as no date at all."""
        payload = _complete_risk_assessment()
        payload['risk_assessment_date'] = empty_value

        assert get_missing_risk_assessment_fields(payload) == ['risk_assessment_date']

    def test_a_zero_id_is_not_treated_as_missing(self) -> None:
        """Only None / empty containers count - a 0 is a value, and the schema rejects it separately."""
        payload = _complete_risk_assessment()
        payload['object_id'] = 0

        assert get_missing_risk_assessment_fields(payload) == []

    def test_every_missing_field_is_reported_in_schema_order(self) -> None:
        """All offenders are collected at once, so one response can name them all."""
        assert get_missing_risk_assessment_fields({}) == list(REQUIRED_RISK_ASSESSMENT_FIELDS)

    def test_several_missing_fields_are_all_reported(self) -> None:
        """A partially filled payload names every field it is still missing."""
        payload = _complete_risk_assessment()
        payload['risk_owner_id'] = None
        payload.pop('risk_assessment_date')

        assert get_missing_risk_assessment_fields(payload) == ['risk_owner_id', 'risk_assessment_date']


class TestGuardRequiredRiskAssessmentFields:
    """The 400 the write paths raise."""

    def test_a_complete_payload_passes(self) -> None:
        """A complete assessment is not refused."""
        guard_required_risk_assessment_fields(_complete_risk_assessment())  # must not raise

    def test_a_missing_field_aborts_400_naming_it(self) -> None:
        """The response names the offending field."""
        payload = _complete_risk_assessment()
        payload['risk_owner_id'] = None

        with pytest.raises(HTTPException) as err:
            guard_required_risk_assessment_fields(payload)

        assert err.value.code == 400
        assert 'risk_owner_id' in err.value.description

    def test_the_message_names_every_missing_field(self) -> None:
        """All missing fields appear in one message, so the caller can highlight them together."""
        with pytest.raises(HTTPException) as err:
            guard_required_risk_assessment_fields({})

        for field_name in REQUIRED_RISK_ASSESSMENT_FIELDS:
            assert field_name in err.value.description
