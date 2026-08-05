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
import { Component, EventEmitter, Input, Output } from '@angular/core';

import { AutomationDefinition, AutomationOperation } from '../../../models/automation-definition.model';
import { AUTOMATION_OPERATION_CHOICES, findAdapter } from '../../../models/target-catalog.model';
import { SelectableTargetSystem } from '../../../services/target-catalog.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Step group 3 - which system the automation talks to and what it does there.
 *
 * Users pick a system and a functional action; which invoker operation implements that action is
 * resolved behind the scenes by the target catalog.
 */
@Component({
    selector: 'app-wizard-step-target',
    templateUrl: './wizard-step-target.component.html',
    styleUrls: ['./wizard-step-target.component.scss'],
    standalone: false
})
export class WizardStepTargetComponent {

    @Input() public definition!: AutomationDefinition;
    @Input() public targetSystems: SelectableTargetSystem[] = [];

    @Output() public definitionChange = new EventEmitter<AutomationDefinition>();

    /** Raised when the system or action changed, so the shell can recompute the mapping. */
    @Output() public targetChange = new EventEmitter<void>();

    public readonly operationChoices = AUTOMATION_OPERATION_CHOICES;

    /* ---------------------------------------------------- EVENTS ---------------------------------------------------- */

    public onSelectSystem(system: SelectableTargetSystem): void {
        this.definition.target = {
            ...this.definition.target,
            connectorId: system.connectorId,
            connectorTitle: system.title,
            invokerName: system.invokerName
        };

        // Keep the action only if the newly chosen system can actually perform it.
        if (!system.availableOperations.includes(this.definition.target.operation)) {
            this.definition.target.operation = system.availableOperations[0] ?? 'create';
        }

        this.definitionChange.emit(this.definition);
        this.targetChange.emit();
    }


    public onSelectOperation(operation: AutomationOperation): void {
        if (!this.isOperationAvailable(operation)) {
            return;
        }

        this.definition.target.operation = operation;
        this.definitionChange.emit(this.definition);
        this.targetChange.emit();
    }


    public onRemoteTypeChanged(value: string): void {
        this.definition.target.remoteObjectTypeId = (value ?? '').trim();
        this.definitionChange.emit(this.definition);
        this.targetChange.emit();
    }

    /* ---------------------------------------------------- GETTERS --------------------------------------------------- */

    public isSelected(system: SelectableTargetSystem): boolean {
        return this.definition.target.connectorId === system.connectorId;
    }


    public isOperationAvailable(operation: AutomationOperation): boolean {
        return this.selectedSystem?.availableOperations.includes(operation) ?? false;
    }


    public get selectedSystem(): SelectableTargetSystem | null {
        return this.targetSystems.find(system => this.isSelected(system)) ?? null;
    }


    /**
     * Label for the foreign system's object-type identifier, when the automation needs one.
     *
     * Only incoming automations read the foreign system, so only they must restrict what is read.
     */
    public get remoteTypeLabel(): string | null {
        if (this.definition.direction !== 'incoming' || !this.selectedSystem) {
            return null;
        }

        return findAdapter(this.selectedSystem.invokerName)?.remoteTypeLabel ?? null;
    }
}
