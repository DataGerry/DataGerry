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
REST route package for CmdbWebhooks and their CmdbWebhookEvents

Holds the two blueprints (``webhook_blueprint`` at ``/webhooks`` and the event blueprint, both
registered by ``init_rest_api``), the ACL rights and delivery constants in ``webhook_constants``, and
``webhook_helper`` - which both validates the route parameters and performs the outbound deliveries.
Nothing is re-exported here; consumers import from the module path, so the package declares no
``__all__``
"""
