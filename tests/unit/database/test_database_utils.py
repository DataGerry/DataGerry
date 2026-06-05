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
Unit tests for cmdb.database.database_utils

Covers the BSON<->JSON codec (object_hook / default) and the retry_operation decorator. Pure tests:
no Mongo. The retry tests patch time.sleep and random.uniform so backoff is instant and
deterministic.
"""
import re
import uuid
import datetime
from typing import Any

import pytest
from bson.objectid import ObjectId
from bson.dbref import DBRef
from bson.min_key import MinKey
from bson.max_key import MaxKey
from bson.timestamp import Timestamp
from pymongo.errors import PyMongoError

from cmdb.database import database_utils
from cmdb.database.database_utils import object_hook, default, retry_operation, MAX_RETRIES
# -------------------------------------------------------------------------------------------------------------------- #
#                                                    object_hook                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_object_hook_oid() -> None:
    """A {$oid} dict decodes to the matching ObjectId"""
    oid = ObjectId()
    assert object_hook({"$oid": str(oid)}) == oid


def test_object_hook_ref() -> None:
    """A {$ref,$id} dict decodes to a DBRef"""
    result = object_hook({"$ref": "objects", "$id": 42})
    assert isinstance(result, DBRef)
    assert result.collection == "objects"
    assert result.id == 42


def test_object_hook_date_from_millis() -> None:
    """A numeric {$date} (ms since epoch) decodes to a UTC datetime"""
    result = object_hook({"$date": 1609459200000})
    assert (result.year, result.month, result.day) == (2021, 1, 1)


def test_object_hook_date_from_isoformat() -> None:
    """A string {$date} falls back to ISO-format parsing and yields a tz-aware datetime

    Note: the production fallback strips the trailing 'Z' and calls astimezone(utc) on a naive
    datetime, so the resulting wall-clock value is sensitive to the host timezone; only the type
    and tz-awareness are asserted here (the exact instant is intentionally not pinned).
    """
    result = object_hook({"$date": "2021-01-01T00:00:00Z"})
    assert isinstance(result, datetime.datetime)
    assert result.tzinfo is not None


def test_object_hook_regex_with_flags() -> None:
    """A {$regex,$options} dict compiles a pattern with the i/m flags applied"""
    result = object_hook({"$regex": "abc", "$options": "im"})
    assert result.pattern == "abc"
    assert result.flags & re.IGNORECASE
    assert result.flags & re.MULTILINE


def test_object_hook_min_and_max_key() -> None:
    """{$minKey}/{$maxKey} decode to MinKey/MaxKey"""
    assert isinstance(object_hook({"$minKey": 1}), MinKey)
    assert isinstance(object_hook({"$maxKey": 1}), MaxKey)


def test_object_hook_uuid() -> None:
    """A {$uuid} dict decodes to a UUID"""
    value = uuid.uuid4()
    assert object_hook({"$uuid": value.hex}) == value


def test_object_hook_passthrough_for_plain_dict() -> None:
    """A dict without a special marker key is returned unchanged"""
    plain = {"name": "demo", "value": 1}
    assert object_hook(plain) is plain

# -------------------------------------------------------------------------------------------------------------------- #
#                                                      default                                                         #
# -------------------------------------------------------------------------------------------------------------------- #

def test_default_objectid() -> None:
    """An ObjectId encodes to {$oid}"""
    oid = ObjectId()
    assert default(oid) == {"$oid": str(oid)}


def test_default_bytes_decoded() -> None:
    """bytes encode to their utf-8 string"""
    assert default(b"hello") == "hello"


def test_default_datetime_to_millis() -> None:
    """A datetime encodes to {$date: <ms since epoch>}"""
    assert default(datetime.datetime(2021, 1, 1, 0, 0, 0)) == {"$date": 1609459200000}


def test_default_regex() -> None:
    """A compiled pattern encodes to {$regex,$options}"""
    assert default(re.compile("abc", re.IGNORECASE | re.MULTILINE)) == {"$regex": "abc", "$options": "im"}


def test_default_min_and_max_key() -> None:
    """MinKey/MaxKey encode to their marker dicts"""
    assert default(MinKey()) == {"$minKey": 1}
    assert default(MaxKey()) == {"$maxKey": 1}


def test_default_timestamp() -> None:
    """A bson Timestamp encodes to {t,i}"""
    assert default(Timestamp(123, 4)) == {"t": 123, "i": 4}


def test_default_uuid() -> None:
    """A UUID encodes to {$uuid: hex}"""
    value = uuid.uuid4()
    assert default(value) == {"$uuid": value.hex}


def test_default_dict_passthrough() -> None:
    """A plain dict is returned as-is"""
    payload = {"a": 1}
    assert default(payload) is payload


def test_default_object_falls_back_to_dunder_dict() -> None:
    """An arbitrary object falls back to its __dict__"""
    class _Carrier:
        def __init__(self) -> None:
            self.x = 1
            self.y = "z"

    assert default(_Carrier()) == {"x": 1, "y": "z"}


def test_default_raises_type_error_when_not_serializable() -> None:
    """An object with neither a known type nor a __dict__ raises TypeError"""
    class _NoDict:
        __slots__ = ()

    with pytest.raises(TypeError):
        default(_NoDict())


@pytest.mark.parametrize('value', [ObjectId(), uuid.uuid4(), MinKey(), MaxKey()])
def test_codec_round_trip(value: Any) -> None:
    """default() output decodes back to the original value via object_hook()"""
    assert object_hook(default(value)) == value

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  retry_operation                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

class _Recorder:
    """A subject whose decorated op() counts calls and fails on demand"""

    def __init__(self, fail_times: int = 0, always: Exception | None = None) -> None:
        self.calls = 0
        self.fail_times = fail_times
        self.always = always

    @retry_operation
    def op(self) -> str:
        """Returns 'ok' unless configured to fail"""
        self.calls += 1

        if self.always is not None:
            raise self.always

        if self.calls <= self.fail_times:
            raise PyMongoError("transient")

        return "ok"


@pytest.fixture(autouse=True)
def _instant_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the retry backoff instant and deterministic"""
    monkeypatch.setattr(database_utils.time, 'sleep', lambda *_args: None)
    monkeypatch.setattr(database_utils.random, 'uniform', lambda *_args: 0.0)


def test_retry_operation_returns_on_success() -> None:
    """A succeeding operation runs once and returns its value"""
    recorder = _Recorder()
    assert recorder.op() == "ok"
    assert recorder.calls == 1


def test_retry_operation_retries_then_succeeds() -> None:
    """A transient PyMongoError is retried until the operation succeeds"""
    recorder = _Recorder(fail_times=2)
    assert recorder.op() == "ok"
    assert recorder.calls == 3


def test_retry_operation_reraises_after_max_retries() -> None:
    """A persistent PyMongoError is re-raised after MAX_RETRIES attempts"""
    recorder = _Recorder(always=PyMongoError("boom"))
    with pytest.raises(PyMongoError):
        recorder.op()
    assert recorder.calls == MAX_RETRIES
