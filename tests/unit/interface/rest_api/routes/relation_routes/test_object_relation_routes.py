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
Unit tests for cmdb.interface.rest_api.routes.relation_routes.object_relation_routes

Covers the two request-shaping helpers of the relation-tab instances route without booting the REST
API: the pagination-parameter validation (inside a minimal Flask request context) and the row
projection (with the counterpart resolution patched at the module path). The mounted blueprint URLs are
asserted too, so the frontend-facing route set cannot change unnoticed.
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.models.object_relation_model import ObjectRelationKey, ObjectRelationRole
from cmdb.interface.rest_api.routes.relation_routes.relation_constants import (
    DEFAULT_TAB_PAGE_SIZE,
    MAX_TAB_PAGE_SIZE,
    TabInstancesKey,
)
from cmdb.interface.rest_api.routes.relation_routes.object_relation_routes import (
    object_relations_blueprint,
    _parse_tab_page_params,
    _build_tab_instance_rows,
)
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.interface.rest_api.routes.relation_routes.object_relation_routes'
URL_PREFIX: str = '/object_relations'

EXPECTED_RULES: set[str] = {
    '/object_relations/',
    '/object_relations/<int:public_id>',
    '/object_relations/delete/many',
    '/object_relations/tabs/<int:object_id>',
    '/object_relations/tabs/<int:object_id>/instances',
}

PARENT_OBJECT_ID: int = 600
CHILD_OBJECT_ID: int = 700
OTHER_CHILD_OBJECT_ID: int = 701
RELATION_ID: int = 42

app = Flask(__name__)


def _instance(public_id: int, child_id: int) -> dict[str, Any]:
    """Builds the stored CmdbObjectRelation shape the row projection reads."""
    return {
        ObjectRelationKey.PUBLIC_ID.value: public_id,
        ObjectRelationKey.RELATION_ID.value: RELATION_ID,
        ObjectRelationKey.RELATION_PARENT_ID.value: PARENT_OBJECT_ID,
        ObjectRelationKey.RELATION_CHILD_ID.value: child_id,
        ObjectRelationKey.FIELD_VALUES.value: [{'name': 'a', 'value': 'b'}],
    }


class TestBlueprintUrls:
    """Mounting the blueprint reproduces the frontend-facing URL set exactly."""

    def test_registers_the_expected_rules(self) -> None:
        """The blueprint exposes the CRUD, bulk-delete and relation-tab URLs and nothing else."""
        local_app = Flask(__name__)
        local_app.register_blueprint(object_relations_blueprint, url_prefix=URL_PREFIX)

        rules = {str(rule) for rule in local_app.url_map.iter_rules() if str(rule).startswith(URL_PREFIX)}

        assert rules == EXPECTED_RULES


class TestParseTabPageParams:
    """_parse_tab_page_params defaults, converts and refuses out-of-range pagination."""

    def test_defaults_when_nothing_is_given(self) -> None:
        """Without parameters the route serves the first default-sized page, sorted by public_id."""
        with app.test_request_context('/'):
            assert _parse_tab_page_params() == (DEFAULT_TAB_PAGE_SIZE, 0, ObjectRelationKey.PUBLIC_ID.value, 1)

    def test_skip_follows_the_page(self) -> None:
        """The skip is derived from page and limit, so page 3 of 5 skips 10."""
        with app.test_request_context('/?page=3&limit=5'):
            assert _parse_tab_page_params()[:2] == (5, 10)

    def test_reads_sort_and_order(self) -> None:
        """An explicit sort field and descending direction are passed through."""
        with app.test_request_context('/?sort=relation_id&order=-1'):
            assert _parse_tab_page_params()[2:] == ('relation_id', -1)

    def test_blank_sort_falls_back_to_public_id(self) -> None:
        """An empty sort parameter must not reach Mongo as an empty field name."""
        with app.test_request_context('/?sort='):
            assert _parse_tab_page_params()[2] == ObjectRelationKey.PUBLIC_ID.value

    @pytest.mark.parametrize('query', ['limit=0', 'limit=-1', f'limit={MAX_TAB_PAGE_SIZE + 1}'],
                             ids=['zero', 'negative', 'above-max'])
    def test_rejects_an_out_of_range_limit(self, query: str) -> None:
        """limit=0 used to mean 'no limit' and could dump a whole tab in one response (regression)."""
        with app.test_request_context(f'/?{query}'):
            with pytest.raises(HTTPException) as exc_info:
                _parse_tab_page_params()

            assert exc_info.value.code == 400

    def test_accepts_the_maximum_limit(self) -> None:
        """The documented upper bound itself is still a valid page size."""
        with app.test_request_context(f'/?limit={MAX_TAB_PAGE_SIZE}'):
            assert _parse_tab_page_params()[0] == MAX_TAB_PAGE_SIZE

    @pytest.mark.parametrize('page', ['0', '-2'], ids=['zero', 'negative'])
    def test_rejects_a_page_below_one(self, page: str) -> None:
        """Pages are 1-based; anything below that is a caller error, not a silent first page."""
        with app.test_request_context(f'/?page={page}'):
            with pytest.raises(HTTPException) as exc_info:
                _parse_tab_page_params()

            assert exc_info.value.code == 400

    @pytest.mark.parametrize('order', ['5', '0', '2'], ids=['unknown', 'zero', 'two'])
    def test_rejects_an_unknown_sort_direction(self, order: str) -> None:
        """Only MongoDB's own 1 / -1 encoding is accepted, instead of failing inside the query."""
        with app.test_request_context(f'/?order={order}'):
            with pytest.raises(HTTPException) as exc_info:
                _parse_tab_page_params()

            assert exc_info.value.code == 400

    @pytest.mark.parametrize(
        'query',
        ['order=desc', 'order=asc', 'limit=ten', 'page=first'],
        ids=['order-word-desc', 'order-word-asc', 'limit-word', 'page-word'],
    )
    def test_rejects_a_non_numeric_value(self, query: str) -> None:
        """A non-numeric value is reported: '?order=desc' silently sorting ascending is a wrong result."""
        with app.test_request_context(f'/?{query}'):
            with pytest.raises(HTTPException) as exc_info:
                _parse_tab_page_params()

            assert exc_info.value.code == 400

    @pytest.mark.parametrize('query', ['limit=', 'page=', 'order='], ids=['limit', 'page', 'order'])
    def test_an_empty_value_uses_the_default(self, query: str) -> None:
        """An empty parameter means 'not given', matching how a blank sort falls back."""
        with app.test_request_context(f'/?{query}'):
            assert _parse_tab_page_params() == (DEFAULT_TAB_PAGE_SIZE, 0, ObjectRelationKey.PUBLIC_ID.value, 1)


