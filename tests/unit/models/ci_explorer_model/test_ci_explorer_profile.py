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
Unit tests for cmdb.models.ci_explorer_model.ci_explorer_profile

Pure tests: no Mongo, no Flask, no fixtures. They exercise the CmdbCiExplorerProfile
(de)serialization contract - from_data / to_json round-trips, the constructor's default and
None-normalisation behaviour, and the error wrapping of each method.

The schema / serialization key names come from CiExplorerProfileKey, the model's key enum; field
values are literal test data. The three edge-source toggles default to TRUE - the frontend graph's
defaults (DEFAULT_PROFILE_SCOPE)
"""
from typing import Any

import pytest

from cmdb.models.ci_explorer_model.ci_explorer_profile import CmdbCiExplorerProfile
from cmdb.models.ci_explorer_model.ci_explorer_profile_constants import CiExplorerProfileKey, DEFAULT_PROFILE_SCOPE
from cmdb.errors.models.cmdb_ci_explorer_profile import (
    CmdbCiExplorerProfileInitError,
    CmdbCiExplorerProfileInitFromDataError,
    CmdbCiExplorerProfileToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

# CmdbCiExplorerProfile schema / serialization keys
KEY_PUBLIC_ID: str = CiExplorerProfileKey.PUBLIC_ID.value
KEY_NAME: str = CiExplorerProfileKey.NAME.value
KEY_TYPES_FILTER: str = CiExplorerProfileKey.TYPES_FILTER.value
KEY_RELATIONS_FILTER: str = CiExplorerProfileKey.RELATIONS_FILTER.value
KEY_WITH_LOCATIONS: str = CiExplorerProfileKey.WITH_LOCATIONS.value
KEY_WITH_IPAM_RELATIONS: str = CiExplorerProfileKey.WITH_IPAM_RELATIONS.value
KEY_WITH_PORT_CONNECTIONS: str = CiExplorerProfileKey.WITH_PORT_CONNECTIONS.value

ALL_KEYS: frozenset[str] = frozenset(key.value for key in CiExplorerProfileKey)
TOGGLE_KEYS: tuple[str, ...] = (KEY_WITH_LOCATIONS, KEY_WITH_IPAM_RELATIONS, KEY_WITH_PORT_CONNECTIONS)

# Sample data reused across tests
SAMPLE_PUBLIC_ID: int = 7
SAMPLE_NAME: str = 'network-overview'
SAMPLE_TYPES_FILTER: list[int] = [1, 2, 3]
SAMPLE_RELATIONS_FILTER: list[int] = [10, 20]


def _full_profile_dict() -> dict[str, Any]:
    """A complete profile document with every key set and the three toggles off - away from their defaults"""
    return {
        KEY_PUBLIC_ID: SAMPLE_PUBLIC_ID,
        KEY_NAME: SAMPLE_NAME,
        KEY_TYPES_FILTER: list(SAMPLE_TYPES_FILTER),
        KEY_RELATIONS_FILTER: list(SAMPLE_RELATIONS_FILTER),
        KEY_WITH_LOCATIONS: False,
        KEY_WITH_IPAM_RELATIONS: False,
        KEY_WITH_PORT_CONNECTIONS: False,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                          from_data - defaults & normalisation                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_from_data_applies_defaults_for_omitted_optionals() -> None:
    """With only public_id + name set, filters default to [] and all three toggles to True - an older document too"""
    profile = CmdbCiExplorerProfile.from_data({KEY_PUBLIC_ID: SAMPLE_PUBLIC_ID, KEY_NAME: SAMPLE_NAME})

    assert profile.types_filter == []
    assert profile.relations_filter == []
    assert (profile.with_locations, profile.with_ipam_relations, profile.with_port_connections) == (True, True, True)


@pytest.mark.parametrize('filter_value', [None, []])
def test_from_data_normalises_empty_filters_to_list(filter_value: list[int] | None) -> None:
    """A None or empty filter in the source document is stored as an empty list"""
    profile = CmdbCiExplorerProfile.from_data({
        KEY_PUBLIC_ID: SAMPLE_PUBLIC_ID,
        KEY_NAME: SAMPLE_NAME,
        KEY_TYPES_FILTER: filter_value,
        KEY_RELATIONS_FILTER: filter_value,
    })

    assert profile.types_filter == []
    assert profile.relations_filter == []


def test_from_data_preserves_given_values() -> None:
    """Every supplied field is carried onto the instance unchanged"""
    profile = CmdbCiExplorerProfile.from_data(_full_profile_dict())

    assert profile.get_public_id() == SAMPLE_PUBLIC_ID
    assert profile.name == SAMPLE_NAME
    assert profile.types_filter == SAMPLE_TYPES_FILTER
    assert profile.relations_filter == SAMPLE_RELATIONS_FILTER
    assert (profile.with_locations, profile.with_ipam_relations, profile.with_port_connections) == (False, False, False)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       to_json                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_to_json_emits_every_schema_key() -> None:
    """to_json serialises exactly the SCHEMA keys (regression guard: no SCHEMA field may be dropped)"""
    profile = CmdbCiExplorerProfile.from_data(_full_profile_dict())

    assert set(CmdbCiExplorerProfile.SCHEMA) == ALL_KEYS
    assert set(CmdbCiExplorerProfile.to_json(profile)) == set(CmdbCiExplorerProfile.SCHEMA)


def test_to_json_round_trips_values() -> None:
    """to_json(from_data(doc)) reproduces the original document"""
    source = _full_profile_dict()

    result = CmdbCiExplorerProfile.to_json(CmdbCiExplorerProfile.from_data(source))

    assert result == source


@pytest.mark.parametrize('with_locations,with_ipam_relations', [
    (True, True),
    (True, False),
    (False, True),
    (False, False),
])
def test_toggle_flags_survive_round_trip(with_locations: bool, with_ipam_relations: bool) -> None:
    """Both boolean toggles round-trip through from_data -> to_json (guards the drop-on-update fix)"""
    source = {
        KEY_PUBLIC_ID: SAMPLE_PUBLIC_ID,
        KEY_NAME: SAMPLE_NAME,
        KEY_WITH_LOCATIONS: with_locations,
        KEY_WITH_IPAM_RELATIONS: with_ipam_relations,
    }

    result = CmdbCiExplorerProfile.to_json(CmdbCiExplorerProfile.from_data(source))

    assert result[KEY_WITH_LOCATIONS] is with_locations
    assert result[KEY_WITH_IPAM_RELATIONS] is with_ipam_relations


# -------------------------------------------------------------------------------------------------------------------- #
#                                                constructor behaviour                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_init_defaults_when_toggles_omitted() -> None:
    """Constructing without the toggles yields all three True - the frontend graph's defaults"""
    profile = CmdbCiExplorerProfile(
        public_id=SAMPLE_PUBLIC_ID,
        name=SAMPLE_NAME,
        types_filter=[],
        relations_filter=[],
    )

    assert (profile.with_locations, profile.with_ipam_relations, profile.with_port_connections) == (True, True, True)


