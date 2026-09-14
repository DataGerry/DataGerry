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
Unit tests for cmdb.manager.extendable_options_manager

DB-free: the manager is built against a mocked MongoDatabaseManager, which its __init__ only stores.
Everything but ``get_option_values`` is inherited from GenericManager and covered once in
test_generic_manager.py, so what is tested here is the binding plus that one read - the snapshot the
CABLE blueprint is seeded from
"""
from typing import Any

from unittest.mock import MagicMock

import pytest

from cmdb.manager import ExtendableOptionsManager
from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import MANAGER_CLASSES, ManagerType
from cmdb.models.extendable_option_model import (
    CmdbExtendableOption,
    ExtendableOptionKey,
    OptionType,
)
from cmdb.errors.manager import BaseManagerGetError, BaseManagerIterationError
from cmdb.errors.manager.extendable_options_manager import (
    EXTENDABLE_OPTIONS_MANAGER_ERRORS,
    ExtendableOptionsManagerGetError,
    ExtendableOptionsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

DB_NAME: str = 'testdb'


@pytest.fixture(name='manager')
def fixture_manager() -> ExtendableOptionsManager:
    """An ExtendableOptionsManager over a mocked database manager (its __init__ performs no I/O)"""
    return ExtendableOptionsManager(MagicMock(name='dbm'), DB_NAME)


def _option(public_id: int, value: Any) -> dict[str, Any]:
    """A stored CmdbExtendableOption document"""
    return _option_of(public_id, value, OptionType.CABLE_TYPE)


def _option_of(public_id: int, value: Any, option_type: OptionType) -> dict[str, Any]:
    """A stored CmdbExtendableOption document of the given OptionType"""
    return {
        ExtendableOptionKey.PUBLIC_ID.value: public_id,
        ExtendableOptionKey.VALUE.value: value,
        ExtendableOptionKey.OPTION_TYPE.value: option_type.value,
    }


class TestTheBinding:
    """What the manager is bound to."""

    def test_is_a_generic_manager(self, manager: ExtendableOptionsManager) -> None:
        """The CRUD is plain, so the shared implementation covers it"""
        assert isinstance(manager, GenericManager)

    def test_stores_extendable_options(self, manager: ExtendableOptionsManager) -> None:
        """The model decides both the collection and how documents are (de)serialised"""
        assert manager.model is CmdbExtendableOption
        assert manager.collection == CmdbExtendableOption.COLLECTION

    def test_uses_its_own_exception_map(self, manager: ExtendableOptionsManager) -> None:
        """A failure has to surface as this manager's error, not another domain's"""
        assert manager.exceptions is EXTENDABLE_OPTIONS_MANAGER_ERRORS

    def test_the_provider_resolves_the_manager_type(self) -> None:
        """Without this entry the route's get_manager call would raise BaseManagerInitError"""
        assert MANAGER_CLASSES[ManagerType.EXTENDABLE_OPTIONS] is ExtendableOptionsManager


