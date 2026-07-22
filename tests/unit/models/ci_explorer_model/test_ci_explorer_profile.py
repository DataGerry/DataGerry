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

The model exposes no dedicated key enum, so the schema / serialization key names are pinned to
the module-level KEY_* constants below (per the no-magic-values rule); field values are literal
test data
"""
from typing import Any

import pytest

from cmdb.models.ci_explorer_model.ci_explorer_profile import CmdbCiExplorerProfile
from cmdb.errors.models.cmdb_ci_explorer_profile import (
    CmdbCiExplorerProfileInitError,
    CmdbCiExplorerProfileInitFromDataError,
    CmdbCiExplorerProfileToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

# CmdbCiExplorerProfile schema / serialization keys (the model exposes no key enum)
KEY_PUBLIC_ID: str = 'public_id'
KEY_NAME: str = 'name'
KEY_TYPES_FILTER: str = 'types_filter'
KEY_RELATIONS_FILTER: str = 'relations_filter'
KEY_WITH_LOCATIONS: str = 'with_locations'
KEY_WITH_IPAM_RELATIONS: str = 'with_ipam_relations'

ALL_KEYS: frozenset[str] = frozenset({
    KEY_PUBLIC_ID,
    KEY_NAME,
    KEY_TYPES_FILTER,
    KEY_RELATIONS_FILTER,
    KEY_WITH_LOCATIONS,
    KEY_WITH_IPAM_RELATIONS,
})

# Sample data reused across tests
SAMPLE_PUBLIC_ID: int = 7
SAMPLE_NAME: str = 'network-overview'
SAMPLE_TYPES_FILTER: list[int] = [1, 2, 3]
SAMPLE_RELATIONS_FILTER: list[int] = [10, 20]


def _full_profile_dict() -> dict[str, Any]:
    """A complete profile document with every key set and the toggles flipped off their defaults"""
    return {
        KEY_PUBLIC_ID: SAMPLE_PUBLIC_ID,
        KEY_NAME: SAMPLE_NAME,
        KEY_TYPES_FILTER: list(SAMPLE_TYPES_FILTER),
        KEY_RELATIONS_FILTER: list(SAMPLE_RELATIONS_FILTER),
        KEY_WITH_LOCATIONS: False,
        KEY_WITH_IPAM_RELATIONS: True,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                          from_data - defaults & normalisation                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_from_data_applies_defaults_for_omitted_optionals() -> None:
    """With only public_id + name set, filters default to [] and the toggles to True / False"""
    profile = CmdbCiExplorerProfile.from_data({KEY_PUBLIC_ID: SAMPLE_PUBLIC_ID, KEY_NAME: SAMPLE_NAME})

    assert profile.types_filter == []
    assert profile.relations_filter == []
    assert profile.with_locations is True
    assert profile.with_ipam_relations is False


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
    assert profile.with_locations is False
    assert profile.with_ipam_relations is True


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
    """Constructing without the toggles yields with_locations True and with_ipam_relations False"""
    profile = CmdbCiExplorerProfile(
        public_id=SAMPLE_PUBLIC_ID,
        name=SAMPLE_NAME,
        types_filter=[],
        relations_filter=[],
    )

    assert profile.with_locations is True
    assert profile.with_ipam_relations is False


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
