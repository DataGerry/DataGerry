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
import { Subscription } from 'rxjs';

import { ValidationService } from '../services/validation.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * The canvas states that stop a wizard from moving on or saving: an unresolved section or field
 * highlight, the latched duplicate-identifier lock, and a section left without fields.
 *
 * Owned by the wizard component so the subscriptions die with it. Each flag is written from a
 * timeout because the canvas pushes these mid change detection, which would otherwise raise
 * ExpressionChangedAfterItHasBeenCheckedError on the buttons bound to them.
 */
export class BuilderWizardBlockingState {

    public isSectionHighlighted: boolean = false;
    public isFieldHighlighted: boolean = false;
    public disableFields: boolean = false;
    public isSectionWithoutFields: boolean = false;

    private readonly subscriptions = new Subscription();

    constructor(validationService: ValidationService) {
        this.subscriptions.add(validationService.isSectionHighlighted$.subscribe((highlighted) => {
            setTimeout(() => this.isSectionHighlighted = highlighted);
        }));

        this.subscriptions.add(validationService.isFieldHighlighted$.subscribe((highlighted) => {
            setTimeout(() => this.isFieldHighlighted = highlighted);
        }));

        this.subscriptions.add(validationService.disableFields$.subscribe((disableFields) => {
            setTimeout(() => this.disableFields = disableFields);
        }));

        this.subscriptions.add(validationService.isSectionWithoutField$.subscribe((withoutFields) => {
            setTimeout(() => this.isSectionWithoutFields = withoutFields);
        }));
    }

    /** True while the canvas is in a state the wizard must not leave or save from. */
    public get blocked(): boolean {
        return this.isSectionHighlighted
            || this.isFieldHighlighted
            || this.disableFields
            || !this.isSectionWithoutFields;
    }

    public destroy(): void {
        this.subscriptions.unsubscribe();
    }
}
