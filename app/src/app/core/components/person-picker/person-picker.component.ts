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
import { Subject, debounceTime, distinctUntilChanged, finalize, map, takeUntil } from 'rxjs';

import { CoreModule } from 'src/app/core/core.module';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { PersonSelectorService } from 'src/app/framework/services/person-selector.service';
import {
    PERSON_KINDS,
    PersonFieldValue,
    PersonKind,
    PersonPickerPage,
    PersonSelection,
    personDisplayLabel,
    personValueIds
} from 'src/app/framework/models/person-selector';
/* ------------------------------------------------------------------------------------------------------------------ */

export interface PersonOption extends PersonSelection {
    display_label: string;
    disabled?: boolean;
}

const PAGE_SIZE = 25;

const SEARCH_DEBOUNCE_MS = 300;

const LOAD_ERROR = 'Persons could not be loaded.';


/** Picks persons and person groups by object id, paged and searched server side. */
@Component({
    selector: 'app-person-picker',
    template: `
        <app-form-select
            (focusin)="onPickerFocus()"
            bindLabel="display_label"
            bindValue="object_id"
            groupBy="type_label"
            [items]="options()"
            [multiple]="multiple()"
            [placeholder]="placeholder()"
            [ariaLabel]="ariaLabel()"
            [dropdownDirection]="dropdownDirection()"
            [appendTo]="appendTo()"
            [loading]="isFetching()"
            [typeahead]="searchTerms$"
            [formControl]="personControl"
            (selectedItemChange)="onSelectionChange($event)"
            (scrolledToEnd)="onScrollEnd()"
        ></app-form-select>
    `,
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: true,
    imports: [CoreModule, ReactiveFormsModule],
    host: { class: 'd-block' },
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => PersonPickerComponent),
            multi: true
        }
    ]
})
export class PersonPickerComponent implements ControlValueAccessor, OnInit {

