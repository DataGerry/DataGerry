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
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subject, debounceTime, distinctUntilChanged, finalize, map, takeUntil } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { RenderFieldComponent } from '../components.fields';
import { CmdbMode } from '../../../modes.enum';
import { PersonSelectorService } from '../../../services/person-selector.service';
import {
    PERSON_KINDS,
    PersonKind,
    PersonPickerPage,
    PersonSelection,
    personDisplayLabel,
    personValueIds
} from '../../../models/person-selector';
/* ------------------------------------------------------------------------------------------------------------------ */

interface PersonOption extends PersonSelection {
    display_label: string;
}

const PAGE_SIZE = 25;

const SEARCH_DEBOUNCE_MS = 300;

const LOAD_ERROR = 'Persons could not be loaded.';


@Component({
    templateUrl: './person.component.html',
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class PersonComponent extends RenderFieldComponent implements OnInit {

    private readonly personSelectorService = inject(PersonSelectorService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly cdr = inject(ChangeDetectorRef);

    private static instances = 0;

    public readonly labelId = `person-field-${ ++PersonComponent.instances }`;

    /** The current selection, kept as options so its labels render whichever page is loaded. */
    private readonly selectedOptions = signal<PersonOption[]>([]);
    private readonly loadedOptions = signal<PersonOption[]>([]);

    public readonly options = computed<PersonOption[]>(() => {
        const selected = this.selectedOptions();
        const selectedIds = new Set(selected.map(option => option.object_id));

        return [...selected, ...this.loadedOptions().filter(option => !selectedIds.has(option.object_id))];
    });

    public readonly selectedLabels = computed(() => this.selectedOptions().map(option => option.display_label));

    public readonly isFetching = signal(false);

    public readonly searchTerms$ = new Subject<string>();

    /** Cancels the page in flight when the list is rebuilt, so a stale page cannot append to it. */
    private readonly listReset$ = new Subject<void>();

    private searchTerm = '';
    private nextPage = 1;
    private hasMorePages = true;
    private isInitialLoad = true;

    public get multiple(): boolean {
        return this.data?.multiple === true;
    }

    public get isEditable(): boolean {
        return this.mode === CmdbMode.Create || this.mode === CmdbMode.Edit || this.mode === CmdbMode.Bulk;
    }

    public get placeholder(): string {
        return this.multiple ? 'Type to search, several possible...' : 'Type to search...';
    }

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        const ids = personValueIds(this.controller?.value ?? this.data?.value);

        this.normalizeControlValue(ids);
        this.watchControlState();
        this.initSelection(ids);

        if (this.isEditable) {
            this.watchSearchTerms();
        }
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    /** The first page loads when the picker is first used, not for every person field on form open. */
    public onPickerFocus(): void {
        if (this.isInitialLoad) {
            this.loadPage();
        }
    }


    public onSelectionChange(selection: PersonOption | PersonOption[] | null): void {
        const picked = Array.isArray(selection) ? selection : selection ? [selection] : [];

        this.selectedOptions.set(picked);
    }


    public onScrollEnd(): void {
        this.loadPage();
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** A single selector stores one id or null, a multiple one a list - whatever shape arrived. */
    private normalizeControlValue(ids: number[]): void {
        const value = this.multiple ? ids : (ids[0] ?? null);

        this.controller?.setValue(value, { emitEvent: false });
    }


    /** Touched and validity are set by the surrounding form, which an OnPush view does not notice. */
    private watchControlState(): void {
        this.controller?.events
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.cdr.markForCheck());
    }


    /** A rendered flat field carries its labels; a multi-data row only holds ids, which are looked up once. */
    private initSelection(ids: number[]): void {
        if (Array.isArray(this.data?.persons)) {
            this.selectedOptions.set(this.data.persons.map((selection: PersonSelection) => this.toOption(selection)));
            return;
        }

        if (!ids.length) {
            return;
        }

        this.loaderService.show();

        this.personSelectorService.resolvePersons(ids)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: (resolved) => {
                    const options = ids
                        .filter(id => resolved.has(id))
                        .map(id => this.toOption(resolved.get(id)));

                    this.selectedOptions.set(options);
                    this.cdr.markForCheck();
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
                kinds: this.selectableKinds(),
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


    /** Settings outside the known kinds are dropped; none left means the backend offers both. */
    private selectableKinds(): PersonKind[] | undefined {
        const kinds = Array.isArray(this.data?.selectable)
            ? PERSON_KINDS.filter(kind => this.data.selectable.includes(kind))
            : [];

        return kinds.length ? kinds : undefined;
    }


    private toOption(selection: PersonSelection): PersonOption {
        return { ...selection, display_label: personDisplayLabel(selection) };
    }
}
