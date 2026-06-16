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
Tier -> feature matrix for the license feature (license feature part P2)

The four license tiers are cumulative: each unlocks every feature of the tiers below it plus its
own additions. Rather than repeat the inherited features in every tier, this module declares only
the features INTRODUCED at each tier (TIER_FEATURE_ADDITIONS) and derives the cumulative set with
features_for(). TIER_FEATURES is the precomputed cumulative map for direct lookup.

Community (FREE) introduces no gated features - every feature not named in LicenseFeature is part
of Community and always available. CORPORATE currently introduces nothing (its set equals BUSINESS)
but keeps its own row so features can be added later without restructuring
"""
from cmdb.security.license.license_constants import LicenseFeature, LicenseTier
# -------------------------------------------------------------------------------------------------------------------- #

# License tiers in ascending order; each tier is a superset of the ones before it
TIER_ORDER: tuple[LicenseTier, ...] = (
    LicenseTier.FREE,
    LicenseTier.CORE,
    LicenseTier.BUSINESS,
    LicenseTier.CORPORATE,
)

# Features INTRODUCED at each tier (not the cumulative set); features_for() accumulates up the chain
TIER_FEATURE_ADDITIONS: dict[LicenseTier, frozenset[LicenseFeature]] = {
    LicenseTier.FREE: frozenset(),
    LicenseTier.CORE: frozenset({
        LicenseFeature.API_ACCESS,
        LicenseFeature.WEBHOOKS,
        LicenseFeature.IPAM,
    }),
    LicenseTier.BUSINESS: frozenset({
        LicenseFeature.ISMS,
        LicenseFeature.AI_DOC_GENERATION,
        LicenseFeature.AUTOMATIONS,
    }),
    LicenseTier.CORPORATE: frozenset(),
}


def features_for(tier: LicenseTier) -> frozenset[LicenseFeature]:
    """
    Resolves the cumulative set of features a tier unlocks

    Walks the tiers in ascending order and unions each tier's additions up to and including the
    requested tier. An unknown tier degrades to the empty (Community) set rather than raising, so
    a malformed license never grants more than Community

    Args:
        tier (LicenseTier): The tier to resolve

    Returns:
        frozenset[LicenseFeature]: Every feature unlocked at that tier (inherited plus its own)
    """
    if tier not in TIER_FEATURE_ADDITIONS:
        return frozenset()

    unlocked: set[LicenseFeature] = set()

    for current in TIER_ORDER:
        unlocked |= TIER_FEATURE_ADDITIONS[current]
        if current == tier:
            break

    return frozenset(unlocked)


# Precomputed cumulative tier -> features map (derived from the additions above) for direct lookup
TIER_FEATURES: dict[LicenseTier, frozenset[LicenseFeature]] = {tier: features_for(tier) for tier in TIER_ORDER}


def tier_has_feature(tier: LicenseTier, feature: LicenseFeature) -> bool:
    """
    Checks whether a tier unlocks a given feature

    Args:
        tier (LicenseTier): The tier to check
        feature (LicenseFeature): The feature to test for

    Returns:
        bool: True if the tier unlocks the feature, False otherwise
    """
    return feature in TIER_FEATURES.get(tier, frozenset())