    private readonly personSelectorService = inject(PersonSelectorService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    public readonly kinds = input<ReadonlyArray<PersonKind>>(PERSON_KINDS);
    public readonly multiple = input(false);
    public readonly placeholder = input('Type to search...');
    /** Accessible name when the picker has no visible label. */
    public readonly ariaLabel = input('');
    public readonly dropdownDirection = input<'bottom' | 'top' | 'auto'>('auto');
    /** Selector the dropdown is attached to, so a clipping container does not cut it off. */
    public readonly appendTo = input('');
    /** Ids the host already holds elsewhere; they are not offered. */
    public readonly excludedIds = input<ReadonlyArray<number>>([]);
    /** Offered but not selectable; ng-select shows a disabled option. */
    public readonly unselectable = input<((selection: PersonSelection) => boolean) | null>(null);

    /** The picked entries, so a host can store which kind each id is. */
    public readonly selectionChange = output<PersonOption[]>();

    protected readonly personControl = new FormControl<PersonFieldValue>(null);

    /** Kept apart from the loaded pages so the selected labels survive a search. */
    private readonly selectedOptions = signal<PersonOption[]>([]);
    private readonly loadedOptions = signal<PersonOption[]>([]);

    protected readonly options = computed<PersonOption[]>(() => {
        const selected = this.selectedOptions();
        const hiddenIds = new Set([...selected.map(option => option.object_id), ...this.excludedIds()]);

        const unselectable = this.unselectable();
        const offered = this.loadedOptions()
            .filter(option => !hiddenIds.has(option.object_id))
            .map(option => (unselectable?.(option) ? { ...option, disabled: true } : option));

        return [...selected, ...offered];
    });

    protected readonly isFetching = signal(false);

    protected readonly searchTerms$ = new Subject<string>();

    /** Cancels the page in flight when the list is rebuilt, so a stale page cannot append to it. */
    private readonly listReset$ = new Subject<void>();

    private readonly valueWritten$ = new Subject<void>();

    private onChange: (value: PersonFieldValue) => void = () => {};
    private onTouched: () => void = () => {};

    private searchTerm = '';
    private nextPage = 1;
    private hasMorePages = true;
    private isInitialLoad = true;
    private resolvingKey = '';

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.personControl.valueChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((value) => {
                this.onChange(value);
                this.onTouched();
            });

        this.watchSearchTerms();
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    /** The first page loads when the picker is first used, not for every picker on form open. */
    protected onPickerFocus(): void {
        if (this.isInitialLoad && this.personControl.enabled) {
            this.loadPage();
        }
    }


    protected onSelectionChange(selection: PersonOption | PersonOption[] | null): void {
        const picked = Array.isArray(selection) ? selection : selection ? [selection] : [];

        this.selectedOptions.set(picked);
        this.selectionChange.emit(picked);
    }


    protected onScrollEnd(): void {
        this.loadPage();
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public writeValue(value: unknown): void {
        const ids = personValueIds(value);

        this.personControl.setValue(this.multiple() ? ids : (ids[0] ?? null), { emitEvent: false });
        this.resolveSelection(ids);
    }

    public registerOnChange(fn: (value: PersonFieldValue) => void): void {
        this.onChange = fn;
    }

    public registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    public setDisabledState(isDisabled: boolean): void {
        if (isDisabled) {
            this.personControl.disable({ emitEvent: false });
            return;
        }

        this.personControl.enable({ emitEvent: false });
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** Stored ids carry no labels, so the ones not already known are looked up once. */
    private resolveSelection(ids: number[]): void {
        const known = new Map(
            [...this.selectedOptions(), ...this.loadedOptions()].map(option => [option.object_id, option])
        );
        const missingIds = ids.filter(id => !known.has(id));
        const missingKey = missingIds.join(',');

        if (missingKey && missingKey === this.resolvingKey) {
            return;
        }

        this.valueWritten$.next();
        this.resolvingKey = missingKey;
        this.selectedOptions.set(ids.filter(id => known.has(id)).map(id => known.get(id)));

        if (!missingIds.length) {
            return;
        }

        this.loaderService.show();

        this.personSelectorService.resolvePersons(missingIds)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                takeUntil(this.valueWritten$),
                finalize(() => {
                    this.resolvingKey = '';
                    this.loaderService.hide();
                })
            )
            .subscribe({
                next: (resolved) => {
                    const options = ids
                        .map(id => known.get(id) ?? (resolved.has(id) ? this.toOption(resolved.get(id)) : null))
                        .filter((option): option is PersonOption => option !== null);

                    this.selectedOptions.set(options);
                },
                error: () => this.toastService.error(LOAD_ERROR)
            });
    }


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


    /** Only the first page runs behind the loader; searching and paging use the dropdown's own spinner. */
    private loadPage(): void {
        if (this.isFetching() || !this.hasMorePages) {
            return;
        }

        const usesLoader = this.isInitialLoad;
        this.isFetching.set(true);

        if (usesLoader) {
            this.loaderService.show();
        }

        this.personSelectorService
            .getSelectablePersons({
                kinds: this.kinds(),
                search: this.searchTerm || undefined,
                page: this.nextPage,
                limit: PAGE_SIZE
            })
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                takeUntil(this.listReset$),
                finalize(() => {
                    this.isFetching.set(false);
                    this.isInitialLoad = false;

                    if (usesLoader) {
                        this.loaderService.hide();
                    }
                })
            )
            .subscribe({
                next: (page) => this.appendPage(page),
                error: () => {
                    this.hasMorePages = false;
                    this.toastService.error(LOAD_ERROR);
                }
            });
    }


    private appendPage(page: PersonPickerPage): void {
        const results = page?.results ?? [];
        const loaded = [...this.loadedOptions(), ...results.map(selection => this.toOption(selection))];

        this.loadedOptions.set(loaded);
        this.hasMorePages = results.length > 0 && loaded.length < (page?.total ?? 0);
        this.nextPage++;
    }


    private resetPages(): void {
        this.listReset$.next();
        this.loadedOptions.set([]);
        this.nextPage = 1;
        this.hasMorePages = true;
    }


    private toOption(selection: PersonSelection): PersonOption {
        return { ...selection, display_label: personDisplayLabel(selection) };
    }
}
