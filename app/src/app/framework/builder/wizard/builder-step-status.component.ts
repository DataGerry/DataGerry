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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * One row of a builder wizard's validation card: the step name and whether that step is currently
 * valid. Shared by the type and relation wizards, which used to carry a copy each.
 */
@Component({
    selector: 'dg-builder-step-status',
    standalone: true,
    changeDetection: ChangeDetectionStrategy.OnPush,
    styles: [`
        span i {
            float: right;
            padding-top: 3px;
        }

        .step-valid i {
            color: #28a745;
        }

        .step-invalid i {
            color: #dc3545;
        }
    `],
    template: `{{ step }}:
        @if (status) {
            <span class="step-valid">
                <i class="far fa-check-circle" aria-hidden="true"></i>
                <span class="visually-hidden">valid</span>
            </span>
        } @else {
            <span class="step-invalid">
                <i class="fas fa-exclamation-circle" aria-hidden="true"></i>
                <span class="visually-hidden">invalid</span>
            </span>
        }
        <div class="clearfix"></div>
    `
})
export class BuilderStepStatusComponent {

    /** Name of the step. */
    @Input() public step: string = '';

    /** Validation status of the step. */
    @Input() public status: boolean = true;
}
