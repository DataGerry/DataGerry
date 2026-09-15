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
Unit tests for the OpenCelium execution-log route helpers

The cloud-mode connector-name rewrite and the required-parameter reads, extracted from the routes so
they can be driven without an OpenCelium round-trip.

**The rewrite had never been executed.** It strips the `<database>_` prefix every connector carries on
a hosted installation, and inline in the route it iterated the payload as a list of dicts while the
manager annotated it as a dict, subscripted `connectorName` unguarded, and unmapped in STRICT mode -
so it would have raised for a payload of the annotated shape, for a flowchart without the key, and for
a connector name carrying no prefix. All three are pinned here, in both payload shapes, because the
real one is OpenCelium's to decide.

The parameter reads are pinned for the opposite reason: they refused `?connectionId=0` as "not
provided", because a parsed 0 is falsy.
"""
from http import HTTPStatus
from typing import Any

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.rest_api.routes.open_celium_routes.oc_connection_log_helper import (
    build_connection_log_manager,
    required_int_param_or_abort,
    required_str_param_or_abort,
    unmap_flowchart_connector_names,
)
from cmdb.interface.rest_api.routes.open_celium_routes.oc_routes_constants import (
    OcLogQueryParam,
    OcResponseKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

CONNECTOR_NAME_KEY: str = OcResponseKey.CONNECTOR_NAME.value
TENANT_DATABASE: str = 'db_customer'


def _app() -> BaseCmdbApp:
    """A BaseCmdbApp with a stub database manager."""
    app = BaseCmdbApp(__name__)
    app.database_manager = 'the-dbm'
    app.cloud_mode = False
    app.local_mode = False

    return app


def _flowchart(connector_name: Any = 'db_customer_MySQL') -> dict[str, Any]:
    """One flowchart of an execution log, as OpenCelium answers it in cloud mode."""
    return {CONNECTOR_NAME_KEY: connector_name, 'label': 'step 1'}


# -------------------------------------------------------------------------------------------------------------------- #
#                                        the cloud-mode connector-name rewrite                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUnmapFlowchartConnectorNames:
    """Stripping the tenant prefix before a flowchart reaches a client."""

    def test_a_list_of_flowcharts_is_unprefixed(self) -> None:
        """The shape the endpoint answers in practice"""
        flowcharts = [_flowchart(), _flowchart('db_customer_Jira')]

        unmap_flowchart_connector_names(flowcharts)

        assert [flowchart[CONNECTOR_NAME_KEY] for flowchart in flowcharts] == ['customer_MySQL', 'customer_Jira']

    def test_a_single_flowchart_dict_is_unprefixed(self) -> None:
        """
        The shape the manager's annotation claimed

        Iterated as a list of dicts, a dict yields its KEYS - so the inline version raised a
        TypeError for exactly this payload, on every hosted request.
        """
        flowchart = _flowchart()

        unmap_flowchart_connector_names(flowchart)

        assert flowchart[CONNECTOR_NAME_KEY] == 'customer_MySQL'

    def test_a_mapping_of_flowcharts_is_unprefixed(self) -> None:
        """A keyed collection is treated as flowcharts too, not as one flowchart"""
        flowcharts = {'first': _flowchart(), 'second': _flowchart('db_customer_Jira')}

        unmap_flowchart_connector_names(flowcharts)

        assert flowcharts['first'][CONNECTOR_NAME_KEY] == 'customer_MySQL'
        assert flowcharts['second'][CONNECTOR_NAME_KEY] == 'customer_Jira'

    def test_the_payload_is_answered_as_well_as_edited(self) -> None:
        """Callers may use either; the route uses the return value"""
        flowcharts = [_flowchart()]

        assert unmap_flowchart_connector_names(flowcharts) is flowcharts

    def test_a_flowchart_without_the_key_is_left_alone(self) -> None:
        """It used to be subscripted unguarded - a KeyError, i.e. a 500 for the whole log view"""
        flowcharts = [{'label': 'step 1'}]

        unmap_flowchart_connector_names(flowcharts)

        assert flowcharts == [{'label': 'step 1'}]

    @pytest.mark.parametrize('connector_name', [None, 7, ['db_customer_MySQL'], {}])
    def test_a_non_text_name_is_left_alone(self, connector_name: Any) -> None:
        """The payload is another product's; a name that is not text cannot carry a prefix"""
        flowcharts = [_flowchart(connector_name)]

        unmap_flowchart_connector_names(flowcharts)

        assert flowcharts[0][CONNECTOR_NAME_KEY] == connector_name

    def test_a_name_without_a_prefix_is_answered_unchanged(self) -> None:
        """
        Unmapped in strict mode this raised ValueError

        A connector registered outside DataGerry's mapping has no `<database>_` prefix to strip, and
        one such connector must not cost the whole log view.
        """
        flowcharts = [_flowchart('MySQL')]

        unmap_flowchart_connector_names(flowcharts)

        assert flowcharts[0][CONNECTOR_NAME_KEY] == 'MySQL'

    def test_only_the_first_underscore_is_split_on(self) -> None:
        """A connector name may itself contain underscores; only the prefix goes"""
        flowcharts = [_flowchart('db_customer_My_SQL_8')]

        unmap_flowchart_connector_names(flowcharts)

        assert flowcharts[0][CONNECTOR_NAME_KEY] == 'customer_My_SQL_8'

    def test_a_bad_entry_does_not_hide_the_good_ones(self) -> None:
        """The point of tolerating rather than raising"""
        flowcharts = [{'label': 'no name'}, _flowchart()]

        unmap_flowchart_connector_names(flowcharts)

        assert flowcharts[1][CONNECTOR_NAME_KEY] == 'customer_MySQL'

    @pytest.mark.parametrize('payload', [None, 'a flowchart', 42])
    def test_an_unexpected_payload_is_passed_through(self, payload: Any, caplog: pytest.LogCaptureFixture) -> None:
        """A log view that cannot render is worse than one showing a prefixed name - so it reports"""
        with caplog.at_level('WARNING'):
            assert unmap_flowchart_connector_names(payload) is payload

        assert 'left unchanged' in caplog.text

    def test_an_empty_list_is_answered_as_is(self) -> None:
        """An execution with no flowcharts is not an error"""
        assert not unmap_flowchart_connector_names([])

    @pytest.mark.parametrize('entry', [None, 'a flowchart', 42, ['nested']])
    def test_a_non_dict_entry_of_a_list_is_skipped(self, entry: Any) -> None:
        """OpenCelium answers a list; what is inside it is not guaranteed to be objects"""
        flowcharts = [entry, _flowchart()]

        unmap_flowchart_connector_names(flowcharts)

        assert flowcharts[0] == entry
        assert flowcharts[1][CONNECTOR_NAME_KEY] == 'customer_MySQL'

    def test_a_non_dict_value_of_a_mapping_is_skipped(self) -> None:
        """A keyed payload may carry metadata beside its flowcharts"""
        flowcharts = {'count': 2, 'first': _flowchart()}

        unmap_flowchart_connector_names(flowcharts)

        assert flowcharts['count'] == 2
        assert flowcharts['first'][CONNECTOR_NAME_KEY] == 'customer_MySQL'


