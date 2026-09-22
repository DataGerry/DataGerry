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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Injectable } from '@angular/core';
import { forkJoin, Observable } from 'rxjs';
import { map, finalize } from 'rxjs/operators';
import { FilterProfile } from '../interfaces/graph.interfaces';
import { BaseApiService } from 'src/app/core/services/base-api.service';
import { TypeService } from 'src/app/framework/services/type.service';
import { RelationService } from 'src/app/framework/services/relaion.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { ProfileManagerModalComponent } from '../modals/profile-manager/profile-manager-modal.component';
import { FullscreenModalService } from 'src/app/core/services/fullscreen-modal.service';
import { ApiCallService } from 'src/app/services/api-call.service';

export interface FilterOption {
  public_id: number;
  display_name: string;
}

/** Both endpoints answer either with a bare list or with a paged envelope. */
function toOptions(response: any, label: (item: any) => string | undefined): FilterOption[] {
  const list = Array.isArray(response) ? response : response?.results;

  return (list ?? []).map((item: any) => ({
    public_id: item?.public_id,
    display_name: label(item) || `#${item?.public_id}`
  }));
}

@Injectable({ providedIn: 'root' })
export class GraphProfileService extends BaseApiService<FilterProfile> {
  public servicePrefix = 'ci_explorer/profile';

  constructor(
    api: ApiCallService,
    private fullscreenModalService: FullscreenModalService
  ) {
    super(api);
  }

  getProfiles(): Observable<FilterProfile[]> {
    return this.handleGetRequest<any>(`${this.servicePrefix}`)
      .pipe(
        map(response => response.results)
      );
  }

  createProfile(profile: FilterProfile): Observable<FilterProfile> {
    return this.handlePostRequest<FilterProfile>(`${this.servicePrefix}`, profile);
  }

  updateProfile(id: number, profile: FilterProfile): Observable<FilterProfile> {
    return this.handlePutRequest<FilterProfile>(`${this.servicePrefix}/${id}`, profile);
  }

  deleteProfile(id: number): Observable<void> {
    return this.handleDeleteRequest<void>(`${this.servicePrefix}/${id}`);
  }

  /**
   * Loads filter options for types and relations
   */
  /** Both lists feed one filter bar, so they are fetched together rather than in sequence. */
  loadFilterOptions(
    typeService: TypeService,
    relationService: RelationService,
    loaderService: LoaderService
  ): Observable<{ types: FilterOption[], relations: FilterOption[] }> {
    // Only the option label is built from the answer, so the rest of the type is left behind.
    const params = {
      filter: '',
      projection: { public_id: 1, label: 1, name: 1 },
      limit: 0,
      sort: 'sort',
      order: 1,
      page: 1
    };

    loaderService.show();

    return forkJoin({
      types: typeService.getTypes(params).pipe(
        map(resp => toOptions(resp, t => t?.label || t?.name))
      ),
      relations: relationService.getRelations().pipe(
        map(resp => toOptions(resp, r => r?.relation_name || r?.label))
      )
    }).pipe(finalize(() => loaderService.hide()));
  }

  /**
   * Saves current filters as a new profile
   */
  saveCurrentFiltersAsProfile(
    modalService: NgbModal,
    typeOptionList: any[],
    relationOptionList: any[],
    typesFilter: number[],
    relationsFilter: number[],
    hasActiveFilters: () => boolean,
    showNotification: (message: string, type: 'info' | 'success' | 'error') => void
  ): void {
    if (!hasActiveFilters()) {
      showNotification('No filters to save', 'info');
      return;
    }

    const modalRef = this.fullscreenModalService.open(modalService, ProfileManagerModalComponent, {
      size: 'xl',
      backdrop: 'static',
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });

    modalRef.componentInstance.initializeOptions(typeOptionList, relationOptionList);

    // Pre-fill with current filters
    modalRef.componentInstance.profileForm.patchValue({
      name: '',
      types_filter: typesFilter,
      relations_filter: relationsFilter
    });
  }

  /**
   * Applies a selected profile
   */
  applyProfile(
    profiles: FilterProfile[],
    selectedProfileId: number | null,
    typesFilter: number[],
    relationsFilter: number[]
  ): { typesFilter: number[], relationsFilter: number[] } {
    const profile = profiles.find(p => p.public_id === selectedProfileId);

    if (!profile) {
      return { typesFilter, relationsFilter };
    }
    return {
      typesFilter: profile.types_filter || [],
      relationsFilter: profile.relations_filter || []
    };
  }

  /**
   * Opens the profile manager modal
   */
  openProfileManager(
    modalService: NgbModal,
    typeOptionList: any[],
    relationOptionList: any[],
    loadProfiles: () => void
  ): void {
    const modalRef = this.fullscreenModalService.open(modalService, ProfileManagerModalComponent, {
      size: 'xl',
      backdrop: 'static',
      scrollable: true,
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });

    modalRef.componentInstance.initializeOptions(typeOptionList, relationOptionList);

    modalRef.result.then((selectedProfile: FilterProfile) => {
      if (selectedProfile) {
        // Profile was applied - the component will handle this
      }
      loadProfiles();
    }).catch(() => {
      loadProfiles();
    });
  }

  /**
   * Checks if there are active filters
   */
  hasActiveFilters(typesFilter: number[], relationsFilter: number[]): boolean {
    return (typesFilter?.length > 0) || (relationsFilter?.length > 0);
  }
}
