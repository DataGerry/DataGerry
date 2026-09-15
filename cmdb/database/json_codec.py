# DataGerry - OpenSource Enterprise CMDB
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
The JSON <-> BSON codec of DataGerry's wire format

Two functions, used in opposite directions:

* ``default`` is the ``json.dumps`` hook for **every REST response** (see
  ``interface/rest_api/responses/base_api_response.py``), the JSON exporter, the object importer and
  the webhook payloads. It turns the BSON values a document carries into the extended-JSON shapes the
  frontend models declare - most importantly a datetime into ``{'$date': <epoch millis>}``
* ``object_hook`` is the ``json.loads`` hook of the BSON round-trip the object and type managers run
  before a write (``json.dumps(doc, default=json_util.default)`` ->
  ``json.loads(..., object_hook=object_hook)``). Its input is therefore **pymongo's** extended JSON,
  not a client payload - which is why it has to cope with both the relaxed spelling
  (``{'$date': '2026-09-09T10:00:00Z'}``) and the canonical one
  (``{'$date': {'$numberLong': '-315619200000'}}``, used for dates outside the relaxed range)

**Timezones are the one thing to get right here.** The MongoDB driver is not created with
``tz_aware``, so every datetime it hands back is naive UTC - and that is what ``default`` assumes when
it encodes one. On the way back a naive timestamp is therefore read as UTC too, never as the host's
local time: reading it as local time made every round-tripped date drift by the server's UTC offset,
which is invisible on a UTC host and two hours wrong in Berlin. The decoding itself is delegated to
``cmdb.utils.coerce_mongo_datetime``, the one implementation of that wire format

