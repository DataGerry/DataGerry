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

Pure tests driven against MagicMock managers: ``abort_if_isms_cap_reached`` (the 400 once a bounded
ISMS collection is full), ``bulk_delete_reporting_in_use`` (delete_item reports
whether a document was removed) and ``update_multiple_items`` (the all-or-nothing bulk update: every
item judged by the write schema first, every reason named in one 400, then one bulk write undone on
failure), plus the RiskAssessment required-field guard - which is where the "name every missing field at
once" behaviour is asserted, since through HTTP the Cerberus schema already rejects four of the five before
the guard is reached.

Also the manager-error message helpers (``manager_error_message(s)``, which fill an entity's labels and
leave ``{public_id}`` for the route decorator) and ``require_created_item`` (the 500 when an insert
cannot read back its own write).
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.class_schema.write_schema_helper import build_write_schema
from cmdb.models.isms_model import IsmsRiskClass
from cmdb.interface.rest_api.routes.isms_routes import isms_routes_constants
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    ISMS_CAP_REACHED_MSG,
    ISMS_LIKELIHOODS_LABEL,
    MAX_ISMS_SCALE_ENTRIES,
    REQUIRED_RISK_ASSESSMENT_FIELDS,
    RISK_CLASS_LABEL,
    THREAT_LABEL,
    VULNERABILITY_LABEL,
    IsmsEntityLabel,
    IsmsManagerErrorMessage,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_helper import (
    abort_if_isms_cap_reached,
    bulk_delete_reporting_in_use,
    duplicate_bulk_ids,
    get_missing_risk_assessment_fields,
    guard_required_risk_assessment_fields,
    manager_error_message,
    manager_error_messages,
    require_created_item,
    update_multiple_items,
)
# -------------------------------------------------------------------------------------------------------------------- #

ID_A: int = 11
ID_B: int = 12
ID_C: int = 13
# The id a bool would alias in Python: True == 1
TRUE_ALIASED_ID: int = 1
MISSING_ID: int = 99


PUBLIC_ID_PLACEHOLDER: str = '{public_id}'
ENTITY_PLACEHOLDERS: tuple[str, ...] = ('{entity}', '{entities}')
# The one verb form every failure message shares; the refusal is phrased as a rule instead
FAILURE_PREFIX: str = 'Failed to '
REFUSALS: frozenset[IsmsManagerErrorMessage] = frozenset({IsmsManagerErrorMessage.USED_BY_RISKS})
# Templates addressing one stored item carry its id
ID_TEMPLATES: frozenset[IsmsManagerErrorMessage] = frozenset({
    IsmsManagerErrorMessage.GET,
    IsmsManagerErrorMessage.UPDATE,
    IsmsManagerErrorMessage.DELETE,
    IsmsManagerErrorMessage.USED_BY_RISKS,
})
ALL_LABELS: list[IsmsEntityLabel] = [
    value for value in vars(isms_routes_constants).values() if isinstance(value, IsmsEntityLabel)
]


class _FirstError(Exception):
    """One manager error class."""


class _SecondError(Exception):
    """Another, mapped to a different template."""


def _counting_manager(count: int) -> MagicMock:
    """A manager whose collection holds ``count`` documents."""
    manager = MagicMock()
    manager.count_documents.return_value = count

    return manager


class TestAbortIfIsmsCapReached:
    """``abort_if_isms_cap_reached`` refuses a create once the collection holds ``cap`` entries."""

    @pytest.mark.parametrize('count', [MAX_ISMS_SCALE_ENTRIES, MAX_ISMS_SCALE_ENTRIES + 1], ids=['at', 'over'])
    def test_a_full_collection_is_a_400_naming_cap_and_entity(self, count: int) -> None:
        """A business rule, not a missing right - so 400, never 403"""
        with pytest.raises(HTTPException) as exc_info:
            abort_if_isms_cap_reached(_counting_manager(count), MAX_ISMS_SCALE_ENTRIES, ISMS_LIKELIHOODS_LABEL)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST
        assert exc_info.value.description == ISMS_CAP_REACHED_MSG.format(cap=MAX_ISMS_SCALE_ENTRIES,
                                                                          entity_label=ISMS_LIKELIHOODS_LABEL)

    def test_one_below_the_cap_passes(self) -> None:
        """The last free slot can still be filled"""
        manager = _counting_manager(MAX_ISMS_SCALE_ENTRIES - 1)

        abort_if_isms_cap_reached(manager, MAX_ISMS_SCALE_ENTRIES, ISMS_LIKELIHOODS_LABEL)  # must not raise

        manager.count_documents.assert_called_once_with()


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


