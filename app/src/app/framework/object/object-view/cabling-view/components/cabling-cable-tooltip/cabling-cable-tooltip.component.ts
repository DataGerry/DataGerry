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
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { CABLING_TOOLTIP } from '../../constants/cabling.constants';
import { CablingCableTooltip, CablingTooltipPlacement } from '../../models/cabling-tooltip.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** The hovered cable's details, pointing at the spot under the pointer. Screen readers use the cable list. */
@Component({
    selector: 'cmdb-cabling-cable-tooltip',
    standalone: true,
    templateUrl: './cabling-cable-tooltip.component.html',
    styleUrls: ['./cabling-cable-tooltip.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: {
        'class': 'cabling-cable-tooltip',
        'aria-hidden': 'true',
        '[class.is-below]': 'placement().below',
        '[style.transform]': 'transform()',
        '[style.--cable-stroke]': 'tooltip().stroke'
    }
})
export class CablingCableTooltipComponent {

    public readonly tooltip = input.required<CablingCableTooltip>();
    public readonly placement = input.required<CablingTooltipPlacement>();
    public readonly selected = input(false);

    protected readonly width = CABLING_TOOLTIP.width;
    protected readonly gap = CABLING_TOOLTIP.gap;

    protected readonly transform = computed(() => `translate3d(${ this.placement().x }px, ${ this.placement().y }px, 0)`);
    protected readonly arrow = computed(() => `${ this.placement().arrow }px`);
}
