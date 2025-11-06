import { ChangeDetectionStrategy, ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { CoreModule } from 'src/app/core/core.module';
import { Router } from '@angular/router';
import { TypeService } from 'src/app/framework/services/type.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { finalize } from 'rxjs/operators';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';

@Component({
  standalone: true,
  selector: 'app-ci-explorer-launch',
  templateUrl: './ci-explorer-launch.page.html',
  imports: [CommonModule, CoreModule]
})
export class CiExplorerLaunchPage implements OnInit {
  public typeIds: number[] = [];
  public selectedId: number | null = null;
  public loading = false;

  constructor(private router: Router, private typeService: TypeService, private loader: LoaderService) {}

  ngOnInit(): void {
    // Fetch all type IDs so objects can be loaded by selector
    const params: any = { filter: '', limit: 0, sort: 'public_id', order: 1, page: 1 };
    this.loading = true;
    this.loader.show();
    this.typeService.getTypes(params)
      .pipe(finalize(() => { this.loading = false; this.loader.hide(); }))
      .subscribe((resp: APIGetMultiResponse<any>) => {
        const ids = (resp?.results || []).map((t: any) => t.public_id);
        // If no types are returned or something fails, pass an empty array explicitly to trigger fallback UX
        this.typeIds = Array.isArray(ids) && ids.length > 0 ? ids : [];
      }, _ => {
        this.typeIds = [];
      });
  }

  onSelect(ids: number[]): void {
    this.selectedId = ids && ids.length ? ids[0] : null;
  }
  open(): void {
    if (!this.selectedId) return;
    this.router.navigate(['/framework/object/view', this.selectedId], { queryParams: { view: 'graph' } });
  }
}
