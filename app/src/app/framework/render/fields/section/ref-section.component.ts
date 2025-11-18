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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

import { Component, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { RenderFieldComponent } from '../components.fields';
import { ObjectService } from '../../../services/object.service';
import { CollectionParameters } from '../../../../services/models/api-parameter';
import { CmdbMode } from '../../../modes.enum';
import { takeUntil } from 'rxjs/operators';
import { BehaviorSubject, ReplaySubject } from 'rxjs';
import { APIGetMultiResponse } from '../../../../services/models/api-response';
import { RenderResult } from '../../../models/cmdb-render';
import { NgSelectComponent } from '@ng-select/ng-select';

@Component({
    selector: 'cmdb-ref-section',
    templateUrl: './ref-section.component.html',
    styleUrls: ['./ref-section.component.scss'],
    standalone: false
})
export class RefSectionComponent extends RenderFieldComponent implements OnInit, OnDestroy {

  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();
  public selected: BehaviorSubject<RenderResult> = new BehaviorSubject(null);
  public objects: Array<RenderResult> = [];
  public loading: boolean = false;

  public totalObjects: number = 0;
  private currentPage: number = 1;
  private maxPage: number = 1;

  @ViewChild('selection', { static: false }) refSelector: NgSelectComponent;

  constructor(private objectService: ObjectService<RenderResult>) {
    super();
  }

  private getApiParameters(page: number = 1): CollectionParameters {
    return {
      filter: { type_id: this.section.reference.type_id }, limit: 10, sort: 'public_id', order: 1, page,
      projection: { object_information: 1, type_information: 1, sections: 1, summary_line: 1, summaries: 1, fields: 1}
    } as CollectionParameters;
  }

  private loadObjectsFromApi(): void {
    this.loading = true;
    this.objectService.getObjects(this.getApiParameters(this.currentPage)).pipe(takeUntil(this.subscriber))
      .subscribe((apiResponse: APIGetMultiResponse<RenderResult>) => {
        this.objects = [...this.objects, ...apiResponse.results as Array<RenderResult>];
        this.totalObjects = apiResponse.total;
        this.maxPage = apiResponse.pager.total_pages;
      }).add(() => this.loading = false);
  }

  private triggerAPICall(): void {
    if (this.section && this.section?.reference) {
      if (this.maxPage && (this.currentPage <= this.maxPage)) {
        this.loadObjectsFromApi();
        this.currentPage += 1;
      }
    }
  }

  /**
   * Loads pre-selected/selected objects.
   * Objects that do not exist in the existing object list
   * are reloaded from the database if necessary.
   * @param publicID
   */
  public loadDisplayObject(publicID: number) {
    const foundObject = this.objects.find(f => f.object_information.object_id === publicID);
    if (foundObject) {
      this.selected.next(foundObject);
    }
    if (publicID) {
      this.objectService.getObject<RenderResult>(publicID).pipe(takeUntil(this.subscriber)).subscribe(
        found => this.selected.next(found)
      );
    }
    this.prepareReferencesData();
  }

  /**
   * Reference section fields is appended to the new data
   * @private
   */
  private prepareReferencesData() {
    if (this.mode === CmdbMode.Bulk && this.selected && this.selected.value) {
      const { value } = this.selected;
      const section = value.sections.find(s => s.name === this.section.reference.section_name);
      const fields: any[] = [];
      for (const name of section.fields) {
        const temp = this.selected.value.fields.find(f => f.name === name);
        if (temp) {
          fields.push(temp);
        }
      }
      const { type_id, type_name, type_label, icon } = value.type_information;
      this.data.references = { type_id, type_name, type_label, type_icon: icon, fields };
    }
  }

  /**
   * Allow to filter by custom search function
   * @param value search term as string
   * @param item RenderResult object
   */
  public searchRef(value: string, item: RenderResult) {
    const term: string = value.toLocaleLowerCase();
    const line: string = item.object_information.object_id + item.summary_line;
    const has_line: boolean = line.toLocaleLowerCase().indexOf(term) > -1 || line.toLocaleLowerCase().includes(term);
    return item.fields.find(f => has_line || ((typeof f.value === 'string' || f.value instanceof String)
      && f.value.toLocaleLowerCase().includes(term)));
  }

  /**
   * Fired while typing search term. Outputs search term with filtered items
   * @param term search term as string
   * @param items RenderResult objects
   */
  public onCustomSearch(term: string, items: RenderResult[]) {
    for (const obj of this.objects) {
      if (this.searchRef(term, obj)) {
        items = [...items, ...[obj]];
      } else {
        this.triggerAPICall();
      }
    }
    return items;
  }

  /**
   * Infinite Scrolling
   */
  public onScrollToEnd(): void {
    this.triggerAPICall();
  }

  public ngOnInit(): void {

    switch (this.mode) {
      case CmdbMode.Create:
      case CmdbMode.Edit:
      case CmdbMode.Bulk: {
        this.triggerAPICall();
        this.loadDisplayObject(this.controller.value);
        break;
      }

      case CmdbMode.View : {
        break;
      }
    }
  }

  public ngOnDestroy(): void {
    this.subscriber?.next();
    this.subscriber?.complete();
  }


}