RISK_CLASS_WRITE_SCHEMA: dict[str, Any] = build_write_schema(IsmsRiskClass.SCHEMA)
BULK_MAX_ITEMS: int = 3


def _risk_class(public_id: Any, **overrides: Any) -> dict[str, Any]:
    """A whole IsmsRiskClass as the frontend sends it back: the list read's nulls included"""
    item: dict[str, Any] = {'public_id': public_id, 'name': f'class-{public_id}', 'color': '#00ff00',
                            'sort': 0, 'description': None}
    item.update(overrides)

    return item


def _stored_manager(existing_ids: list[int]) -> MagicMock:
    """A manager whose find_all and get_one_by answer the stored risk classes of the given ids"""
    stored: dict[int, dict[str, Any]] = {public_id: _risk_class(public_id, name='stored') for public_id in existing_ids}
    manager = MagicMock()
    manager.find_all.return_value = list(stored.values())
    manager.get_one_by.side_effect = lambda criteria: stored.get(criteria['public_id'])

    return manager


def _bulk_update(manager: MagicMock, data: Any, max_items: int = BULK_MAX_ITEMS) -> list[dict[str, Any]]:
    """Runs the helper with the real risk-class model and write schema"""
    return update_multiple_items(manager, IsmsRiskClass, data, RISK_CLASS_WRITE_SCHEMA, RISK_CLASS_LABEL, max_items)


def _refusal(manager: MagicMock, data: Any, max_items: int = BULK_MAX_ITEMS) -> HTTPException:
    """The 400 a refused bulk update raises, after asserting nothing was written"""
    with pytest.raises(HTTPException) as raised:
        _bulk_update(manager, data, max_items)

    assert raised.value.code == HTTPStatus.BAD_REQUEST
    manager.bulk_write.assert_not_called()

    return raised.value


