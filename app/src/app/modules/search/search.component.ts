/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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
import { Component, OnDestroy, OnInit } from '@angular/core';
import { AbstractControl, UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { ActivatedRoute, Router} from '@angular/router';
import { HttpParams } from '@angular/common/http';

import { ReplaySubject, takeUntil } from 'rxjs';

import { SearchService } from './services/search.service';

import { SearchResultList } from './models/search-result';
import { PageLengthEntry } from '../../layout/table/components/table-page-size/table-page-size.component';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    templateUrl: './search.component.html',
    styleUrls: ['./search.component.scss'],
    standalone: false
})
export class SearchComponent implements OnInit, OnDestroy {
    // Get the form control of the input field
    public get input(): AbstractControl {
        return this.searchInputForm.get('input');
    }

    // Default page size
    private readonly defaultLimit: number = 10;

    private skip: number = 0;
    public limit: number = this.defaultLimit;
    public currentPage: number = 1;

    // Max number of size for pagination truncate
    public maxNumberOfSites: number[];
    private initSearch: boolean = true;
    private initFilter: boolean = true;

    public searchInputForm: UntypedFormGroup;

    // List of search results
    public searchResultList: SearchResultList;
    public publicIdResult;
    public filterResultList: any[];

    public queryParameters: any = [];

    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    public readonly defaultResultSizeList: Array<PageLengthEntry> = [
        { label: '10', value: 10 },
        { label: '25', value: 25 },
        { label: '50', value: 50 },
        { label: '100', value: 100 },
        { label: '200', value: 200 }
    ];

    // Page size select form group
    public resultSizeForm: UntypedFormGroup = new UntypedFormGroup({
        size: new UntypedFormControl(this.limit),
    });

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    constructor(private route: ActivatedRoute, private searchService: SearchService, private router: Router) {
        this.searchInputForm = new UntypedFormGroup({
            input: new UntypedFormControl('', Validators.required)
        });
    }


    public ngOnInit(): void {
        this.route.queryParamMap.pipe(takeUntil(this.subscriber)).subscribe(params => {
            this.queryParameters = params.get('query');

            if (params.has('limit')) {
                this.limit = (+JSON.parse(params.get('limit')));
                this.resultSizeForm.get('size').setValue(this.limit);
            }

            if (params.has('page')) {
                this.currentPage = (+JSON.parse(params.get('page')));
            } else {
                this.currentPage = 1;
            }

            if (params.has('skip')) {
                this.skip = (+JSON.parse(params.get('skip')));
            } else {
                this.skip = 0;
            }

            this.initSearch = true;
            this.initFilter = (window.history.state.load || window.history.state.load === undefined);
            this.onSearch();
        });

        this.resultLength.valueChanges.pipe(takeUntil(this.subscriber))
        .subscribe((size: number) => {
            this.limit = size;
            this.router.navigate(
                [],
                {
                    relativeTo: this.route,
                    queryParams: { limit: this.limit },
                    queryParamsHandling: 'merge'
                }).then();
                this.onSearch();
        });
    }


    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
    }

/* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

    /**
     * Get the form control of the size selection
     */
    public get resultLength(): UntypedFormControl {
        return this.resultSizeForm.get('size') as UntypedFormControl;
    }


    /**
     * Triggers the actual search api call
     */
    public onSearch(): void {
        this.publicIdResult = undefined;
        let params = new HttpParams();
        params = params.set('limit', this.limit.toString());
        params = params.set('skip', this.skip.toString());

        this.searchService.postSearch(this.queryParameters, params).pipe(
            takeUntil(this.subscriber)).subscribe((results: SearchResultList) => {
                this.searchResultList = results;
                this.filterResultList = this.initFilter && results !== null ? results.groups : this.filterResultList;

                if (this.initSearch) {
                    this.maxNumberOfSites = Array.from({ length: (this.searchResultList.total_results) }, (v, k) => k + 1);
                    this.initSearch = false;
                    this.initFilter = false;
                }
            }
        );
    
        let localParameters = JSON.parse(this.queryParameters);

        if (localParameters.length === 1) {
            localParameters[0].searchForm = 'publicID';
            localParameters = JSON.stringify(localParameters);
            this.searchService.postSearch(localParameters, params).pipe(takeUntil(this.subscriber))
            .subscribe((results: SearchResultList) => {
                    if (results !== null && results.results.length > 0) {
                        this.publicIdResult = results.results[0];
                    }
                }
            );
        } 
    }


    /**
     * Pagination page was changed.
     * @param event: Data from the change event.
     */
    public onChangePage(event): void {
        this.currentPage = event;
        this.skip = (this.currentPage - 1) * this.limit;
        this.setPageParam(this.currentPage);
        this.onSearch();

    }


    private setPageParam(page): void {
        this.router.navigate(
            [],
            {
                relativeTo: this.route,
                queryParams: { page, skip: this.skip, query: this.queryParameters },
                queryParamsHandling: 'merge'
            }
        ).then();
    }
}