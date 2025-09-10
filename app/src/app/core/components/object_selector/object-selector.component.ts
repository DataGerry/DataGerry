// import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
// import { CollectionParameters } from 'src/app/services/models/api-parameter';
// import { APIGetMultiResponse } from 'src/app/services/models/api-response';
// import { LoaderService } from 'src/app/core/services/loader.service';
// import { finalize } from 'rxjs';
// import { RenderResult } from 'src/app/framework/models/cmdb-render';
// import { ObjectService } from 'src/app/framework/services/object.service';
// import { ToastService } from 'src/app/layout/toast/toast.service';


// @Component({
//   selector: 'app-object-selector',
//   templateUrl: './object-selector.component.html',
//   styleUrls: ['./object-selector.component.scss']
// })
// export class ObjectSelectorComponent implements OnInit {
//   /**
//    * Which type IDs to fetch from the server. If empty, no fetch is performed.
//    */
//   @Input() typeIds: number[] = [];

//   /**
//    * Whether multiple selection is allowed.
//    */
//   @Input() multiple = false;

//   /**
//    * The parent may pass an array of numeric IDs or an array of full objects.
//    * so we can display them properly in the ng-select.
//    */
//   @Input() selectedIds: any[] = [];

//   /**
//    * This event emits ONLY an array of numeric IDs (e.g. [2, 5, 7])
//    */
//   @Output() selectionChange = new EventEmitter<number[]>();

//   /**
//    * The fetched list of objects available for selection
//    */
//   public objectList: RenderResult[] = [];

//   /**
//    *  the label templates can show the entire object details.
//    */
//   public selectedObjects: RenderResult[] = [];
//   public isLoading$ = this.loaderService.isLoading$;


//   constructor(private objectService: ObjectService,   private loaderService: LoaderService, private toast: ToastService) {}

//   ngOnInit(): void {
//     this.fetchObjects();
//   }

//   private fetchObjects(): void {
//     if (!this.typeIds || this.typeIds.length === 0) {
//       this.initSelectedObjects();
//       return;
//     }

//     const params: CollectionParameters = {
//       filter: [{ $match: { type_id: { $in: this.typeIds } } }],
//       limit: 0,
//       sort: 'public_id',
//       order: 1,
//       page: 1
//     };

//     this.loaderService.show();
//     this.objectService.getObjects(params).pipe(finalize(() => this.loaderService.hide())).subscribe({
//       next: (response: APIGetMultiResponse<RenderResult>) => {
//         this.objectList = response.results || [];
//         this.initSelectedObjects();
//       },
//       error: (err) => {
//         this.toast.error(err?.error?.message);
//         this.objectList = [];
//         this.initSelectedObjects(); // fallback
//       }
//     });
//   }

//   /**
//    * Once we have objectList, we match up our parent's passed-in selectedIds.
//    * If the parent passed in numeric IDs, we look them up in objectList.
//    * If the parent passed in full objects, we extract their IDs and do the same.
//    */
//   private initSelectedObjects(): void {
//     // Convert anything in selectedIds to numeric object IDs
//     const numericIds: number[] = (this.selectedIds || []).map(item => {
//       if (typeof item === 'number') {
//         return item;
//       } else if (item && item.object_information?.object_id) {
//         return item.object_information.object_id;
//       }
//       return null;
//     }).filter(x => x !== null) as number[];

//     // Now build the "selectedObjects" array from our fetched objectList
//     this.selectedObjects = this.objectList.filter(obj =>
//       numericIds.includes(obj.object_information.object_id)
//     );

//   }

//   /**
//    * Called whenever the user changes selection in <ng-select>.
//    * If multiple=true, selectedValue is an array of RenderResult.
//    * If multiple=false, selectedValue is a single RenderResult (or null).
//    */
//   public onSelectionChange(selectedValue: RenderResult | RenderResult[] | null): void {
//     if (!selectedValue) {
//       // No selection
//       this.selectedObjects = [];
//       this.selectionChange.emit([]);
//       return;
//     }

//     // Convert single to array if multiple is on
//     const arrayVal = Array.isArray(selectedValue) ? selectedValue : [selectedValue];
//     this.selectedObjects = arrayVal;