class TestUpdateMultipleItems:
    """``update_multiple_items`` judges every item first, then writes them all in one bulk write"""

    def test_every_item_is_written_in_one_ordered_bulk_write(self) -> None:
        """One existence read, one write, one success entry per item in request order"""
        manager = _stored_manager([ID_A, ID_B])

        results = _bulk_update(manager, [_risk_class(ID_B, sort=0), _risk_class(ID_A, sort=1)])

        assert results == [{'public_id': ID_B, 'status': 'success'}, {'public_id': ID_A, 'status': 'success'}]
        manager.find_all.assert_called_once_with(criteria={'public_id': {'$in': [ID_B, ID_A]}})
        manager.get_item.assert_not_called()
        manager.update_item.assert_not_called()
        operations = manager.bulk_write.call_args.args[0]
        assert [(op._filter, op._doc['$set']['sort']) for op in operations] == [  # pylint: disable=protected-access
            ({'public_id': ID_B}, 0), ({'public_id': ID_A}, 1),
        ]

    def test_the_written_document_is_the_models_serialisation(self) -> None:
        """Unknown keys are purged, the id comes from the item, a left-out optional key is stored as null"""
        manager = _stored_manager([ID_A])
        item = {'public_id': ID_A, 'name': 'High', 'color': '#ff0000', 'ui_state': 'dragging'}

        _bulk_update(manager, [item])

        written = manager.bulk_write.call_args.args[0][0]._doc['$set']  # pylint: disable=protected-access
        assert written == {'public_id': ID_A, 'name': 'High', 'color': '#ff0000', 'sort': None, 'description': None}

    def test_an_empty_list_writes_nothing(self) -> None:
        """Nothing to do is not an error"""
        manager = MagicMock()

        assert _bulk_update(manager, []) == []
        manager.find_all.assert_not_called()
        manager.bulk_write.assert_not_called()

    @pytest.mark.parametrize('body', [{'public_id': ID_A}, None, 'items'], ids=['object', 'none', 'string'])
    def test_a_body_that_is_not_a_list_is_refused(self, body: Any) -> None:
        """Named with the entity's real plural"""
        refusal = _refusal(MagicMock(), body)

        assert refusal.description == 'The request body must be a list of RiskClasses!'

    def test_more_items_than_allowed_are_refused(self) -> None:
        """The cap is checked before any item is judged"""
        manager = MagicMock()
        refusal = _refusal(manager, [_risk_class(ID_A)] * (BULK_MAX_ITEMS + 1))

        assert refusal.description == (
            f'At most {BULK_MAX_ITEMS} RiskClasses can be updated at once, but {BULK_MAX_ITEMS + 1} were sent!'
        )
        manager.find_all.assert_not_called()

    def test_exactly_the_cap_is_accepted(self) -> None:
        """The cap itself is allowed"""
        ids = [ID_A, ID_B, ID_C]

        assert len(_bulk_update(_stored_manager(ids), [_risk_class(i) for i in ids])) == BULK_MAX_ITEMS

    def test_every_invalid_item_is_named_and_nothing_is_written(self) -> None:
        """One bad item refuses the whole list, and the refusal names each reason with its position"""
        manager = _stored_manager([ID_A, ID_B])
        refusal = _refusal(manager, [
            _risk_class(ID_A, name=123),
            'not an item',
            _risk_class(ID_B, color='', sort='first'),
        ])

        assert refusal.description == (
            'No RiskClasses were updated, because some items are invalid: '
            f'item #1 (public_id {ID_A}): name: must be of string type'
            ' | item #2 is not an object'
            f' | item #3 (public_id {ID_B}): color: empty values not allowed; sort: must be of integer type'
        )
        manager.find_all.assert_not_called()

    def test_a_missing_required_key_is_named(self) -> None:
        """A whole object is required, as on the single update"""
        item = _risk_class(ID_A)
        del item['color']

        assert 'color: required field' in _refusal(_stored_manager([ID_A]), [item]).description

    @pytest.mark.parametrize('public_id', [None, True, str(ID_A), float(ID_A), [ID_A]],
                             ids=['missing', 'bool', 'string', 'float', 'list'])
    def test_an_item_without_an_integer_id_is_refused(self, public_id: Any) -> None:
        """A bool too: True == 1 in Python, but MongoDB would not match it against the stored id"""
        item = _risk_class(public_id)

        if public_id is None:
            del item['public_id']

        refusal = _refusal(_stored_manager([TRUE_ALIASED_ID, ID_A]), [_risk_class(ID_B), item])

        assert refusal.description.endswith('item #2 has no integer public_id')

    def test_an_id_sent_twice_is_refused(self) -> None:
        """Last-one-wins is no order anybody chose"""
        manager = _stored_manager([ID_A, ID_B])
        refusal = _refusal(manager, [_risk_class(ID_A), _risk_class(ID_B), _risk_class(ID_A)])

        assert refusal.description == (
            f'No RiskClasses were updated, because these ids are sent more than once: [{ID_A}]'
        )
        manager.find_all.assert_not_called()

    def test_an_unknown_id_is_refused(self) -> None:
        """Every missing id named, ascending"""
        manager = _stored_manager([ID_A])
        refusal = _refusal(manager, [_risk_class(MISSING_ID), _risk_class(ID_A), _risk_class(ID_C)])

        assert refusal.description == (
            f'No RiskClasses were updated, because these ids do not exist: [{ID_C}, {MISSING_ID}]'
        )

    def test_a_failed_write_is_undone_and_re_raised(self) -> None:
        """Every item goes back to its snapshot; the request fails with the error the write hit"""
        manager = _stored_manager([ID_A, ID_B])
        manager.bulk_write.side_effect = RuntimeError('write failed')

        with pytest.raises(RuntimeError, match='write failed'):
            _bulk_update(manager, [_risk_class(ID_A), _risk_class(ID_B)])

        restored = sorted(call.args[0] for call in manager.replace.call_args_list)
        assert restored == [ID_A, ID_B]
        assert manager.replace.call_args_list[0].args[1]['name'] == 'stored'


class TestDuplicateBulkIds:
    """``duplicate_bulk_ids`` names each repeated id once"""

    def test_distinct_ids_have_no_duplicates(self) -> None:
        """All distinct"""
        assert duplicate_bulk_ids([ID_A, ID_B]) == []

    def test_each_repeat_is_named_once_ascending(self) -> None:
        """Three of one, two of another"""
        assert duplicate_bulk_ids([ID_B, ID_A, ID_B, ID_A, ID_B]) == [ID_A, ID_B]


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


