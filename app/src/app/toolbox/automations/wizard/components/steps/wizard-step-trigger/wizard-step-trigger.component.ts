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
import { Component, EventEmitter, inject, Input, Output } from '@angular/core';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { CronExpressionModalComponent } from '../../../../components/cron-expression-modal/cron-expression-modal.component';
import { AutomationDefinition, AutomationTriggerType } from '../../../models/automation-definition.model';
import { TriggerChoice, TRIGGER_CHOICES } from '../../../models/automation-wizard-step.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Step group 1 - when the automation runs.
 *
 * Covers the concept's first logical step plus the automation's name, which every later step
 * references in the summary.
 */
@Component({
    selector: 'app-wizard-step-trigger',
    templateUrl: './wizard-step-trigger.component.html',
    styleUrls: ['./wizard-step-trigger.component.scss'],
    standalone: false
})
export class WizardStepTriggerComponent {

    @Input() public definition!: AutomationDefinition;
    @Output() public definitionChange = new EventEmitter<AutomationDefinition>();

    private readonly modalService = inject(NgbModal);

    public readonly triggerChoices: ReadonlyArray<TriggerChoice> = TRIGGER_CHOICES;

    /* ---------------------------------------------------- EVENTS ---------------------------------------------------- */

    public onSelectTrigger(choice: TriggerChoice): void {
        if (!choice.available) {
            return;
        }

        this.definition.trigger.type = choice.type;

        // A cron expression only belongs to the scheduled trigger; drop a stale one.
        if (choice.type !== 'scheduled') {
            this.definition.trigger.cronExp = '';
        }

        this.emit();
    }


    public isSelected(type: AutomationTriggerType): boolean {
        return this.definition.trigger.type === type;
    }


    public onNameChanged(value: string): void {
        this.definition.name = value ?? '';
        this.emit();
    }


    public onDescriptionChanged(value: string): void {
        this.definition.description = value ?? '';
        this.emit();
    }


    /** Reuses the module's existing cron editor rather than adding a second one. */
    public openCronEditor(): void {
        const modalRef = this.modalService.open(CronExpressionModalComponent, { size: 'lg' });
        modalRef.componentInstance.currentCron = this.definition.trigger.cronExp;
        modalRef.componentInstance.automationName = this.definition.name;

        modalRef.result
            .then((cronExp: string) => {
                if (cronExp) {
                    this.definition.trigger.cronExp = cronExp;
                    this.emit();
                }
            })
            .catch(() => undefined);
    }


    private emit(): void {
        this.definitionChange.emit(this.definition);
    }
}
