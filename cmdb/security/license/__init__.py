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
On-premise license feature: offline, signed license files gating features by license tier

Sits beside acl/ auth/ key/ token/ in cmdb/security/. Reproduces OpenCelium's offline license
primitives (RSA public-key decrypt as a homemade signature, HMAC-SHA256 machine binding, Base64 +
JSON transport) so the same Service Portal tech can issue DataGerry licenses. License gating
applies to the on-premise deployment only - never the cloud version or its --local test mode.

This package is built incrementally; it currently exposes the license constants/enums (P1), the
machine fingerprint utility (P3), the HMAC binding primitive (P4), the Base64+JSON transport
helpers (P5), the RSA public-key decrypt primitive (P6), the activation-request model (P8), the
activation-request lifecycle helpers (P9), the license entitlement model (P10), the verification
chain (P11) and the free/default fallback (P12). What a license unlocks is carried by the
entitlement's `features` list (the sole gating source), not derived from `type`. Import these names
from the package path, not the inner modules
"""
from cmdb.security.license.license_constants import (
    FINGERPRINT_FALLBACK,
    LICENSE_HMAC_SECRET,
    LICENSE_PUBLIC_KEY_PEM,
    ActivationRequestKey,
    ActivationRequestStatus,
    LicenseEntitlementKey,
    LicenseFeature,
    LicenseTier,
    LicenseVerificationStatus,
    PlatformName,
)
from cmdb.security.license.machine_fingerprint import get_machine_fingerprint
from cmdb.security.license.hmac_binding import (
    compute_hmac,
    constant_time_equals,
    machine_binding_hmac,
)
from cmdb.security.license.transport import (
    decode_binary,
    decode_json,
    encode_binary,
    encode_json,
)
from cmdb.security.license.rsa_decrypt import (
    decrypt_license_blob,
    public_decrypt,
)
from cmdb.security.license.activation_request import LicenseActivationRequest
from cmdb.security.license.entitlement import LicenseEntitlement
from cmdb.security.license.verification import LicenseVerificationResult, verify_license
from cmdb.security.license.fallback import (
    default_activation_request,
    default_entitlement,
    entitlement_or_default,
)
from cmdb.security.license.activation_lifecycle import (
    DEFAULT_TTL_SECONDS,
    activation_request_blob,
    build_activation_request,
    is_request_expired,
    new_request_id,
)
# -------------------------------------------------------------------------------------------------------------------- #


__all__: list[str] = [
    'FINGERPRINT_FALLBACK',
    'LICENSE_HMAC_SECRET',
    'LICENSE_PUBLIC_KEY_PEM',
    'ActivationRequestKey',
    'ActivationRequestStatus',
    'LicenseEntitlementKey',
    'LicenseFeature',
    'LicenseTier',
    'LicenseVerificationStatus',
    'PlatformName',
    'get_machine_fingerprint',
    'compute_hmac',
    'constant_time_equals',
    'machine_binding_hmac',
    'decode_binary',
    'decode_json',
    'encode_binary',
    'encode_json',
    'decrypt_license_blob',
    'public_decrypt',
    'LicenseActivationRequest',
    'LicenseEntitlement',
    'LicenseVerificationResult',
    'verify_license',
    'default_activation_request',
    'default_entitlement',
    'entitlement_or_default',
    'DEFAULT_TTL_SECONDS',
    'activation_request_blob',
    'build_activation_request',
    'is_request_expired',
    'new_request_id',
]
