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
    computed,
    forwardRef,
    inject,
    input,
    output,
    signal,
    OnInit
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ControlValueAccessor, FormControl, NG_VALUE_ACCESSOR, ReactiveFormsModule } from '@angular/forms';
import { Subject, debounceTime, distinctUntilChanged, finalize, map, takeUntil } from 'rxjs';

import { CoreModule } from 'src/app/core/core.module';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ObjectSearchFilterService } from 'src/app/core/services/object-search-filter.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';

import { RackAssignableObject, RackAssignableOption } from '../../models/rack-overview.types';
import { RackOverviewService } from '../../services/rack-overview.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Assignable objects are pulled in pages as the dropdown is scrolled. */
const PAGE_SIZE = 10;

/** Keystrokes are collected for this long before the search hits the backend. */
const SEARCH_DEBOUNCE_MS = 300;


/**
 * Picks the object to mount into a rack. Owns its own paging, server-side search and the hint that a
 * candidate already sits in another rack; the host only binds a form control and reads the id out of it.
 */
@Component({
    selector: 'cmdb-rack-object-picker',
    templateUrl: './rack-object-picker.component.html',
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: true,
    imports: [CoreModule, ReactiveFormsModule],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => RackObjectPickerComponent),
            multi: true
        }
    ]
})
export class RackObjectPickerComponent implements ControlValueAccessor, OnInit {

