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
import {
    ChangeDetectorRef,
    Component,
    inject,
    Input,
    OnDestroy,
    OnInit
} from '@angular/core';
import { FormControl, UntypedFormGroup } from '@angular/forms';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { Subject, finalize, forkJoin, takeUntil } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { CmdbMode } from 'src/app/framework/modes.enum';
import { CmdbType } from 'src/app/framework/models/cmdb-type';
import {
    CmdbObject,
    MultiDataSectionEntry,
    MultiDataSectionFieldValue,
    MultiDataSectionSet
} from 'src/app/framework/models/cmdb-object';
import { RenderResult } from 'src/app/framework/models/cmdb-render';
import { ObjectService } from 'src/app/framework/services/object.service';
import { TypeService } from 'src/app/framework/services/type.service';
import { APIUpdateMultiResponse } from 'src/app/services/models/api-response';
import {
    IPAM_INTERFACE_FIELD_NAMES,
    IPAM_INTERFACE_SECTION_NAME
} from 'src/app/framework/render/special-types/ipam-interface/models/interface-fields';

import { IpamAssignableObject } from '../../models/ipam-overview.types';
import { IpamOverviewService } from '../../services/ipam-overview.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Server clamps page_size into [1, 500]; request the max so the picker holds every assignable object. */
const ASSIGNABLE_PAGE_SIZE = 500;


@Component({
    selector: 'cmdb-ipam-assign-ip-modal',
    templateUrl: './ipam-assign-ip-modal.component.html',
    styleUrls: ['./ipam-assign-ip-modal.component.scss'],
    standalone: false
})
export class IpamAssignIpModalComponent implements OnInit, OnDestroy {

    public readonly activeModal = inject(NgbActiveModal);
    private readonly ipamOverviewService = inject(IpamOverviewService);
    private readonly objectService = inject(ObjectService);
    private readonly typeService = inject(TypeService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly changesRef = inject(ChangeDetectorRef);

    @Input() public subnetId: number | null = null;
    @Input() public subnetCidr = '';
    @Input() public ip = '';

    public readonly MODES = CmdbMode;
    public readonly objectControl = new FormControl<number | null>(null);
    public assignableItems: IpamAssignableObject[] = [];
    public selectedType: CmdbType | null = null;
    // All of the object's interfaces (existing rows + the new pre-filled row, rendered first) in a
    // single editable table. Row actions are gated in SCSS: existing rows show none, the new row
    // shows only edit.
    public interfaceRenderResult: RenderResult | null = null;
    public interfaceRenderForm = new UntypedFormGroup({});
    public hasInterfaceSection = true;
    public readonly isLoading$ = this.loaderService.isLoading$;

    private nativeObject: CmdbObject | null = null;
    // multi_data_id of the new row, so it can be located among the existing rows on save.
    private newRowId = 0;
    // Subnet, IP and type are predetermined by the assign context. They are locked in the edit
    // form, so their original values are captured here and restored before saving (a disabled
    // control is dropped from the form value).
    private lockedFieldOriginals = new Map<number, { subnet: unknown; ip: unknown; type: unknown }>();
    private readonly destroy$ = new Subject<void>();

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.loadAssignableObjects();
    }

    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onObjectSelected(selected: IpamAssignableObject | null): void {
        this.resetInterfaceView();

        if (!selected) {
            this.changesRef.markForCheck();
            return;
        }

        this.loadObjectInterface(selected);
    }

