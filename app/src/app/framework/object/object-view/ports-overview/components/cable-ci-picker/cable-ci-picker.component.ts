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
    forwardRef,
    inject,
    input,
    output,
    signal
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ControlValueAccessor, FormControl, NG_VALUE_ACCESSOR, ReactiveFormsModule } from '@angular/forms';

import { Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, finalize, map, takeUntil } from 'rxjs/operators';

import { CoreModule } from 'src/app/core/core.module';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';

import { UnassignedCable } from '../../models/port-connection.types';
import { PortConnectionService } from '../../services/port-connection.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Cables are pulled in pages as the dropdown is scrolled. */
const PAGE_SIZE = 10;

/** Keystrokes are collected for this long before the search hits the backend. */
const SEARCH_DEBOUNCE_MS = 300;


/** One selectable cable, labelled the way the user recognises it. */
export interface CableOption {
    public_id: number;
    option_label: string;
}


/**
 * Selects the cable CI a connection is linked to, paged and searched server side.
 *
 * Only cables that are not already on another connection are offered, which is what the route
 * answers - so the list itself rules out a double link instead of the write failing on one.
 */
@Component({
    selector: 'cmdb-cable-ci-picker',
    templateUrl: './cable-ci-picker.component.html',
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: true,
    imports: [CoreModule, ReactiveFormsModule],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => CableCiPickerComponent),
            multi: true
        }
    ]
})
export class CableCiPickerComponent implements ControlValueAccessor, OnInit {

    private readonly portConnectionService = inject(PortConnectionService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    /** The connection being edited, so its own cable is offered too and can be preselected. */
    public readonly connectionId = input<number | null>(null);

    public readonly label = input('Cable CI');
    public readonly placeholder = input('Type to search cables...');
    public readonly required = input(false);
    public readonly errorMessage = input('');

    /** Passed straight to the dropdown, so a host whose layout clips the panel can re-parent it. */
    public readonly appendTo = input('');

    /** The picked cable itself, for a host that has to name the choice rather than store its id. */
    public readonly cableSelected = output<CableOption | null>();

    protected readonly options = signal<CableOption[]>([]);
    protected readonly isFetching = signal(false);

    protected readonly cableControl = new FormControl<number | null>(null);

    /** The dropdown pushes what the user types in here; the list is searched server side. */
    protected readonly searchTerms$ = new Subject<string>();

    private onChange: (cableId: number | null) => void = () => {};
    private onTouched: () => void = () => {};

    /** Cancels the page in flight when the list is rebuilt, so a stale page cannot append to it. */
    private readonly listReset$ = new Subject<void>();

    /** The picked cable stays an option through a search, so its label keeps rendering. */
    private pinnedOption: CableOption | null = null;

    private searchTerm = '';
    private nextPage = 1;
    private hasMorePages = true;

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.cableControl.valueChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((cableId) => {
                this.onChange(cableId);
                this.onTouched();
            });

        this.watchSearchTerms();
        this.loadPage(true);
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    protected onOptionSelected(option: CableOption | null): void {
        this.pinnedOption = option;
        this.cableSelected.emit(option);
    }


    /** Reaching the end of the option list pulls the next page in. */
    protected onScrollEnd(): void {
        this.loadPage(false);
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public writeValue(cableId: number | null): void {
        this.cableControl.setValue(cableId ?? null, { emitEvent: false });

        if (cableId == null) {
            this.pinnedOption = null;
        }
    }

    public registerOnChange(fn: (cableId: number | null) => void): void {
        this.onChange = fn;
    }

    public registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    public setDisabledState(isDisabled: boolean): void {
        if (isDisabled) {
            this.cableControl.disable({ emitEvent: false });
            return;
        }

        this.cableControl.enable({ emitEvent: false });
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** A typed term replaces the list with the backend's answer for it, rather than filtering locally. */
    private watchSearchTerms(): void {
        this.searchTerms$
            .pipe(
                map((term) => (term ?? '').trim()),
                debounceTime(SEARCH_DEBOUNCE_MS),
                distinctUntilChanged(),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((term) => {
                this.searchTerm = term;
                this.resetPages();
                this.loadPage(false);
            });
    }


    /**
     * Loads the next page and appends it.
     *
     * Only the list the picker opens with runs behind the modal loader; a search or a further page
     * reports through the dropdown's own spinner, which leaves the user in the field they type in.
     */
    private loadPage(useModalLoader: boolean): void {
        if (this.isFetching() || !this.hasMorePages) {
            return;
        }

        this.isFetching.set(true);

        if (useModalLoader) {
            this.loaderService.show();
        }

        this.portConnectionService
            .getUnassignedCables({
                page: this.nextPage,
                limit: PAGE_SIZE,
                search: this.searchTerm || undefined,
                connectionId: this.connectionId()
            })
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                takeUntil(this.listReset$),
                finalize(() => {
                    this.isFetching.set(false);

                    if (useModalLoader) {
                        this.loaderService.hide();
                    }
                })
            )
            .subscribe({
                next: (response) => this.appendPage(response),
                error: (err) => {
                    // Stop paging on a failed page rather than retrying the same one on every scroll.
                    this.hasMorePages = false;
                    this.toastService.error(err?.error?.message);
                }
            });
    }


    private appendPage(response: APIGetMultiResponse<UnassignedCable>): void {
        const page = (response?.results ?? []).map((cable) => this.toOption(cable));
        const merged = this.dedupeById([...this.options(), ...page]);

        this.options.set(merged);
        this.hasMorePages = page.length === PAGE_SIZE && merged.length < (response?.total ?? merged.length);
        this.nextPage = this.nextPage + 1;

        this.pinCurrentSelection(merged);
    }


    /** An edit opens with a cable already stored, and only the page it arrives on can name it. */
    private pinCurrentSelection(options: CableOption[]): void {
        const selectedId = this.cableControl.value;

        if (selectedId == null || this.pinnedOption?.public_id === selectedId) {
            return;
        }

        this.pinnedOption = options.find((option) => option.public_id === selectedId) ?? null;

        if (this.pinnedOption) {
            this.cableSelected.emit(this.pinnedOption);
        }
    }


    /**
     * Drops the loaded pages and stops the page in flight from restoring them. The picked cable is
     * kept: a narrower list is about browsing the candidates, not about revoking a choice already made.
     */
    private resetPages(): void {
        this.listReset$.next();
        this.options.set(this.pinnedOption ? [this.pinnedOption] : []);
        this.nextPage = 1;
        this.hasMorePages = true;
    }


    /** A cable is recognised by its name; the type and a retired flag tell two similar ones apart. */
    private toOption(cable: UnassignedCable): CableOption {
        const name = (cable?.name ?? '').trim() || `Cable #${ cable?.public_id }`;
        const details = [cable?.cable_type?.trim(), cable?.active === false ? 'inactive' : ''].filter(Boolean);

        return {
            public_id: cable?.public_id,
            option_label: details.length ? `${ name } (${ details.join(', ') })` : name
        };
    }


    /** A page can carry the pinned selection again, so the merged list is reduced to one row per cable. */
    private dedupeById(options: CableOption[]): CableOption[] {
        const seen = new Set<number>();

        return options.filter((option) => {
            if (seen.has(option.public_id)) {
                return false;
            }

            seen.add(option.public_id);

            return true;
        });
    }
}
