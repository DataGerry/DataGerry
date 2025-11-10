import { Component } from '@angular/core';

@Component({
    selector: 'app-reports-overview',
    template: `
    <div class="container">
      <div class="row">
        <div class="col-md-3 mb-4" *ngFor="let card of reportCards">
          <div class="card">
            <a [routerLink]="card.link">
              <div class="dash-card primary">
                <i [class]="card.icon"></i>
                <span class="text-title">{{ card.title }}</span>
              </div>
            </a>
          </div>
        </div>
      </div>
    </div>
  `,
    styles: [],
    standalone: false
})
export class ReportsOverviewComponent {
  public reportCards = [
    {
      title: 'Risk Matrix Report',
      icon: 'fas fa-th-large',
      link: '/isms/reports/risk_matrix'
    },
    {
      title: 'Statement of Applicability',
      icon: 'fas fa-shield-alt',
      link: '/isms/reports/soa'
    },
    {
      title: 'Risk treatment plan',
      icon: 'fas fa-clipboard-check',
      link: '/isms/reports/risk_treatment_plan'
    },
    {
      title: 'Risk Assessments',
      icon: 'fas fa-file-alt',
      link: '/isms/reports/risk_assesments'
    }
  ];
}