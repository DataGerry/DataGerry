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
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

import { AutomationDefinition } from '../../models/automation-definition.model';
import { TRIGGER_CHOICES } from '../../models/automation-wizard-step.model';
import { AUTOMATION_OPERATION_CHOICES } from '../../models/target-catalog.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Running summary of the choices made so far, shown beside the steps as the mockup does.
 *
 * Purely presentational, so it can stay OnPush - the wizard replaces the definition object on every
 * change rather than mutating it in place at this level.
 */
@Component({
    selector: 'app-automation-summary-panel',
    templateUrl: './automation-summary-panel.component.html',
    styleUrls: ['./automation-summary-panel.component.scss'],
    standalone: false,
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class AutomationSummaryPanelComponent {

    @Input() public definition!: AutomationDefinition;
    @Input() public readableDescription = '';

    /* --------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public get triggerTitle(): string {
        return TRIGGER_CHOICES.find(choice => choice.type === this.definition.trigger.type)?.title ?? '-';
    }


    public get triggerIcon(): string {
        return TRIGGER_CHOICES.find(choice => choice.type === this.definition.trigger.type)?.icon ?? 'fas fa-bolt';
    }


    public get operationLabel(): string {
        return AUTOMATION_OPERATION_CHOICES
            .find(choice => choice.value === this.definition.target.operation)?.label ?? '-';
    }


    public get directionLabel(): string {
        return this.definition.direction === 'outgoing'
            ? 'DataGerry to target system'
            : 'Target system to DataGerry';
    }


    public get mappedCount(): number {
        return this.definition.mapping.filter(entry => !!entry.target).length;
    }
}
