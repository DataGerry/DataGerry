import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { trigger, state, style, transition, animate } from '@angular/animations';
import { BehaviorSubject, Observable, combineLatest, map } from 'rxjs';
import { Notification, NotificationType } from 'src/app/core/state/notification/notification.model';
import { NotificationQuery } from 'src/app/core/state/notification/notification.query';
import { NotificationService } from 'src/app/core/state/notification/notification.service';

type NotificationFilterType = NotificationType | 'all';

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
  public readonly filterOptions: ReadonlyArray<{ label: string; value: NotificationFilterType }> = [
    { label: 'All', value: 'all' },    
    { label: 'Success', value: 'success' },
    { label: 'Error', value: 'error' },
    { label: 'Warning', value: 'warning' },
    { label: 'Info', value: 'info' },
  ];
  public readonly selectedFilter$: Observable<NotificationFilterType>;
  public readonly filteredNotifications$: Observable<Notification[]>;

  private readonly selectedFilterSubject = new BehaviorSubject<NotificationFilterType>('all');

  constructor(
    private readonly notificationQuery: NotificationQuery,
    private readonly notificationService: NotificationService
  ) {
    this.selectedFilter$ = this.selectedFilterSubject.asObservable();
    this.filteredNotifications$ = combineLatest([this.notifications$, this.selectedFilter$]).pipe(
      map(([notifications, selectedFilter]) => selectedFilter === 'all'
        ? notifications
        : notifications.filter(notification => notification.type === selectedFilter))
    );
  }

  public onClose(): void {
    this.close.emit();
  }

  public clearNotifications(): void {
    this.notificationService.clear();
  }

  public setFilter(filter: NotificationFilterType): void {
    this.selectedFilterSubject.next(filter);
  }

  public trackById(_index: number, notification: Notification): string {
    return notification.id;
  }
}