class TestBuildTabInstanceRows:
    """_build_tab_instance_rows projects a page and attaches the resolved counterpart."""

    def test_resolves_the_opposite_side_for_a_parent_tab(self) -> None:
        """On a parent tab the counterpart is the child object of every instance."""
        objects_manager = MagicMock()
        request_user = MagicMock()
        summaries = {CHILD_OBJECT_ID: {'object_id': CHILD_OBJECT_ID}}

        with patch(f'{MODULE_PATH}.resolve_counterpart_summaries', return_value=summaries) as resolve:
            rows = _build_tab_instance_rows(
                [_instance(1, CHILD_OBJECT_ID)], ObjectRelationRole.PARENT.value, request_user, objects_manager,
            )

        assert resolve.call_args.args[0] == [CHILD_OBJECT_ID]
        assert rows == [{
            ObjectRelationKey.PUBLIC_ID.value: 1,
            ObjectRelationKey.RELATION_ID.value: RELATION_ID,
            ObjectRelationKey.FIELD_VALUES.value: [{'name': 'a', 'value': 'b'}],
            TabInstancesKey.COUNTERPART.value: {'object_id': CHILD_OBJECT_ID},
        }]

    def test_resolves_the_opposite_side_for_a_child_tab(self) -> None:
        """On a child tab the counterpart is the parent object instead."""
        with patch(f'{MODULE_PATH}.resolve_counterpart_summaries', return_value={}) as resolve:
            _build_tab_instance_rows(
                [_instance(1, CHILD_OBJECT_ID)], ObjectRelationRole.CHILD.value, MagicMock(), MagicMock(),
            )

        assert resolve.call_args.args[0] == [PARENT_OBJECT_ID]

    def test_unresolved_counterpart_becomes_none(self) -> None:
        """A missing / inactive / ACL-hidden counterpart leaves the row's counterpart null."""
        with patch(f'{MODULE_PATH}.resolve_counterpart_summaries', return_value={}):
            rows = _build_tab_instance_rows(
                [_instance(1, CHILD_OBJECT_ID)], ObjectRelationRole.PARENT.value, MagicMock(), MagicMock(),
            )

        assert rows[0][TabInstancesKey.COUNTERPART.value] is None

    def test_missing_field_values_default_to_an_empty_list(self) -> None:
        """A document written before field_values existed still yields a usable row."""
        instance = _instance(1, CHILD_OBJECT_ID)
        del instance[ObjectRelationKey.FIELD_VALUES.value]

        with patch(f'{MODULE_PATH}.resolve_counterpart_summaries', return_value={}):
            rows = _build_tab_instance_rows(
                [instance], ObjectRelationRole.PARENT.value, MagicMock(), MagicMock(),
            )

        assert rows[0][ObjectRelationKey.FIELD_VALUES.value] == []

    def test_keeps_the_instance_order_and_resolves_once(self) -> None:
        """The rows follow the page order and all counterparts are resolved in a single call."""
        instances = [_instance(1, CHILD_OBJECT_ID), _instance(2, OTHER_CHILD_OBJECT_ID)]

        with patch(f'{MODULE_PATH}.resolve_counterpart_summaries', return_value={}) as resolve:
            rows = _build_tab_instance_rows(
                instances, ObjectRelationRole.PARENT.value, MagicMock(), MagicMock(),
            )

        resolve.assert_called_once()
        assert [row[ObjectRelationKey.PUBLIC_ID.value] for row in rows] == [1, 2]

    def test_an_empty_page_yields_no_rows(self) -> None:
        """An empty page still returns an (empty) list, so the response shape is stable."""
        with patch(f'{MODULE_PATH}.resolve_counterpart_summaries', return_value={}):
            assert _build_tab_instance_rows([], ObjectRelationRole.PARENT.value, MagicMock(), MagicMock()) == []