    private readonly rackOverviewService = inject(RackOverviewService);
    private readonly objectSearchFilterService = inject(ObjectSearchFilterService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    public readonly rackId = input.required<number>();

    /** Passed straight to the dropdown, so a host whose layout clips the panel can re-parent it. */
    public readonly appendTo = input('');

    /** The picked object itself, for a host that has to react to a new choice rather than to its id. */
    public readonly objectSelected = output<RackAssignableObject | null>();

    protected readonly options = signal<RackAssignableOption[]>([]);
    protected readonly selectedOption = signal<RackAssignableOption | null>(null);
    /** Off by default: the picker offers objects mounted in another rack as well. */
    protected readonly showOnlyUnmounted = signal(false);
    protected readonly isFetching = signal(false);
    /** Rows actually fetched, which the pinned selection is not part of. */
    protected readonly loadedCount = signal(0);
    protected readonly total = signal(0);

    protected readonly objectControl = new FormControl<number | null>(null);

    /** The dropdown pushes what the user types in here; the list is searched server side. */
    protected readonly searchTerms$ = new Subject<string>();

    /** Warns that mounting the picked object moves it out of the rack it currently sits in. */
    protected readonly assignedRackNotice = computed<string | null>(() => {
        const selected = this.selectedOption();

        if (!selected?.assigned_rack_id) {
            return null;
        }

        if (selected.assigned_rack_id === this.rackId()) {
            return 'This object is already mounted in this rack.';
        }

        return `This object is currently mounted in ${this.assignedRackLabel(selected)}.`
            + ' Mounting it here removes it from that rack.';
    });

    private onChange: (objectId: number | null) => void = () => {};
    private onTouched: () => void = () => {};

    /** Cancels the page in flight when the list is rebuilt, so a stale page cannot append to it. */
    private readonly listReset$ = new Subject<void>();

    private searchTerm = '';
    private nextPage = 1;
    private hasMorePages = true;
    private isInitialLoad = true;

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.objectControl.valueChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((objectId) => {
                this.onChange(objectId);
                this.onTouched();
            });

        this.watchSearchTerms();
        this.loadPage();
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    protected onOptionSelected(option: RackAssignableOption | null): void {
        this.selectedOption.set(option);
        this.objectSelected.emit(option);
    }

    /** Switching between "all objects" and "free objects only" rebuilds the list from the first page. */
    protected onOnlyUnmountedChange(onlyUnmounted: boolean): void {
        this.showOnlyUnmounted.set(onlyUnmounted);
        this.resetPages();
        this.loadPage();
    }

    /** Reaching the end of the option list pulls the next page in. */
    protected onScrollEnd(): void {
        this.loadPage();
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public writeValue(objectId: number | null): void {
        this.objectControl.setValue(objectId ?? null, { emitEvent: false });

        if (objectId == null) {
            this.selectedOption.set(null);
        }
    }

    public registerOnChange(fn: (objectId: number | null) => void): void {
        this.onChange = fn;
    }

    public registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    public setDisabledState(isDisabled: boolean): void {
        if (isDisabled) {
            this.objectControl.disable({ emitEvent: false });
            return;
        }

        this.objectControl.enable({ emitEvent: false });
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** A typed term replaces the list with the backend's answer for it, rather than filtering locally. */
    private watchSearchTerms(): void {
        this.searchTerms$
            .pipe(
                map(term => (term ?? '').trim()),
                debounceTime(SEARCH_DEBOUNCE_MS),
                distinctUntilChanged(),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((term) => {
                this.searchTerm = term;
                this.resetPages();
                this.loadPage();
            });
    }

    /**
     * Loads the next page and appends it. Only the load the picker opens with runs behind the modal
     * loader; a search or a further page reports through the dropdown's own spinner, which leaves the
     * user in the field they are typing in.
     */
    private loadPage(): void {
        if (this.isFetching() || !this.hasMorePages) {
            return;
        }

        const usesModalLoader = this.isInitialLoad;
        const searchFilter = this.objectSearchFilterService.buildFieldValueSearchPipeline(this.searchTerm);
        this.isFetching.set(true);

        if (usesModalLoader) {
            this.loaderService.show();
        }

        this.rackOverviewService
            .getAssignableObjects(
                this.rackId(),
                {
                    filter: searchFilter.length ? searchFilter : undefined,
                    limit: PAGE_SIZE,
                    sort: 'public_id',
                    order: 1,
                    page: this.nextPage
                },
                this.showOnlyUnmounted()
            )
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                takeUntil(this.listReset$),
                finalize(() => {
                    this.isFetching.set(false);
                    this.isInitialLoad = false;

                    if (usesModalLoader) {
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

    private appendPage(response: APIGetMultiResponse<RackAssignableObject>): void {
        const page = response?.results ?? [];
        const merged = this.dedupeByObjectId([...this.options(), ...page.map(item => this.toOption(item))]);
        const loaded = this.loadedCount() + page.length;

        this.options.set(this.withSelectedOption(merged));
        this.loadedCount.set(loaded);
        this.total.set(response?.total ?? loaded);
        this.hasMorePages = page.length > 0 && loaded < this.total();
        this.nextPage = this.nextPage + 1;
    }

    /**
     * Drops the loaded pages and stops the page in flight from restoring them. The picked object is
     * kept: a narrower list is about browsing the candidates, not about revoking a choice already made.
     */
    private resetPages(): void {
        this.listReset$.next();

        this.options.set(this.withSelectedOption([]));
        this.loadedCount.set(0);
        this.total.set(0);
        this.nextPage = 1;
        this.hasMorePages = true;
    }

    /** A page can carry the pinned selection again, so the merged list is reduced to one row per object. */
    private dedupeByObjectId(options: RackAssignableOption[]): RackAssignableOption[] {
        const seenObjectIds = new Set<number>();
        const unique: RackAssignableOption[] = [];

        for (const option of options) {
            if (!seenObjectIds.has(option.public_id)) {
                seenObjectIds.add(option.public_id);
                unique.push(option);
            }
        }

        return unique;
    }

    /** The picked object stays an option through a search or a filter change, so its label keeps rendering. */
    private withSelectedOption(options: RackAssignableOption[]): RackAssignableOption[] {
        const selected = this.selectedOption();

        if (!selected || options.some(option => option.public_id === selected.public_id)) {
            return options;
        }

        return [selected, ...options];
    }

    private toOption(item: RackAssignableObject): RackAssignableOption {
        const option_label = item.assigned_rack_id
            ? `${item.summary_line} - mounted in ${this.assignedRackLabel(item)}`
            : item.summary_line;

        return { ...item, option_label };
    }

    /** Racks carry a name, but an unnamed one is still identifiable by its id. */
    private assignedRackLabel(item: RackAssignableObject): string {
        return item.assigned_rack_name?.trim() || `rack #${item.assigned_rack_id}`;
    }
}
