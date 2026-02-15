import { Component, OnInit } from '@angular/core';
import { SystemService } from '../system.service';

@Component({
    selector: 'cmdb-information',
    templateUrl: './information.component.html',
    styleUrls: ['./information.component.scss'],
    standalone: false
})
export class InformationComponent implements OnInit {

  public systemInfos: any;

  constructor(private systemService: SystemService) {
  }

  public ngOnInit(): void {
    this.systemService.getDatagerryInformation().subscribe((infos: any[]) => {
      this.systemInfos = infos;
    });
  }

  public convertToDate(secs) {
    const secsInt = parseInt(secs, 10);
    const days = Math.floor(secsInt / 86400) % 7;
    const hours = Math.floor(secsInt / 3600) % 24;
    const minutes = Math.floor(secsInt / 60) % 60;
    const seconds = secsInt % 60;
    return [days, hours, minutes, seconds]
      .map(v => v < 10 ? '0' + v : v)
      .filter((v, i) => v !== '00' || i > 0)
      .join(':');
  }

}
