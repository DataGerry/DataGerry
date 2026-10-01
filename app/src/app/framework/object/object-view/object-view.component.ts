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
  OnInit,
  inject
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { BehaviorSubject, EMPTY, Observable, Subject, catchError, filter, finalize, switchMap, takeUntil } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { CmdbMode } from 'src/app/framework/modes.enum';
import { ObjectChangeNotifierService } from 'src/app/framework/services/object-change-notifier.service';
import { ObjectService } from 'src/app/framework/services/object.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { RenderResult } from 'src/app/framework/models/cmdb-render';
import { SpecialType } from 'src/app/framework/models/special-type';
import { LicenseFeature } from 'src/app/settings/license-management/models/license.model';
import { PremiumFeatureService } from 'src/app/settings/license-management/premium-feature/premium-feature.service';
import { RACK_VIEW_RIGHT } from './rack-overview/models/rack-overview.types';
import { CI_EXPLORER_VIEW_RIGHT } from 'src/app/framework/models/ci-explorer.model';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { PORT_VIEW_RIGHT } from './ports-overview/models/ports-overview.types';
import { ObjectViewMode } from './object-view-mode';

const TOGGLE_ACTIVE_CLASS = 'btn-sm btn-primary object-view-toggle__btn';
const TOGGLE_IDLE_CLASS = 'btn-sm btn-outline-primary object-view-toggle__btn';

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
  public viewMode = ObjectViewMode.TABLE;
  public readonly viewModes = ObjectViewMode;
  /** The section only frames the rack drawing, so it needs the rack view right. */
  public readonly rackViewRight = RACK_VIEW_RIGHT;
  /** The graph view is the CI Explorer, so its toggle answers to the CI Explorer view right. */
  public readonly ciExplorerViewRight = CI_EXPLORER_VIEW_RIGHT;
  /** The cabling view reads the port routes, so its toggle answers to the port view right. */
  public readonly portViewRight = PORT_VIEW_RIGHT;

  // Graph header object selector
  public selectedObjectIdForSelector: number | null = null;
  public isHeaderSelectorLoading = false;

  public get isSupernet(): boolean {
    return this.renderResult?.object_information?.special_type === SpecialType.SUPERNET;
  }

  public get isSubnet(): boolean {
    return this.renderResult?.object_information?.special_type === SpecialType.SUBNET;
  }

  public get isRack(): boolean {
    return this.renderResult?.object_information?.special_type === SpecialType.RACK;
  }

  /** The rack view belongs to the licensed IPAM feature, so an unlicensed instance never renders it. */
  public get showRackView(): boolean {
    return this.isRack && this.premiumFeatureService.isAvailable(LicenseFeature.Ipam);
  }

  /** Cabling is drawn from ports: the type has to use them, and the port routes sit behind the IPAM licence. */
  public get cablingAvailable(): boolean {
    return this.renderResult?.type_information?.uses_ports === true
      && this.premiumFeatureService.isAvailable(LicenseFeature.Ipam);
  }

  public get isGraphView(): boolean {
    return this.viewMode === ObjectViewMode.GRAPH;
  }

  /** Falls back to the table while the object on screen cannot have a cabling view. */
  public get isCablingView(): boolean {
    return this.viewMode === ObjectViewMode.CABLING && this.cablingAvailable;
  }

  public get isTableView(): boolean {
    return !this.isGraphView && !this.isCablingView;
  }

  private pendingSelectedId: number | null = null;
  private readonly unsubscribe = new Subject<void>();
  /** What the view is built from. Fed by the route on arrival, and by a re-read after a write. */
  private readonly objectViewSubject = new BehaviorSubject<RenderResult>(undefined);
  private readonly objectService = inject(ObjectService);
  private readonly objectChanges = inject(ObjectChangeNotifierService);
  private readonly loaderService = inject(LoaderService);
  private readonly premiumFeatureService = inject(PremiumFeatureService);
  private readonly permissionService = inject(PermissionService);

  /** `?view=graph` and `?view=cabling` are links anyone can follow, so the rights decide whether they open. */
  private readonly canViewCiExplorer = this.permissionService.hasRight(CI_EXPLORER_VIEW_RIGHT)
    || this.permissionService.hasExtendedRight(CI_EXPLORER_VIEW_RIGHT);
  private readonly canViewPorts = this.permissionService.hasRight(PORT_VIEW_RIGHT)
    || this.permissionService.hasExtendedRight(PORT_VIEW_RIGHT);

  /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

  constructor(
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
    this.activateRoute.queryParamMap
      .pipe(takeUntil(this.unsubscribe))
      .subscribe(params => {
        const view = params.get('view');

        if (view === ObjectViewMode.GRAPH || view === ObjectViewMode.CABLING) {
          this.toggleView(view);
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

    // Written from elsewhere on the page - the rack view saves the rack's notes - the object is read
    // again and the whole view is rebuilt from the answer, rather than a value being copied into it.
    this.objectChanges.changed$
      .pipe(
        filter((objectId) => objectId === this.currentObjectID),
        switchMap((objectId) => this.readObject(objectId)),
        takeUntil(this.unsubscribe)
      )
      .subscribe((result) => this.objectViewSubject.next(result));
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

  /** A view whose right is missing is refused, and the page stays on the view it shows. */
  public toggleView(mode: ObjectViewMode): void {
    if ((mode === ObjectViewMode.GRAPH && !this.canViewCiExplorer)
      || (mode === ObjectViewMode.CABLING && !this.canViewPorts)) {
      return;
    }

    this.viewMode = mode;
  }

  public toggleClass(active: boolean): string {
    return active ? TOGGLE_ACTIVE_CLASS : TOGGLE_IDLE_CLASS;
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

  /* --------------------------------------------------- PRIVATE FUNCTIONS --------------------------------------------------- */

  private readObject(objectId: number): Observable<RenderResult> {
    this.loaderService.show();

    return this.objectService.getObject<RenderResult>(objectId).pipe(
      // An empty answer is dropped rather than shown: the view reads the object without guarding it,
      // so handing it nothing would take the page down instead of leaving the old values up.
      filter((result): result is RenderResult => !!result),
      // Reported here rather than in the subscriber: an error reaching the outer stream would end it,
      // and no later write would be picked up.
      catchError((err) => {
        this.toastService.error(err?.error?.message);

        return EMPTY;
      }),
      finalize(() => this.loaderService.hide())
    );
  }
}