class TestGetOptionValues:
    """The snapshot a consumer that cannot reference the option list is seeded from."""

    def test_reads_only_the_requested_list(self, manager: ExtendableOptionsManager) -> None:
        """A PORT_SPEED value appearing in a cable-type select would be nonsense"""
        manager.find = MagicMock(return_value=[])

        manager.get_option_values(OptionType.CABLE_TYPE.value)

        assert manager.find.call_args.kwargs['criteria'] == {
            ExtendableOptionKey.OPTION_TYPE.value: OptionType.CABLE_TYPE.value,
        }

    def test_orders_by_public_id(self, manager: ExtendableOptionsManager) -> None:
        """
        The predefined values keep the order they were seeded in, customer additions follow

        Sorting by value instead would scramble a deliberately ordered list - the port speeds ship
        ascending, and '100M' sorts before '10G' alphabetically.
        """
        manager.find = MagicMock(return_value=[])

        manager.get_option_values(OptionType.CABLE_TYPE.value)

        assert manager.find.call_args.kwargs['sort'] == [
            (ExtendableOptionKey.PUBLIC_ID.value, CmdbExtendableOption.DAO_ASCENDING),
        ]

    def test_returns_the_plain_values(self, manager: ExtendableOptionsManager) -> None:
        """The caller wants the values, not the documents that carry them"""
        manager.find = MagicMock(return_value=[_option(1, 'Cat6a'), _option(2, 'OM4')])

        assert manager.get_option_values(OptionType.CABLE_TYPE.value) == ['Cat6a', 'OM4']

    def test_an_empty_list_is_an_empty_result(self, manager: ExtendableOptionsManager) -> None:
        """A customer may have deleted every option of a list; that is not an error"""
        manager.find = MagicMock(return_value=[])

        assert manager.get_option_values(OptionType.CABLE_TYPE.value) == []

    def test_a_drifted_document_is_skipped_rather_than_serialised(
            self, manager: ExtendableOptionsManager) -> None:
        """
        A non-string value would end up as an option name the frontend can not render

        Skipping it keeps the rest of the list usable instead of failing the whole type creation.
        """
        manager.find = MagicMock(return_value=[_option(1, 'Cat6a'), _option(2, None), _option(3, 7)])

        assert manager.get_option_values(OptionType.CABLE_TYPE.value) == ['Cat6a']

    def test_wraps_a_read_failure(self, manager: ExtendableOptionsManager) -> None:
        """A BaseManager failure surfaces as the manager's own error type"""
        manager.find = MagicMock(side_effect=BaseManagerGetError('boom'))

        with pytest.raises(ExtendableOptionsManagerGetError):
            manager.get_option_values(OptionType.CABLE_TYPE.value)


class TestGetOptionValuesById:
    """The public_id -> value lookup a report resolves its option references through."""

    def test_reads_every_requested_list_in_one_query(self, manager: ExtendableOptionsManager) -> None:
        """One '$in' over the index's option_type prefix, not a query per list"""
        manager.find = MagicMock(return_value=[])

        manager.get_option_values_by_id([OptionType.IMPLEMENTATION_STATE.value, OptionType.CONTROL_MEASURE.value])

        assert manager.find.call_count == 1
        assert manager.find.call_args.kwargs['criteria'] == {
            ExtendableOptionKey.OPTION_TYPE.value: {
                '$in': [OptionType.IMPLEMENTATION_STATE.value, OptionType.CONTROL_MEASURE.value],
            },
        }

    def test_reads_only_the_three_keys_a_label_lookup_needs(self, manager: ExtendableOptionsManager) -> None:
        """The SOA report resolves labels for every control measure it lists; no document body is needed"""
        manager.find = MagicMock(return_value=[])

        manager.get_option_values_by_id([OptionType.CONTROL_MEASURE.value])

        assert manager.find.call_args.kwargs['projection'] == {
            ExtendableOptionKey.PUBLIC_ID.value: 1,
            ExtendableOptionKey.VALUE.value: 1,
            ExtendableOptionKey.OPTION_TYPE.value: 1,
        }

    def test_the_values_are_grouped_by_option_type(self, manager: ExtendableOptionsManager) -> None:
        """Both lists come back from one read, and the caller needs them apart"""
        manager.find = MagicMock(return_value=[
            _option_of(1, 'Open', OptionType.IMPLEMENTATION_STATE),
            _option_of(2, 'Implemented', OptionType.IMPLEMENTATION_STATE),
            _option_of(3, 'ISO 27001:2022', OptionType.CONTROL_MEASURE),
        ])

        assert manager.get_option_values_by_id([
            OptionType.IMPLEMENTATION_STATE.value, OptionType.CONTROL_MEASURE.value,
        ]) == {
            OptionType.IMPLEMENTATION_STATE.value: {1: 'Open', 2: 'Implemented'},
            OptionType.CONTROL_MEASURE.value: {3: 'ISO 27001:2022'},
        }

    def test_an_empty_request_reads_nothing(self, manager: ExtendableOptionsManager) -> None:
        """A caller with no option types to resolve must not send a '$in' over the whole collection"""
        manager.find = MagicMock(return_value=[])

        assert manager.get_option_values_by_id([]) == {}
        assert manager.find.call_count == 0

    def test_a_list_with_no_readable_option_gets_no_entry(self, manager: ExtendableOptionsManager) -> None:
        """An absent entry and an empty map are the same answer: nothing resolves"""
        manager.find = MagicMock(return_value=[])

        assert manager.get_option_values_by_id([OptionType.CONTROL_MEASURE.value]) == {}

    def test_a_drifted_document_is_left_out(self, manager: ExtendableOptionsManager) -> None:
        """
        An option missing its value or option_type simply does not resolve

        Mapping it to None would put a null where the report shows a label, which reads as a
        resolved value rather than as a missing one.
        """
        manager.find = MagicMock(return_value=[
            _option_of(1, 'Open', OptionType.IMPLEMENTATION_STATE),
            {ExtendableOptionKey.PUBLIC_ID.value: 2,
             ExtendableOptionKey.OPTION_TYPE.value: OptionType.IMPLEMENTATION_STATE.value},
            {ExtendableOptionKey.VALUE.value: 'orphan',
             ExtendableOptionKey.OPTION_TYPE.value: OptionType.IMPLEMENTATION_STATE.value},
        ])

        assert manager.get_option_values_by_id([OptionType.IMPLEMENTATION_STATE.value]) == {
            OptionType.IMPLEMENTATION_STATE.value: {1: 'Open'},
        }

    def test_wraps_a_read_failure(self, manager: ExtendableOptionsManager) -> None:
        """A BaseManager failure surfaces as the manager's own error type"""
        manager.find = MagicMock(side_effect=BaseManagerGetError('boom'))

        with pytest.raises(ExtendableOptionsManagerGetError):
            manager.get_option_values_by_id([OptionType.CONTROL_MEASURE.value])


