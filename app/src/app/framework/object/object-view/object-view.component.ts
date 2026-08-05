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
  ChangeDetectorRef,
  Component,
  OnDestroy,
  OnInit
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { BehaviorSubject, Subject, finalize, takeUntil } from 'rxjs';

import { CmdbMode } from 'src/app/framework/modes.enum';
import { TypeService } from 'src/app/framework/services/type.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { RenderResult } from 'src/app/framework/models/cmdb-render';
import { SpecialType } from 'src/app/framework/models/special-type';

@Component({
  selector: 'cmdb-object-view',
  templateUrl: './object-view.component.html',
  styleUrls: ['./object-view.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  standalone: false,
  host: {
    '(window:scroll)': 'onWindowScroll()'
  }
})
export class ObjectViewComponent implements OnInit, OnDestroy {

  /* --------------------------------------------------- PUBLIC STATE --------------------------------------------------- */

  public mode: CmdbMode = CmdbMode.View;
  public renderResult: RenderResult;
  public currentObjectID: number;
  public isGraphView = false;

  // Graph header object selector
  public allTypeIds: number[] = [];
  public typesLoaded = false;
  public selectedObjectIdForSelector: number | null = null;
  public isHeaderSelectorLoading = false;

  public get isSupernet(): boolean {
    return this.renderResult?.object_information?.special_type === SpecialType.SUPERNET;
  }

  public get isSubnet(): boolean {
    return this.renderResult?.object_information?.special_type === SpecialType.SUBNET;
  }

  private pendingSelectedId: number | null = null;
  private readonly unsubscribe = new Subject<void>();
  private readonly objectViewSubject = new BehaviorSubject<RenderResult>(undefined);

  /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

  constructor(
    private typeService: TypeService,
    private activateRoute: ActivatedRoute,
    private toastService: ToastService,
    private changesRef: ChangeDetectorRef,
    private router: Router
  ) {
    this.activateRoute.data.subscribe({
      next: (data: any) => this.objectViewSubject.next(data.object as RenderResult),
      error: (err) => this.toastService.error(err?.error?.message)
    });
  }

  ngOnInit(): void {
    // Auto-switch to graph view when the query param view=graph is present
    this.activateRoute.queryParamMap
      .pipe(takeUntil(this.unsubscribe))
      .subscribe(params => {
        if (params.get('view') === 'graph') {
          this.isGraphView = true;
        }
      });

    this.objectViewSubject.pipe(takeUntil(this.unsubscribe)).subscribe({
      next: (result) => {
        this.renderResult = result;
        this.currentObjectID = result?.object_information?.object_id;
        this.changesRef.markForCheck();
      },
      error: (err) => this.toastService.error(err?.error?.message)
    });

    // Load all type IDs for the graph object selector
    const params = { filter: '', limit: 0, sort: 'public_id', order: 1, page: 1 } as any;
    this.typeService.getTypes(params)
      .pipe(takeUntil(this.unsubscribe), finalize(() => this.changesRef.markForCheck()))
      .subscribe({
        next: (resp: any) => {
          this.allTypeIds = (resp?.results || []).map((type: any) => type.public_id);
          this.typesLoaded = true;
        },
        error: () => {
          this.typesLoaded = true;
        }
      });
  }

  ngOnDestroy(): void {
    this.unsubscribe.next();
    this.unsubscribe.complete();
  }

  /* --------------------------------------------------- EVENTS --------------------------------------------------- */

  public onWindowScroll(): void {
    const navbar = document.getElementsByClassName('object-view-navbar') as HTMLCollectionOf<Element>;
    if (!navbar[0]) {
      return;
    }
    const scrolled = document.body.scrollTop > 20;
    navbar[0].id = scrolled ? 'object-form-action' : '';
    navbar[0].classList.toggle('shadow', scrolled);
  }

  public toggleView(showGraph: boolean): void {
    this.isGraphView = showGraph;
  }

  /** Graph header selector change */
  public onGraphHeaderObjectChange(ids: number[]): void {
    this.pendingSelectedId = ids && ids.length ? ids[0] : null;
  }

  public openSelectedObject(): void {
    const targetId = this.pendingSelectedId ?? this.currentObjectID;
    if (!targetId || targetId === this.currentObjectID) {
      return;
    }
    this.router.navigate([`/framework/object/view/${targetId}`], { queryParams: { view: 'graph' } });
  }

  /**
   * Handles root node selection from the graph editor and navigates to the new
   * object's view page while preserving graph mode.
   */
  public onRootNodeSelected(objectId: number): void {
    if (!objectId || objectId === this.currentObjectID) {
      return;
    }
    this.router.navigate([`/framework/object/view/${objectId}`], { queryParams: { view: 'graph' } });
  }
}