An object that is none of the known BSON types is serialised through its own zero-argument
``to_json()`` when it has one, and through its ``__dict__`` otherwise. The models' ``to_json`` is a
classmethod taking the instance, so it is deliberately NOT called here - only an instance method is
"""
import calendar
import datetime
import inspect
import re
import uuid
from logging import Logger, getLogger
from typing import Any, Callable

from bson.dbref import DBRef
from bson.max_key import MaxKey
from bson.min_key import MinKey
from bson.objectid import ObjectId
from bson.timestamp import Timestamp

from cmdb.utils import BaseStrEnum, MONGO_DATE_KEY, coerce_mongo_datetime
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'MongoJsonKey',
    'default',
    'object_hook',
]

LOGGER: Logger = getLogger(__name__)


class MongoJsonKey(BaseStrEnum):
    """
    The extended-JSON keys this codec reads and writes

    MongoDB's own vocabulary, not DataGerry's - the names come from the extended-JSON specification
    that ``bson.json_util`` implements. DATE is the same string ``cmdb.utils`` names, because the
    frontend's ``{'$date': …}`` wrapper and pymongo's are the same shape
    """
    OID = '$oid'
    REF = '$ref'
    ID = '$id'
    DB = '$db'
    DATE = MONGO_DATE_KEY
    NUMBER_LONG = '$numberLong'
    REGEX = '$regex'
    OPTIONS = '$options'
    MIN_KEY = '$minKey'
    MAX_KEY = '$maxKey'
    UUID = '$uuid'
    TIMESTAMP_TIME = 't'
    TIMESTAMP_INCREMENT = 'i'


# The regex option flags this codec understands, in both directions. MongoDB knows more ('x', 's',
# 'u'), and a flag that is not listed here is dropped rather than guessed at
REGEX_FLAG_BY_OPTION: dict[str, int] = {
    'i': re.IGNORECASE,
    'm': re.MULTILINE,
}

_MILLISECONDS_PER_SECOND: int = 1000

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     json -> bson                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def _decode_date(wrapper: dict[str, Any]) -> datetime.datetime | None:
    """
    Reads a ``{'$date': …}`` wrapper as a UTC-aware datetime

    Three spellings reach this: epoch milliseconds (what the frontend sends and what ``default``
    writes), an ISO-8601 string (pymongo's relaxed extended JSON) and a nested
    ``{'$numberLong': '<millis>'}`` (its canonical spelling, used for dates outside the relaxed
    range - a date before 1970 arrives this way). The value itself is decoded by
    ``coerce_mongo_datetime``, so this codec and the request-side coercion cannot disagree

    Args:
        wrapper (dict[str, Any]): A dict carrying the DATE key

    Returns:
        datetime.datetime | None: The timestamp as a UTC-aware datetime, or None when the wrapper
                                  does not carry a usable one
    """
    wrapped: Any = wrapper[MongoJsonKey.DATE.value]

    if isinstance(wrapped, dict) and MongoJsonKey.NUMBER_LONG.value in wrapped:
        wrapped = wrapped[MongoJsonKey.NUMBER_LONG.value]

        try:
            wrapped = int(wrapped)
        except (TypeError, ValueError):
            return None

    decoded: datetime.datetime | None = coerce_mongo_datetime({MongoJsonKey.DATE.value: wrapped})

    if decoded is None:
        return None

    # A timestamp without a zone is UTC: that is what the driver stores and what 'default' writes.
    # Reading it as the host's local time is what used to shift every round-tripped date
    if decoded.tzinfo is None:
        return decoded.replace(tzinfo=datetime.timezone.utc)

    return decoded.astimezone(datetime.timezone.utc)


def _decode_regex_flags(options: Any) -> int:
    """
    Translates a ``$options`` string into ``re`` flags

    ``$options`` is optional in MongoDB, so a missing or non-string value means "no flags" rather
    than an error

    Args:
        options (Any): The raw ``$options`` value

    Returns:
        int: The combined `re` flags
    """
    if not isinstance(options, str):
        return 0

    flags: int = 0

    for option, flag in REGEX_FLAG_BY_OPTION.items():
        if option in options:
            flags |= flag

    return flags


def object_hook(dct: dict[str, Any]) -> Any:
    """
    Converts one extended-JSON document into its BSON / Python value

    The ``json.loads`` hook of the BSON round-trip the object and type managers run before a write.
    A dict that carries none of the extended-JSON keys - or carries one it cannot decode - is passed
    through unchanged, which is what keeps a drifted document loadable instead of failing a write

    Args:
        dct (dict[str, Any]): One decoded JSON object

    Raises:
        bson.errors.InvalidId: When a ``$oid`` value is not a valid ObjectId
        ValueError: When a ``$uuid`` value is not a valid UUID
        re.error: When a ``$regex`` pattern does not compile

    Returns:
        Any: The BSON value the document describes, or the document itself
    """
    if MongoJsonKey.OID.value in dct:
        return ObjectId(str(dct[MongoJsonKey.OID.value]))

    if MongoJsonKey.REF.value in dct:
        if MongoJsonKey.ID.value not in dct:
            # A DBRef without an id is not a reference; report it and keep the document readable
            LOGGER.warning("[object_hook] '%s' without '%s' - kept as a plain document",
                           MongoJsonKey.REF.value, MongoJsonKey.ID.value)

            return dct

        return DBRef(dct[MongoJsonKey.REF.value],
                     dct[MongoJsonKey.ID.value],
                     dct.get(MongoJsonKey.DB.value))

    if MongoJsonKey.DATE.value in dct:
        decoded: datetime.datetime | None = _decode_date(dct)

        if decoded is None:
            LOGGER.warning("[object_hook] Unusable '%s' value: %r", MongoJsonKey.DATE.value,
                           dct[MongoJsonKey.DATE.value])

            return dct

        return decoded

    if MongoJsonKey.REGEX.value in dct:
        return re.compile(dct[MongoJsonKey.REGEX.value],
                          _decode_regex_flags(dct.get(MongoJsonKey.OPTIONS.value)))

    if MongoJsonKey.MIN_KEY.value in dct:
        return MinKey()

    if MongoJsonKey.MAX_KEY.value in dct:
        return MaxKey()

    if MongoJsonKey.UUID.value in dct:
        return uuid.UUID(dct[MongoJsonKey.UUID.value])

    return dct

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     bson -> json                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def _encode_datetime(value: datetime.datetime) -> dict[str, int]:
    """
    Encodes a datetime as ``{'$date': <epoch millis>}``

    An aware value is shifted to UTC first; a naive one is already UTC, because the driver is not
    created with ``tz_aware``. Sub-millisecond precision is dropped, which is the resolution MongoDB
    stores

    Args:
        value (datetime.datetime): The timestamp to encode

    Returns:
        dict[str, int]: The extended-JSON wrapper the frontend models declare
    """
    if value.utcoffset() is not None:
        value = value - value.utcoffset()

    millis: int = int(
        calendar.timegm(value.timetuple()) * _MILLISECONDS_PER_SECOND
        + value.microsecond / _MILLISECONDS_PER_SECOND
    )

    return {MongoJsonKey.DATE.value: millis}


def _encode_regex(value: re.Pattern) -> dict[str, str]:
    """
    Encodes a compiled pattern as ``{'$regex': …, '$options': …}``

    Only the flags `object_hook` can read back are reported, so the pair round-trips

    Args:
        value (re.Pattern): The compiled pattern

    Returns:
        dict[str, str]: The extended-JSON wrapper
    """
    options: str = ''.join(
        option for option, flag in REGEX_FLAG_BY_OPTION.items() if value.flags & flag
    )

    return {MongoJsonKey.REGEX.value: value.pattern, MongoJsonKey.OPTIONS.value: options}


# The encoder of each BSON type, checked in order. A datetime is listed before the plain types
# because it is the one that carries a timezone decision; the rest are unambiguous
_ENCODERS: tuple[tuple[type | tuple[type, ...], Callable[[Any], Any]], ...] = (
    (bytes, lambda value: value.decode('utf-8')),
    (ObjectId, lambda value: {MongoJsonKey.OID.value: str(value)}),
    (DBRef, lambda value: value.as_doc()),
    (datetime.datetime, _encode_datetime),
    (re.Pattern, _encode_regex),
    (MinKey, lambda _value: {MongoJsonKey.MIN_KEY.value: 1}),
    (MaxKey, lambda _value: {MongoJsonKey.MAX_KEY.value: 1}),
    (Timestamp, lambda value: {MongoJsonKey.TIMESTAMP_TIME.value: value.time,
                               MongoJsonKey.TIMESTAMP_INCREMENT.value: value.inc}),
    (uuid.UUID, lambda value: {MongoJsonKey.UUID.value: value.hex}),
)


def _instance_to_json(obj: Any) -> Callable[[], Any] | None:
    """
    Answers with the object's own ``to_json()`` when it is an instance method

    The models spell ``to_json`` as a **classmethod taking the instance**
    (``CmdbObject.to_json(instance)``), so calling ``obj.to_json()`` on one would fail with a missing
    argument. Only a plain instance method is used - which today is `RenderResult`, `SearchResult`
    and `SearchResultMap`, the three objects a response hands to this encoder

    Args:
        obj (Any): The object about to be serialised

    Returns:
        Callable[[], Any] | None: The bound method, or None when the object has no usable one
    """
    attribute: Any = inspect.getattr_static(type(obj), 'to_json', None)

    if not inspect.isfunction(attribute):
        return None

    return getattr(obj, 'to_json')


def default(obj: Any) -> Any:
    """
    Converts one BSON / Python value into its JSON representation

    The ``json.dumps`` hook behind every REST response. ``json.dumps`` calls it only for values it
    cannot serialise itself, so dicts, lists, strings and numbers never arrive here

    Args:
        obj (Any): The value to serialise

    Raises:
        TypeError: When the value is neither a known BSON type nor serialisable through its own
                   ``to_json()`` or ``__dict__``

    Returns:
        Any: A JSON-serialisable representation of the value
    """
    for types, encoder in _ENCODERS:
        if isinstance(obj, types):
            return encoder(obj)

    to_json: Callable[[], Any] | None = _instance_to_json(obj)

    if to_json is not None:
        return to_json()

    try:
        # The last resort, and the reason a class that must cross the wire should declare to_json:
        # an attribute dump publishes whatever the instance happens to carry
        LOGGER.debug("[default] Serialising %s through its __dict__", type(obj))

        return obj.__dict__
    except Exception as err:
        raise TypeError(f"{obj} not JSON serializable - Type: {type(obj)}. Error: {err}") from err
