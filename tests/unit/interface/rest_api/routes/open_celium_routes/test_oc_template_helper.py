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
Unit tests for the OpenCelium template route helpers

The two decisions the detailed template route used to make inline, now testable without driving a
route:

* **which invoker marks a template as DataGerry's own.** A hosted cloud installation is registered
  in OpenCelium under `DataGerryCloud`, an on-premise one under `DataGerry` - and the wrong choice
  does not fail, it answers an EMPTY template list. The route's own test module ran on-premise only,
  so this branch had never been executed.
* **the filter itself**, over payloads that come from another product: any level of
  `connection` -> `fromConnector`/`toConnector` -> `invoker` -> `name` can be absent **or explicitly
  null**, and the old `.get(key, {})` chain raised `AttributeError` on the null case - a 500 for the
  whole list because one template was malformed.

`filter_datagerry_templates` also absorbs the manager's `None` (OpenCelium answered an empty body),
which one of the two list routes used to hand to the frontend as `null`.
"""
from typing import Any

import pytest

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.rest_api.routes.open_celium_routes.oc_routes_constants import OcResponseKey
from cmdb.interface.rest_api.routes.open_celium_routes.oc_template_helper import (
    build_template_manager,
    datagerry_invoker_name,
    filter_datagerry_templates,
)

from cmdb.open_celium.oc_constants import OC_DATAGERRY_CLOUD_INVOKER_NAME, OC_DATAGERRY_INVOKER_NAME
# -------------------------------------------------------------------------------------------------------------------- #

OTHER_INVOKER: str = 'SomeOtherProduct'
USER_DATABASE: str = 'db_test'


def _app(*, cloud_mode: bool = False, local_mode: bool = False) -> BaseCmdbApp:
    """A BaseCmdbApp flagged for the given mode."""
    app = BaseCmdbApp(__name__)
    app.cloud_mode = cloud_mode
    app.local_mode = local_mode

    return app


def _template(*, from_invoker: Any = None, to_invoker: Any = None) -> dict[str, Any]:
    """A business template naming the given invokers on its two connector sides."""
    return {
        OcResponseKey.CONNECTION.value: {
            OcResponseKey.FROM_CONNECTOR.value: {
                OcResponseKey.INVOKER.value: {OcResponseKey.NAME.value: from_invoker},
            },
            OcResponseKey.TO_CONNECTOR.value: {
                OcResponseKey.INVOKER.value: {OcResponseKey.NAME.value: to_invoker},
            },
        },
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                              the invoker name decision                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDatagerryInvokerName:
    """Which invoker a template must name to count as DataGerry's own."""

    def test_on_premise_uses_the_plain_name(self) -> None:
        """The default installation is registered in OpenCelium as 'DataGerry'"""
        with _app().test_request_context():
            assert datagerry_invoker_name() == OC_DATAGERRY_INVOKER_NAME

    def test_hosted_cloud_uses_the_cloud_name(self) -> None:
        """
        The branch that had never been executed

        A cloud installation is a different invoker over there; matching the on-premise name would
        answer an empty list to every cloud tenant, and an empty list is not an error.
        """
        with _app(cloud_mode=True).test_request_context():
            assert datagerry_invoker_name() == OC_DATAGERRY_CLOUD_INVOKER_NAME

    def test_local_development_in_cloud_mode_uses_the_plain_name(self) -> None:
        """`--cloud --local` is a developer's local stack, not a hosted tenant"""
        with _app(cloud_mode=True, local_mode=True).test_request_context():
            assert datagerry_invoker_name() == OC_DATAGERRY_INVOKER_NAME

    def test_the_two_names_are_distinct(self) -> None:
        """If they ever collapse into one value the whole branch is pointless"""
        assert OC_DATAGERRY_INVOKER_NAME != OC_DATAGERRY_CLOUD_INVOKER_NAME


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    the filter                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestFilterDatagerryTemplates:
    """Keeping the templates that name the invoker on either side."""

    def test_a_matching_from_connector_is_kept(self) -> None:
        """The Automations view offers these as starting points for a new connection"""
        template = _template(from_invoker=OC_DATAGERRY_INVOKER_NAME, to_invoker=OTHER_INVOKER)

        assert filter_datagerry_templates([template], OC_DATAGERRY_INVOKER_NAME) == [template]

    def test_a_matching_to_connector_is_kept(self) -> None:
        """Either side counts - the template describes a connection in one direction"""
        template = _template(from_invoker=OTHER_INVOKER, to_invoker=OC_DATAGERRY_INVOKER_NAME)

        assert filter_datagerry_templates([template], OC_DATAGERRY_INVOKER_NAME) == [template]

    def test_a_foreign_template_is_dropped(self) -> None:
        """A template between two other products is useless in DataGerry's Automations view"""
        template = _template(from_invoker=OTHER_INVOKER, to_invoker=OTHER_INVOKER)

        assert filter_datagerry_templates([template], OC_DATAGERRY_INVOKER_NAME) == []

    def test_the_cloud_name_matches_only_cloud_templates(self) -> None:
        """The other half of the invoker decision, from the filter's side"""
        on_premise = _template(from_invoker=OC_DATAGERRY_INVOKER_NAME)
        hosted = _template(from_invoker=OC_DATAGERRY_CLOUD_INVOKER_NAME)

        assert filter_datagerry_templates(
            [on_premise, hosted], OC_DATAGERRY_CLOUD_INVOKER_NAME
        ) == [hosted]

    def test_the_order_open_celium_listed_is_kept(self) -> None:
        """The view shows them in the order they arrive; a filter must not reorder"""
        first = _template(from_invoker=OC_DATAGERRY_INVOKER_NAME)
        second = _template(to_invoker=OC_DATAGERRY_INVOKER_NAME)

        assert filter_datagerry_templates([first, second], OC_DATAGERRY_INVOKER_NAME) == [first, second]

    def test_none_is_an_empty_list(self) -> None:
        """
        The manager reports 'OpenCelium answered an empty body' as None

        One of the two list routes used to hand that null straight to the frontend while the other
        answered [].
        """
        assert filter_datagerry_templates(None, OC_DATAGERRY_INVOKER_NAME) == []

    def test_an_empty_list_stays_empty(self) -> None:
        """No templates configured is not an error"""
        assert filter_datagerry_templates([], OC_DATAGERRY_INVOKER_NAME) == []

    @pytest.mark.parametrize('template', [
        {},
        {OcResponseKey.CONNECTION.value: None},
        {OcResponseKey.CONNECTION.value: {}},
        {OcResponseKey.CONNECTION.value: {OcResponseKey.FROM_CONNECTOR.value: None}},
        {OcResponseKey.CONNECTION.value: {OcResponseKey.FROM_CONNECTOR.value: {
            OcResponseKey.INVOKER.value: None,
        }}},
        {OcResponseKey.CONNECTION.value: {OcResponseKey.FROM_CONNECTOR.value: {
            OcResponseKey.INVOKER.value: 'DataGerry',
        }}},
        {OcResponseKey.CONNECTION.value: 'not-a-mapping'},
    ])
    def test_a_malformed_template_is_dropped_not_fatal(self, template: dict[str, Any]) -> None:
        """
        A null level used to raise AttributeError, i.e. a 500 for the whole list

        The payload is another product's; every level of it is treated as optional.
        """
        assert filter_datagerry_templates([template], OC_DATAGERRY_INVOKER_NAME) == []

    def test_a_malformed_template_does_not_hide_the_good_ones(self) -> None:
        """The point of dropping rather than failing"""
        good = _template(from_invoker=OC_DATAGERRY_INVOKER_NAME)

        assert filter_datagerry_templates(
            [{OcResponseKey.CONNECTION.value: None}, good], OC_DATAGERRY_INVOKER_NAME
        ) == [good]

    @pytest.mark.parametrize('entry', [None, 'a template', 42, ['nested']])
    def test_a_non_dict_entry_is_dropped(self, entry: Any) -> None:
        """OpenCelium answers a list; what is in it is not guaranteed to be objects"""
        assert filter_datagerry_templates([entry], OC_DATAGERRY_INVOKER_NAME) == []

    def test_a_null_invoker_name_never_matches(self) -> None:
        """A template whose invoker has no name matches nothing, not even an empty invoker name"""
        assert filter_datagerry_templates([_template()], OC_DATAGERRY_INVOKER_NAME) == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the manager factory                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildTemplateManager:
    """The construction the four routes used to repeat."""

    def test_it_scopes_the_manager_to_the_users_database(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        The caller's database is what makes the manager read the right OpenCelium credentials

        In cloud mode each tenant has its own; passing the wrong one would talk to another
        installation's OpenCelium.
        """
        recorded: dict[str, Any] = {}

        class _RecordingManager:
            """Captures how the factory constructs the manager."""

            def __init__(self, dbm: Any, database: str) -> None:
                """Records both arguments."""
                recorded['dbm'] = dbm
                recorded['database'] = database

        monkeypatch.setattr(
            'cmdb.interface.rest_api.routes.open_celium_routes.oc_template_helper.OcTemplateManager',
            _RecordingManager,
        )

        app = _app()
        app.database_manager = 'the-dbm'
        request_user = type('_User', (), {'database': USER_DATABASE})()

        with app.test_request_context():
            manager = build_template_manager(request_user)

        assert isinstance(manager, _RecordingManager)
        assert recorded == {'dbm': 'the-dbm', 'database': USER_DATABASE}
