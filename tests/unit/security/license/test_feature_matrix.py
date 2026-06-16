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
Unit tests for cmdb.security.license.feature_matrix

Pins the cumulative tier -> feature contract: the exact feature set each tier unlocks, the
monotonic superset relationship between tiers, that CORPORATE currently equals BUSINESS, that
Community (FREE) unlocks nothing, and that every declared LicenseFeature is reachable from some
tier (no orphan feature). Pure tests
"""
import pytest

from cmdb.security.license.feature_matrix import (
    TIER_FEATURES,
    TIER_ORDER,
    features_for,
    tier_has_feature,
)
from cmdb.security.license.license_constants import LicenseFeature, LicenseTier
# -------------------------------------------------------------------------------------------------------------------- #

# Pinned cumulative tier -> feature contract (the resolved set, not the per-tier additions)
EXPECTED_TIER_FEATURES: dict[LicenseTier, set[LicenseFeature]] = {
    LicenseTier.FREE: set(),
    LicenseTier.CORE: {
        LicenseFeature.API_ACCESS,
        LicenseFeature.WEBHOOKS,
        LicenseFeature.IPAM,
    },
    LicenseTier.BUSINESS: {
        LicenseFeature.API_ACCESS,
        LicenseFeature.WEBHOOKS,
        LicenseFeature.IPAM,
        LicenseFeature.ISMS,
        LicenseFeature.AI_DOC_GENERATION,
        LicenseFeature.AUTOMATIONS,
    },
    LicenseTier.CORPORATE: {
        LicenseFeature.API_ACCESS,
        LicenseFeature.WEBHOOKS,
        LicenseFeature.IPAM,
        LicenseFeature.ISMS,
        LicenseFeature.AI_DOC_GENERATION,
        LicenseFeature.AUTOMATIONS,
    },
}


# -------------------------------------------------------------------------------------------------------------------- #
#                                         cumulative feature sets                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    'tier,expected',
    list(EXPECTED_TIER_FEATURES.items()),
    ids=[tier.value for tier in EXPECTED_TIER_FEATURES],
)
def test_features_for_matches_contract(tier: LicenseTier, expected: set[LicenseFeature]) -> None:
    """features_for() returns exactly the pinned cumulative set for each tier"""
    assert set(features_for(tier)) == expected


def test_precomputed_map_matches_resolver() -> None:
    """The precomputed TIER_FEATURES map agrees with features_for() for every tier"""
    assert TIER_FEATURES == {tier: features_for(tier) for tier in TIER_ORDER}


def test_free_unlocks_nothing() -> None:
    """Community (FREE) unlocks no gated feature - every unlisted feature is always available"""
    assert features_for(LicenseTier.FREE) == frozenset()


def test_corporate_currently_equals_business() -> None:
    """CORPORATE currently unlocks the same features as BUSINESS (its own row, today equal)"""
    assert features_for(LicenseTier.CORPORATE) == features_for(LicenseTier.BUSINESS)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          monotonic supersets                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_each_tier_is_superset_of_the_one_below() -> None:
    """Every tier's feature set is a superset of the tier below it (tiers are cumulative)"""
    for lower, higher in zip(TIER_ORDER, TIER_ORDER[1:]):
        assert features_for(lower) <= features_for(higher)


def test_every_feature_is_reachable() -> None:
    """Every declared LicenseFeature is unlocked by at least the top tier (no orphan feature)"""
    assert set(features_for(LicenseTier.CORPORATE)) == set(LicenseFeature)


def test_features_for_unknown_tier_degrades_to_empty() -> None:
    """An unrecognised tier value yields the empty (Community) feature set rather than raising"""
    assert features_for('enterprise') == frozenset()


# -------------------------------------------------------------------------------------------------------------------- #
#                                            tier_has_feature                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_tier_has_feature_true_for_unlocked() -> None:
    """tier_has_feature() is True when the tier unlocks the feature"""
    assert tier_has_feature(LicenseTier.CORE, LicenseFeature.IPAM) is True


def test_tier_has_feature_false_for_locked() -> None:
    """tier_has_feature() is False when the feature belongs to a higher tier"""
    assert tier_has_feature(LicenseTier.CORE, LicenseFeature.ISMS) is False
