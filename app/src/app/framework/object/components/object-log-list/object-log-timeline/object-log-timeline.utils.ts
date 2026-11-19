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

import moment from 'moment';
import 'moment-timezone';

import { CmdbLog } from '../../../../models/cmdb-log';
import { LogMode } from '../../../../modes.enum';
import { TimelineDay, TimelineEvent } from './object-log-timeline.types';
/* ------------------------------------------------------------------------------------------------------------------ */

const DEFAULT_TIMEZONE = 'UTC';

/**
 * Groups logs (newest first) into days, and runs of activation changes by one user into one item.
 */
export function buildTimeline(logs: CmdbLog[], timezone: string | undefined, now: Date): TimelineDay[] {
    const zone = timezone || DEFAULT_TIMEZONE;
    const today = moment.tz(now, zone);
    const days: TimelineDay[] = [];

    for (const log of logs) {
        const logMoment = moment.tz(readLogTime(log), zone);
        const dayKey = logMoment.format('YYYY-MM-DD');
        let day = days[days.length - 1];

        if (!day || day.key !== dayKey) {
            day = { key: dayKey, label: dayLabel(logMoment, today), items: [] };
            days.push(day);
        }

        addToDay(day, toEvent(log, logMoment));
    }

    return days;
}

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

function addToDay(day: TimelineDay, event: TimelineEvent): void {
    const previous = day.items[day.items.length - 1];

    if (event.mode === LogMode.ACTIVE_CHANGE && previous) {
        if (previous.type === 'activation-group' && previous.events[0].log.user_id === event.log.user_id) {
            previous.events.push(event);
            previous.firstTime = event.time;
            return;
        }

        if (previous.type === 'single' && previous.event.mode === LogMode.ACTIVE_CHANGE
            && previous.event.log.user_id === event.log.user_id) {
            day.items[day.items.length - 1] = {
                id: `activation-${previous.event.log.public_id}`,
                type: 'activation-group',
                userName: previous.event.log.user_name,
                events: [previous.event, event],
                nowActive: previous.event.active,
                firstTime: event.time,
                lastTime: previous.event.time,
            };
            return;
        }
    }

    day.items.push({ id: `log-${event.log.public_id}`, type: 'single', event });
}

function toEvent(log: CmdbLog, logMoment: moment.Moment): TimelineEvent {
    return {
        log,
        mode: log.action,
        time: logMoment.format('HH:mm'),
        isoTime: logMoment.toISOString(),
        changedFields: log.action === LogMode.EDIT ? changedFieldNames(log.changes) : [],
        active: log.action === LogMode.ACTIVE_CHANGE && log.changes?.new === true,
    };
}

/** A changed value sits on both sides of the diff, so names are counted once. */
function changedFieldNames(changes: unknown): string[] {
    const diff = changes as { old?: unknown; new?: unknown } | null;
    const entries = [diff?.old, diff?.new]
        .filter((side): side is { name: string }[] => Array.isArray(side))
        .flat();

    return [...new Set(entries.map(entry => entry?.name).filter((name): name is string => !!name))];
}

/** The backend sends `{ $date: <ms> }` or a timestamp string. */
function readLogTime(log: CmdbLog): number | string {
    return log.log_time?.$date ?? log.log_time;
}

function dayLabel(logMoment: moment.Moment, today: moment.Moment): string {
    const date = logMoment.format('dddd, D MMMM YYYY');

    if (logMoment.isSame(today, 'day')) {
        return `Today · ${date}`;
    }

    if (logMoment.isSame(today.clone().subtract(1, 'day'), 'day')) {
        return `Yesterday · ${date}`;
    }

    return date;
}
