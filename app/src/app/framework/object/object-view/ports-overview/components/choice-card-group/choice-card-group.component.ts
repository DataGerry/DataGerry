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
import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
/* ------------------------------------------------------------------------------------------------------------------ */

/** One card of the group. `value` is what the host stores for the choice. */
export interface ChoiceCard<T> {
    value: T;
    icon: string;
    label: string;
    text: string;
}


/**
 * A single choice out of a handful, drawn as cards.
 *
 * Native radios carry the state, so the group is reachable with the keyboard and reads as one to a
 * screen reader; the card is only their label.
 */
@Component({
    selector: 'cmdb-choice-card-group',
    templateUrl: './choice-card-group.component.html',
    styleUrls: ['./choice-card-group.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: true
})
export class ChoiceCardGroupComponent<T> {

    public readonly choices = input<readonly ChoiceCard<T>[]>([]);
    public readonly selected = input<T | null>(null);

    /** Groups the radios of one instance; two groups on the same page must not share a name. */
    public readonly name = input.required<string>();

    /** What the group as a whole is asking for, for a screen reader. */
    public readonly groupLabel = input('');

    public readonly choiceSelected = output<T>();
}
