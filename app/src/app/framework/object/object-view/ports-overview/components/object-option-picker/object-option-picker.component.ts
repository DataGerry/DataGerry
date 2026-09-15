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
    effect,
    forwardRef,
    inject,
    input,
    output,
    signal,
    untracked
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ControlValueAccessor, FormControl, NG_VALUE_ACCESSOR, ReactiveFormsModule } from '@angular/forms';

import { Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, finalize, map, takeUntil } from 'rxjs/operators';

import { CoreModule } from 'src/app/core/core.module';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ObjectSearchFilterService } from 'src/app/core/services/object-search-filter.service';
import { RenderResult } from 'src/app/framework/models/cmdb-render';
import { ObjectService } from 'src/app/framework/services/object.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';

import { objectDisplayLabel } from '../../utils/object-label.util';
/* ------------------------------------------------------------------------------------------------------------------ */

/** An option is an id and a label, so the fields and sections of every object are left unread. */
const OPTION_LABEL_PROJECTION = {
    'object_information.object_id': 1,
    'summary_line': 1,
    'type_information': 1
};

/** Objects are pulled in pages as the dropdown is scrolled. */
const PAGE_SIZE = 10;

/** Keystrokes are collected for this long before the search hits the backend. */
const SEARCH_DEBOUNCE_MS = 300;


/** One selectable object, labelled the way the user recognises it. */
export interface ObjectOption {
    public_id: number;
    option_label: string;

    /** The type the option is listed under, so a long device list reads by class. */
    group: string;
}


/**
 * Selects one object out of a set of types, paged and searched server side.
 *
 * The `public_id` is the control value. Built on the shared select so the label, the id wiring and
 * the error row behave like every other field of the form it sits in.
 */
@Component({
    selector: 'cmdb-object-option-picker',
    templateUrl: './object-option-picker.component.html',
    styleUrls: ['./object-option-picker.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: true,
    imports: [CoreModule, ReactiveFormsModule],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => ObjectOptionPickerComponent),
            multi: true
        }
    ]
})
export class ObjectOptionPickerComponent implements ControlValueAccessor, OnInit {

    private readonly objectService = inject(ObjectService);
    private readonly objectSearchFilterService = inject(ObjectSearchFilterService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    /** The types to offer objects of. An empty list offers nothing and asks the server for nothing. */
    public readonly typeIds = input<number[]>([]);

    public readonly label = input('Object');
    public readonly placeholder = input('Type to search objects...');
    public readonly required = input(false);
    public readonly errorMessage = input('');

    /** Passed straight to the dropdown, so a host whose layout clips the panel can re-parent it. */
    public readonly appendTo = input('');

    /** The picked object itself, for a host that has to name the choice rather than store its id. */
    public readonly objectSelected = output<ObjectOption | null>();

    protected readonly options = signal<ObjectOption[]>([]);
    protected readonly isFetching = signal(false);

    protected readonly objectControl = new FormControl<number | null>(null);

    /** The dropdown pushes what the user types in here; the list is searched server side. */
    protected readonly searchTerms$ = new Subject<string>();

    private onChange: (objectId: number | null) => void = () => {};
    private onTouched: () => void = () => {};

    /** Cancels the page in flight when the list is rebuilt, so a stale page cannot append to it. */
    private readonly listReset$ = new Subject<void>();

    /** The picked object stays an option through a search, so its label keeps rendering. */
    private pinnedOption: ObjectOption | null = null;

    private searchTerm = '';
    private nextPage = 1;
    private hasMorePages = true;
    private loadedTypeKey = '';

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor() {
        // The scope usually arrives once its types have been resolved, and only a real change reloads.
        effect(() => {
            const typeKey = this.typeIds().join(',');

            if (typeKey === this.loadedTypeKey) {
                return;
            }

            this.loadedTypeKey = typeKey;
            untracked(() => {
                this.resetPages();
                this.loadPage(true);
            });
        });
    }

    public ngOnInit(): void {
        this.objectControl.valueChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((objectId) => {
                this.onChange(objectId);
                this.onTouched();
            });

        this.watchSearchTerms();
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    protected onOptionSelected(option: ObjectOption | null): void {
        this.pinnedOption = option;
        this.objectSelected.emit(option);
    }


    /** Reaching the end of the option list pulls the next page in. */
    protected onScrollEnd(): void {
        this.loadPage(false);
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public writeValue(objectId: number | null): void {
        this.objectControl.setValue(objectId ?? null, { emitEvent: false });

        if (objectId == null) {
            this.pinnedOption = null;
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
        if (this.isFetching() || !this.hasMorePages || this.typeIds().length === 0) {
            return;
        }

        const searchFilter = this.objectSearchFilterService.buildSearchPipeline(this.searchTerm, this.typeIds());

        this.isFetching.set(true);

        if (useModalLoader) {
            this.loaderService.show();
        }

        this.objectService
            .getObjects({
                filter: searchFilter.length ? searchFilter : undefined,
                projection: OPTION_LABEL_PROJECTION,
                limit: PAGE_SIZE,
                sort: 'public_id',
                order: 1,
                page: this.nextPage
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


    private appendPage(response: APIGetMultiResponse<RenderResult>): void {
        const page = (response?.results ?? []).map((result) => this.toOption(result));
        const merged = this.dedupeById([...this.options(), ...page]);

        this.options.set(merged);
        this.hasMorePages = page.length === PAGE_SIZE && merged.length < (response?.total ?? merged.length);
        this.nextPage = this.nextPage + 1;
    }


    /**
     * Drops the loaded pages and stops the page in flight from restoring them. The picked object is
     * kept: a narrower list is about browsing the candidates, not about revoking a choice already made.
     */
    private resetPages(): void {
        this.listReset$.next();
        this.options.set(this.pinnedOption ? [this.pinnedOption] : []);
        this.nextPage = 1;
        this.hasMorePages = true;
    }


    private toOption(result: RenderResult): ObjectOption {
        return {
            public_id: result?.object_information?.object_id,
            option_label: objectDisplayLabel(result),
            group: result?.type_information?.type_label?.trim() || 'Unknown type'
        };
    }


    /** A page can carry the pinned selection again, so the merged list is reduced to one row per object. */
    private dedupeById(options: ObjectOption[]): ObjectOption[] {
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