class TestIterateOptionDocuments:
    """The read behind the list route, which answers documents rather than models."""

    def test_it_answers_the_documents_and_the_total(self, manager: ExtendableOptionsManager) -> None:
        """The route needs both: the page it sends and the total the envelope carries"""
        documents = [_option(1, 'Cat6a'), _option(2, 'OM4')]
        manager.iterate_query = MagicMock(return_value=(documents, 2))

        assert manager.iterate_option_documents(BuilderParameters({})) == (documents, 2)

    def test_no_model_is_built(self, manager: ExtendableOptionsManager) -> None:
        """
        Deliberately not iterate_items: that builds a model per document

        The frontend asks for the whole list (limit=0) twice per ISMS or port form, and the route
        converted every instance straight back into a dict.
        """
        manager.iterate_query = MagicMock(return_value=([_option(1, 'Cat6a')], 1))

        documents, _ = manager.iterate_option_documents(BuilderParameters({}))

        assert all(isinstance(document, dict) for document in documents)

    def test_the_query_parameters_are_passed_through(self, manager: ExtendableOptionsManager) -> None:
        """Filter, sort and pagination are the collection parameters the route parsed"""
        builder_params = BuilderParameters({ExtendableOptionKey.OPTION_TYPE.value: OptionType.PORT_TYPE.value})
        manager.iterate_query = MagicMock(return_value=([], 0))

        manager.iterate_option_documents(builder_params)

        assert manager.iterate_query.call_args.args[0] is builder_params

    def test_wraps_a_read_failure(self, manager: ExtendableOptionsManager) -> None:
        """A failed aggregation surfaces as the manager's iteration error, which the route maps to 400"""
        manager.iterate_query = MagicMock(side_effect=BaseManagerIterationError('boom'))

        with pytest.raises(ExtendableOptionsManagerIterationError):
            manager.iterate_option_documents(BuilderParameters({}))