# -------------------------------------------------------------------------------------------------------------------- #
#                                            the required query parameters                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRequiredIntParam:
    """The ids the log-list route forwards to OpenCelium."""

    def test_a_value_is_answered(self) -> None:
        """The parsed integer is what the manager is called with"""
        with _app().test_request_context('/?connectionId=12'):
            assert required_int_param_or_abort(OcLogQueryParam.CONNECTION_ID) == 12

    def test_zero_is_a_value(self) -> None:
        """
        0 counts as provided

        The guard read the parsed value for truthiness, so `?connectionId=0` was reported as "not
        provided" - a message that sends the caller looking for the wrong mistake. Whether the id
        exists is OpenCelium's to answer.
        """
        with _app().test_request_context('/?connectionId=0'):
            assert required_int_param_or_abort(OcLogQueryParam.CONNECTION_ID) == 0

    def test_a_negative_value_is_a_value_too(self) -> None:
        """Same reasoning: this proxy does not invent id rules OpenCelium does not have"""
        with _app().test_request_context('/?connectionId=-3'):
            assert required_int_param_or_abort(OcLogQueryParam.CONNECTION_ID) == -3

    def test_an_absent_parameter_aborts_400(self) -> None:
        """The caller sent no id at all"""
        with _app().test_request_context('/'):
            with pytest.raises(HTTPException) as exc_info:
                required_int_param_or_abort(OcLogQueryParam.CONNECTION_ID)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST
        assert 'was not provided' in str(exc_info.value.description)

    @pytest.mark.parametrize('query', ['/?connectionId=', '/?connectionId=abc', '/?connectionId=1.5'])
    def test_an_unusable_value_aborts_400_with_its_own_message(self, query: str) -> None:
        """It WAS provided, so the message says what is wrong with it instead"""
        with _app().test_request_context(query):
            with pytest.raises(HTTPException) as exc_info:
                required_int_param_or_abort(OcLogQueryParam.CONNECTION_ID)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST
        assert 'whole number' in str(exc_info.value.description)


