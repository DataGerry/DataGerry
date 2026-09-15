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
Unit tests for SystemConfigReader, the process-wide config-file singleton

Everything that needs `etc/cmdb.conf` - the database updaters, the gunicorn bootstrap, the REST
init, the OpenCelium and ChatGPT connectors - reaches it through `SystemConfigReader()`. The class
is unusual in two ways, and both are pinned here:

* **`__new__` returns a `ConfigFileReader`, not a `SystemConfigReader`.** The wrapper class is
  therefore never instantiated and `__init__` never runs. That is what makes `__getattr__` /
  `__setattr__` unreachable in production
* **the cache ignores its arguments after the first call.** `SystemConfigReader('other.conf')` does
  NOT re-point the reader; the supported way to choose a config is to mutate `RUNNING_CONFIG_NAME` /
  `RUNNING_CONFIG_LOCATION` before the first call, which is what `cmdb.__main__` does

The two delegating dunders are exercised through an instance built with `object.__new__`, which
bypasses the override. They cannot run in production, and they are kept anyway: they are what tells
a reader - and pylint - that this class delegates. Removing them leaves the ~15 sites that read a
value through `SystemConfigReader()` reported as `no-member`.

`SystemConfigReader.instance` is a process-wide singleton the rest of the suite depends on, so every
test that touches it goes through `monkeypatch.setattr`, which restores it afterwards.
"""
from types import SimpleNamespace

import pytest

from cmdb.manager.system_manager.config_file_reader import ConfigFileReader
from cmdb.manager.system_manager.system_config_reader import SystemConfigReader
# -------------------------------------------------------------------------------------------------------------------- #

# `backing` is requested by tests that never read it: taking the fixture is what installs the stub in
# the singleton slot and restores the real reader afterwards, which is the point of requesting it
# pylint: disable=unused-argument

SECTION_VALUE: str = 'from-the-reader'


@pytest.fixture(name='backing')
def fixture_backing(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Puts a stub in the singleton slot and restores the real one afterwards."""
    stub = SimpleNamespace(existing=SECTION_VALUE)
    monkeypatch.setattr(SystemConfigReader, 'instance', stub)

    return stub


def _uninstantiated_wrapper() -> SystemConfigReader:
    """
    Builds the one thing production never has: an actual `SystemConfigReader` instance

    `object.__new__` bypasses the overridden `__new__`, which is the only way to reach the two
    delegating dunders at all.
    """
    return object.__new__(SystemConfigReader)


class TestTheSingleton:
    """`__new__` hands back the reader itself, and caches it for the life of the process."""

    def test_it_answers_a_config_file_reader(self, backing: SimpleNamespace) -> None:
        """The declared return type is honest: callers get the reader, not a wrapper around it."""
        assert SystemConfigReader() is backing

    def test_the_wrapper_class_is_never_instantiated(self, backing: SimpleNamespace) -> None:
        """This is what makes `__getattr__` / `__setattr__` unreachable in production."""
        assert not isinstance(SystemConfigReader(), SystemConfigReader)

    def test_later_calls_ignore_their_arguments(self, backing: SimpleNamespace) -> None:
        """
        The reader cannot be re-pointed once initialised

        Worth pinning because the signature suggests otherwise: passing a different config name looks
        like it would load that file, and it silently does not.
        """
        assert SystemConfigReader('some-other.conf', '/somewhere/else') is backing

    def test_the_first_call_constructs_and_caches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty slot is filled once; every later call reuses it."""
        built: list[tuple] = []

        class _StubReader:
            """Records the arguments it was constructed with."""
            def __init__(self, config_name, config_location) -> None:
                built.append((config_name, config_location))

        monkeypatch.setattr(SystemConfigReader, 'instance', None)
        monkeypatch.setattr(
            'cmdb.manager.system_manager.system_config_reader.ConfigFileReader', _StubReader,
        )

        first = SystemConfigReader('cmdb.conf', '/etc')
        second = SystemConfigReader()

        assert first is second
        assert built == [('cmdb.conf', '/etc')]

    def test_the_real_bootstrap_builds_a_config_file_reader(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Nothing stubbed: the class it caches is the one the whole codebase reads config through."""
        monkeypatch.setattr(SystemConfigReader, 'instance', None)

        assert isinstance(SystemConfigReader(None), ConfigFileReader)


class TestTheDelegatingDunders:
    """
    Unreachable in production, kept for what they document

    Reached here through `object.__new__`. They are the file's last two uncovered statements, and the
    reason they exist at all is that removing them makes pylint report `no-member` at every site that
    reads a value off a `SystemConfigReader()` result - the object is declared as this class, even
    though at runtime it is a `ConfigFileReader`.
    """

    def test_a_read_is_delegated_to_the_cached_reader(self, backing: SimpleNamespace) -> None:
        """`__getattr__` runs only for attributes the wrapper does not have itself."""
        assert _uninstantiated_wrapper().existing == SECTION_VALUE

    def test_a_read_of_an_unknown_attribute_still_raises(self, backing: SimpleNamespace) -> None:
        """Delegation must not turn a genuine typo into a silent None."""
        with pytest.raises(AttributeError):
            _ = _uninstantiated_wrapper().no_such_attribute

    def test_a_write_is_delegated_to_the_cached_reader(self, backing: SimpleNamespace) -> None:
        """`__setattr__` runs for every assignment, so nothing is ever stored on the wrapper."""
        wrapper = _uninstantiated_wrapper()
        wrapper.written = 'value'

        assert backing.written == 'value'

    def test_a_write_leaves_the_wrapper_itself_empty(self, backing: SimpleNamespace) -> None:
        """The wrapper holds no state of its own - that is the whole point of the delegation."""
        wrapper = _uninstantiated_wrapper()
        wrapper.written = 'value'

        assert not vars(wrapper)

    def test_a_write_is_readable_back_through_the_delegation(self, backing: SimpleNamespace) -> None:
        """Both halves against one instance: what was set through it is read back through it."""
        wrapper = _uninstantiated_wrapper()
        wrapper.round_tripped = 'value'

        assert wrapper.round_tripped == 'value'
