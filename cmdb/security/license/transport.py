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
Base64 + JSON transport helpers for the license feature (license feature part P5)

Two blob shapes cross the license boundary. The activation request is Base64-encoded plaintext
JSON (encode_json / decode_json). The license entitlement is Base64-encoded RSA ciphertext - opaque
bytes until P6 decrypts them (encode_binary / decode_binary).

Decoders use strict Base64 (validate=True) so malformed input raises rather than silently decoding
partial data; callers in the verification chain catch the error and degrade to Community
"""
import base64
import json
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

# Compact JSON separators (no spaces), matching the typical Java serializer output for parity
JSON_SEPARATORS: tuple[str, str] = (',', ':')

# Text encoding used for the JSON payloads on both sides of Base64
TEXT_ENCODING: str = 'utf-8'


def encode_json(data: dict[str, Any]) -> str:
    """
    Serializes a dict to compact JSON and Base64-encodes it (the activation-request blob shape)

    Args:
        data (dict[str, Any]): The payload to encode

    Returns:
        str: The Base64-encoded UTF-8 JSON
    """
    raw = json.dumps(data, separators=JSON_SEPARATORS).encode(TEXT_ENCODING)

    return base64.b64encode(raw).decode('ascii')


def decode_json(blob: str) -> dict[str, Any]:
    """
    Decodes a Base64-encoded JSON blob back into a dict

    Args:
        blob (str): The Base64-encoded UTF-8 JSON

    Returns:
        dict[str, Any]: The decoded payload

    Raises:
        binascii.Error: If 'blob' is not valid Base64
        UnicodeDecodeError: If the decoded bytes are not valid UTF-8
        json.JSONDecodeError: If the decoded text is not valid JSON
    """
    raw = base64.b64decode(blob, validate=True)

    return json.loads(raw.decode(TEXT_ENCODING))


def encode_binary(raw: bytes) -> str:
    """
    Base64-encodes raw bytes (the license-ciphertext blob shape)

    Args:
        raw (bytes): The bytes to encode (e.g. RSA ciphertext)

    Returns:
        str: The Base64-encoded bytes
    """
    return base64.b64encode(raw).decode('ascii')


def decode_binary(blob: str) -> bytes:
    """
    Decodes a Base64-encoded binary blob back into raw bytes

    Args:
        blob (str): The Base64-encoded bytes

    Returns:
        bytes: The decoded raw bytes (e.g. RSA ciphertext for P6 to decrypt)

    Raises:
        binascii.Error: If 'blob' is not valid Base64
    """
    return base64.b64decode(blob, validate=True)
