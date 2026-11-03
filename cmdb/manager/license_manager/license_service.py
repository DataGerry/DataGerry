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
Implementation of LicenseService (license feature part P13)

The single entry point the rest of the backend asks "what is licensed right now". It resolves the
active license on demand: read the stored blob (ActiveLicenseManager), verify it (P11 against the
activation requests), and degrade to the free entitlement on any failure or when none is stored
(P12). From the resolved entitlement it answers the current tier (display-only), has_feature()
straight off the entitlement's features list (the sole gating source), is_active() and the
operation-usage limit; activate() verifies-then-stores an uploaded blob and deactivate() reverts to
free.

Resolution is on demand rather than cached at startup: gunicorn runs multiple workers and the lazy
approach (mirroring the activation-request TTL) avoids stale per-worker caches. It is NOT only the admin/status
surface that pays it: every gated route and every HTTP Basic request resolves the licence. So a request resolves
it at most once - the request's instance (``license_guard.request_license_service``, kept on ``flask.g``) is told to
keep the state it resolved (``keep_resolved_state``) - and the decrypt and schema check of the stored blob, about
half of one resolution with the shipped RSA-4096 key, are decoded once per process
(``verification.decode_entitlement``); the two database reads, which make an activation or removal visible at once,
run on every resolution. The on-premise guard lives at the route layer (the service
itself is mode-agnostic and unit-testable). The public key is injectable for testing; production
uses the shipped key
"""
from logging import Logger, getLogger
from typing import NamedTuple, Optional

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.active_license_manager import ActiveLicenseManager
from cmdb.manager.license_manager.license_activation_requests_manager import LicenseActivationRequestsManager

from cmdb.security.license.entitlement import LicenseEntitlement
from cmdb.security.license.fallback import default_entitlement, entitlement_or_default
from cmdb.security.license.license_constants import (
    LICENSE_PUBLIC_KEY_PEM,
    LicenseFeature,
    LicenseVerificationStatus,
)
from cmdb.security.license.verification import LicenseVerificationResult, verify_license
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                LicenseState - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class LicenseState(NamedTuple):
    """
    The resolved license state in a single value

    Carries the effective entitlement (verified or free), the verification status (None when no
    license is stored), and whether a stored license is currently valid
    """
    entitlement: LicenseEntitlement
    status: Optional[LicenseVerificationStatus]
    active: bool

    def has_feature(self, feature: LicenseFeature) -> bool:
        """
        Whether this state's entitlement unlocks a feature

        Reads straight off the entitlement's features list - the sole source of truth. A feature the
        license does not list (including every feature on the free default) is not unlocked

        Args:
            feature (LicenseFeature): The feature to check

        Returns:
            bool: True if the entitlement lists the feature
        """
        return feature.value in self.entitlement.features


# -------------------------------------------------------------------------------------------------------------------- #
#                                               LicenseService - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class LicenseService:
    """
    Resolves and exposes the install's active license and what it grants
    """

    def __init__(
        self,
        dbm: MongoDatabaseManager,
        database: str | None = None,
        public_key_pem: str = LICENSE_PUBLIC_KEY_PEM,
    ) -> None:
        """
        Initialises the LicenseService

        Args:
            dbm (MongoDatabaseManager): The database interaction manager
            database (str | None): Target tenant database name (cloud mode); None on-premise
            public_key_pem (str): PEM public key used to verify licenses; defaults to the shipped key
        """
        self.active_license_manager = ActiveLicenseManager(dbm, database)
        self.activation_requests_manager = LicenseActivationRequestsManager(dbm, database)
        self.public_key_pem = public_key_pem
        # Off unless keep_resolved_state was called: an instance resolves on every question, as it always did
        self._keeps_state: bool = False
        self._kept_state: Optional[LicenseState] = None


    def keep_resolved_state(self) -> None:
        """
        Makes this instance resolve the licence once and answer that state from then on

        For an instance that lives as long as one request: every feature question of the request then reads one
        resolution. ``activate`` and ``deactivate`` drop the kept state, so the instance answers the licence they
        wrote. Any other instance is unaffected - it resolves on every question
        """
        self._keeps_state = True


    def _verify_stored(self) -> Optional[LicenseVerificationResult]:
        """
        Verifies the stored active license blob, if any

        Returns:
            Optional[LicenseVerificationResult]: The verification result, or None if none is stored
        """
        blob = self.active_license_manager.get_active_license_blob()

        if blob is None:
            return None

        return verify_license(blob, self.activation_requests_manager, public_key_pem=self.public_key_pem)


    def current_state(self) -> LicenseState:
        """
        Resolves the full license state in a single pass

        Kept and answered again when ``keep_resolved_state`` was called on this instance

        Returns:
            LicenseState: The effective entitlement, the verification status (None when no license
            is stored) and whether a stored license is currently valid
        """
        if self._kept_state is not None:
            return self._kept_state

        result = self._verify_stored()

        if result is None:
            state = LicenseState(default_entitlement(), None, False)
        else:
            state = LicenseState(entitlement_or_default(result), result.status, result.is_valid)

        if self._keeps_state:
            self._kept_state = state

        return state


    def current_entitlement(self) -> LicenseEntitlement:
        """
        Resolves the currently effective entitlement

        Returns:
            LicenseEntitlement: The verified entitlement, or the free entitlement when none is
            stored or verification fails
        """
        return self.current_state().entitlement


    def current_status(self) -> Optional[LicenseVerificationStatus]:
        """
        Returns the verification status of the stored license

        Returns:
            Optional[LicenseVerificationStatus]: The status, or None when no license is stored
            (the install runs on the free default)
        """
        return self.current_state().status


    def is_active(self) -> bool:
        """
        Whether a stored license is currently valid

        Returns:
            bool: True if a stored license verifies as VALID; False when running on the free default
        """
        return self.current_state().active


    def current_tier(self) -> str:
        """
        The currently effective license tier

        Returns:
            str: The tier discriminator (a LicenseTier value) of the current entitlement
        """
        return self.current_entitlement().license_type


    def has_feature(self, feature: LicenseFeature) -> bool:
        """
        Whether the current license unlocks a feature

        Reads straight off the entitlement's features list - the sole source of truth. A feature the
        license does not list (including every feature on the free default) is not unlocked

        Args:
            feature (LicenseFeature): The feature to check

        Returns:
            bool: True if the current entitlement lists the feature
        """
        return self.current_state().has_feature(feature)


    def activate(self, blob: str) -> LicenseVerificationResult:
        """
        Verifies an uploaded license blob and stores it as active when valid

        Unlike the ongoing verification used for feature gating, activation also enforces the bound
        activation request's TTL: a license bound to a request older than its window is rejected with
        ACTIVATION_REQUEST_EXPIRED and not stored.

        Args:
            blob (str): The Base64 license blob to activate

        Returns:
            LicenseVerificationResult: The verification result; the blob is stored only when VALID
        """
        result = verify_license(
            blob,
            self.activation_requests_manager,
            public_key_pem=self.public_key_pem,
            enforce_activation_ttl=True,
        )

        if result.is_valid:
            self.active_license_manager.set_active_license(blob)
            self._kept_state = None

        return result


    def deactivate(self) -> bool:
        """
        Removes the active license, reverting the install to the free tier

        Returns:
            bool: True if a license was removed, False if none was active
        """
        removed: bool = self.active_license_manager.clear_active_license()
        self._kept_state = None

        return removed
