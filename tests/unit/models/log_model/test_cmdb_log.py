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
Unit tests for cmdb.models.log_model.cmdb_log

The factory picks the log class, and everything interesting about it is what happens when the stored
`log_type` cannot be resolved: it falls back to CmdbObjectLog rather than raising, because one corrupt
row must not take down a whole log list. The three ways a value can be unusable - absent, unregistered,
unhashable - are asserted separately, since they arrive from different failures (a write path that
forgot the key, a type removed from the registry, a hand-edited or half-migrated document).

The registry is class-level state shared by the whole process, so every test that registers a type
restores it afterwards.
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.models.log_model.cmdb_log import CmdbLog
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.errors.cmdb_object import RequiredInitKeyNotFoundError
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 4711
OBJECT_ID: int = 12
USER_ID: int = 1

CUSTOM_LOG_TYPE: str = 'CustomTestLog'


class _CustomLog(CmdbObjectLog):
    """A second registered log type, to prove the registry is consulted rather than assumed"""


@pytest.fixture(name='clean_registry', autouse=True)
def fixture_clean_registry():
    """Restores the process-wide registry, which framework.constants populates at import time."""
    original: dict[Any, Any] = dict(CmdbLog.REGISTERED_LOG_TYPE)

    yield CmdbLog.REGISTERED_LOG_TYPE

    CmdbLog.REGISTERED_LOG_TYPE.clear()
    CmdbLog.REGISTERED_LOG_TYPE.update(original)


def _log_data(**overrides: Any) -> dict[str, Any]:
    """The keyword payload LogsManager.insert_log builds, minus whatever a test drops."""
    data: dict[str, Any] = {
        'public_id': PUBLIC_ID,
        'log_type': CmdbObjectLog.__name__,
        'log_time': datetime(2026, 9, 11, tzinfo=timezone.utc),
        'action': 'CREATE',
        'action_name': 'CREATE',
        'object_id': OBJECT_ID,
        'version': '1.0.0',
        'user_id': USER_ID,
        'user_name': 'admin',
        'render_state': None,
        'changes': [],
        'comment': None,
    }
    data.update(overrides)

    return data


# -------------------------------------------------------------------------------------------------------------------- #
class TestTheRegistry:
    """register_log_type is the only way a type reaches the factory."""

    def test_a_registered_type_is_used(self) -> None:
        """The ordinary case, and the one framework.constants performs at import time"""
        CmdbLog.register_log_type(CUSTOM_LOG_TYPE, _CustomLog)

        assert isinstance(CmdbLog(**_log_data(log_type=CUSTOM_LOG_TYPE)), _CustomLog)

    def test_registering_twice_replaces_the_entry(self) -> None:
        """A later registration wins, so a plugin can override a built-in type"""
        CmdbLog.register_log_type(CUSTOM_LOG_TYPE, _CustomLog)
        CmdbLog.register_log_type(CUSTOM_LOG_TYPE, CmdbObjectLog)

        assert CmdbLog.REGISTERED_LOG_TYPE[CUSTOM_LOG_TYPE] is CmdbObjectLog


class TestTheFallback:
    """
    Every way a stored log_type can be unusable answers with DEFAULT_LOG_TYPE

    Falling back rather than raising is what keeps one corrupt document from failing the whole log
    list; the three cases are separate because they come from different failures.
    """

    def test_an_unregistered_type_falls_back(self) -> None:
        """A type removed from the registry, or written by a version that had one more"""
        instance = CmdbLog(**_log_data(log_type='NoSuchLogType'))

        assert isinstance(instance, CmdbObjectLog)

    def test_a_missing_log_type_is_refused_by_the_log_class_not_the_lookup(self) -> None:
        """
        A payload with no log_type at all gets past the FACTORY and is refused by the log class

        The lookup falls back to the default rather than raising KeyError, and the refusal then comes
        from the constructor, which has no default for `log_type`. The distinction is the point: the
        caller sees a missing-argument error naming the field, not a bare KeyError out of a registry
        lookup they know nothing about.
        """
        data = _log_data()
        data.pop('log_type')

        with pytest.raises(TypeError) as raised:
            CmdbLog(**data)

        assert 'log_type' in str(raised.value)

    def test_a_none_log_type_falls_back(self) -> None:
        """None is hashable, so this is an ordinary registry miss rather than a type error"""
        assert isinstance(CmdbLog(**_log_data(log_type=None)), CmdbObjectLog)

    @pytest.mark.parametrize('unhashable', [['a', 'list'], {'a': 'dict'}, {'a', 'set'}], ids=str)
    def test_an_unhashable_log_type_falls_back(self, unhashable: Any) -> None:
        """
        The case the old `(KeyError, ValueError)` tuple missed

        A dict lookup with an unhashable key raises TypeError, not KeyError - so a hand-edited or
        half-migrated row carrying a list where a name belongs would escape the factory and surface
        as a 500 on the log list instead of reading as an ordinary object log.
        """
        assert isinstance(CmdbLog(**_log_data(log_type=unhashable)), CmdbObjectLog)


class TestTheInstance:
    """What the factory hands back is a fully built log, not a CmdbLog."""

    def test_the_payload_reaches_the_constructor(self) -> None:
        """The kwargs are forwarded, so the instance carries what the manager assembled"""
        instance = CmdbLog(**_log_data())

        assert (instance.public_id, instance.object_id, instance.user_id) == (PUBLIC_ID, OBJECT_ID, USER_ID)

    def test_the_factory_never_returns_itself(self) -> None:
        """__new__ returns the chosen class's instance, so no CmdbLog ever exists"""
        assert not isinstance(CmdbLog(**_log_data()), CmdbLog)

    def test_a_positional_call_is_refused_by_the_dao_not_by_the_lookup(self) -> None:
        """
        Positional construction cannot work here, and the refusal now comes from the right place

        `__new__` must not forward its positional arguments into the class LOOKUP, which declares none,
        so a positional call raised `TypeError: __get_log_class() takes 1 positional argument` before
        any log class was reached. It now reaches CmdbDAO.__new__, which validates REQUIRED_INIT_KEYS
        against the KEYWORD arguments alone and names the key that is missing - the answer a caller can
        act on.
        """
        data = _log_data()
        public_id = data.pop('public_id')

        with pytest.raises(RequiredInitKeyNotFoundError) as raised:
            CmdbLog(public_id, **data)

        assert 'public_id' in str(raised.value)
