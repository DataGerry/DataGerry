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
import { Injectable, inject } from '@angular/core';

import { Observable, Subject, forkJoin, of } from 'rxjs';
import { map, shareReplay } from 'rxjs/operators';

import { ExtendableOptionService } from 'src/app/toolbox/isms/services/extendable-option.service';
import { ExtendableOption } from 'src/app/framework/models/object-group.model';
import { Field, FieldOption } from 'src/app/framework/models/cmdb-section-template';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Resolves a field's `option_type` into the `options` list select renderers expect, cached per type.
 * Option value is the `public_id` as a string.
 */
@Injectable({
    providedIn: 'root'
})
export class ExtendableOptionCatalogService {
    private readonly extendableOptionService = inject(ExtendableOptionService);
    private readonly catalog = new Map<string, Observable<FieldOption[]>>();
    private readonly invalidated = new Subject<string | null>();

    /** Emits the dropped OptionType, or null when the whole catalog was dropped. */
    public readonly changes$: Observable<string | null> = this.invalidated.asObservable();

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** Cached select options of one OptionType. */
    public optionsFor(optionType: string): Observable<FieldOption[]> {
        return this.optionsForTypes([optionType]).pipe(
            map((optionsByType) => optionsByType.get(optionType) ?? [])
        );
    }


    /** Cached select options of any number of OptionTypes, keyed by type. */
    public optionsForTypes(optionTypes: readonly string[]): Observable<Map<string, FieldOption[]>> {
        const wanted = [...new Set(optionTypes)];

        if (wanted.length === 0) {
            return of(new Map<string, FieldOption[]>());
        }

        const streams = this.streamsFor(wanted);

        return forkJoin(streams).pipe(
            map((lists) => new Map(wanted.map((optionType, index) => [optionType, lists[index]])))
        );
    }


    /** Copies the fields with every `option_type` select resolved. The input stays untouched. */
    public resolveFieldOptions<T extends Field>(fields: readonly T[]): Observable<T[]> {
        return this.optionsForTypes(this.collectOptionTypes(fields)).pipe(
            map((optionsByType) => fields.map((field) => field.option_type
                ? { ...field, options: optionsByType.get(field.option_type) ?? [] }
                : { ...field }))
        );
    }


    /** Drops one cached list, or all of them, after the options were changed. */
    public invalidate(optionType?: string): void {
        if (optionType) {
            this.catalog.delete(optionType);
        } else {
            this.catalog.clear();
        }

        this.invalidated.next(optionType ?? null);
    }


    /** True when `optionType` has to be read again after the reported change. */
    public affects(optionType: string, changed: string | null): boolean {
        return !!optionType && (changed === null || changed === optionType);
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** Fetches every type not cached yet in ONE request; each type then reads its own slice. */
    private streamsFor(optionTypes: string[]): Observable<FieldOption[]>[] {
        const missing = optionTypes.filter((optionType) => !this.catalog.has(optionType));

        if (missing.length > 0) {
            const batch = this.fetch(missing);

            for (const optionType of missing) {
                this.catalog.set(optionType, batch.pipe(
                    map((optionsByType) => optionsByType.get(optionType) ?? [])
                ));
            }
        }

        return optionTypes.map((optionType) => this.catalog.get(optionType));
    }


    /** Shared so concurrent callers and later single-type lookups reuse the same response. */
    private fetch(optionTypes: string[]): Observable<Map<string, FieldOption[]>> {
        return this.extendableOptionService.getExtendableOptionsByTypes(optionTypes).pipe(
            map((response) => this.groupByOptionType(response?.results ?? [])),
            shareReplay({ bufferSize: 1, refCount: false })
        );
    }


    private groupByOptionType(options: ExtendableOption[]): Map<string, FieldOption[]> {
        const grouped = new Map<string, FieldOption[]>();

        for (const option of options) {
            const list = grouped.get(option.option_type) ?? [];
            list.push({ name: String(option.public_id), label: option.value });
            grouped.set(option.option_type, list);
        }

        return grouped;
    }


    private collectOptionTypes(fields: readonly Field[]): string[] {
        return fields
            .map((field) => field.option_type)
            .filter((optionType): optionType is string => !!optionType);
    }
}
