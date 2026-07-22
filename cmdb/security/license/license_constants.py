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
Constants, enums and shipped crypto material for the on-premise license feature

This module is the single owner of the license feature's magic values: the license tiers, the
feature discriminators each tier unlocks, the activation-request / entitlement wire-format keys
(camelCase, matching OpenCelium byte-for-byte for parity), the platform tokens the machine
fingerprint branches on, and the crypto material DataGerry ships with every install (the RSA
PUBLIC key plus the HMAC secret). The matching RSA PRIVATE key never ships - it lives only with
the license generator/portal (see tools/license/generate_license_keys.py).

Every string enum extends BaseStrEnum so members compare equal to their wire-format string value
for dict lookup, equality and JSON (de)serialization. Use these members instead of bare string
literals everywhere the license feature reads or writes a tier, feature, status or wire-format key
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

# Per-field fallback value emitted by the machine fingerprint when a field cannot be resolved
# (kept for OpenCelium parity; a missing hardware identifier degrades to this token, not an error)
FINGERPRINT_FALLBACK: str = '0'


class LicenseTier(BaseStrEnum):
    """
    The four cumulative license tiers, each a superset of the previous one

    The value is the wire-format `type` discriminator carried by a license entitlement and the
    key into the tier->feature matrix. FREE is the Community tier: it is the embedded fallback
    used when there is no license AND the degrade target whenever a license is invalid (decrypt
    failure, HMAC/binding mismatch, expired or malformed) - the feature must never hard-fail or
    lock the user out. CORE, BUSINESS and CORPORATE are the paid tiers in ascending order;
    CORPORATE is modelled as its own distinct tier even though its feature set currently equals
    BUSINESS, because its feature assignments may diverge later
    """
    FREE = 'free'
    CORE = 'core'
    BUSINESS = 'business'
    CORPORATE = 'corporate'


class LicenseFeature(BaseStrEnum):
    """
    The individually gated features a license can unlock

    Each member names one feature whose availability is decided by the active license: a feature is
    unlocked only when the entitlement's `features` list contains its value (the list is the sole
    source of truth; `type` is display-only). Any feature NOT listed here belongs to Community and
    is always available. The backend gates on the members it knows and ignores any unknown feature
    string a license carries, so a portal can ship a feature ahead of backend support. REST_API
    reserves the external-API channel for a future license (the UI-vs-external channel split is
    deferred); the remaining members map one-to-one onto the DataGerry features a license grants
    """
    REST_API = 'rest_api'
    IPAM = 'ipam'
    ISMS = 'isms'
    DOCUMENT_GENERATOR = 'document_generator'
    AUTOMATIONS = 'automations'


class ActivationRequestStatus(BaseStrEnum):
    """
    Lifecycle status of a stored activation request

    A DB-only field tracking the request lifecycle; it is NOT part of the downloaded request file.
    PENDING is the status of a freshly built activation request the admin downloads and of the
    embedded default request. PROCESSED marks a request whose matching license has been applied.
    EXPIRED marks a request that has aged past its TTL or was superseded by a newer request (set in
    bulk when a new request is created, or lazily on read). The string values are uppercase tokens
    """
    PENDING = 'PENDING'
    PROCESSED = 'PROCESSED'
    EXPIRED = 'EXPIRED'


class LicenseVerificationStatus(BaseStrEnum):
    """
    Outcome of the license verification chain

    VALID is the single success state (the entitlement is usable). Every other member names a
    distinct failure stage so the status route can explain why a license was rejected; all failures
    degrade the install to the Community (free) tier. DECRYPT_FAILED covers a bad Base64 / ciphertext
    / PKCS#1 padding / non-JSON payload; SCHEMA_INVALID a decrypted payload that is not a well-formed
    entitlement; NO_ACTIVATION_REQUEST a license whose hmac matches no stored activation request on
    this machine; BINDING_MISMATCH a stored request whose hmac no longer equals the license hmac;
    ACTIVATION_REQUEST_EXPIRED a bound activation request whose TTL has elapsed (enforced only at
    activation time, never during ongoing feature gating); NOT_YET_VALID a startDate in the future;
    EXPIRED an endDate in the past
    """
    VALID = 'valid'
    DECRYPT_FAILED = 'decrypt_failed'
    SCHEMA_INVALID = 'schema_invalid'
    NO_ACTIVATION_REQUEST = 'no_activation_request'
    BINDING_MISMATCH = 'binding_mismatch'
    ACTIVATION_REQUEST_EXPIRED = 'activation_request_expired'
    NOT_YET_VALID = 'not_yet_valid'
    EXPIRED = 'expired'


