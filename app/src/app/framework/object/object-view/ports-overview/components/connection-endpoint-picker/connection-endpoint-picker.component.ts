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
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    OnInit,
    computed,
    forwardRef,
    inject,
    input,
    output,
    signal
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ControlValueAccessor, FormControl, NG_VALUE_ACCESSOR, ReactiveFormsModule } from '@angular/forms';

import { Observable, forkJoin, of } from 'rxjs';
import { catchError, finalize } from 'rxjs/operators';

import { CoreModule } from 'src/app/core/core.module';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { CmdbPortConnection, ConnectionEndpoint } from '../../models/port-connection.types';
import { CmdbPort } from '../../models/ports-overview.types';
import { PortConnectionService } from '../../services/port-connection.service';
import { PortService } from '../../services/port.service';
import { PortTypeCatalogService } from '../../services/port-type-catalog.service';
import { indexConnectionsByPort } from '../../utils/port-connection.util';
import { portSideGroup, portSideLabel } from '../../utils/port-side.util';
import { ObjectOption, ObjectOptionPickerComponent } from '../object-option-picker/object-option-picker.component';
/* ------------------------------------------------------------------------------------------------------------------ */

/** One selectable port of the chosen device. Grouped by the face it sits on, for a patch panel. */
interface PortOption {
    portId: number;
    option_label: string;
    sideLabel: string;
    group: string;
}


/**
 * Picks the far end of a cable: first the device, then one of its free ports.
 *
 * A cabled port is left out of the list rather than offered and refused - a port holds at most one
 * cable, so the backend would answer 400. The port id is the control value; the host reads the
 * resolved endpoint from `endpointChange` when it has to name what is being connected.
 */
@Component({
    selector: 'cmdb-connection-endpoint-picker',
    templateUrl: './connection-endpoint-picker.component.html',
    styleUrls: ['./connection-endpoint-picker.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: true,
    imports: [CoreModule, ReactiveFormsModule, ObjectOptionPickerComponent],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => ConnectionEndpointPickerComponent),
            multi: true
        }
    ]
})
export class ConnectionEndpointPickerComponent implements ControlValueAccessor, OnInit {

    private readonly portTypeCatalog = inject(PortTypeCatalogService);
    private readonly portService = inject(PortService);
    private readonly portConnectionService = inject(PortConnectionService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    /** The near end of the cable; a port cannot be connected to itself. */
    public readonly excludePortId = input<number | null>(null);

    /** Passed straight to the dropdowns, so a host whose layout clips the panel can re-parent it. */
    public readonly appendTo = input('');

    /** Rendered under the port field. The host decides when the missing answer is worth reporting. */
    public readonly errorMessage = input('');

    /** The picked port together with the device it belongs to, for a host that has to name the pair. */
    public readonly endpointChange = output<ConnectionEndpoint | null>();

    /** Types that declare ports; only their objects can be an end of a cable. */
    protected readonly portCapableTypeIds = signal<number[]>([]);
    protected readonly portOptions = signal<PortOption[]>([]);
    protected readonly hasLoadedPorts = signal(false);

    /** How many of the device's ports are already cabled, which is why they are not on the list. */
    protected readonly cabledPortCount = signal(0);

    protected readonly deviceControl = new FormControl<number | null>(null);
    protected readonly portControl = new FormControl<number | null>(null);

    protected readonly portNotice = computed<string | null>(() => {
        if (!this.hasLoadedPorts() || this.portOptions().length > 0) {
            return null;
        }

        return this.cabledPortCount() > 0
            ? 'Every port of this device already carries a cable. Disconnect one of them first.'
            : 'This device has no free port. Create its ports before cabling it.';
    });

    private selectedDeviceLabel = '';

    private onChange: (portId: number | null) => void = () => {};
    private onTouched: () => void = () => {};

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.portControl.valueChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((portId) => {
                this.onChange(portId);
                this.onTouched();
                this.endpointChange.emit(this.toEndpoint(portId));
            });

        this.loadPortCapableTypes();
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    /** A different device replaces the port list; the previous choice would no longer belong to it. */
    protected onDeviceSelected(device: ObjectOption | null): void {
        this.selectedDeviceLabel = device?.option_label ?? '';
        this.portControl.setValue(null);
        this.portOptions.set([]);
        this.cabledPortCount.set(0);
        this.hasLoadedPorts.set(false);

        if (device) {
            this.loadPortsOfDevice(device.public_id);
        }
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public writeValue(portId: number | null): void {
        this.portControl.setValue(portId ?? null, { emitEvent: false });
    }

    public registerOnChange(fn: (portId: number | null) => void): void {
        this.onChange = fn;
    }

    public registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    public setDisabledState(isDisabled: boolean): void {
        const action = isDisabled ? 'disable' : 'enable';

        this.deviceControl[action]({ emitEvent: false });
        this.portControl[action]({ emitEvent: false });
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private loadPortCapableTypes(): void {
        this.loaderService.show();

        this.portTypeCatalog.portCapableTypeIds()
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: (typeIds) => this.portCapableTypeIds.set(typeIds),
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }


    /**
     * The device's ports together with what is already connected to them.
     *
     * Both are needed: the port list alone reports a panel port as connected through its internal
     * pairing, which says nothing about whether that port can still take a cable.
     */
    private loadPortsOfDevice(objectId: number): void {
        this.loaderService.show();

        forkJoin({
            ports: this.portService.getPortsOfObject(objectId),
            connections: this.readConnections(objectId)
        })
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: ({ ports, connections }) => this.applyPorts(ports, connections),
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }


    /** A denied or failed connection read must not hide the device's ports; it only widens the list. */
    private readConnections(objectId: number): Observable<CmdbPortConnection[]> {
        return this.portConnectionService.getConnectionsOfObject(objectId).pipe(
            catchError(() => of<CmdbPortConnection[]>([]))
        );
    }


    private applyPorts(ports: CmdbPort[], connections: CmdbPortConnection[]): void {
        const byPort = indexConnectionsByPort(connections);
        const excluded = this.excludePortId();
        const selectable = ports.filter(
            (port) => port.public_id !== excluded && !byPort.get(port.public_id)?.cable
        );

        this.cabledPortCount.set(ports.filter((port) => !!byPort.get(port.public_id)?.cable).length);
        this.portOptions.set(selectable.map((port) => this.toPortOption(port)));
        this.hasLoadedPorts.set(true);
    }


    private toPortOption(port: CmdbPort): PortOption {
        return {
            portId: port.public_id,
            option_label: port.name?.trim() || `Port #${ port.public_id }`,
            sideLabel: portSideLabel(port.side),
            group: portSideGroup(port.side)
        };
    }


    private toEndpoint(portId: number | null): ConnectionEndpoint | null {
        const port = this.portOptions().find((option) => option.portId === portId);

        if (!port) {
            return null;
        }

        return {
            portId: port.portId,
            portName: port.option_label,
            sideLabel: port.sideLabel,
            objectId: this.deviceControl.value,
            objectLabel: this.selectedDeviceLabel
        };
    }
}
