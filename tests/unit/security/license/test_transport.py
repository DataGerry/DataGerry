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
Unit tests for cmdb.security.license.transport

Covers the two blob shapes: Base64+JSON round-trips for the activation request (including
non-ASCII and the compact no-space separators) and Base64 round-trips for opaque binary
ciphertext. Also pins that the strict decoders reject malformed input so the verification chain
can catch and degrade. Pure tests
"""
import base64
import binascii
import json

import pytest

from cmdb.security.license.transport import (
    decode_binary,
    decode_json,
    encode_binary,
    encode_json,
)
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                            JSON blob transport                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_encode_decode_json_round_trip() -> None:
    """A dict survives an encode -> decode round-trip unchanged"""
    payload = {'id': 'abc', 'ttl': 3600, 'machineUuid': 'm-1', 'nested': {'a': [1, 2, 3]}}

    assert decode_json(encode_json(payload)) == payload


def test_encode_json_is_base64_of_compact_json() -> None:
    """encode_json emits Base64 of compact (no-space) JSON for Java-serializer parity"""
    payload = {'a': 1, 'b': 2}

    decoded_text = base64.b64decode(encode_json(payload)).decode('utf-8')

    assert decoded_text == json.dumps(payload, separators=(',', ':'))
    assert ', ' not in decoded_text


def test_json_round_trip_preserves_non_ascii() -> None:
    """Non-ASCII values survive the UTF-8 + Base64 round-trip"""
    payload = {'computerName': 'rechner-müll-ä'}

    assert decode_json(encode_json(payload)) == payload


def test_decode_json_rejects_invalid_base64() -> None:
    """Strict Base64 decoding raises on non-Base64 input rather than silently decoding"""
    with pytest.raises(binascii.Error):
        decode_json('not valid base64!!!')


def test_decode_json_rejects_non_json_payload() -> None:
    """Valid Base64 that is not JSON raises a JSON decode error"""
    not_json = base64.b64encode(b'plain text, not json').decode('ascii')

    with pytest.raises(json.JSONDecodeError):
        decode_json(not_json)


# -------------------------------------------------------------------------------------------------------------------- #
#                                           binary blob transport                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_encode_decode_binary_round_trip() -> None:
    """Opaque bytes survive an encode -> decode round-trip unchanged"""
    raw = bytes(range(256))

    assert decode_binary(encode_binary(raw)) == raw


def test_decode_binary_rejects_invalid_base64() -> None:
    """Strict Base64 decoding raises on malformed binary blobs"""
    with pytest.raises(binascii.Error):
        decode_binary('@@@not-base64@@@')
