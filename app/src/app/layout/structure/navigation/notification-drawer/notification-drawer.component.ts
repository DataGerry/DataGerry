import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { trigger, state, style, transition, animate } from '@angular/animations';
import { Observable } from 'rxjs';
import { Notification } from 'src/app/core/state/notification/notification.model';
import { NotificationQuery } from 'src/app/core/state/notification/notification.query';
import { NotificationService } from 'src/app/core/state/notification/notification.service';

@Component({
  selector: 'cmdb-notification-drawer',
  templateUrl: './notification-drawer.component.html',
  styleUrls: ['./notification-drawer.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  animations: [
    trigger('drawerState', [
      state('closed', style({ transform: 'translateX(100%)' })),
      state('open', style({ transform: 'translateX(0)' })),
      transition('closed <=> open', animate('220ms ease-in-out'))
    ])
  ],
  standalone: false
})
export class NotificationDrawerComponent {
  @Input() open = false;
  @Output() close = new EventEmitter<void>();

  public readonly notifications$: Observable<Notification[]> = this.notificationQuery.notifications$;

  constructor(
    private readonly notificationQuery: NotificationQuery,
    private readonly notificationService: NotificationService
  ) {}

  public onClose(): void {
    this.close.emit();
  }

  public clearNotifications(): void {
    this.notificationService.clear();
  }

  public trackById(_index: number, notification: Notification): string {
    return notification.id;
  }
}