@pytest.mark.parametrize('filter_value', [None, []])
def test_init_normalises_falsy_filters_to_list(filter_value: list[int] | None) -> None:
    """None or an empty list for either filter is stored as an empty list"""
    profile = CmdbCiExplorerProfile(
        public_id=SAMPLE_PUBLIC_ID,
        name=SAMPLE_NAME,
        types_filter=filter_value,
        relations_filter=filter_value,
    )

    assert profile.types_filter == []
    assert profile.relations_filter == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    error wrapping                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('bad_data', [None, [], 'not-a-dict', 42])
def test_from_data_wraps_non_dict_input(bad_data: Any) -> None:
    """Input without a .get interface is wrapped as CmdbCiExplorerProfileInitFromDataError"""
    with pytest.raises(CmdbCiExplorerProfileInitFromDataError):
        CmdbCiExplorerProfile.from_data(bad_data)


def test_from_data_requires_public_id() -> None:
    """A document without public_id cannot be coerced and is wrapped as InitFromDataError"""
    with pytest.raises(CmdbCiExplorerProfileInitFromDataError):
        CmdbCiExplorerProfile.from_data({KEY_NAME: SAMPLE_NAME})


@pytest.mark.parametrize('bad_instance', [None, 'not-a-profile', 42])
def test_to_json_wraps_invalid_instance(bad_instance: Any) -> None:
    """An object lacking the profile interface is wrapped as CmdbCiExplorerProfileToJsonError"""
    with pytest.raises(CmdbCiExplorerProfileToJsonError):
        CmdbCiExplorerProfile.to_json(bad_instance)


def test_init_wraps_non_coercible_public_id() -> None:
    """A non-coercible public_id surfaces as CmdbCiExplorerProfileInitError"""
    with pytest.raises(CmdbCiExplorerProfileInitError):
        CmdbCiExplorerProfile(
            public_id=object(),
            name=SAMPLE_NAME,
            types_filter=[],
            relations_filter=[],
        )


# -------------------------------------------------------------------------------------------------------------------- #
#                                         the third toggle and the shared defaults                                     #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('with_port_connections', [True, False])
def test_the_port_connections_toggle_round_trips(with_port_connections: bool) -> None:
    """with_port_connections is stored and answered like the other two"""
    source = {KEY_PUBLIC_ID: SAMPLE_PUBLIC_ID, KEY_NAME: SAMPLE_NAME, KEY_WITH_PORT_CONNECTIONS: with_port_connections}

    result = CmdbCiExplorerProfile.to_json(CmdbCiExplorerProfile.from_data(source))

    assert result[KEY_WITH_PORT_CONNECTIONS] is with_port_connections


def test_the_defaults_are_the_frontends() -> None:
    """All three on - DEFAULT_CI_EXPLORER_SCOPE in ci-explorer.model.ts"""
    assert DEFAULT_PROFILE_SCOPE == {key: True for key in TOGGLE_KEYS}


@pytest.mark.parametrize('key', TOGGLE_KEYS)
def test_the_schema_defaults_every_toggle_to_true(key: str) -> None:
    """A write that leaves a toggle out stores its default - a create and an update alike"""
    assert CmdbCiExplorerProfile.SCHEMA[key]['default'] is True
    assert CmdbCiExplorerProfile.SCHEMA[key]['type'] == 'boolean'


def test_the_two_id_filters_do_not_share_a_rule() -> None:
    """Each filter gets its own rule dict, so a change to one could never leak into the other"""
    types_rule = CmdbCiExplorerProfile.SCHEMA[KEY_TYPES_FILTER]
    relations_rule = CmdbCiExplorerProfile.SCHEMA[KEY_RELATIONS_FILTER]

    assert types_rule == relations_rule
    assert types_rule is not relations_rule
    assert types_rule['schema'] is not relations_rule['schema']

