import { Component, inject, EventEmitter, HostListener, Input, Output } from '@angular/core';
import { finalize } from 'rxjs';
import { NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';

import { AutomationsService } from '../../services/automations.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { AuthService } from 'src/app/modules/auth/services/auth.service';
import { ConnectionService } from 'src/app/modules/connect/services/connection.service';
import { environment } from 'src/environments/environment';
import { OpenCeliumLogsModalComponent } from '../opencelium-logs-modal/opencelium-logs-modal.component';

type LogStatus = 's' | 'f';
type LogEntry = {
  log_date: string | { $date?: number };
  connection_id: number;
  status: LogStatus;
  execution_id: number;
};

@Component({
  selector: 'app-automation-logs-menu',
  templateUrl: './automation-logs-menu.component.html',
  styleUrls: ['./automation-logs-menu.component.scss'],
  standalone: false,
})
export class AutomationLogsMenuComponent {
  @Input() schedulerId?: number;
  @Input() status: LogStatus = 's';
  @Output() logsModalOpenChange = new EventEmitter<boolean>();

  public isOpen = false;
  public isLoading = false;
  public entries: LogEntry[] = [];
  public selectedExecutionId: number | null = null;
  private isFullscreen = false;
  private modalRef?: NgbModalRef;
  private readonly menuId = `automation-logs-${Math.random().toString(36).slice(2)}`;

  private readonly automationsService = inject(AutomationsService);
  private readonly toast = inject(ToastService);
  private readonly modalService = inject(NgbModal);
  private readonly authService = inject(AuthService);
  private readonly connectionService = inject(ConnectionService);

  @HostListener('document:click')
  onDocumentClick() {
    if (this.isOpen) {
      this.isOpen = false;
    }
  }

  @HostListener('window:automationLogsMenuOpen', ['$event'])
  onMenuOpenEvent(event: Event): void {
    const detail = (event as CustomEvent<{ id?: string }>).detail;
    if (this.isOpen && detail?.id && detail.id !== this.menuId) {
      this.isOpen = false;
    }
  }

  toggleMenu(event: Event): void {
    event?.stopPropagation();
    if (!this.schedulerId) {
      return;
    }
    this.isOpen = !this.isOpen;
    if (this.isOpen && !this.entries.length && !this.isLoading) {
      this.loadLogs();
    }
    if (this.isOpen) {
      window.dispatchEvent(new CustomEvent('automationLogsMenuOpen', { detail: { id: this.menuId } }));
    }
  }

  loadLogs(): void {
    if (!this.schedulerId) {
      return;
    }
    this.isLoading = true;
    this.automationsService.getSchedulerLogs(this.schedulerId, this.status)
      .pipe(finalize(() => {
        this.isLoading = false;
      }))
      .subscribe({
        next: (logs) => {
          this.entries = Array.isArray(logs) ? logs : [];
        },
        error: (err) => {
          this.toast.error(err?.error?.message || 'Failed to load logs');
          this.entries = [];
        }
      });
  }

  selectLogEntry(entry: LogEntry, event: Event): void {
    event?.stopPropagation();
    if (!entry?.execution_id) {
      return;
    }
    this.selectedExecutionId = entry.execution_id;
    this.isFullscreen = false;
    this.isOpen = false;
    this.openLogsModal();
  }

  private openLogsModal(): void {
    if (!this.selectedExecutionId) {
      return;
    }
    const executionId = this.selectedExecutionId;
    this.modalRef = this.modalService.open(OpenCeliumLogsModalComponent, {
      size: 'xl',
      scrollable: true,
      windowClass: 'oc-logs-modal'
    });
    this.modalRef.componentInstance.executionId = executionId;
    this.modalRef.componentInstance.baseUrl = this.getBaseUrl();
    this.modalRef.componentInstance.token = this.getUserToken();
    this.modalRef.componentInstance.isFullscreen = this.isFullscreen;
    this.modalRef.componentInstance.onToggleFullscreen = (next) => {
      this.setFullscreen(next);
    };
    this.logsModalOpenChange.emit(true);
    this.modalRef.result.then(
      () => {
        this.clearModalState();
      },
      () => {
        this.clearModalState();
      }
    );
  }

  private setFullscreen(next: boolean): void {
    this.isFullscreen = next;
    const modalWindow = document.querySelector('ngb-modal-window.oc-logs-modal');
    if (modalWindow) {
      modalWindow.classList.toggle('oc-logs-fullscreen', next);
      const dialog = modalWindow.querySelector('.modal-dialog') as HTMLElement | null;
      const content = modalWindow.querySelector('.modal-content') as HTMLElement | null;
      if (next) {
        if (dialog) {
          dialog.style.width = '100vw';
          dialog.style.maxWidth = '100vw';
          dialog.style.height = '100vh';
          dialog.style.margin = '0';
          dialog.style.position = 'fixed';
          dialog.style.left = '0';
          dialog.style.top = '0';
        }
        if (content) {
          content.style.width = '100vw';
          content.style.height = '100vh';
          content.style.minHeight = '100vh';
          content.style.borderRadius = '0';
        }
      } else {
        if (dialog) {
          dialog.style.width = '';
          dialog.style.maxWidth = '';
          dialog.style.height = '';
          dialog.style.margin = '';
          dialog.style.position = '';
          dialog.style.left = '';
          dialog.style.top = '';
        }
        if (content) {
          content.style.width = '';
          content.style.height = '';
          content.style.minHeight = '';
          content.style.borderRadius = '';
        }
      }
    }
  }

  private clearModalState(): void {
    this.setFullscreen(false);
    this.selectedExecutionId = null;
    this.modalRef = undefined;
    this.logsModalOpenChange.emit(false);
  }

  formatLogDate(value: string | { $date?: number }): string {
    if (!value) return '-';
    const raw =
      typeof value === 'string'
        ? value
        : typeof value?.$date === 'number'
          ? value.$date
          : '';
    if (!raw) return '-';
    const date = new Date(raw);
    return isNaN(date.getTime()) ? `${raw}` : date.toLocaleString();
  }

  getUserToken(): string {
    const token = this.authService.currentUserTokenValue?.token;
    return token ? `Bearer ${token}` : '';
  }

  getBaseUrl(): string {
    if (environment.cloudMode) {
      const host = environment.apiUrl.replace(/^https?:\/\//, '');
      const port =
        environment.protocol === 'https' ? 443 : environment.apiPort;
      const base = port
        ? `${environment.protocol}://${host}:${port}`
        : `${environment.protocol}://${host}`;
      return `${base}/rest/open_celium/`;
    }

    return `${this.connectionService.getApiBaseUrl()}/rest/open_celium/`;
  }
}