class TestRequiredStrParam:
    """The status filter and the loop index."""

    def test_a_value_is_answered(self) -> None:
        """Forwarded to OpenCelium unchanged"""
        with _app().test_request_context('/?status=SUCCESS'):
            assert required_str_param_or_abort(OcLogQueryParam.STATUS) == 'SUCCESS'

    def test_an_absent_parameter_aborts_400(self) -> None:
        """Nothing was sent"""
        with _app().test_request_context('/'):
            with pytest.raises(HTTPException) as exc_info:
                required_str_param_or_abort(OcLogQueryParam.STATUS)

        assert 'was not provided' in str(exc_info.value.description)

    def test_an_empty_value_aborts_400_with_its_own_message(self) -> None:
        """`?status=` was sent - reporting it as absent would be wrong"""
        with _app().test_request_context('/?status='):
            with pytest.raises(HTTPException) as exc_info:
                required_str_param_or_abort(OcLogQueryParam.STATUS)

        assert 'was empty' in str(exc_info.value.description)

    def test_the_loop_index_uses_the_same_rule(self) -> None:
        """An operator that loops has one set of children per iteration"""
        with _app().test_request_context('/?loopIndex=0'):
            assert required_str_param_or_abort(OcLogQueryParam.LOOP_INDEX) == '0'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the manager factory                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildConnectionLogManager:
    """The construction the six routes used to repeat."""

    def test_it_scopes_the_manager_to_the_users_database(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        The caller's database selects the OpenCelium installation to talk to

        In cloud mode each tenant has its own credentials; the wrong database would read another
        installation's logs.
        """
        recorded: dict[str, Any] = {}

        class _RecordingManager:
            """Captures how the factory constructs the manager."""

            def __init__(self, dbm: Any, database: str) -> None:
                """Records both arguments."""
                recorded['dbm'] = dbm
                recorded['database'] = database

        monkeypatch.setattr(
            'cmdb.interface.rest_api.routes.open_celium_routes.oc_connection_log_helper.OcConnectionLogManager',
            _RecordingManager,
        )

        request_user = type('_User', (), {'database': TENANT_DATABASE})()

        with _app().test_request_context():
            manager = build_connection_log_manager(request_user)

        assert isinstance(manager, _RecordingManager)
        assert recorded == {'dbm': 'the-dbm', 'database': TENANT_DATABASE}
