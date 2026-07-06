import { Component, inject, AfterViewInit, ChangeDetectorRef, Input, OnDestroy, OnInit, ViewEncapsulation } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { LoaderService } from 'src/app/core/services/loader.service';

@Component({
  selector: 'app-opencelium-logs-modal',
  templateUrl: './opencelium-logs-modal.component.html',
  styleUrls: ['./opencelium-logs-modal.component.scss'],
  standalone: false,
  encapsulation: ViewEncapsulation.None
})
export class OpenCeliumLogsModalComponent implements AfterViewInit, OnDestroy {
  public readonly activeModal = inject(NgbActiveModal);
  private readonly loaderService = inject(LoaderService);
  private readonly cdr = inject(ChangeDetectorRef);

  public isLoading$ = this.loaderService.isLoading$;

  @Input() baseUrl = '';
  @Input() token = '';
  @Input() executionId: number | null = null;
  @Input() isFullscreen = false;
  @Input() onToggleFullscreen?: (next: boolean) => void;

  ngAfterViewInit(): void {
    Promise.resolve().then(() => {
      this.loaderService.show();
      this.cdr.detectChanges();
    });
  }

  ngOnDestroy(): void {
    this.loaderService.hide();
  }
  
  toggleFullscreen(): void {
    this.isFullscreen = !this.isFullscreen;
    this.onToggleFullscreen?.(this.isFullscreen);
  }


  onLogViewLoaded(): void {
    this.loaderService.hide();
  }
}
