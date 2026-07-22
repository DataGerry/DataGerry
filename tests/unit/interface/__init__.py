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
Unit tests for the cmdb.interface package

Pure tests for the HTTP transport layer: route handlers, blueprints, and Flask wiring. Tests
exercise the bare route functions through Flask test-request contexts, with the orchestrator
layer patched out so each test verifies only the route's own responsibilities (query-param
parsing, input sanitisation, response shaping). No Mongo, no real auth
"""
