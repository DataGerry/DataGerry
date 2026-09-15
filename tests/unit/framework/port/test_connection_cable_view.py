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
Unit tests for cmdb.framework.port.connection_cable_view

The read half of "a cable is described once": a connection carries the five cable_* values itself or
names a Cable CI that owns them, and both have to arrive at a client as ONE block. What is pinned
here is the shape of that block, that the two batched reads really are batched, and that a reference
which no longer resolves is reported rather than repaired.

The two managers are MagicMocks - the queries they receive are asserted, not executed; the same rules
run against a real MongoDB in tests/integration/framework/test_integration_port_connections.py
"""
from typing import Any

from unittest.mock import MagicMock

from cmdb.framework.port.connection_cable_view import (
    attach_cable_view,
    attach_cable_views,
    build_cable_view,
    coerce_cable_text,
    collect_cable_ci_ids,
    collect_cable_type_ids,
    load_cable_cis,
    load_cable_type_labels,
)
from cmdb.models.extendable_option_model import ExtendableOptionKey, OptionType
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.port_connection_model import (
    CableSource,
    CableViewKey,
    ConnectionType,
    PortConnectionKey,
    CABLE_FIELD_KEYS,
    CABLE_VIEW_KEY,
)
from cmdb.models.special_type_model.cable_constants import CableField
# -------------------------------------------------------------------------------------------------------------------- #

CONNECTION_ID: int = 1
CABLE_CI_ID: int = 9950
OTHER_CABLE_CI_ID: int = 9951
CABLE_TYPE_ID: int = 7


def _cable_ci(public_id: int = CABLE_CI_ID, **field_values: Any) -> dict[str, Any]:
    """Builds a CABLE CmdbObject document carrying the given dg-cable-* values."""
    return {
        CmdbObjectKey.PUBLIC_ID.value: public_id,
        CmdbObjectKey.FIELDS.value: [
            {CmdbObjectFieldKey.NAME.value: name, CmdbObjectFieldKey.VALUE.value: value}
            for name, value in field_values.items()
        ],
    }


def _connection(**overrides: Any) -> dict[str, Any]:
    """Builds a stored CABLE connection document, cable keys included."""
    connection: dict[str, Any] = {
        PortConnectionKey.PUBLIC_ID.value: CONNECTION_ID,
        PortConnectionKey.ENDPOINTS.value: [1, 2],
        PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.CABLE.value,
        PortConnectionKey.CABLE_NAME.value: None,
        PortConnectionKey.CABLE_TYPE.value: None,
        PortConnectionKey.CABLE_LENGTH.value: None,
        PortConnectionKey.CABLE_COLOR.value: None,
        PortConnectionKey.CABLE_DESCRIPTION.value: None,
        PortConnectionKey.AUTHOR_ID.value: 1,
    }
    connection.update(overrides)

    return connection


def _objects_manager(found: list[dict[str, Any]]) -> MagicMock:
    """An ObjectsManager stub whose find_objects() answers with the given documents."""
    manager = MagicMock(name='objects_manager')
    manager.find_objects = MagicMock(return_value=found)

    return manager


def _options_manager(found: list[dict[str, Any]]) -> MagicMock:
    """An ExtendableOptionsManager stub whose find() answers with the given option documents."""
    manager = MagicMock(name='extendable_options_manager')
    manager.find = MagicMock(return_value=found)

    return manager


def _option(public_id: int = CABLE_TYPE_ID, value: str = 'CAT6') -> dict[str, Any]:
    """Builds a CmdbExtendableOption document of the CABLE_TYPE list."""
    return {
        ExtendableOptionKey.PUBLIC_ID.value: public_id,
        ExtendableOptionKey.VALUE.value: value,
        ExtendableOptionKey.OPTION_TYPE.value: OptionType.CABLE_TYPE.value,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  coerce_cable_text                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCoerceCableText:
    """Every value in the block is text, whatever the CI happens to store."""

    def test_a_string_is_returned_unchanged(self) -> None:
        """The ordinary case"""
        assert coerce_cable_text('CAT6') == 'CAT6'

    def test_none_stays_none(self) -> None:
        """An unfilled field has no value to report"""
        assert coerce_cable_text(None) is None

    def test_an_empty_string_reads_as_no_value(self) -> None:
        """'' and 'not filled in' are the same thing to a reader, and one of them renders as a gap"""
        assert coerce_cable_text('') is None

    def test_a_number_is_rendered(self) -> None:
        """
        The reason this function exists

        A CSV import can leave 5 where a text field was meant to hold '5 m', and the read of a link
        must not fail over a value someone typed years ago.
        """
        assert coerce_cable_text(5) == '5'
        assert coerce_cable_text(2.5) == '2.5'

    def test_a_list_or_dict_is_dropped(self) -> None:
        """There is no one-line rendering of either, and passing one through would surprise a client"""
        assert coerce_cable_text(['a']) is None
        assert coerce_cable_text({'a': 1}) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 batched collection                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCollectIds:
    """What the two batched reads are asked for."""

    def test_cable_ci_ids_are_collected_once_each(self) -> None:
        """Two connections naming the same CI are one read, not two"""
        ids = collect_cable_ci_ids([
            _connection(**{PortConnectionKey.CABLE_CI_ID.value: CABLE_CI_ID}),
            _connection(**{PortConnectionKey.CABLE_CI_ID.value: CABLE_CI_ID}),
            _connection(**{PortConnectionKey.CABLE_CI_ID.value: OTHER_CABLE_CI_ID}),
        ])

        assert sorted(ids) == [CABLE_CI_ID, OTHER_CABLE_CI_ID]

    def test_a_connection_without_a_cable_ci_contributes_nothing(self) -> None:
        """The key is absent, not null, on a connection that names no CI"""
        assert collect_cable_ci_ids([_connection()]) == []

    def test_cable_type_ids_come_from_inline_connections_only(self) -> None:
        """
        A CI-linked connection's type is a label on the CI

        Resolving an option id it does not carry would be a read for nothing - and the stored
        cable_type of such a connection is refused on write in the first place.
        """
        ids = collect_cable_type_ids([
            _connection(**{PortConnectionKey.CABLE_TYPE.value: CABLE_TYPE_ID}),
            _connection(**{
                PortConnectionKey.CABLE_CI_ID.value: CABLE_CI_ID,
                PortConnectionKey.CABLE_TYPE.value: 99,
            }),
        ])

        assert ids == [CABLE_TYPE_ID]


class TestBatchedLoads:
    """One query each, whatever the length of the page."""

    def test_the_cable_cis_are_read_with_a_single_in_query(self) -> None:
        """A 48-port switch costs one read here, not forty-eight"""
        manager = _objects_manager([_cable_ci()])

        result = load_cable_cis(manager, [CABLE_CI_ID, OTHER_CABLE_CI_ID])

        manager.find_objects.assert_called_once_with(
            criteria={CmdbObjectKey.PUBLIC_ID.value: {'$in': [CABLE_CI_ID, OTHER_CABLE_CI_ID]}},
            as_dict=True,
        )
        assert result == {CABLE_CI_ID: _cable_ci()}

    def test_no_cable_ci_means_no_query(self) -> None:
        """A page of connections that inventory nothing pays for nothing"""
        manager = _objects_manager([])

        assert load_cable_cis(manager, []) == {}
        manager.find_objects.assert_not_called()

    def test_the_labels_are_read_scoped_to_the_cable_type_list(self) -> None:
        """An id belonging to another option list is a stale reference, not a label to show"""
        manager = _options_manager([_option()])

        result = load_cable_type_labels(manager, [CABLE_TYPE_ID])

        manager.find.assert_called_once_with(criteria={
            ExtendableOptionKey.PUBLIC_ID.value: {'$in': [CABLE_TYPE_ID]},
            ExtendableOptionKey.OPTION_TYPE.value: OptionType.CABLE_TYPE.value,
        })
        assert result == {CABLE_TYPE_ID: 'CAT6'}

    def test_no_cable_type_means_no_query(self) -> None:
        """Same as the CIs: nothing referenced, nothing read"""
        manager = _options_manager([])

        assert load_cable_type_labels(manager, []) == {}
        manager.find.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  build_cable_view                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildCableView:
    """The block itself, in both storage modes."""

    def test_an_internal_connection_has_no_cable_at_all(self) -> None:
        """
        None rather than a block of nulls

        A patch panel's front-to-rear pairing is a fact about the panel, not a piece of cabling, and
        saying so once is clearer than five empty values a client has to interpret.
        """
        internal = _connection(**{PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.INTERNAL.value})

        assert build_cable_view(internal, {}, {}) is None

    def test_an_inline_cable_reports_both_the_label_and_the_option_id(self) -> None:
        """The stored value is an id; a client should not have to resolve it to render a row"""
        view = build_cable_view(
            _connection(**{
                PortConnectionKey.CABLE_NAME.value: 'Patch A-12',
                PortConnectionKey.CABLE_TYPE.value: CABLE_TYPE_ID,
                PortConnectionKey.CABLE_LENGTH.value: '1.5 m',
                PortConnectionKey.CABLE_COLOR.value: 'grey',
            }),
            {},
            {CABLE_TYPE_ID: 'CAT5e'},
        )

        assert view[CableViewKey.SOURCE.value] == CableSource.INLINE.value
        assert view[CableViewKey.CABLE_CI_ID.value] is None
        assert view[CableViewKey.NAME.value] == 'Patch A-12'
        assert view[CableViewKey.TYPE.value] == 'CAT5e'
        assert view[CableViewKey.TYPE_ID.value] == CABLE_TYPE_ID
        assert view[CableViewKey.LENGTH.value] == '1.5 m'
        assert view[CableViewKey.COLOR.value] == 'grey'
        assert view[CableViewKey.DESCRIPTION.value] is None

    def test_an_inline_cable_type_whose_option_was_deleted_keeps_the_id(self) -> None:
        """The same treatment a dangling cable CI gets: report what is stored, resolve what resolves"""
        view = build_cable_view(
            _connection(**{PortConnectionKey.CABLE_TYPE.value: CABLE_TYPE_ID}), {}, {},
        )

        assert view[CableViewKey.TYPE.value] is None
        assert view[CableViewKey.TYPE_ID.value] == CABLE_TYPE_ID

    def test_a_linked_cable_ci_answers_with_the_cis_own_values(self) -> None:
        """The point of linking a CI: the asset owns the values and the link shows them"""
        cable_ci = _cable_ci(**{
            CableField.NAME.value: 'CAB-000471',
            CableField.TYPE.value: 'CAT6',
            CableField.LENGTH.value: '3 m',
            CableField.COLOR.value: 'blue',
            CableField.DESCRIPTION.value: 'Rack 12 -> Rack 14',
        })

        view = build_cable_view(
            _connection(**{PortConnectionKey.CABLE_CI_ID.value: CABLE_CI_ID}),
            {CABLE_CI_ID: cable_ci},
            {},
        )

        assert view[CableViewKey.SOURCE.value] == CableSource.CI.value
        assert view[CableViewKey.CABLE_CI_ID.value] == CABLE_CI_ID
        assert view[CableViewKey.NAME.value] == 'CAB-000471'
        assert view[CableViewKey.TYPE.value] == 'CAT6'
        assert view[CableViewKey.LENGTH.value] == '3 m'
        assert view[CableViewKey.COLOR.value] == 'blue'
        assert view[CableViewKey.DESCRIPTION.value] == 'Rack 12 -> Rack 14'
        assert CableViewKey.RESOLVED.value not in view

    def test_a_linked_cable_ci_reports_no_option_id(self) -> None:
        """
        Not a gap: a CmdbType select stores its option's LABEL and knows no CmdbExtendableOption id

        Guessing one back would map across two lists that are allowed to drift apart (backlog #196).
        """
        view = build_cable_view(
            _connection(**{PortConnectionKey.CABLE_CI_ID.value: CABLE_CI_ID}),
            {CABLE_CI_ID: _cable_ci(**{CableField.TYPE.value: 'CAT6'})},
            {},
        )

        assert view[CableViewKey.TYPE.value] == 'CAT6'
        assert view[CableViewKey.TYPE_ID.value] is None

    def test_a_deleted_cable_ci_is_reported_and_the_link_survives(self) -> None:
        """
        The soft reference of step 10: reported, never cascaded

        Deleting an inventoried cable does not delete the link - the two ports are still patched
        together - so the block keeps the id, says it did not resolve, and holds no values.
        """
        view = build_cable_view(
            _connection(**{PortConnectionKey.CABLE_CI_ID.value: CABLE_CI_ID}), {}, {},
        )

        assert view[CableViewKey.SOURCE.value] == CableSource.CI.value
        assert view[CableViewKey.CABLE_CI_ID.value] == CABLE_CI_ID
        assert view[CableViewKey.RESOLVED.value] is False
        assert view[CableViewKey.NAME.value] is None

    def test_a_ci_value_that_is_not_text_is_rendered_as_text(self) -> None:
        """A number left in a text field by an import reads as a value, not as a failure"""
        view = build_cable_view(
            _connection(**{PortConnectionKey.CABLE_CI_ID.value: CABLE_CI_ID}),
            {CABLE_CI_ID: _cable_ci(**{CableField.LENGTH.value: 5})},
            {},
        )

        assert view[CableViewKey.LENGTH.value] == '5'

    def test_both_modes_key_the_block_in_the_same_order(self) -> None:
        """A response whose fields move between two rows of one list reads like two shapes"""
        inline = build_cable_view(_connection(), {}, {})
        from_ci = build_cable_view(
            _connection(**{PortConnectionKey.CABLE_CI_ID.value: CABLE_CI_ID}),
            {CABLE_CI_ID: _cable_ci()},
            {},
        )

        assert list(inline.keys()) == list(from_ci.keys())


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 attach_cable_views                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestAttachCableViews:
    """What the routes actually hand back."""

    def test_the_flat_cable_keys_are_replaced_by_the_block(self) -> None:
        """
        Removed, not kept beside it

        Returning a value twice, once raw and once resolved, leaves a client free to read the one
        that is null for half the connections.
        """
        result = attach_cable_views(
            [_connection(**{PortConnectionKey.CABLE_NAME.value: 'Patch 1'})],
            _objects_manager([]),
            _options_manager([]),
        )

        assert len(result) == 1
        assert all(key.value not in result[0] for key in CABLE_FIELD_KEYS)
        assert result[0][CABLE_VIEW_KEY][CableViewKey.NAME.value] == 'Patch 1'

    def test_the_other_connection_keys_are_untouched(self) -> None:
        """Only the cable half of the document is rewritten"""
        result = attach_cable_views([_connection()], _objects_manager([]), _options_manager([]))

        assert result[0][PortConnectionKey.PUBLIC_ID.value] == CONNECTION_ID
        assert result[0][PortConnectionKey.ENDPOINTS.value] == [1, 2]
        assert result[0][PortConnectionKey.AUTHOR_ID.value] == 1

    def test_a_whole_page_costs_two_reads(self) -> None:
        """The reason the lookups are collected first: a device's cabling is not an N+1"""
        objects_manager = _objects_manager([_cable_ci(), _cable_ci(OTHER_CABLE_CI_ID)])
        options_manager = _options_manager([_option()])

        attach_cable_views(
            [
                _connection(**{PortConnectionKey.CABLE_CI_ID.value: CABLE_CI_ID}),
                _connection(**{PortConnectionKey.CABLE_CI_ID.value: OTHER_CABLE_CI_ID}),
                _connection(**{PortConnectionKey.CABLE_TYPE.value: CABLE_TYPE_ID}),
                _connection(**{PortConnectionKey.CABLE_NAME.value: 'Patch 3'}),
            ],
            objects_manager,
            options_manager,
        )

        assert objects_manager.find_objects.call_count == 1
        assert options_manager.find.call_count == 1

    def test_an_empty_list_reads_nothing(self) -> None:
        """A device with no cabling answers [] without touching the database"""
        objects_manager = _objects_manager([])
        options_manager = _options_manager([])

        assert attach_cable_views([], objects_manager, options_manager) == []
        objects_manager.find_objects.assert_not_called()
        options_manager.find.assert_not_called()

    def test_the_single_form_returns_one_connection(self) -> None:
        """attach_cable_view is the same rule, for the routes that answer with one document"""
        result = attach_cable_view(
            _connection(**{PortConnectionKey.CABLE_CI_ID.value: CABLE_CI_ID}),
            _objects_manager([_cable_ci(**{CableField.NAME.value: 'CAB-000471'})]),
            _options_manager([]),
        )

        assert result[CABLE_VIEW_KEY][CableViewKey.NAME.value] == 'CAB-000471'
