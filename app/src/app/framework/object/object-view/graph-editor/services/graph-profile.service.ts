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
import { Observable } from 'rxjs';
import { map, finalize } from 'rxjs/operators';
import { FilterProfile } from '../interfaces/graph.interfaces';
import { BaseApiService } from 'src/app/core/services/base-api.service';
import { TypeService } from 'src/app/framework/services/type.service';
import { RelationService } from 'src/app/framework/services/relaion.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { ProfileManagerModalComponent } from '../modals/profile-manager/profile-manager-modal.component';

@Injectable({ providedIn: 'root' })
export class GraphProfileService extends BaseApiService<FilterProfile> {
  public servicePrefix = 'ci_explorer/profile';

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
  loadFilterOptions(
    typeService: TypeService,
    relationService: RelationService,
    loaderService: LoaderService,
    showErrorNotification: (message: string) => void
  ): Observable<{ types: any[], relations: any[] }> {
    return new Observable(observer => {
      const params = { filter: '', limit: 0, sort: 'sort', order: 1, page: 1 };
      let typesResult: any[] = [];
      let relationsResult: any[] = [];

      loaderService.show();

      typeService.getTypes(params)
        .pipe(finalize(() => loaderService.hide()))
        .subscribe({
          next: resp => {
            const list = Array.isArray(resp) ? resp : resp?.results;
            typesResult = list?.map(t => ({
              public_id: t?.public_id,
              display_name: t?.label || t?.name || `#${t.public_id}`
            }));
            
            // Now load relations
            loaderService.show();
            relationService.getRelations()
              .pipe(finalize(() => loaderService.hide()))
              .subscribe({
                next: relResp => {
                  const relList = Array.isArray(relResp) ? relResp : relResp?.results;
                  relationsResult = relList?.map(r => ({
                    public_id: r?.public_id,
                    display_name: r?.relation_name || r?.label || `#${r?.public_id}`
                  }));
                  observer.next({ types: typesResult, relations: relationsResult });
                  observer.complete();
                },
                error: e => {
                  showErrorNotification(e?.error?.message);
                  observer.error(e);
                }
              });
          },
          error: e => {
            showErrorNotification(e?.error?.message);
            observer.error(e);
          }
        });
    });
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

    const modalRef = modalService.open(ProfileManagerModalComponent, {
      size: 'xl',
      backdrop: 'static'
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
    relationsFilter: number[],
    loadInitialGraph: (reset: boolean) => void,
    showNotification: (message: string, type: 'info' | 'success' | 'error') => void
  ): { typesFilter: number[], relationsFilter: number[] } {
    const profile = profiles.find(p => p.public_id === selectedProfileId);
    if (profile) {
      const newTypesFilter = profile.types_filter || [];
      const newRelationsFilter = profile.relations_filter || [];
      showNotification(`Applied profile: ${profile.name}`, 'success');
      return { typesFilter: newTypesFilter, relationsFilter: newRelationsFilter };
    }
    return { typesFilter, relationsFilter };
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
    const modalRef = modalService.open(ProfileManagerModalComponent, {
      size: 'xl',
      backdrop: 'static',
      scrollable: true
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
