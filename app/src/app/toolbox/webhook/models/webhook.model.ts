/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2026 becon GmbH
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU Affero General Public License as
* published by the Free Software Foundation, either version 3 of the
* License, or (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU Affero General Public License for more details.
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
export interface Webhook {
    public_id: number;
    name: string;
    url: string;
    event_types: string[];
    active: boolean;
    /** Set by the server to the user who last saved the webhook; null when it has no owner. */
    owner_id: number | null;
}

export type WebhookOwnerStatus = 'none' | 'active' | 'inactive' | 'deleted' | 'unresolved';

export interface WebhookOwner {
    status: WebhookOwnerStatus;
    label: string;
}

export interface WebhookRow extends Webhook {
    owner: WebhookOwner;
}

export interface WebhookCreate {
    name: string;
    url: string;
    event_types: string[];
    active: boolean;
}

export interface WebhookUpdate extends WebhookCreate {
    public_id: number;
}
