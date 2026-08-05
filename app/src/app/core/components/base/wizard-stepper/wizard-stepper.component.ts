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
import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
/* ------------------------------------------------------------------------------------------------------------------ */

/** A single step descriptor rendered by the stepper. */
export interface WizardStep {
    title: string;
    icon: string;

    /** Optional one-line explanation shown under the title. */
    subtitle?: string;
}

/** Compact stepper showing completed / active / upcoming states. */
@Component({
    selector: 'cmdb-wizard-stepper',
    templateUrl: './wizard-stepper.component.html',
    styleUrls: ['./wizard-stepper.component.scss'],
    standalone: false,
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class WizardStepperComponent {
    @Input() public steps: WizardStep[] = [];
    @Input() public current = 0;

    /**
     * Furthest step the user may jump to.
     *
     * Defaults to `current` so the original behaviour - review what you have seen, do not skip
     * ahead - is unchanged for callers that do not set it.
     */
    @Input() public reachable: number | null = null;

    /**
     * Layout direction. Vertical suits a sidebar, horizontal a band above the content.
     *
     * Both collapse to the compact horizontal form on small screens.
     */
    @Input() public orientation: 'vertical' | 'horizontal' = 'vertical';

    @Output() public stepSelected = new EventEmitter<number>();

    /* --------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public isCompleted(index: number): boolean {
        return index < this.current;
    }


    public isActive(index: number): boolean {
        return index === this.current;
    }


    public isReachable(index: number): boolean {
        return index <= (this.reachable ?? this.current);
    }


    /** Only reachable steps are navigable, so users can review but not skip ahead. */
    public onSelect(index: number): void {
        if (this.isReachable(index)) {
            this.stepSelected.emit(index);
        }
    }
}
