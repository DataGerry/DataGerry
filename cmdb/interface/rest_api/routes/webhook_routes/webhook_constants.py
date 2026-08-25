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
Shared constants for the CmdbWebhook and CmdbWebhookEvent REST routes
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'WebhookRight',
]


class WebhookRight(BaseStrEnum):
    """
    ACL right identifiers guarding the CmdbWebhook and CmdbWebhookEvent REST routes

    The four rights come from ``WebhookRight`` in cmdb.models.right_model.framework_rights, which puts
    them under ``base.framework.webhook``. There is no separate right for a CmdbWebhookEvent: an event
    is the delivery log of a webhook, so reading one needs VIEW and deleting one needs DELETE - the
    same rights that guard the webhook it belongs to
    """
    ADD = 'base.framework.webhook.add'
    VIEW = 'base.framework.webhook.view'
    EDIT = 'base.framework.webhook.edit'
    DELETE = 'base.framework.webhook.delete'