//     // Map the selected objects to numeric IDs
//     const idArray = arrayVal.map(obj => obj.object_information.object_id);
//     this.selectionChange.emit(idArray);

//   }

//   /**
//    *  grouping logic for <ng-select> (to display by type label).
//    */
//   public groupByFn = (item: RenderResult) => item.type_information.type_label;
//   public groupValueFn = (_: string, children: RenderResult[]) => ({
//     name: children[0].type_information.type_label,
//     total: children.length
//   });
// }


import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { CollectionParameters } from 'src/app/services/models/api-parameter';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';
import { LoaderService } from 'src/app/core/services/loader.service';
import { finalize } from 'rxjs';
import { RenderResult } from 'src/app/framework/models/cmdb-render';
import { ObjectService } from 'src/app/framework/services/object.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

@Component({
  selector: 'app-object-selector',
  templateUrl: './object-selector.component.html',
  styleUrls: ['./object-selector.component.scss']
})
export class ObjectSelectorComponent implements OnInit {
  @Input() typeIds: number[] = [];
  @Input() multiple = false;
  @Input() selectedIds: any[] = [];
  @Input() isViewMode = false;
  @Output() selectionChange = new EventEmitter<number[]>();

  public objectList: RenderResult[] = [];
  public selectedObjects: RenderResult[] | RenderResult | null = null; // Updated type
  public isLoading$ = this.loaderService.isLoading$;

  constructor(
    private objectService: ObjectService,
    private loaderService: LoaderService,
    private toast: ToastService
  ) {}

  ngOnInit(): void {
    this.fetchObjects();
  }

  private fetchObjects(): void {
    if (!this.typeIds || this.typeIds.length === 0) {
      this.initSelectedObjects();
      return;
    }

    const params: CollectionParameters = {
      filter: [{ $match: { type_id: { $in: this.typeIds } } }],
      limit: 0,
      sort: 'public_id',
      order: 1,
      page: 1
    };

    this.loaderService.show();
    this.objectService.getObjects(params).pipe(finalize(() => this.loaderService.hide())).subscribe({
      next: (response: APIGetMultiResponse<RenderResult>) => {
        this.objectList = response.results || [];
        this.initSelectedObjects();
      },
      error: (err) => {
        this.toast.error(err?.error?.message);
        this.objectList = [];
        this.initSelectedObjects();
      }
    });
  }

  private initSelectedObjects(): void {
    const numericIds: number[] = (this.selectedIds || []).map(item => {
      if (typeof item === 'number') {
        return item;
      } else if (item && item.object_information?.object_id) {
        return item.object_information.object_id;
      }
      return null;
    }).filter(x => x !== null) as number[];

    if (this.multiple) {
      this.selectedObjects = this.objectList.filter(obj =>
        numericIds.includes(obj.object_information.object_id)
      );
    } else {
      const id = numericIds[0]; // Take the first ID for single selection
      this.selectedObjects = id ? this.objectList.find(obj => obj.object_information.object_id === id) || null : null;
    }
  }

  public onSelectionChange(selectedValue: RenderResult | RenderResult[] | null): void {
    // Case 1: selectedValue is null or undefined
    if (!selectedValue) {
      this.selectedObjects = this.multiple ? [] : null;
      this.selectionChange.emit([]);
      return;
    }
  
    // Case 2: Multiple selection (expecting an array)
    if (this.multiple) {
      if (Array.isArray(selectedValue)) {
        this.selectedObjects = selectedValue; // Type: RenderResult[]
        const idArray = selectedValue.map(obj => obj.object_information.object_id);
        this.selectionChange.emit(idArray);
      } else {
        console.error('Expected an array for multiple selection, but got a single object');
      }
    }
    // Case 3: Single selection (expecting a single object)
    else {
      if (!Array.isArray(selectedValue)) {
        this.selectedObjects = selectedValue; // Type: RenderResult
        this.selectionChange.emit([selectedValue.object_information.object_id]);
      } else {
        console.error('Expected a single object for single selection, but got an array');
      }
    }
  }

  public groupByFn = (item: RenderResult) => item.type_information.type_label;
  public groupValueFn = (_: string, children: RenderResult[]) => ({
    name: children[0].type_information.type_label,
    total: children.length
  });
}