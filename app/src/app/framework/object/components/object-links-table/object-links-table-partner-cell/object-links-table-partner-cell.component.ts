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

import { Component, Input, OnDestroy, OnInit } from '@angular/core';
import { LinkService } from '../../../../services/link.service';
import { CmdbLink } from '../../../../models/cmdb-link';
import { ObjectService } from '../../../../services/object.service';
import { RenderResult } from '../../../../models/cmdb-render';
import { CmdbObject } from '../../../../models/cmdb-object';
import { BehaviorSubject, Observable, ReplaySubject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

@Component({
  selector: 'cmdb-object-links-table-partner-cell',
  templateUrl: './object-links-table-partner-cell.component.html',
  styleUrls: ['./object-links-table-partner-cell.component.scss']
})
export class ObjectLinksTablePartnerCellComponent implements OnInit, OnDestroy {

  /**
   * Global un-subscriber for http calls to the rest backend.
   */
  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

  @Input() public objectID: number;

  public link: CmdbLink;

  @Input('link')
  public set Link(link: CmdbLink) {
    this.link = link;
    this.partnerIDSubject.next(this.linkService.getPartnerID(this.objectID, this.link));
  }

  public errorLoading: boolean = false;

  public partnerIDSubject: BehaviorSubject<number> = new BehaviorSubject<number>(undefined);
  public partnerIDObservable: Observable<number> = this.partnerIDSubject.asObservable();
  public partnerObject: RenderResult | CmdbObject;

  constructor(private linkService: LinkService, private objectService: ObjectService) {
  }

  public ngOnInit(): void {
    this.partnerIDObservable.pipe(takeUntil(this.subscriber)).subscribe((id: number) => {
      this.objectService.getObject(id).pipe(takeUntil(this.subscriber))
      .subscribe((result: RenderResult | CmdbObject) => {
          this.partnerObject = result;
        },
        () => this.errorLoading = true);
    });
  }

  /**
   * Unsubscribe all on component destroy.
   */
  public ngOnDestroy(): void {
    this.subscriber?.next();
    this.subscriber?.complete();
  }


}
