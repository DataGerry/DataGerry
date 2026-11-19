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

import { CmdbLog } from '../../../../models/cmdb-log';
import { LogMode } from '../../../../modes.enum';
/* ------------------------------------------------------------------------------------------------------------------ */

export interface TimelineEvent {
    log: CmdbLog;
    mode: LogMode;
    time: string;
    isoTime: string;
    changedFields: string[];
    active: boolean;
}

export interface TimelineSingleItem {
    id: string;
    type: 'single';
    event: TimelineEvent;
}

export interface TimelineActivationGroup {
    id: string;
    type: 'activation-group';
    userName: string;
    events: TimelineEvent[];
    nowActive: boolean;
    firstTime: string;
    lastTime: string;
}

export type TimelineItem = TimelineSingleItem | TimelineActivationGroup;

export interface TimelineDay {
    key: string;
    label: string;
    items: TimelineItem[];
}
