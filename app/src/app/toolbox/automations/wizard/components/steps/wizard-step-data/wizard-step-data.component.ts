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

import { CmdbType } from 'src/app/framework/models/cmdb-type';

import { AutomationDefinition, AutomationDirection, AutomationField } from '../../../models/automation-definition.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Step group 2 - which data the automation works on.
 *
 * Covers the concept's "object selection" and "field selection" steps, preceded by the direction:
 * whether DataGerry is the source or the destination decides what everything after this means. Only
 * DataGerry object types and fields appear here - no API structures.
 */
@Component({
    selector: 'app-wizard-step-data',
    templateUrl: './wizard-step-data.component.html',
    styleUrls: ['./wizard-step-data.component.scss'],
    standalone: false
})
export class WizardStepDataComponent {

    @Input() public definition!: AutomationDefinition;
    @Input() public objectTypes: CmdbType[] = [];
    @Input() public availableFields: AutomationField[] = [];

    @Output() public definitionChange = new EventEmitter<AutomationDefinition>();
    @Output() public objectTypeChange = new EventEmitter<number | null>();

    /** Filter text of the available-fields list. */
    public fieldFilter = '';

    public readonly directions: ReadonlyArray<{ value: AutomationDirection; title: string; description: string; icon: string }> = [
        {
            value: 'outgoing',
            title: 'DataGerry to target system',
            description: 'Objects from DataGerry are written to another system.',
            icon: 'fas fa-arrow-right-from-bracket'
        },
        {
            value: 'incoming',
            title: 'Target system to DataGerry',
            description: 'Objects from another system are written into DataGerry.',
            icon: 'fas fa-arrow-right-to-bracket'
        }
    ];

    /* ---------------------------------------------------- EVENTS ---------------------------------------------------- */

    public onSelectDirection(direction: AutomationDirection): void {
        if (this.definition.direction === direction) {
            return;
        }

        this.definition.direction = direction;
        // The mapping sides swap with the direction, so previous pairs no longer apply.
        this.definition.mapping = [];
        this.emit();
    }


    public onSelectObjectType(typeId: number | null): void {
        this.objectTypeChange.emit(typeId);
    }


    public isFieldSelected(field: AutomationField): boolean {
        return this.definition.fields.some(selected => selected.name === field.name);
    }


    public onToggleField(field: AutomationField): void {
        if (this.isFieldSelected(field)) {
            this.removeField(field);

            return;
        }

        this.definition.fields = [...this.definition.fields, field];
        this.emit();
    }


    public removeField(field: AutomationField): void {
        this.definition.fields = this.definition.fields.filter(selected => selected.name !== field.name);
        // A removed field must not linger in the mapping.
        this.definition.mapping = this.definition.mapping.filter(entry => entry.source !== field.name);
        this.emit();
    }


    public onSelectAll(): void {
        this.definition.fields = [...this.filteredFields];
        this.emit();
    }


    public onReset(): void {
        this.definition.fields = [];
        this.definition.mapping = [];
        this.emit();
    }

    /* ---------------------------------------------------- GETTERS --------------------------------------------------- */

    public get filteredFields(): AutomationField[] {
        const needle = this.fieldFilter.trim().toLowerCase();

        if (!needle) {
            return this.availableFields;
        }

        return this.availableFields.filter(field =>
            field.label.toLowerCase().includes(needle) || field.name.toLowerCase().includes(needle)
        );
    }


    public get selectedCount(): number {
        return this.definition.fields.length;
    }


    private emit(): void {
        this.definitionChange.emit(this.definition);
    }
}