    public onAssign(): void {
        if (!this.canSubmit || !this.nativeObject) {
            return;
        }

        const entry = this.interfaceRenderForm.get(this.mdsControlName)?.value as MultiDataSectionEntry | null;
        const newRow = entry?.values?.find(row => row.multi_data_id === this.newRowId);
        if (!newRow) {
            return;
        }

        this.restoreLockedFields(entry);
        // Only the new row is appended; the object's existing interfaces stay untouched.
        this.appendInterfaceRows(this.nativeObject, [newRow]);
        this.nativeObject.comment = this.buildComment();
        this.persist(this.nativeObject);
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public get canSubmit(): boolean {
        if (!this.interfaceRenderResult || !this.selectedType || !this.nativeObject) {
            return false;
        }
        const entry = this.interfaceRenderForm.get(this.mdsControlName)?.value as MultiDataSectionEntry | null;
        return !!entry?.values?.some(row => row.multi_data_id === this.newRowId);
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private get mdsControlName(): string {
        return `dg-mds-${IPAM_INTERFACE_SECTION_NAME}`;
    }

    private loadAssignableObjects(): void {
        this.loaderService.show();

        this.ipamOverviewService
            .getAssignableObjects({ page: 1, page_size: ASSIGNABLE_PAGE_SIZE })
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: (response) => {
                    this.assignableItems = response?.rows ?? [];
                    this.changesRef.markForCheck();
                },
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }

    private loadObjectInterface(selected: IpamAssignableObject): void {
        this.loaderService.show();

        forkJoin({
            render: this.objectService.getObject<RenderResult>(selected.public_id),
            native: this.objectService.getObject<CmdbObject>(selected.public_id, true),
            type: this.typeService.getType(selected.type_info.public_id)
        })
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: ({ render, native, type }) => this.buildInterfaceView(render, native, type),
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }

    private buildInterfaceView(render: RenderResult, native: CmdbObject, type: CmdbType): void {
        const section = this.findInterfaceSection(type);

        if (!section) {
            this.hasInterfaceSection = false;
            this.changesRef.markForCheck();
            return;
        }

        this.selectedType = type;
        this.nativeObject = native;
        this.interfaceRenderResult = this.buildInterfaceRenderResult(render, section);
        this.lockedFieldOriginals = this.captureLockedOriginals(this.interfaceRenderResult.multi_data_sections);
        this.changesRef.markForCheck();
    }

    private findInterfaceSection(type: CmdbType): any | null {
        const sections = type?.render_meta?.sections ?? [];
        return sections.find(
            (section: any) => section?.name === IPAM_INTERFACE_SECTION_NAME && section?.type === 'multi-data-section'
        ) ?? null;
    }

    /**
     * Render result for the single interface table: the object's existing rows plus the new
     * pre-filled row inserted first (this subnet + this IP), with the predetermined fields locked.
     * The new row's id is recorded so it can be isolated on save and targeted for row actions.
     */
    private buildInterfaceRenderResult(render: RenderResult, section: any): RenderResult {
        const result: RenderResult = { ...render };
        result.sections = [section];
        result.fields = this.lockPredefinedFields(render.fields ?? []);
        result.multi_data_sections = this.buildCombinedMultiData(render.multi_data_sections ?? [], section);
        return result;
    }

    /**
     * Clones the object's multi-data sections and inserts the new pre-filled interface row at the
     * front of the IPAM interface section, assigning it a fresh multi_data_id (recorded in
     * {@link newRowId}). Rendering it first keeps it visible on page one and lets the row-action
     * CSS target it as the first row.
     */
    private buildCombinedMultiData(existing: any[], section: any): any[] {
        const sections = (existing ?? []).map(entry => ({ ...entry, values: [...(entry.values ?? [])] }));
        const newRow = this.buildPrefilledRow(section);
        const entry = sections.find(item => item.section_id === IPAM_INTERFACE_SECTION_NAME);

        if (entry) {
            this.newRowId = entry.highest_id;
            newRow.multi_data_id = this.newRowId;
            entry.values = [newRow, ...entry.values];
            entry.highest_id = entry.highest_id + 1;
        } else {
            this.newRowId = 0;
            newRow.multi_data_id = this.newRowId;
            sections.push({ section_id: IPAM_INTERFACE_SECTION_NAME, highest_id: 1, values: [newRow] });
        }

        return sections;
    }

    /**
     * Disables the fields the assign context already determines - the network, the IP and the
     * address type - so none of them can be changed in the row edit form. With no IP in the
     * edited candidate the interface row validator short-circuits to valid, so disabling the
     * type carries no family-mismatch risk.
     */
    private lockPredefinedFields(fields: any[]): any[] {
        const lockedNames: string[] = [
            IPAM_INTERFACE_FIELD_NAMES.SUBNET,
            IPAM_INTERFACE_FIELD_NAMES.IP_ADDRESS,
            IPAM_INTERFACE_FIELD_NAMES.TYPE
        ];

        return (fields ?? []).map(field =>
            lockedNames.includes(field?.name) ? { ...field, disabled: true } : field
        );
    }

    private buildPrefilledRow(section: any): MultiDataSectionSet {
        const overrides: { [fieldName: string]: unknown } = {
            [IPAM_INTERFACE_FIELD_NAMES.ACTIVE]: true,
            [IPAM_INTERFACE_FIELD_NAMES.TYPE]: this.resolveFamily(this.ip),
            [IPAM_INTERFACE_FIELD_NAMES.SUBNET]: this.subnetId,
            [IPAM_INTERFACE_FIELD_NAMES.IP_ADDRESS]: this.ip
        };

        const fieldNames: string[] = section?.fields ?? [];
        const data: MultiDataSectionFieldValue[] = fieldNames.map(name => ({
            name,
            value: name in overrides ? overrides[name] : ''
        }));

        return { multi_data_id: 0, data };
    }

    private resolveFamily(ip: string): string {
        return ip?.includes(':') ? 'ipv6' : 'ipv4';
    }

    private captureLockedOriginals(sections: any[]): Map<number, { subnet: unknown; ip: unknown; type: unknown }> {
        const map = new Map<number, { subnet: unknown; ip: unknown; type: unknown }>();
        const entry = (sections ?? []).find(item => item.section_id === IPAM_INTERFACE_SECTION_NAME);

        for (const row of entry?.values ?? []) {
            map.set(row.multi_data_id, {
                subnet: this.findRowValue(row, IPAM_INTERFACE_FIELD_NAMES.SUBNET),
                ip: this.findRowValue(row, IPAM_INTERFACE_FIELD_NAMES.IP_ADDRESS),
                type: this.findRowValue(row, IPAM_INTERFACE_FIELD_NAMES.TYPE)
            });
        }

        return map;
    }

    private restoreLockedFields(entry: MultiDataSectionEntry): void {
        for (const row of entry.values ?? []) {
            const original = this.lockedFieldOriginals.get(row.multi_data_id);
            if (!original) {
                continue;
            }
            this.restoreRowValue(row, IPAM_INTERFACE_FIELD_NAMES.SUBNET, original.subnet);
            this.restoreRowValue(row, IPAM_INTERFACE_FIELD_NAMES.IP_ADDRESS, original.ip);
            this.restoreRowValue(row, IPAM_INTERFACE_FIELD_NAMES.TYPE, original.type);
        }
    }

    private findRowValue(row: MultiDataSectionSet, name: string): unknown {
        return row?.data?.find(entry => entry.name === name)?.value;
    }

    private restoreRowValue(row: MultiDataSectionSet, name: string, value: unknown): void {
        const target = row.data?.find(entry => entry.name === name);
        if (target) {
            if (target.value === undefined || target.value === null || target.value === '') {
                target.value = value;
            }
        } else if (row.data) {
            row.data.push({ name, value });
        }
    }

    /**
     * Appends the new interface row(s) to the object's existing IPAM interface section, preserving
     * every current interface. Each row gets a fresh multi_data_id from the section's running
     * counter so it never collides with an existing row.
     */
    private appendInterfaceRows(object: CmdbObject, rows: MultiDataSectionSet[]): void {
        if (!Array.isArray(object.multi_data_sections)) {
            object.multi_data_sections = [];
        }

        let entry = object.multi_data_sections.find(section => section.section_id === IPAM_INTERFACE_SECTION_NAME);
        if (!entry) {
            entry = { section_id: IPAM_INTERFACE_SECTION_NAME, highest_id: 0, values: [] };
            object.multi_data_sections.push(entry);
        }

        for (const row of rows) {
            entry.values.push({ multi_data_id: entry.highest_id, data: row.data });
            entry.highest_id = entry.highest_id + 1;
        }
    }

    private buildComment(): string {
        return this.subnetCidr ? `Assigned ${this.ip} to ${this.subnetCidr}` : `Assigned ${this.ip}`;
    }

    private persist(object: CmdbObject): void {
        this.loaderService.show();

        this.objectService
            .putObject(object.public_id, object)
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: (response: APIUpdateMultiResponse) => {
                    if (response?.failed?.length) {
                        for (const fail of response.failed) {
                            this.toastService.error(fail?.error_message);
                        }
                        return;
                    }
                    this.activeModal.close(true);
                },
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }

    private resetInterfaceView(): void {
        this.interfaceRenderForm = new UntypedFormGroup({});
        this.interfaceRenderResult = null;
        this.selectedType = null;
        this.nativeObject = null;
        this.hasInterfaceSection = true;
        this.newRowId = 0;
        this.lockedFieldOriginals = new Map();
    }
}