class ActivationRequestKey(BaseStrEnum):
    """
    Keys of the activation-request JSON blob the admin downloads (Base64-encoded plaintext)

    Names every field of the `{id, hmac, ttl, status, machineUuid, macAddress, systemUUID,
    computerName}` activation-request document. The four machine-field values are the camelCase
    keys produced by the machine fingerprint util (machine_fingerprint.get_machine_fingerprint),
    so the fingerprint dict slots directly into the request. The camelCase spelling is the
    OpenCelium wire format and must not be renamed
    """
    ID = 'id'
    HMAC = 'hmac'
    TTL = 'ttl'
    STATUS = 'status'
    MACHINE_UUID = 'machineUuid'
    MAC_ADDRESS = 'macAddress'
    SYSTEM_UUID = 'systemUUID'
    COMPUTER_NAME = 'computerName'


class LicenseEntitlementKey(BaseStrEnum):
    """
    Keys of the decrypted license entitlement JSON

    Names every field of the `{hmac, startDate, endDate, subId, licenseId, type, features}`
    entitlement recovered by decrypting the license blob with the public key. FEATURES is
    the list of unlocked feature keys (LicenseFeature values) and is the SOLE source of truth for
    what the license grants; TYPE only labels the license for display and does NOT drive gating.
    HMAC must equal the activation request's hmac (the machine-binding check); START_DATE / END_DATE
    are epoch milliseconds with END_DATE 0 meaning no expiry. The camelCase spelling is the
    OpenCelium wire format and must not be renamed
    """
    HMAC = 'hmac'
    START_DATE = 'startDate'
    END_DATE = 'endDate'
    SUB_ID = 'subId'
    LICENSE_ID = 'licenseId'
    TYPE = 'type'
    FEATURES = 'features'


class PlatformName(BaseStrEnum):
    """
    Operating-system tokens returned by platform.system()

    The machine fingerprint util branches on these to pick the per-OS command that reads each
    hardware identifier. The values are exactly the strings platform.system() reports on each
    platform (Windows / Linux / macOS)
    """
    WINDOWS = 'Windows'
    LINUX = 'Linux'
    DARWIN = 'Darwin'


# -------------------------------------------------------------------------------------------------------------------- #
#                                            SHIPPED CRYPTO MATERIAL                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
# The RSA PUBLIC key and the HMAC secret below ship with every install and are used to decrypt and
# verify license entitlements. They are intentionally embedded (the HMAC secret is forgeable by
# anyone with the source - an accepted parity cost, identical to OpenCelium's hardcoded secret).
# The matching RSA PRIVATE key NEVER ships; regenerate this material with
# tools/license/generate_license_keys.py.

# PEM-encoded RSA-4096 public key that decrypts (public-key "verifies") license entitlement blobs
LICENSE_PUBLIC_KEY_PEM: str = """\
-----BEGIN PUBLIC KEY-----
MIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEAxdqurWuDtZRbJ9agxtbQ
cevxbkSk4G7Zue8YwhGyfgFafTGVnvl/uGrkConBxszej2s7Ogd+5z1STqJhZGCk
d6/xCjEq2Mxcd3RkwcTp36pkYuN9q1+TUQhGPgB/J26ZSnX/oTEekzDZpnK0b+cV
oej+67fHC+r1jFvph1/BED7MIjf83Bp89xBkDKWRvPpY66lj5gxMM9y1od9wWR9W
R3+xPmMcPBNPZCkTyoP8pBoww51mrUOAEUUEsUeUxZvit9GTuKkn8VgcnCJQ4q9X
rt32Cn4eCoqrvdQXkKDSI8qsfS/NX+MlmQ76w3P65Ce473z2NkfCqyQKNDczZe6W
LuEQCCJqN3jeXVpQwTZkZ1oRG2aMgoOkYV4EuD4UIGlSQyhQaLjwUbsxsij2ceXV
TpDcuhT8d9cnJGZAhdMSMTymSqS/vkVvqvWbPyd2fXKyYhKLisBqEka+uQHeDEpF
V3+Sgn1i4jdDNXiRFaokPknFHnXdTivwE3a7f7tZwabwyf/T9Yg3GGzHd7KC64XN
G8SJTn1+F5L1Bcx9jwkNoxHF/xd25ipP1Wn966bB8fDVm9imfyCsHLVSEjSOLtew
629mOoXJE1VwuQ0AJCyGq5zXj04gVQ8TYDAoVuaQ0FdrJUxpiL6RPUueJsQaWv9B
pI+lJ4luWh4jgu9nJc8aV9cCAwEAAQ==
-----END PUBLIC KEY-----"""

# HMAC-SHA256 secret used for machine binding and the counter tamper-seal; used as UTF-8 key bytes
LICENSE_HMAC_SECRET: str = 'NI6okPS8ZGwmGYYJUI0V/lsRQxwU/pBp68afDZ1p8qKOHo7wrJchhZLtxuBhVfOq'