class TestManagerErrorTemplates:
    """The shape every IsmsManagerErrorMessage keeps, so one rule reads the same on every route."""

    @pytest.mark.parametrize('template', list(IsmsManagerErrorMessage), ids=lambda t: t.name)
    def test_every_template_names_its_entity(self, template: IsmsManagerErrorMessage) -> None:
        """A message that does not say which entity failed would read the same on twelve routes."""
        assert any(placeholder in template.value for placeholder in ENTITY_PLACEHOLDERS)

    @pytest.mark.parametrize('template', list(IsmsManagerErrorMessage), ids=lambda t: t.name)
    def test_exactly_the_single_item_templates_carry_the_id(self, template: IsmsManagerErrorMessage) -> None:
        """The id is in every message about one stored item, and in no message about several."""
        assert (PUBLIC_ID_PLACEHOLDER in template.value) == (template in ID_TEMPLATES)

    @pytest.mark.parametrize('template', list(IsmsManagerErrorMessage), ids=lambda t: t.name)
    def test_every_failure_uses_the_one_verb_form(self, template: IsmsManagerErrorMessage) -> None:
        """"Failed to ..." everywhere - the drift between "Could not" and "Failed to" is what this pins."""
        assert template.value.startswith(FAILURE_PREFIX) == (template not in REFUSALS)

    def test_no_two_entities_share_a_label(self) -> None:
        """A label copied from a sibling entity would name the wrong thing in every message."""
        singulars = [label.singular for label in ALL_LABELS]
        plurals = [label.plural for label in ALL_LABELS]

        assert len(set(singulars)) == len(singulars)
        assert len(set(plurals)) == len(plurals)


class TestManagerErrorMessage:
    """Filling a template with an entity's labels, the id left for the route."""

    def test_the_singular_label_is_filled_and_the_id_kept(self) -> None:
        """``{public_id}`` survives, for handle_manager_errors to fill from the route argument."""
        message = manager_error_message(THREAT_LABEL, IsmsManagerErrorMessage.GET)

        assert THREAT_LABEL.singular in message
        assert PUBLIC_ID_PLACEHOLDER in message
        assert not any(placeholder in message for placeholder in ENTITY_PLACEHOLDERS)

    def test_the_plural_label_is_filled(self) -> None:
        """The list and bulk messages speak of several."""
        message = manager_error_message(VULNERABILITY_LABEL, IsmsManagerErrorMessage.ITERATE)

        assert VULNERABILITY_LABEL.plural in message
        assert not any(placeholder in message for placeholder in ENTITY_PLACEHOLDERS)

    def test_the_result_still_formats_with_the_id(self) -> None:
        """What the decorator does with it next."""
        message = manager_error_message(THREAT_LABEL, IsmsManagerErrorMessage.DELETE)

        assert str(ID_A) in message.format(public_id=ID_A)


class TestManagerErrorMessages:
    """A route's whole table, one template per error class."""

    def test_each_class_gets_its_own_filled_template(self) -> None:
        """Order and pairing are kept - a swapped pair would give each class the other's message."""
        table = manager_error_messages(THREAT_LABEL, {
            _FirstError: IsmsManagerErrorMessage.INSERT,
            _SecondError: IsmsManagerErrorMessage.GET_CREATED,
        })

        assert table == {
            _FirstError: manager_error_message(THREAT_LABEL, IsmsManagerErrorMessage.INSERT),
            _SecondError: manager_error_message(THREAT_LABEL, IsmsManagerErrorMessage.GET_CREATED),
        }

    def test_an_empty_table_stays_empty(self) -> None:
        """Nothing is invented; handle_manager_errors refuses an empty table itself."""
        assert not manager_error_messages(THREAT_LABEL, {})


class TestRequireCreatedItem:
    """The read-back of a created item: found is the answer, missing is the server's own fault."""

    def test_a_found_item_is_answered(self) -> None:
        """The document itself, untouched."""
        item = {'public_id': ID_A}

        assert require_created_item(item, THREAT_LABEL) is item

    @pytest.mark.parametrize('missing', [None, {}], ids=['none', 'empty'])
    def test_a_missing_item_is_a_500(self, missing: dict | None) -> None:
        """Not a 404: the caller asked for nothing, the server lost sight of its own write."""
        with pytest.raises(HTTPException) as exc_info:
            require_created_item(missing, THREAT_LABEL)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert exc_info.value.description == manager_error_message(
            THREAT_LABEL, IsmsManagerErrorMessage.GET_CREATED,
        )
