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

import {
    AutomationDefinition,
    AutomationDirection,
    AutomationField,
    AutomationMappingEntry,
    AutomationSystemField,
    findSystemField,
    systemFieldValue,
    toAutomationField
} from '../../../models/automation-definition.model';
import { SelectableTargetSystem } from '../../../services/target-catalog.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Which end of the automation a pole shows. */
type Pole = 'left' | 'right';

/**
 * Step group 2 - the two ends an automation joins.
 *
 * Both ends are configured where they belong rather than in steps of their own, because they are
 * not steps: an automation always has exactly these two, and the direction between them is a
 * switch. DataGerry's end needs no call to be described - the object type and its fields are known,
 * so the read or write is built from them and only shown for reassurance.
 */
@Component({
    selector: 'app-wizard-step-link',
    templateUrl: './wizard-step-link.component.html',
    styleUrls: ['./wizard-step-link.component.scss'],
    standalone: false
})
export class WizardStepLinkComponent {

    @Input() public definition!: AutomationDefinition;
    @Input() public objectTypes: CmdbType[] = [];
    @Input() public availableFields: AutomationField[] = [];
    @Input() public systemFields: AutomationSystemField[] = [];
    @Input() public targetSystems: SelectableTargetSystem[] = [];

    @Output() public definitionChange = new EventEmitter<AutomationDefinition>();
    @Output() public objectTypeChange = new EventEmitter<number | null>();

    /** Raised when the system or action changed, so the shell can rebuild the mapping. */
    @Output() public targetChange = new EventEmitter<void>();


    /** Only one end is edited at a time; the other stays a summary. */
    public open: Pole | null = null;
    public fieldFilter = '';

    /* ----------------------------------------------------- POLES ---------------------------------------------------- */

    public isDataGerry(pole: Pole): boolean {
        return (pole === 'left') === (this.definition.direction === 'outgoing');
    }


    public roleOf(pole: Pole): 'source' | 'target' {
        return pole === 'left' ? 'source' : 'target';
    }


    public toggle(pole: Pole): void {
        this.open = this.open === pole ? null : pole;
    }


    /**
     * Turns the automation around.
     *
     * A value read out of a DataGerry object is unavailable once DataGerry is the side being
     * written, so those selections cannot survive the switch; fixed values can. The mapping goes
     * either way, because both of its sides change meaning.
     */
    public onSwapDirection(): void {
        const direction: AutomationDirection = this.definition.direction === 'outgoing'
            ? 'incoming'
            : 'outgoing';

        this.definition.direction = direction;
        this.definition.fields = this.definition.fields.filter(field => {
            const systemField = findSystemField(field.name);

            return !systemField || systemField.kind === 'constant' || direction === 'outgoing';
        });
        this.definition.mapping = [];
        this.definition.unmapped = [];
        this.open = null;
        this.emit();
        this.targetChange.emit();
    }

    /* --------------------------------------------------- DATAGERRY -------------------------------------------------- */

    public onSelectObjectType(typeId: number | null): void {
        this.objectTypeChange.emit(typeId);
    }


    public isFieldSelected(field: AutomationField): boolean {
        return this.definition.fields.some(selected => selected.name === field.name);
    }


    public onToggleField(field: AutomationField): void {
        if (this.isFieldSelected(field)) {
            this.definition.fields = this.definition.fields.filter(
                selected => selected.name !== field.name
            );
            this.definition.mapping = dropSource(this.definition.mapping, field.name);
        } else {
            this.definition.fields = [...this.definition.fields, field];
        }

        this.emit();
    }


    public isSystemFieldSelected(field: AutomationSystemField): boolean {
        return this.definition.fields.some(selected => selected.name === field.key);
    }


    public onToggleSystemField(field: AutomationSystemField): void {
        if (this.isSystemFieldSelected(field)) {
            this.definition.fields = this.definition.fields.filter(
                selected => selected.name !== field.key
            );
            this.definition.mapping = dropSource(this.definition.mapping, field.key);
        } else {
            this.definition.fields = [...this.definition.fields, toAutomationField(field)];
        }

        this.emit();
    }


    /** The literal a fixed value stands for, so the user sees what will be sent. */
    public valuePreview(field: AutomationSystemField): string {
        return field.kind === 'constant' ? systemFieldValue(field, this.definition) : '';
    }


    public onSelectAll(): void {
        // Only the type's own fields are listed here; a system field the user picked stays picked.
        const systemSelection = this.definition.fields.filter(field => findSystemField(field.name));

        this.definition.fields = [...systemSelection, ...this.filteredFields];
        this.emit();
    }


    public onSelectNone(): void {
        this.definition.fields = [];
        this.definition.mapping = [];
        this.definition.unmapped = [];
        this.emit();
    }


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

    /* ------------------------------------------------- TARGET SYSTEM ------------------------------------------------ */

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

        this.emit();
        this.targetChange.emit();
    }


    public isSelectedSystem(system: SelectableTargetSystem): boolean {
        return this.definition.target.connectorId === system.connectorId;
    }


    public get selectedSystem(): SelectableTargetSystem | undefined {
        return this.targetSystems.find(system => system.connectorId === this.definition.target.connectorId);
    }

    /* --------------------------------------------------- BACKGROUND ------------------------------------------------- */

    /**
     * The call the assistant builds on the DataGerry side.
     *
     * Shown for reassurance, not for editing: everything in it follows from the object type and the
     * fields, both of which are chosen right above it.
     */
    public get dataGerryCall(): string {
        const type = this.definition.objectType.typeId ?? '…';

        return this.definition.direction === 'outgoing'
            ? `GET {url}/rest/objects/?filter={"type_id":${type}}&page=1&sort=public_id&order=1`
            : `POST {url}/rest/objects/   ·   PUT {url}/rest/objects/{public_id}`;
    }


    private emit(): void {
        this.definitionChange.emit(this.definition);
    }
}


/** Takes a source out of every target it fed, and drops the targets left with nothing. */
function dropSource(mapping: AutomationMappingEntry[], field: string): AutomationMappingEntry[] {
    return mapping
        .map(entry => ({ ...entry, sources: entry.sources.filter(source => source.field !== field) }))
        .filter(entry => entry.sources.length > 0);
}
