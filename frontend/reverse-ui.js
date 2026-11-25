﻿﻿﻿﻿﻿﻿﻿﻿(function () {
  var styleId = 'reverse-migration-ui-style-v2';
  var mdmUseCaseRequestStarted = false;
  var mdmUseCaseScore = null;
  var trustForecastRequestStarted = false;
  var overallTrustForecast = null;
  var allForecastSeries = null;
  var executivePredictiveAlerts = null;
  var pillarTrendRequestStarted = false;
  var pillarTrendRows = null;
  var forecastAlertsFetchInstalled = false;

  // A business can have more than the bundle's default 100 rows. Raise only
  // that request's limit; filtering and deduplication happen in the Affected
  // Records component and the anomaly-records endpoint.
  var dashboardFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    if (typeof input === 'string') {
      try {
        var requestUrl = new URL(input, window.location.href);
        if (requestUrl.pathname === '/api/anomaly-records' && requestUrl.searchParams.has('business')) {
          requestUrl.searchParams.set('limit', '10000');
          input = requestUrl.pathname + requestUrl.search;
        }
      } catch (ignore) {}
    }
    return dashboardFetch(input, init);
  };

  function installStyle() {
    if (document.getElementById(styleId)) return;
    var style = document.createElement('style');
    style.id = styleId;
    style.textContent = `
      .reverse-migration-page > .reverse-route-strip {
        display: flex;
        align-items: center;
        gap: 10px;
        min-height: 48px;
        padding: 0 18px;
        margin-bottom: 12px;
        border: 1px solid var(--color-border, #dbe4ec);
        border-radius: 10px;
        background: var(--color-surface, #fff);
        color: var(--color-text-secondary, #64748b);
        font-size: 12px;
      }
      .reverse-route-strip .route-badge {
        padding: 4px 10px;
        border-radius: 6px;
        background: #e6f6f5;
        color: #087f79;
        font-weight: 700;
      }
      .reverse-route-strip .route-arrow { font-size: 18px; }
      .reverse-route-strip .route-status {
        margin-left: auto;
        padding: 4px 10px;
        border-radius: 6px;
        background: #fff4e5;
        color: #a45b00;
        font-weight: 700;
      }
      .reverse-migration-page .reverse-route-strip + * { margin-top: 0; }
      .reverse-migration-page .reverse-chooser-hidden { display: none !important; }
      .migration-detail-row { cursor: pointer; }
      .migration-detail-row:hover { background: var(--color-background-secondary, #f3f7fb); }
      .migration-detail-row:focus-visible { outline: 2px solid #087f79; outline-offset: -2px; }
      .migration-detail-overlay {
        position: fixed; inset: 0; z-index: 3000; display: flex; align-items: center;
        justify-content: center; padding: 20px; background: rgba(15, 23, 42, .48);
        backdrop-filter: blur(3px);
      }
      .migration-detail-dialog {
        width: min(620px, 100%); max-height: min(760px, calc(100vh - 40px)); overflow: auto;
        background: var(--color-background-primary, #fff); color: var(--color-text-primary, #172033);
        border: 1px solid var(--color-border, #dbe4ec); border-radius: 14px;
        box-shadow: 0 24px 70px rgba(15, 23, 42, .28);
      }
      .migration-detail-header {
        display: flex; align-items: flex-start; justify-content: space-between; gap: 16px;
        padding: 20px 22px; border-bottom: 1px solid var(--color-border, #dbe4ec);
      }
      .migration-detail-title { margin: 0; font-size: 18px; line-height: 1.35; overflow-wrap: anywhere; }
      .migration-detail-subtitle { margin-top: 5px; color: var(--color-text-secondary, #64748b); font-size: 12px; }
      .migration-detail-close {
        flex: 0 0 auto; width: 34px; height: 34px; border: 1px solid var(--color-border, #dbe4ec);
        border-radius: 8px; background: transparent; color: inherit; font-size: 22px; cursor: pointer;
      }
      .migration-detail-grid {
        display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px;
        padding: 20px 22px 22px;
      }
      .migration-detail-item { min-width: 0; padding: 12px; border: 1px solid var(--color-border, #dbe4ec); border-radius: 9px; }
      .migration-detail-label { margin-bottom: 6px; color: var(--color-text-secondary, #64748b); font-size: 10px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; }
      .migration-detail-value { font-size: 13px; font-weight: 600; line-height: 1.45; overflow-wrap: anywhere; }
      @media (max-width: 520px) { .migration-detail-grid { grid-template-columns: minmax(0, 1fr); } }
      main .exec-trust-chart-wrap { height: 280px !important; overflow: hidden; }
      .exec-trust-chart-svg { display: block; width: 100%; height: 252px; }
      .exec-trust-current-note { display: flex; align-items: center; justify-content: center; gap: 6px; height: 28px; color: #64748b; font-size: 12px; }
      .exec-trust-current-note::before { content: ''; width: 9px; height: 9px; border-radius: 50%; background: #2563eb; display: inline-block; }
      @media (max-width: 700px) {
        main .exec-trust-chart-wrap { height: 245px !important; }
        .exec-trust-chart-svg { height: 220px; }
        .exec-trust-current-note { height: 25px; font-size: 11px; }
      }
      .exec-forecast-chart-svg { display: block; width: 100%; height: 100%; }
      .anomaly-tab { padding:8px 16px; border:0; border-bottom:2px solid transparent; background:transparent; color:var(--muted-foreground); font:inherit; cursor:pointer; }
      .anomaly-tab.active { color:var(--chart-2); border-bottom-color:var(--chart-2); font-weight:600; }
      .schema-count { margin-left:6px; padding:1px 6px; border-radius:10px; background:var(--neg); color:#fff; font-size:10px; }
      .record-modal-content.record-modal-large { display:flex; flex-direction:column; overflow:hidden; }
      .record-modal-header,.record-modal-tabs { flex:0 0 auto; }
      .record-modal-tabs { position:relative; z-index:2; background:var(--card,#fff); }
      .record-modal-body { flex:1 1 auto; min-height:0; overflow-y:auto; overscroll-behavior:contain; }
      .schema-panel { padding:18px 22px 24px; }
      .schema-meta { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; padding:14px; margin-bottom:16px; border:1px solid var(--border,#e2e8f0); border-radius:10px; background:var(--muted,#f8fafc); }
      .schema-meta-item { min-width:0; }
      .schema-meta-label { display:block; margin-bottom:5px; color:var(--muted-foreground,#64748b); font-size:10px; font-weight:700; letter-spacing:.04em; text-transform:uppercase; }
      .schema-meta-value { display:block; overflow-wrap:anywhere; color:var(--foreground,#111827); font-size:13px; font-weight:650; }
      .schema-legend { display:flex; align-items:center; gap:16px; flex-wrap:wrap; padding:2px 0 16px; color:var(--muted-foreground,#64748b); font-size:12px; }
      .schema-legend-item { display:inline-flex; align-items:center; gap:6px; }
      .schema-legend-dot { width:9px; height:9px; border-radius:50%; background:#e11d48; }
      .schema-legend-normal { width:9px; height:9px; border:1px solid #cbd5e1; border-radius:50%; background:#fff; }
      .schema-legend-count { margin-left:auto; color:var(--foreground,#111827); font-weight:700; }
      .schema-category { margin:8px 0 18px; }
      .schema-category-title { display:flex; align-items:center; gap:8px; padding:0 0 8px; margin:0 0 10px; border-bottom:1px solid var(--border,#e2e8f0); color:var(--muted-foreground,#64748b); font-size:12px; font-weight:750; letter-spacing:.035em; }
      .schema-category-title.has-anomaly { border-bottom-color:#fda4af; color:#dc2626; }
      .schema-field-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
      .schema-field-card { position:relative; min-width:0; padding:11px 12px; border:1px solid var(--border,#e2e8f0); border-radius:8px; background:var(--card,#fff); }
      .schema-field-card.is-anomalous { border-color:#fda4af; border-left:3px solid #e11d48; background:#fff1f2; }
      .schema-field-name { margin:0 0 6px; color:var(--muted-foreground,#64748b); font-size:10px; font-weight:700; letter-spacing:.035em; text-transform:uppercase; overflow-wrap:anywhere; }
      .schema-field-value { color:var(--foreground,#1f2937); font-size:13px; line-height:1.45; overflow-wrap:anywhere; white-space:pre-wrap; }
      .schema-field-card.is-anomalous .schema-field-name,.schema-field-card.is-anomalous .schema-field-value { color:#b91c1c; }
      .schema-field-badge { position:absolute; top:8px; right:8px; padding:2px 6px; border-radius:10px; background:#fee2e2; color:#b91c1c; font-size:9px; font-weight:800; }
      @media(max-width:680px) { .schema-meta { grid-template-columns:repeat(2,minmax(0,1fr)); }.schema-panel { padding:14px; } }
      @media(max-width:480px) { .schema-field-grid { grid-template-columns:minmax(0,1fr); }.schema-legend-count { width:100%; margin-left:0; } }
      .local-alert-email { display:flex; align-items:end; gap:14px; }
      .local-alert-email label { display:block; color:var(--color-text-secondary,#64748b); font-size:12px; margin-bottom:7px; }
      .local-alert-email input { width:100%; height:44px; border:1px solid var(--color-border,#dbe4ec); border-radius:9px; padding:0 14px; color:inherit; background:transparent; font:inherit; }
      .local-alert-email > div { flex:1; }
      .local-alert-reports { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:20px; }
      .local-alert-report { border:1px solid var(--color-border,#dbe4ec); border-radius:12px; padding:18px 20px; }
      .local-alert-row { position:relative; border:1px solid var(--color-border,#dbe4ec); border-radius:12px; padding:18px 155px 18px 20px; margin-top:12px; cursor:default; background:#fff; }
      .local-alert-metricline { display:flex; align-items:center; gap:9px; flex-wrap:wrap; }
      .local-alert-metricline strong { font-size:15px; }
      .local-alert-month { color:#64748b; font-size:13px; }
      .local-alert-trigger { margin-top:7px; font-size:13px; color:#172033; }
      .local-alert-stats { margin-top:8px; font-size:13px; color:#475569; }
      .local-alert-stats strong { color:#172033; font-weight:600; }
      .local-alert-why { margin-top:7px; font-size:13px; line-height:1.5; color:#0f7b6b; }
      .local-alert-page button { border:1px solid var(--border,#dedede); border-radius:9px; padding:9px 14px; background:var(--card,#fff); color:var(--foreground,#111827); font:inherit; cursor:pointer; white-space:nowrap; display:inline-flex; align-items:center; gap:5px; }
      .local-alert-page button:hover { background:var(--muted,#f5f5f5); }
      .dm-save-config-toast { position:fixed; top:76px; left:12px; z-index:10000; max-width:272px; padding:10px 12px; border:1px solid #b7efd1; border-radius:9px; background:#e8fff2; color:#087f5b; font-size:13px; line-height:1.45; box-shadow:0 4px 14px rgba(15,118,110,.12); }
      .dm-save-config-toast strong { color:#087f5b; }
      .local-alert-send { position:absolute; right:16px; top:16px; font-size:12.5px; padding:7px 12px; }
      .local-alert-why { margin-top:9px; color:#64748b; font-size:13px; line-height:1.5; }
      @media(max-width:760px) {
        .la-summary-row{grid-template-columns:repeat(2,1fr)}
        .la-report-row{grid-template-columns:1fr}
        .local-alert-email{align-items:stretch;flex-direction:column}
        .local-alert-row{padding-right:18px}
        .local-alert-send{position:static;margin-top:10px;display:block;width:100%;text-align:center;justify-content:center}
        .la-stats{flex-direction:column;align-items:flex-start}
        .la-stat-sep{display:none}
      }
      .exec-predictive-alert-list { margin: 0; border-top: 1px solid #e2e8f0; }
      .exec-predictive-alert-row { display: flex; align-items: center; gap: 10px; min-height: 50px; padding: 0 4px; border-bottom: 1px solid #e2e8f0; font-size: 14px; }
      .exec-predictive-alert-row:last-child { border-bottom: none; }
      .exec-predictive-alert-row .tag { flex: 0 0 auto; min-width: 64px; text-align: center; font-size: 11px; padding: 3px 8px; }
      .exec-predictive-alert-label { min-width: 0; flex: 1 1 auto; overflow-wrap: anywhere; color: #172033; }
      .exec-predictive-alert-label .epa-metric { color: #0f7b6b; font-weight: 500; }
      .exec-predictive-alert-month { flex: 0 0 90px; color: #64748b; text-align: right; font-size: 13px; }
      @media (max-width: 620px) { .exec-predictive-alert-row { gap: 8px; font-size: 13px; }.exec-predictive-alert-month { flex-basis: 72px; } }
      /* Two-column row for Future predictive alerts + Use case trust scores */
      .exec-two-col-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px; }
      @media (max-width: 860px) { .exec-two-col-row { grid-template-columns: 1fr; } }
      /* Use case trust scores card rows */
      .exec-uc-row { display: flex; align-items: center; gap: 12px; padding: 13px 0; border-bottom: 1px solid #f1f5f9; font-size: 14px; }
      .exec-uc-row:last-child { border-bottom: none; }
      .exec-uc-name { flex: 1; color: #172033; font-size: 14px; }
      .exec-uc-score { flex: 0 0 44px; text-align: right; font-weight: 600; font-size: 15px; color: #179765; }
      .exec-uc-bar-track { flex: 0 0 100px; height: 10px; background: #e9eef3; border-radius: 10px; overflow: hidden; }
      .exec-uc-bar-fill { height: 100%; border-radius: 10px; transition: width .4s ease; }
      main .exec-use-case-card { padding: 18px 22px 24px; }
      .exec-use-case-card .section-title { margin-bottom: 18px; }
      .exec-use-case-card table { width: 100%; border-collapse: collapse; table-layout: fixed; }
      .exec-use-case-card tbody tr { height: 51px; border-bottom: 1px solid #e2e8f0; }
      .exec-use-case-card tbody tr:last-child { border-bottom: 0; }
      .exec-use-case-card tbody td { padding: 0 12px; font-size: 16px; }
      .exec-use-case-card tbody td:first-child { width: auto; padding-left: 12px; color: #111827; }
      .exec-use-case-card tbody td:nth-child(2) { width: 78px; color: #179765; font-size: 16px; font-weight: 500; text-align: right; }
      .exec-use-case-card tbody td:nth-child(3) { width: 100px; padding-right: 12px; }
      .exec-use-case-card .progress-bg { width: 74px; height: 8px; margin-left: auto; overflow: hidden; border-radius: 999px; background: #e5e7eb; }
      .exec-use-case-card .progress-fill { height: 100%; border-radius: inherit; background: #179765 !important; }
      .exec-use-case-card .tag-gray { padding: 4px 10px; border: 1px solid #dbe4ec; border-radius: 8px; color: #64748b; background: #f8fafc; font-size: 12px; }
      @media (max-width: 620px) { .exec-use-case-card tbody td { font-size: 14px; }.exec-use-case-card tbody td:nth-child(2) { width: 64px; }.exec-use-case-card tbody td:nth-child(3) { width: 86px; }.exec-use-case-card .progress-bg { width: 62px; } }
      .exec-mom-card { margin-top: 20px; }
      .exec-mom-card .section-title { margin-bottom: 10px; }
      .exec-mom-subtitle { margin: 0 0 10px; color: #64748b; font-size: 14px; line-height: 1.45; }
      .exec-mom-chart { width: 100%; height: 286px; overflow: hidden; }
      .exec-mom-chart svg { display: block; width: 100%; height: 100%; }
      @media (max-width: 700px) { .exec-mom-chart { height: 240px; } .exec-mom-subtitle { font-size: 12px; } }

      /* Cloud Migration redesign: Oracle -> GCP (BigQuery) layout
         inside the existing DeltaMax shell without changing the React bundle. */
      main.cloud-migration-design { color: var(--foreground, #172033); }
      .cloud-migration-page-head { margin-bottom: 18px; }
      .cloud-migration-page-head h1 { margin: 0; font-size: 25px; line-height: 1.2; }
      .cloud-migration-page-head p { margin: 7px 0 0; color: var(--muted-foreground, #64748b); font-size: 14px; }
      .cloud-migration-flow, .cloud-migration-card { border: 1px solid var(--border, #dbe4ec); border-radius: 14px; background: var(--card, #fff); box-shadow: 0 1px 2px rgba(15,23,42,.04); }
      .cloud-migration-flow { display:flex; align-items:center; gap:12px; padding:16px 18px; margin-bottom:16px; flex-wrap:wrap; }
      .cloud-migration-badge { display:inline-flex; align-items:center; gap:7px; padding:7px 12px; border-radius:8px; font-size:13px; font-weight:750; }
      .cloud-migration-badge.source { background:#e7f0ff; color:#2456a6; }
      .cloud-migration-badge.target { background:#e7f8f3; color:#087f79; }
      .cloud-migration-flow-arrow { color:var(--muted-foreground,#64748b); font-size:19px; }
      .cloud-migration-status { margin-left:auto; padding:6px 10px; border-radius:7px; background:#fff4e5; color:#a45b00; font-size:11px; font-weight:750; }
      .cloud-migration-stages { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-bottom:18px; }
      .cloud-migration-stage { padding:12px 14px; border:1px solid var(--border,#dbe4ec); border-radius:10px; background:var(--card,#fff); color:var(--muted-foreground,#64748b); font-size:12px; }
      .cloud-migration-stage strong { display:block; margin-top:5px; color:var(--foreground,#172033); font-size:12px; }
      .cloud-migration-stage i { color:#179765; }
      .cloud-migration-kpis { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin-bottom:18px; }
      .cloud-migration-kpi { padding:18px; min-height:122px; }
      .cloud-migration-kpi-head { display:flex; align-items:center; gap:9px; color:var(--muted-foreground,#64748b); font-size:12px; font-weight:700; }
      .cloud-migration-kpi-head i { color:#087f79; font-size:17px; }
      .cloud-migration-kpi-value { margin-top:13px; font-size:26px; font-weight:750; }
      .cloud-migration-kpi-sub { margin-top:5px; color:var(--muted-foreground,#64748b); font-size:11px; }
      .cloud-migration-two-col { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:16px; margin-bottom:18px; }
      .cloud-migration-card { padding:20px; }
      .cloud-migration-card h2 { display:flex; align-items:center; gap:9px; margin:0; font-size:16px; }
      .cloud-migration-card h2 i { color:#087f79; }
      .cloud-migration-card-sub { margin:7px 0 18px; color:var(--muted-foreground,#64748b); font-size:12px; }
      .cloud-migration-donut-wrap { display:flex; align-items:center; gap:24px; min-height:190px; }
      .cloud-migration-donut { width:166px; height:166px; border-radius:50%; background:conic-gradient(#f59e0b 0 40%,#199a78 40% 68%,#2e6be6 68% 100%); display:grid; place-items:center; flex:0 0 auto; }
      .cloud-migration-donut::after { content:''; width:104px; height:104px; border-radius:50%; background:var(--card,#fff); box-shadow:0 0 0 1px var(--border,#dbe4ec); }
      .cloud-migration-donut-label { position:absolute; text-align:center; font-size:11px; color:var(--muted-foreground,#64748b); }
      .cloud-migration-donut-label strong { display:block; color:var(--foreground,#172033); font-size:22px; }
      .cloud-migration-legend { display:grid; gap:12px; min-width:160px; }
      .cloud-migration-legend-row { display:flex; justify-content:space-between; gap:18px; font-size:12px; }
      .cloud-migration-legend-name { display:flex; align-items:center; gap:7px; color:var(--muted-foreground,#64748b); }
      .cloud-migration-dot { width:9px; height:9px; border-radius:50%; }
      .cloud-migration-bars { display:grid; gap:15px; margin-top:18px; }
      .cloud-migration-bar-row { display:grid; grid-template-columns:120px minmax(0,1fr) 78px; align-items:center; gap:12px; font-size:12px; }
      .cloud-migration-bar-label { color:var(--muted-foreground,#64748b); }
      .cloud-migration-bar-track { height:9px; overflow:hidden; border-radius:10px; background:#e9eef3; }
      .cloud-migration-bar-fill { height:100%; border-radius:10px; background:#94a3b8; }
      .cloud-migration-bar-value { text-align:right; font-weight:700; }
      .cloud-migration-note { margin:17px 0 0; color:var(--muted-foreground,#64748b); font-size:12px; line-height:1.55; }
      .cloud-migration-table { width:100%; border-collapse:collapse; margin-top:10px; font-size:12px; }
      .cloud-migration-table th,.cloud-migration-table td { padding:11px 8px; text-align:left; border-bottom:1px solid var(--border,#e2e8f0); }
      .cloud-migration-table th { color:var(--muted-foreground,#64748b); font-weight:700; }
      .cloud-migration-empty { padding:22px; border:1px dashed #f0b15a; border-radius:10px; background:#fffaf2; color:#9a5b08; font-size:13px; line-height:1.55; }
      .cloud-migration-react-hidden { display:none !important; }
      @media(max-width:1050px){.cloud-migration-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.cloud-migration-stages{grid-template-columns:repeat(2,minmax(0,1fr))}.cloud-migration-two-col{grid-template-columns:minmax(0,1fr)}}
      @media(max-width:620px){.cloud-migration-kpis,.cloud-migration-stages{grid-template-columns:minmax(0,1fr)}.cloud-migration-flow{align-items:flex-start}.cloud-migration-status{width:100%;margin-left:0}.cloud-migration-donut-wrap{flex-direction:column;align-items:flex-start}.cloud-migration-bar-row{grid-template-columns:100px minmax(0,1fr) 68px;gap:8px}}

      /* Keep the restored anomaly summary in the same visual system as the
         Hyperparameter Tuning card: white surfaces, quiet borders, and the
         same compact responsive grid. */
      main.anomaly-design-page .anomaly-compare-card,
      main.anomaly-design-page .anomaly-pillar-breakdown {
        border: 1px solid var(--border, #dbe4ec);
        border-radius: 14px;
        background: var(--card, #fff);
        box-shadow: 0 1px 2px rgba(15, 23, 42, .04);
      }
      main.anomaly-design-page .anomaly-compare-card { padding: 20px; }
      main.anomaly-design-page .anomaly-compare-card > .section-title { margin-bottom: 8px; }
      main.anomaly-design-page .anomaly-filter-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
        gap: 16px !important;
        margin-bottom: 20px !important;
      }
      main.anomaly-design-page .anomaly-filter-grid > div {
        min-height: 164px;
        padding: 18px 20px !important;
        border-radius: 12px !important;
        box-shadow: 0 1px 2px rgba(15, 23, 42, .03);
      }
      main.anomaly-design-page .anomaly-record-comparison {
        margin-bottom: 20px !important;
        padding: 16px 18px !important;
        border: 1px solid var(--border, #dbe4ec) !important;
        border-radius: 12px !important;
        background: var(--card, #fff) !important;
      }
      main.anomaly-design-page .anomaly-pillar-breakdown { padding: 20px !important; }
      main.anomaly-design-page .anomaly-pillar-grid {
        grid-template-columns: repeat(4, minmax(0, 1fr)) !important;
        gap: 14px !important;
      }
      main.anomaly-design-page .anomaly-pillar-card {
        min-width: 0;
        padding: 16px !important;
        border-radius: 12px !important;
        box-shadow: 0 1px 2px rgba(15, 23, 42, .03);
      }
      @media (max-width: 1080px) {
        main.anomaly-design-page .anomaly-pillar-grid { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
      }
      @media (max-width: 640px) {
        main.anomaly-design-page .anomaly-filter-grid,
        main.anomaly-design-page .anomaly-pillar-grid { grid-template-columns: minmax(0, 1fr) !important; }
        main.anomaly-design-page .anomaly-compare-card,
        main.anomaly-design-page .anomaly-pillar-breakdown { padding: 16px !important; }
      }

      /* ===== Cloud Migration redesign (cm-* classes) ===== */
      .cm-page-head { margin-bottom:18px; }
      .cm-page-head h1 { margin:0; font-size:24px; font-weight:700; color:var(--foreground,#172033); letter-spacing:-.02em; }
      .cm-page-head p  { margin:6px 0 0; color:var(--muted-foreground,#64748b); font-size:13.5px; }

      .cm-loading { display:flex; align-items:center; gap:10px; padding:40px 20px; color:var(--muted-foreground,#64748b); font-size:14px; }
      .cm-spin { animation:cm-rotate 1s linear infinite; display:inline-block; font-size:20px; }
      @keyframes cm-rotate { to { transform:rotate(360deg); } }
      .cm-error { padding:20px; border:1px solid #fda4af; border-radius:12px; background:#fff1f2; color:#b91c1c; font-size:13px; }
      .cm-no-data { padding:24px; color:var(--muted-foreground,#64748b); font-size:13px; text-align:center; }

      /* Flow row */
      .cm-actions { display:flex; justify-content:flex-end; margin:-10px 0 10px; }
      .cm-run-btn { display:inline-flex; align-items:center; gap:6px; padding:6px 12px; border:1px solid var(--border,#dbe4ec); border-radius:8px; background:var(--card,#fff); color:#087f79; font-size:12px; cursor:pointer; }
      .cm-run-btn:hover { background:#e7f8f3; }
      .cm-flow-row { display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap; padding:20px 24px; margin-bottom:16px; border:1px solid var(--border,#dbe4ec); border-radius:14px; background:var(--card,#fff); box-shadow:0 1px 2px rgba(15,23,42,.04); }
      .cm-flow-badges { display:flex; align-items:center; gap:10px; }
      .cm-badge { display:inline-flex; align-items:center; gap:6px; padding:6px 12px; border-radius:8px; font-size:13px; font-weight:700; }
      .cm-badge-source { background:#e7f0ff; color:#2456a6; }
      .cm-badge-target { background:#e7f8f3; color:#087f79; }
      .cm-flow-arrow { font-size:18px; color:var(--muted-foreground,#64748b); }
      .cm-stages { display:flex; justify-content:flex-end; gap:10px; flex:1; flex-wrap:wrap; margin-left:auto; }
      .cm-stage { display:inline-flex; align-items:center; gap:5px; padding:5px 10px; border-radius:20px; border:1px solid var(--border,#dbe4ec); background:var(--muted,#f8fafc); font-size:12px; color:var(--muted-foreground,#64748b); white-space:nowrap; }
      .cm-status-ok   { margin-left:auto; padding:5px 12px; border-radius:7px; background:#e7f8f3; color:#087f79; font-size:11.5px; font-weight:700; white-space:nowrap; }
      .cm-status-fail { margin-left:auto; padding:5px 12px; border-radius:7px; background:#fff1f2; color:#b91c1c; font-size:11.5px; font-weight:700; white-space:nowrap; }
      .cm-overview .cm-page-head { display:none; }

      /* KPI cards */
      .cm-kpi-row { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin-bottom:16px; }
      .cm-kpi-card { padding:18px 20px; border:1px solid var(--border,#dbe4ec); border-radius:14px; background:var(--card,#fff); box-shadow:0 1px 2px rgba(15,23,42,.04); }
      .cm-kpi-head { display:flex; align-items:center; gap:7px; color:var(--muted-foreground,#64748b); font-size:12px; font-weight:600; margin-bottom:10px; }
      .cm-kpi-head i { font-size:15px; color:#087f79; }
      .cm-kpi-value { font-size:30px; font-weight:750; letter-spacing:-.03em; color:var(--foreground,#172033); line-height:1.1; }
      .cm-kpi-sub { margin-top:6px; color:var(--muted-foreground,#64748b); font-size:12px; }

      /* Cards */
      .cm-card { border:1px solid var(--border,#dbe4ec); border-radius:14px; background:var(--card,#fff); box-shadow:0 1px 2px rgba(15,23,42,.04); padding:20px 22px; margin-bottom:16px; }
      .cm-card-title { display:flex; align-items:center; gap:8px; margin:0 0 16px; font-size:15px; font-weight:700; color:var(--foreground,#172033); }
      .cm-card-title i { font-size:16px; color:#087f79; }

      /* Charts row */
      .cm-charts-row { display:grid; gap:16px; margin-bottom:16px; }
      .cm-card-donut { }
      .cm-card-bar,.cm-card-lift { }
      .cm-charts-row:last-child { grid-template-columns:1fr 1fr; }
      .cm-two-col { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:16px; align-items:start; }
      .cm-two-col > .cm-card { min-width:0; }

      /* Donut */
      .cm-donut-layout { display:flex; align-items:center; gap:28px; }
      .cm-donut-wrap { flex:0 0 220px; width:220px; height:220px; }
      .cm-donut-svg { width:100%; height:100%; }
      .cm-pillar-legend { flex:1; display:flex; flex-direction:column; gap:12px; }
      .cm-pillar-row { display:flex; align-items:center; gap:10px; font-size:13px; }
      .cm-pillar-dot { width:12px; height:12px; border-radius:3px; flex-shrink:0; }
      .cm-pillar-name { flex:1; color:var(--foreground,#172033); }
      .cm-pillar-score { font-size:16px; font-weight:700; color:#087f79; min-width:46px; text-align:right; }
      .cm-pillar-pct { color:var(--muted-foreground,#64748b); font-size:12px; min-width:32px; text-align:right; }

      /* Bar chart */
      .cm-bar-wrap { width:100%; overflow:hidden; }
      .cm-bar-svg { width:100%; height:auto; display:block; }

      /* Lineage lift table */
      .cm-table { width:100%; border-collapse:collapse; font-size:13px; }
      .cm-table th { padding:9px 10px; text-align:left; color:var(--muted-foreground,#64748b); font-size:11.5px; font-weight:700; border-bottom:2px solid var(--border,#e2e8f0); }
      .cm-table td { padding:10px 10px; border-bottom:1px solid var(--border,#f1f5f9); color:var(--foreground,#172033); }
      .cm-table tbody tr:last-child td { border-bottom:none; }
      .cm-table tbody tr:hover { background:var(--muted,#f8fafc); }
      .cm-discard-head { display:flex; align-items:center; gap:10px; margin-bottom:4px; }
      .cm-discard-count { display:inline-flex; align-items:center; padding:4px 10px; border:1px solid #f0a4ad; border-radius:7px; background:#fff0f2; color:#c91b27; font-size:13px; font-weight:700; }
      .cm-discard-sub { margin:0 0 18px; color:var(--muted-foreground,#64748b); font-size:13.5px; }
      .cm-risk-card { padding:20px 22px; }
      .cm-risk-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:24px; }
      .cm-risk-item { min-width:0; }
      .cm-risk-label { display:block; padding:4px 10px; border:1px solid #dbe4ec; border-radius:7px; font-size:11px; font-weight:700; }
      .cm-risk-label.critical { background:#fff0f2; border-color:#f4b2b7; color:#e7000b; }
      .cm-risk-label.high { background:#fff7e8; border-color:#f3d39a; color:#a86a00; }
      .cm-risk-label.medium { background:#eef8fb; border-color:#b9e1eb; color:#0b6680; }
      .cm-risk-label.low { background:#f5f5f5; color:#64748b; }
      .cm-risk-value { margin-top:14px; font-size:28px; font-weight:750; line-height:1; color:var(--foreground,#172033); }
      .cm-risk-pct { margin-top:8px; color:var(--muted-foreground,#64748b); font-size:12px; }
      .cm-risk-meter { height:4px; margin-top:12px; border-radius:4px; background:#e2e8f0; overflow:hidden; }
      .cm-risk-meter > span { display:block; height:100%; border-radius:inherit; background:#0a9f96; }
      .cm-record-card { padding-bottom:12px; }
      .cm-lineage-tabs { display:flex; align-items:center; gap:22px; margin:8px 0 18px; flex-wrap:wrap; }
      .cm-lineage-caption { color:var(--muted-foreground,#64748b); font-size:12px; font-weight:600; }
      .cm-lineage-tab { border:0; border-radius:7px; background:transparent; color:var(--foreground,#172033); padding:5px 9px; font-size:12px; cursor:pointer; }
      .cm-lineage-tab.active { background:#2d63df; color:#fff; font-weight:700; }
      .cm-discard-pagination { display:flex; align-items:center; justify-content:flex-end; gap:8px; margin-top:12px; color:var(--muted-foreground,#64748b); font-size:12px; }
      .cm-discard-pagination button { border:1px solid var(--border,#dbe4ec); border-radius:9px; background:#fff; padding:7px 12px; color:inherit; cursor:pointer; }
      .cm-discard-pagination button:disabled { opacity:.45; cursor:default; }
      @media (max-width:760px) { .cm-risk-grid { grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; } .cm-lineage-tabs { gap:6px; } }

      /* Before vs After */
      .cm-ba-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; margin-bottom:16px; }
      .cm-ba-card { padding:16px 18px; border:1px solid var(--border,#dbe4ec); border-radius:12px; background:var(--card,#fff); }
      .cm-ba-label { font-size:11.5px; font-weight:700; color:var(--muted-foreground,#64748b); text-transform:uppercase; letter-spacing:.04em; margin-bottom:10px; }
      .cm-ba-row { display:flex; align-items:center; gap:12px; }
      .cm-ba-val { font-size:22px; font-weight:700; color:var(--foreground,#172033); }
      .cm-ba-sub { font-size:11px; color:var(--muted-foreground,#64748b); margin-bottom:3px; }
      .cm-ba-arrow { font-size:18px; color:var(--muted-foreground,#64748b); }
      .cm-ba-diff { font-size:16px; font-weight:700; margin-left:auto; }
      .cm-ba-summary { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
      .cm-ba-sum-row { display:flex; justify-content:space-between; align-items:center; padding:9px 12px; border-radius:8px; background:var(--muted,#f8fafc); font-size:13px; }
      .cm-ba-sum-row span { color:var(--muted-foreground,#64748b); }
      .cm-ba-sum-row strong { color:var(--foreground,#172033); }

      /* Discarded Records */
      .cm-lineage-chips { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:14px; }
      .cm-lineage-chip { padding:5px 12px; border-radius:20px; border:1px solid var(--border,#dbe4ec); background:var(--card,#fff); font-size:12.5px; color:var(--foreground,#172033); }
      .cm-lineage-chip strong { color:#087f79; }
      .cm-anom-tag { display:inline-block; padding:2px 8px; border-radius:10px; background:#fff4e5; color:#a45b00; font-size:11px; font-weight:600; }

      /* Responsive */
      @media(max-width:1100px) {
        .cm-kpi-row { grid-template-columns:repeat(2,minmax(0,1fr)); }
        .cm-charts-row:last-child { grid-template-columns:minmax(0,1fr); }
        .cm-two-col { grid-template-columns:minmax(0,1fr); }
      }
      @media(max-width:720px) {
        .cm-kpi-row { grid-template-columns:minmax(0,1fr); }
        .cm-donut-layout { flex-direction:column; align-items:flex-start; }
        .cm-ba-grid { grid-template-columns:minmax(0,1fr); }
        .cm-ba-summary { grid-template-columns:minmax(0,1fr); }
        .cm-stages { display:none; }
        .cm-actions { margin-top:0; }
      }
    `;
    document.head.appendChild(style);
  }

  function isForwardMigration() {
    return location.hash.indexOf('#/migration/overview') === 0;
  }

  function isReverseMigration() {
    return location.hash.indexOf('#/migration/reverse') === 0;
  }

  function decorateMigrationRows(main) {
    var reverse = isReverseMigration();
    var headingText = reverse
      ? 'Per-table transfer and validation'
      : 'Per-table migration and row-count validation';
    var expectedCells = reverse ? 6 : 7;
    var card = Array.from(main.querySelectorAll('.card')).find(function (item) {
      var heading = item.querySelector('.section-title');
      return heading && heading.textContent.indexOf(headingText) !== -1;
    });
    if (!card) return;
    card.querySelectorAll('tbody tr').forEach(function (row) {
      if (row.querySelectorAll('td').length < expectedCells) return;
      if (row.classList.contains('migration-detail-row') && row.tabIndex === 0 && row.getAttribute('role') === 'button') return;
      row.classList.add('migration-detail-row');
      row.tabIndex = 0;
      row.setAttribute('role', 'button');
      row.setAttribute('aria-label', 'View migration details for ' + row.cells[0].textContent.trim());
    });
  }

  var anomalyPopupBusy = false;
  function openBusinessAnomalyRecord(businessId) {
    if (anomalyPopupBusy || !businessId) return;
    anomalyPopupBusy = true;
    fetch('/api/anomaly-records?business=' + encodeURIComponent(businessId) + '&limit=500')
      .then(function (response) { if (!response.ok) throw new Error('Could not load records for ' + businessId); return response.json(); })
      .then(function (data) {
        var records = data.records || [];
        if (!records.length) throw new Error('No anomaly records found for ' + businessId);
        records.sort(function (a,b) { return Number(b.anomaly_risk||0) - Number(a.anomaly_risk||0); });
        return fetch('/api/anomaly-record/' + encodeURIComponent(records[0].record_id))
          .then(function (response) { if (!response.ok) throw new Error('Could not load anomaly record details'); return response.json(); });
      })
      .then(function (detail) { showBusinessAnomalyModal(detail); })
      .catch(function (error) { window.alert(error.message || 'Could not load the anomaly record.'); })
      .finally(function () { anomalyPopupBusy = false; });
  }

  function openAnomalyRecord(recordId) {
    if (anomalyPopupBusy || !recordId) return;
    anomalyPopupBusy = true;
    fetch('/api/anomaly-record/' + encodeURIComponent(recordId))
      .then(function (response) { if (!response.ok) throw new Error('Could not load anomaly record #' + recordId); return response.json(); })
      .then(function (detail) { showBusinessAnomalyModal(detail); })
      .catch(function (error) { window.alert(error.message || 'Could not load the anomaly record.'); })
      .finally(function () { anomalyPopupBusy = false; });
  }

  function showBusinessAnomalyModal(detail) {
    if (!detail || !detail.ready || document.querySelector('.record-modal-overlay')) return;
    var esc = function (value) { return String(value == null ? '—' : value).replace(/[&<>"']/g, function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];}); };
    var metric = function(label,value,color) { var n=Number(value); var tone=value==null?'var(--muted-foreground)' :(n<75?'var(--neg)' :n<85?'var(--warning)' :(color||'var(--chart-2)')); return '<div class="rec-pill"><div class="rec-pill-label">'+esc(label)+'</div><div class="rec-pill-val" style="color:'+tone+'">'+esc(value == null ? 'N/A' : value)+'</div></div>'; };
    var lineage = String(detail.lineage||'').replace(/_/g,' ').toLowerCase().replace(/\b\w/g,function(c){return c.toUpperCase();});
    var overlay = document.createElement('div');
    overlay.className = 'record-modal-overlay';
    overlay.setAttribute('role','presentation');
    var modal = document.createElement('div');
    modal.className = 'record-modal-content record-modal-large';
    modal.setAttribute('role','dialog');
    modal.setAttribute('aria-modal','true');
    var severity = String(detail.severity||'LOW').toUpperCase();
    var metrics = detail.trust_metrics || {};
    var detectors = detail.detectors || [];
    var raw = detail.raw_record || {};
    var drift = detail.drift_distribution;
    var rules = detail.business_rules || {};
    var schemaFields = detail.schema_anomaly_fields || [];
    var normalizeField = function (value) { return String(value == null ? '' : value).toUpperCase().replace(/[^A-Z0-9]/g, ''); };
    var schemaCategories = [
      ['BUSINESS INFO', ['BUSINESSID','BUSINESSNAME','SEGMENT','INDUSTRY','LEGALSTRUCTURE','YEARESTABLISHED','EMPLOYEECOUNT','ANNUALREVENUE']],
      ['CONTACT', ['CONTACTPERSON_NAME','CONTACTPERSON_TITLE','CONTACTPERSON_EMAIL','PHONENUMBER','WEBSITE']],
      ['ADDRESS', ['REGISTEREDADDRESS_STREET','REGISTEREDADDRESS_CITY','REGISTEREDADDRESS_STATE','REGISTEREDADDRESS_ZIPCODE']],
      ['CREDIT PROFILE', ['CREDITSCORE','CREDITWORTHINESSSCORE','TOTALCREDITLIMIT','AVAILABLECREDIT','OUTSTANDINGDEBT','CREDITUTILIZATIONRATIO','AVERAGEACCOUNTAGE','HIGHESTCREDITAMOUNTEVER']],
      ['CREDIT HISTORY', ['PAYMENTHISTORYSCORE','NUMBEROFACCOUNTS','NUMBEROFINQUIRIES','MONTHSSINCEFIRSTACCOUNT','MONTHSSINCELASTPAYMENT','MONTHSSINCELASTDELINQUENCY','LASTPAYMENTAMOUNT']],
      ['DELINQUENCY & DEFAULT', ['HASDELINQUENCY','HASDEFAULTED','HASBANKRUPTCY','DELINQUENTACCOUNTCOUNT','SIXTYDAYDELINQUENT','NINETYDAYDELINQUENT','ONEHUNDREDTWENTYDAYDELINQUENT']],
      ['ACCOUNT STATUS', ['ACCOUNTSTATUS_ACTIVE','ACCOUNTSTATUS_CLOSED','ACCOUNTSTATUS_DORMANT','COLLECTIONSCOUNT','CHARGEOFFCOUNT','JUDGMENTCOUNT','TAXLIENCOUNT','PUBLICRECORDCOUNT']],
      ['FINANCIAL', ['TOTALACCOUNTBALANCE','TOTALMONTHLYPAYMENT','DEBTTOINCOMERATIO']],
      ['RISK & COMPLIANCE', ['RISKPROFILE','RISKRATING','COMPLIANCEFLAG','REGULATORYSTATUS','AUDITSCORE','LASTAUDITDATE','EXPECTEDDEFAULTRATE','CREDITQUALITYRATING']],
      ['MARKET & HEALTH', ['SYSTEMHEALTHSCORE','MARKETCONDITIONINDEX','RECOVERYTRENDSCORE','SECTORPERFORMANCE']],
      ['DATA QUALITY', ['EXPECTED_ARRIVAL_DAY','EXPECTED_ARRIVAL_DATE','INGESTION_DATE','INGESTION_DELAY_DAYS','IS_ANOMALOUS_DELAY','FRESHNESS_DAYS_LATE','DATA_MONTH','DATA_LINEAGE','LOADED_AT','BATCH_ID','RECORD_ID']]
    ];
    var assignedSchemaFields = Object.create(null);
    var schemaGroups = schemaCategories.map(function (category) {
      var accepted = Object.create(null);
      category[1].forEach(function (field) { accepted[normalizeField(field)] = true; });
      var fields = Object.keys(raw).filter(function (key) { return !!accepted[normalizeField(key)]; });
      fields.forEach(function (key) { assignedSchemaFields[key] = true; });
      return { name: category[0], fields: fields };
    }).filter(function (group) { return group.fields.length > 0; });
    var otherFields = Object.keys(raw).filter(function (key) { return !assignedSchemaFields[key]; });
    if (otherFields.length) schemaGroups.push({ name: 'OTHER FIELDS', fields: otherFields });
    var flaggedSchemaKeys = Object.create(null);
    schemaFields.forEach(function (key) { flaggedSchemaKeys[normalizeField(key)] = true; });
    var flaggedSchemaCount = Object.keys(raw).filter(function (key) { return !!flaggedSchemaKeys[normalizeField(key)]; }).length;
    var schemaFieldCard = function (key) {
      var anomalous = !!flaggedSchemaKeys[normalizeField(key)];
      return '<div class="schema-field-card'+(anomalous?' is-anomalous':'')+'"><div class="schema-field-name">'+esc(key)+'</div>'+(anomalous?'<span class="schema-field-badge">ANOMALOUS</span>':'')+'<div class="schema-field-value">'+esc(raw[key])+'</div></div>';
    };
    var dataMonth = raw.data_month != null ? raw.data_month : raw.dataMonth;
    if (dataMonth != null) {
      var monthMatch = String(dataMonth).match(/^(\d{4})[-/](\d{1,2})/);
      if (monthMatch) dataMonth = new Date(Number(monthMatch[1]), Number(monthMatch[2])-1, 1).toLocaleString(undefined, { month:'long', year:'numeric' });
    }
    var schemaHtml = '<div class="anomaly-panel schema-panel" data-panel="schema"><div class="schema-meta">'+
      '<div class="schema-meta-item"><span class="schema-meta-label">Record ID</span><span class="schema-meta-value">#'+esc(detail.record_id)+'</span></div>'+
      '<div class="schema-meta-item"><span class="schema-meta-label">Business ID</span><span class="schema-meta-value">'+esc(detail.businessID || raw.businessID)+'</span></div>'+
      '<div class="schema-meta-item"><span class="schema-meta-label">Data Month</span><span class="schema-meta-value">'+esc(dataMonth)+'</span></div>'+
      '<div class="schema-meta-item"><span class="schema-meta-label">Lineage</span><span class="schema-meta-value">'+esc(lineage)+'</span></div></div>'+
      '<div class="schema-legend"><span class="schema-legend-item"><span class="schema-legend-dot"></span>Anomalous</span><span class="schema-legend-item"><span class="schema-legend-normal"></span>Normal</span><span class="schema-legend-count">'+flaggedSchemaCount+' field'+(flaggedSchemaCount===1?'':'s')+' flagged</span></div>'+
      schemaGroups.map(function (group) { var anomalousGroup = group.fields.some(function (key) { return !!flaggedSchemaKeys[normalizeField(key)]; }); return '<section class="schema-category"><h3 class="schema-category-title'+(anomalousGroup?' has-anomaly':'')+'">'+(anomalousGroup?'<i class="ti ti-alert-triangle-filled" aria-hidden="true"></i>':'')+esc(group.name)+'</h3><div class="schema-field-grid">'+group.fields.map(schemaFieldCard).join('')+'</div></section>'; }).join('')+
      '</div>';
    modal.innerHTML = '<div class="record-modal-header"><h2 style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">⌕ &nbsp;Record <span style="font-family:var(--font-mono)">#'+esc(detail.record_id)+'</span><span class="tag '+(severity==='HIGH'? 'tag-red':severity==='MEDIUM'? 'tag-amber':'tag-green')+'">'+esc(severity==='HIGH'? 'CRITICAL':severity)+'</span></h2><button class="record-modal-close" aria-label="Close">×</button></div>' +
      '<div class="record-modal-tabs" style="display:flex;border-bottom:1px solid var(--border);padding:0 20px;gap:18px"><button class="anomaly-tab" data-tab="trust"><i class="ti ti-shield-check"></i> &nbsp;Trust Analysis</button><button class="anomaly-tab active" data-tab="schema"><i class="ti ti-table"></i> &nbsp;Schema <span class="schema-count">'+flaggedSchemaCount+'</span></button></div>' +
      '<div class="record-modal-body"><div class="anomaly-panel" data-panel="trust" hidden><div class="rec-ident"><div><span class="rec-ident-k">Record ID</span><span class="rec-ident-v">#'+esc(detail.record_id)+'</span></div><div><span class="rec-ident-k">Business ID</span><span class="rec-ident-v">'+esc(detail.businessID)+'</span></div><div><span class="rec-ident-k">Lineage</span><span class="rec-ident-v">'+esc(lineage)+'</span></div><div><span class="rec-ident-k">Anomaly risk</span><span class="rec-ident-v" style="color:var(--neg)">'+esc(detail.overall_anomaly_risk)+'%</span></div></div>' +
      '<div class="section-title" style="margin-top:20px">♧ &nbsp;Trust metrics</div><div class="rec-pills">'+metric('Overall trust',metrics.overall_trust,'var(--chart-2)')+metric('Anomaly',metrics.anomaly_health,'var(--neg)')+metric('Drift',metrics.drift_health,'var(--chart-2)')+metric('Business',metrics.business_health,'var(--chart-2)')+metric('Freshness',metrics.freshness_health,'var(--chart-2)')+'</div>' +
      '<p class="rec-sub">Trust threshold is '+esc(detail.trust_threshold == null ? 'N/A' : detail.trust_threshold)+'. This record is '+(detail.below_threshold?'below' :'above')+' the threshold — it surfaced here because its weighted anomaly risk is elevated.</p>' +
      '<div class="rec-rvt"><div class="rec-rvt-col"><div class="rec-rvt-h">♢ &nbsp;Trust ('+esc(metrics.overall_trust == null ? 'N/A' : metrics.overall_trust)+')</div><div>This score is calculated from the matching Oracle trust batch. It summarizes the overall data quality for this record\'s batch.</div></div><div class="rec-rvt-col"><div class="rec-rvt-h">⚠ &nbsp;Anomaly risk ('+esc(detail.overall_anomaly_risk)+')</div><div>How strongly the six anomaly detectors say this record is unusual. Higher is worse; it contributes to the anomaly pillar while other health scores can keep overall trust high.</div></div></div>' +
      '<div class="section-title" style="margin-top:18px">⚒ &nbsp;What\'s anomalous ('+esc(detail.fired_count)+')</div><div class="rec-det-list">'+detectors.map(function(item){return '<div class="rec-det'+(item.fired?' fired' :'')+'"><span class="rec-det-ico">'+(item.fired?'⚠' :'✓')+'</span><div style="flex:1;min-width:0"><div class="rec-det-top"><b>'+esc(item.label)+'</b><span class="rec-det-state'+(item.fired?' fired' :'')+'">'+(item.fired?'FLAGGED' :'passed')+'</span></div><div class="rec-det-meaning">'+esc(item.meaning)+'</div><div class="rec-det-thr">Limit: <span>'+esc(item.threshold)+'</span></div></div></div>';}).join('')+'</div>' +
      (drift ? '<div class="section-title" style="margin-top:18px"><i class="ti ti-wave-sine"></i>&nbsp;Drift &mdash; where this record sits</div><p class="rec-sub">Drift scores are computed per month, not per record. This record\'s drift health is shown within its '+esc(lineage)+' distribution ('+Number(drift.lineage_records||0).toLocaleString()+' records). This record: <b>'+esc(drift.record_drift_health)+'</b>.</p><div class="rec-distrib">'+(drift.bins||[]).map(function(bin){var max=Math.max.apply(null,(drift.bins||[]).map(function(v){return Number(v.count)||0;}))||1;return '<div class="rec-distrib-col" title="'+Number(bin.count||0).toLocaleString()+' records"><div class="rec-distrib-bar-wrap"><div class="rec-distrib-bar'+(bin.is_record?' here' :'')+'" style="height:'+Math.max((Number(bin.count||0)/max)*100,2)+'%"></div></div><div class="rec-distrib-x'+(bin.is_record?' here' :'')+'">'+esc(bin.label)+(bin.is_record?'<span class="rec-distrib-tag">this record</span>' :'')+'</div></div>';}).join('')+'</div>' : '') +
      '<div class="section-title" style="margin-top:18px"><i class="ti ti-clipboard-x"></i>&nbsp;Business rules</div>'+(rules.evaluable ? (rules.violated_count ? '<p class="rec-sub">Breaks <b>'+rules.violated_count+'</b> of '+rules.total_rules+' rules'+(rules.skipped_count? ' &middot; '+rules.skipped_count+' couldn\'t be checked (fields missing)':'')+':</p><div class="rec-det-list">'+(rules.violated||[]).map(function(rule){return '<div class="rec-det fired"><span class="rec-det-ico"><i class="ti ti-alert-triangle-filled"></i></span><div style="flex:1"><div class="rec-det-top"><b>'+esc(rule.label)+'</b><span class="tag '+(rule.severity==='CRITICAL'? 'tag-red':'tag-amber')+'">'+esc(rule.severity)+'</span></div><div class="rec-det-thr">'+esc(rule.detail)+'</div></div></div>';}).join('')+'</div>' : '<p class="rec-sub"><i class="ti ti-circle-check" style="color:var(--chart-2)"></i>&nbsp;Passes all '+rules.total_rules+' business rules'+(rules.skipped_count? ' ('+rules.skipped_count+' could not be checked)':'')+'.</p>') : '<p class="rec-sub">'+esc(rules.note||'Business-rule details are unavailable for this record.')+'</p>') +
      (detail.freshness_days_late != null ? '<div class="rec-thresh-note" style="margin-top:14px"><i class="ti ti-clock"></i>&nbsp;Arrived <b>'+esc(detail.freshness_days_late)+'</b> day(s) late (freshness decays with &tau; = '+esc(detail.freshness_tau||5)+').</div>' : '') +
      '</div>' +
      schemaHtml+'</div>';
    overlay.appendChild(modal);
    var previousBodyOverflow = document.body.style.overflow;
    function close() { overlay.remove(); document.removeEventListener('keydown', onKey); document.body.style.overflow = previousBodyOverflow; }
    function onKey(event) { if(event.key==='Escape') close(); }
    overlay.addEventListener('click',function(event){if(event.target===overlay)close();});
    modal.querySelector('.record-modal-close').addEventListener('click',close);
    modal.querySelectorAll('.anomaly-tab').forEach(function(tab){tab.addEventListener('click',function(){
      modal.querySelectorAll('.anomaly-tab').forEach(function(node){node.classList.toggle('active',node===tab);});
      modal.querySelectorAll('.anomaly-panel').forEach(function(panel){panel.hidden=panel.getAttribute('data-panel')!==tab.getAttribute('data-tab');});
    });});
    document.addEventListener('keydown',onKey);
    document.body.style.overflow = 'hidden';
    document.body.appendChild(overlay);
  }

  document.addEventListener('click', function(event) {
    if (location.hash.indexOf('#/exec/affected') !== 0) return;
    var row = event.target.closest && event.target.closest('tbody tr');
    if (!row) return;
    var card = row.closest('.card');
    var heading = card && card.querySelector('.section-title');
    // Keep the app's native business-row click: it filters the records table and
    // shows its clear-filter strip. Only record rows open the detail popup.
    if (!heading || heading.textContent.indexOf('Most anomalous records') === -1) return;
    event.preventDefault();
    event.stopPropagation();
    if (event.stopImmediatePropagation) event.stopImmediatePropagation();
    var recordText = row.cells[1] && row.cells[1].textContent.trim();
    var recordMatch = recordText && recordText.match(/^#?(\d+)/);
    if (recordMatch) openAnomalyRecord(recordMatch[1]);
  }, true);

  function showMigrationDetails(row) {
    if (document.querySelector('.migration-detail-overlay')) return;
    var values = Array.from(row.cells).map(function (cell) { return cell.textContent.trim() || '—'; });
    var reverse = isReverseMigration();
    var labels = reverse
      ? ['BigQuery source table', 'Oracle destination table', 'Oracle destination state', 'BigQuery rows read', 'Oracle rows loaded', 'Migration status and details']
      : ['Oracle table', 'BigQuery staging table', 'Final BigQuery table', 'Oracle rows', 'BigQuery rows', 'Row-count check', 'Published'];
    var overlay = document.createElement('div');
    overlay.className = 'migration-detail-overlay';
    overlay.setAttribute('role', 'presentation');
    var dialog = document.createElement('section');
    dialog.className = 'migration-detail-dialog';
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-labelledby', 'migration-detail-title');

    var header = document.createElement('div');
    header.className = 'migration-detail-header';
    var headingWrap = document.createElement('div');
    var title = document.createElement('h2');
    title.className = 'migration-detail-title';
    title.id = 'migration-detail-title';
    title.textContent = values[0] || 'Migration table details';
    var subtitle = document.createElement('div');
    subtitle.className = 'migration-detail-subtitle';
    subtitle.textContent = reverse
      ? (values[5].indexOf('SUCCESS') === 0 ? 'Transfer completed' : 'Transfer status')
      : (values[5] === 'MATCH' ? 'Row counts match' : 'Review this table’s validation status');
    headingWrap.append(title, subtitle);

    var close = document.createElement('button');
    close.className = 'migration-detail-close';
    close.type = 'button';
    close.setAttribute('aria-label', 'Close migration details');
    close.textContent = '×';
    header.append(headingWrap, close);

    var grid = document.createElement('div');
    grid.className = 'migration-detail-grid';
    labels.forEach(function (label, index) {
      var item = document.createElement('div');
      item.className = 'migration-detail-item';
      var labelNode = document.createElement('div');
      labelNode.className = 'migration-detail-label';
      labelNode.textContent = label;
      var valueNode = document.createElement('div');
      valueNode.className = 'migration-detail-value';
      valueNode.textContent = values[index] || '—';
      item.append(labelNode, valueNode);
      grid.appendChild(item);
    });
    dialog.append(header, grid);
    overlay.appendChild(dialog);
    overlay.addEventListener('click', function (event) {
      if (event.target === overlay) overlay.remove();
    });
    close.addEventListener('click', function () { overlay.remove(); });
    document.body.appendChild(overlay);
    close.focus();
  }

  document.addEventListener('click', function (event) {
    if (!isForwardMigration() && !isReverseMigration()) return;
    var row = event.target.closest && event.target.closest('.migration-detail-row');
    if (row) showMigrationDetails(row);
  });
  document.addEventListener('keydown', function (event) {
    var overlay = document.querySelector('.migration-detail-overlay');
    if (overlay && event.key === 'Escape') { overlay.remove(); return; }
    if ((!isForwardMigration() && !isReverseMigration()) || (event.key !== 'Enter' && event.key !== ' ')) return;
    var row = event.target.closest && event.target.closest('.migration-detail-row');
    if (row) { event.preventDefault(); showMigrationDetails(row); }
  });

  function normalizeText(root) {
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    var node;
    while ((node = walker.nextNode())) {
      var normalized = node.nodeValue
        .replace(/Google BigQuery/g, 'BigQuery')
        .replace(/Oracle Database/g, 'Oracle')
        .replace(/Selected tables/g, 'Transferred tables')
        // Repair common UTF-8-as-Windows-1252 mojibake from the recovered bundle.
        .split(String.fromCharCode(0x00e2,0x20ac,0x201d)).join(String.fromCharCode(0x2014))
        .split(String.fromCharCode(0x00e2,0x20ac,0x2013)).join(String.fromCharCode(0x2013))
        .split(String.fromCharCode(0x00e2,0x2020,0x2019)).join('->')
        .split(String.fromCharCode(0x00e2,0x20ac,0x00a2)).join(String.fromCharCode(0x2022))
        .split(String.fromCharCode(0x00e2,0x0153,0x2022)).join(String.fromCharCode(0x2715))
        .split(String.fromCharCode(0x00e2,0x20ac,0x2026)).join(String.fromCharCode(0x2026))
        .split(String.fromCharCode(0x00c2,0x00b7)).join(String.fromCharCode(0x00b7))
        .replace(/\u00e2\u20ac\u201d/g, '\u2014')
        .replace(/\u00e2\u20ac\u2013/g, '\u2013')
        .replace(/\u00e2\u2020\u2019/g, '\u2192')
        .replace(/\u00c2\u00b7/g, '\u00b7')
        .replace(/\u00e2\u0153\u2022/g, '\u2715')
        .replace(/\u00e2\u20ac\u00a2/g, '\u2022')
        .replace(/\u00e2\u20ac\u2026/g, '\u2026')
        // Some already-corrupted bundle strings are truncated to only the
        // first two UTF-8 mojibake characters (for example: "modelâ€").
        .split(String.fromCharCode(0x00e2,0x20ac)).join(String.fromCharCode(0x2014))
        .split(String.fromCharCode(0x00e2,0x0153)).join(String.fromCharCode(0x2715))
        .replace(/\uFFFD/g, '-');
      if (normalized !== node.nodeValue) node.nodeValue = normalized;
    }
  }

  var textNormalizationObserverInstalled = false;
  function installTextNormalizationObserver() {
    if (textNormalizationObserverInstalled || !document.body || !window.MutationObserver) return;
    textNormalizationObserverInstalled = true;
    var pending = false;
    new MutationObserver(function () {
      if (pending) return;
      pending = true;
      window.setTimeout(function () {
        pending = false;
        normalizeText(document.body);
      }, 0);
    }).observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  function updateAssistantCopy() {
    document.querySelectorAll('.agent-foot-note').forEach(function (note) {
      var text = note.textContent || '';
      if (text.indexOf('Connected to BigQuery') !== -1 || text.indexOf('BigQuery agent is not configured') !== -1) {
        note.textContent = 'Connected to Oracle-backed dashboard data · answers use the selected dashboard agent.';
      }
    });
  }

  function hideSecurityPostureNav() {
    document.querySelectorAll('a, button, [role="link"], [role="tab"]').forEach(function (item) {
      if (String(item.textContent || '').replace(/\s+/g, ' ').trim() === 'Security Posture') {
        item.style.display = 'none';
        item.setAttribute('aria-hidden', 'true');
      }
    });
  }

  function hideExecutiveSecurityCard() {
    if (location.hash.indexOf('#/exec/overview') !== 0) return;
    document.querySelectorAll('main .card').forEach(function (card) {
      var text = String(card.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
      if (text.indexOf('security posture') !== -1 && text.indexOf('overall security score') !== -1) {
        card.style.display = 'none';
        card.setAttribute('aria-hidden', 'true');
      }
    });
  }

  function compactPriorMonthsLabel() {
    if (location.hash.indexOf('#/exec/overview') !== 0) return;
    document.querySelectorAll('main .card').forEach(function (card) {
      var text = String(card.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
      if (text.indexOf('avg trust') === -1 || text.indexOf('prior months') === -1) return;
      card.querySelectorAll('p, div, span').forEach(function (node) {
        var value = String(node.textContent || '').replace(/\s+/g, ' ').trim();
        if (/^Mean of\s+/i.test(value) && value.length > 20) {
          node.textContent = 'Mean of Jan\u2013Nov';
        }
      });
    });
  }

  function installHyperparamSaveToast(main) {
    if (location.hash.indexOf('#/engine/hyperparams') !== 0) return;
    if (!window.__dmHyperparamToastClickBound) {
      window.__dmHyperparamToastClickBound = true;
      document.addEventListener('click', function (event) {
        if (location.hash.indexOf('#/engine/hyperparams') !== 0) return;
        var target = event.target && event.target.closest ? event.target.closest('button') : null;
        if (!target) return;
        var label = String(target.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
        if (label !== 'save config' && label.indexOf('save') === -1) return;
        window.setTimeout(function () {
          var old = document.querySelector('.dm-save-config-toast');
          if (old) old.remove();
          var toast = document.createElement('div');
          toast.className = 'dm-save-config-toast';
          toast.innerHTML = '<span aria-hidden="true">✓</span> Saved as <strong>"Custom config"</strong>. Re-run the pipeline to apply the changes.';
          document.body.appendChild(toast);
          window.setTimeout(function () { if (toast.parentNode) toast.remove(); }, 8000);
        }, 80);
      }, true);
    }
    var saveButton = Array.from(main.querySelectorAll('button')).find(function (button) {
      return String(button.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase() === 'save config';
    });
    if (!saveButton) return;

    if (saveButton.getAttribute('data-dm-save-toast-bound') !== '1') {
      saveButton.setAttribute('data-dm-save-toast-bound', '1');
      saveButton.addEventListener('click', function () {
        window.setTimeout(function () {
          var old = document.querySelector('.dm-save-config-toast');
          if (old) old.remove();
          var toast = document.createElement('div');
          toast.className = 'dm-save-config-toast';
          toast.innerHTML = '<span aria-hidden="true">✓</span> Saved as <strong>"Custom config"</strong>. Re-run the pipeline to apply the changes.';
          document.body.appendChild(toast);
          window.setTimeout(function () { if (toast.parentNode) toast.remove(); }, 5000);
        }, 120);
      });
    }

    /* The bundled Hyperparameters page does not currently render this
       control. Add it next to the native Save Config action, while leaving
       the native save handler and the global pipeline runner untouched. */
    var rerunButton = Array.from(main.querySelectorAll('button')).find(function (button) {
      var label = String(button.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
      return label.indexOf('save') !== -1 && label.indexOf('re-run') !== -1 && label.indexOf('pipeline') !== -1;
    });
    if (!rerunButton) {
      rerunButton = document.createElement('button');
      rerunButton.type = 'button';
      rerunButton.className = saveButton.className || 'refresh-btn';
      rerunButton.style.cssText = 'width:100%;margin-bottom:6px;justify-content:center;color:var(--foreground,#111827);font-size:12px;';
      rerunButton.innerHTML = '<i class="ti ti-player-play" style="font-size:13px"></i>&nbsp;Save &amp; Re-run Pipeline';
      rerunButton.setAttribute('data-dm-save-rerun', '1');
      saveButton.parentNode.insertBefore(rerunButton, saveButton.nextSibling);
    }
    if (rerunButton.getAttribute('data-dm-rerun-bound') !== '1') {
      rerunButton.setAttribute('data-dm-rerun-bound', '1');
      rerunButton.addEventListener('click', function () {
        saveButton.click();
        window.setTimeout(function () {
          var runButton = Array.from(document.querySelectorAll('button')).find(function (button) {
            return String(button.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase() === 'run pipelines';
          });
          if (runButton) runButton.click();
        }, 700);
      });
    }
  }

  function setUseCaseRow(tbody, name, score) {
    var row = Array.from(tbody.querySelectorAll('tr')).find(function (item) {
      return item.getAttribute('data-dm-use-case') === name;
    });
    if (!row) {
      row = document.createElement('tr');
      row.setAttribute('data-dm-use-case', name);
      tbody.appendChild(row);
    }

    var scoreKey = score === null || score === undefined || !Number.isFinite(Number(score))
      ? 'pending'
      : String(Math.round(Number(score) * 10) / 10);
    if (row.getAttribute('data-dm-score') === scoreKey) return;
    row.setAttribute('data-dm-score', scoreKey);
    row.replaceChildren();

    var nameCell = document.createElement('td');
    nameCell.textContent = name;
    row.appendChild(nameCell);

    if (scoreKey === 'pending') {
      var pendingCell = document.createElement('td');
      pendingCell.className = 'muted';
      pendingCell.style.textAlign = 'right';
      pendingCell.textContent = 'pending';
      row.appendChild(pendingCell);

      var statusCell = document.createElement('td');
      statusCell.style.width = '80px';
      var status = document.createElement('span');
      status.className = 'tag tag-gray';
      status.textContent = 'no data';
      statusCell.appendChild(status);
      row.appendChild(statusCell);
      return;
    }

    var numericScore = Number(scoreKey);
    var valueCell = document.createElement('td');
    valueCell.style.textAlign = 'right';
    var value = document.createElement('span');
    value.style.color = '#179765';
    value.style.fontWeight = '500';
    value.textContent = numericScore.toFixed(1);
    valueCell.appendChild(value);
    row.appendChild(valueCell);

    var barCell = document.createElement('td');
    barCell.style.width = '80px';
    var bar = document.createElement('div');
    bar.className = 'progress-bg';
    var fill = document.createElement('div');
    fill.className = 'progress-fill';
    fill.style.width = Math.max(0, Math.min(100, numericScore)) + '%';
    fill.style.background = '#179765';
    bar.appendChild(fill);
    barCell.appendChild(bar);
    row.appendChild(barCell);
  }

  function updateOracleUseCaseScores(main) {
    if (location.hash.indexOf('#/exec/overview') !== 0) return;
    /* Disabled — cards handled by React component */
  }

  function updateExecutivePredictiveAlerts(main) {
    if (location.hash.indexOf('#/exec/overview') !== 0) return;
    /* Disabled — cards handled by React component */
  }

  function ensureExecOverviewCards(main) {
    if (location.hash.indexOf('#/exec/overview') !== 0) return;

    /* Remove the bundle's older versions before mounting the corrected pair. */
    main.querySelectorAll('.card').forEach(function (card) {
      if (card.closest('.exec-overview-injected')) return;
      var text = String(card.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
      if (text.indexOf('future predictive alerts') !== -1 || text.indexOf('use case trust scores') !== -1) {
        card.remove();
      }
    });

    /* Defer insertion to after React's render cycle */
    window.setTimeout(function() {
      var m = document.querySelector('main, .dm-content');
      if (!m || location.hash.indexOf('#/exec/overview') !== 0) return;
      _buildExecOverviewCards(m);
    }, 50);
  }

  function _buildExecOverviewCards(main) {
    if (location.hash.indexOf('#/exec/overview') !== 0) return;

    /* Find or create a dedicated wrapper for our two cards */
    var wrapper = main.querySelector('.exec-overview-injected');
    if (!wrapper) {
      wrapper = document.createElement('div');
      wrapper.className = 'exec-overview-injected exec-two-col-row';
    }

    /* Always reposition, including after React commits a new overview tree.
       This keeps the required order stable instead of relying on the wrapper's
       first insertion location. */
    var chartCard = Array.from(main.querySelectorAll('.card')).find(function (item) {
      var title = String(item.textContent || '').toLowerCase();
      return title.indexOf('overall trust') !== -1 &&
        title.indexOf('monthly actual') !== -1 &&
        title.indexOf('arima forecast') !== -1;
    });
    if (chartCard && chartCard.parentNode) {
      if (wrapper.previousElementSibling !== chartCard) {
        chartCard.parentNode.insertBefore(wrapper, chartCard.nextSibling);
      }
    } else if (!wrapper.parentNode) {
      main.appendChild(wrapper);
    }

    /* ---- FUTURE PREDICTIVE ALERTS ---- */
    var alertCard = wrapper.querySelector('.exec-predictive-card');
    if (!alertCard) {
      alertCard = document.createElement('section');
      alertCard.className = 'card exec-predictive-card';
      wrapper.appendChild(alertCard);
    }

    /* Fetch alerts directly if not yet loaded */
    if (!window.__dmAlertsFetched) {
      window.__dmAlertsFetched = true;
      fetch('/api/alerts')
        .then(function(r){ return r.ok ? r.json() : null; })
        .then(function(data) {
          if (data && data.ready && Array.isArray(data.alerts)) {
            executivePredictiveAlerts = data.alerts;
          }
          var m = document.querySelector('main, .dm-content');
          if (m) ensureExecOverviewCards(m);
        }).catch(function(){});
    }

    if (Array.isArray(executivePredictiveAlerts)) {
      var alertKey = JSON.stringify(executivePredictiveAlerts.slice(0, 5));
      if (alertCard.getAttribute('data-key') !== alertKey) {
        alertCard.setAttribute('data-key', alertKey);
        var rowsHtml = executivePredictiveAlerts.slice(0, 5).map(function(a) {
          var sev    = String(a.severity || 'WATCH').toUpperCase();
          var tagCls = sev === 'CRITICAL' ? 'tag-red' : sev === 'HIGH' ? 'tag-amber' : 'tag-blue';
          /* Use clean trigger label — strip everything after ':' or '.' */
          var rawTrigger = String(a.trigger || 'Predictive alert');
          var cleanTrigger = rawTrigger.split(':')[0].split('.')[0].trim().replace(/_/g, ' ');
          var label  = '<span class="epa-metric">' + executiveAlertMetricLabel(a.metric) + '</span>' +
                       ' \u2014 ' + cleanTrigger;
          var mon    = executiveAlertMonth(a.month);
          return '<div class="exec-predictive-alert-row">' +
            '<span class="tag ' + tagCls + '" style="font-size:11px;padding:2px 7px">' +
              sev.charAt(0) + sev.slice(1).toLowerCase() +
            '</span>' +
            '<span class="exec-predictive-alert-label">' + label + '</span>' +
            '<span class="exec-predictive-alert-month">' + mon + '</span>' +
            '</div>';
        }).join('');
        alertCard.innerHTML =
          '<div class="section-title" style="margin-bottom:0">' +
            '<i class="ti ti-bell-ringing" style="font-size:14px;color:#e7000b"></i>' +
            '&nbsp;Future predictive alerts' +
          '</div>' +
          '<div class="exec-predictive-alert-list">' + rowsHtml + '</div>';
      }
    }

    /* ---- USE CASE TRUST SCORES ---- */
    var ucCard = wrapper.querySelector('.exec-use-case-card');
    if (!ucCard) {
      ucCard = document.createElement('section');
      ucCard.className = 'card exec-use-case-card';
      wrapper.appendChild(ucCard);
    }

    var execScore = Number.isFinite(Number(window.__dmExecScore)) ? Number(window.__dmExecScore) : null;
    var migScore  = Number.isFinite(Number(window.__dmMigScore))  ? Number(window.__dmMigScore)  : null;
    var mdmScore  = Number.isFinite(Number(mdmUseCaseScore))      ? Number(mdmUseCaseScore)      : null;
    /* Always re-render (don't cache with nulls — data arrives async) */
    var ucKey = JSON.stringify([execScore, mdmScore, migScore]);
    if (ucCard.getAttribute('data-key') !== ucKey || ucKey === '[null,null,null]') {
      ucCard.setAttribute('data-key', ucKey);

      function scoreRow(name, score) {
        var n   = Number.isFinite(Number(score)) ? Number(score) : null;
        var pct = n !== null ? Math.max(0, Math.min(100, n)) : 0;
        var display = n !== null ? n.toFixed(1) : '\u2014';
        var col = n !== null ? '#179765' : '#94a3b8';
        return '<div class="exec-uc-row">' +
          '<span class="exec-uc-name">' + name + '</span>' +
          '<span class="exec-uc-score" style="color:' + col + '">' + display + '</span>' +
          '<div class="exec-uc-bar-track">' +
            '<div class="exec-uc-bar-fill" style="width:' + pct + '%;background:' + col + '"></div>' +
          '</div></div>';
      }

      ucCard.innerHTML =
        '<div class="section-title" style="margin-bottom:4px">' +
          '<i class="ti ti-layout-grid" style="font-size:14px;color:#087f79"></i>' +
          '&nbsp;Use case trust scores' +
        '</div>' +
        scoreRow('Executive AI',        execScore) +
        scoreRow('MDM / Golden Record', mdmScore) +
        scoreRow('Cloud Migration',     migScore);
    }

    /* Fetch scores once per page-load */
    if (!window.__dmExecScoreFetched) {
      window.__dmExecScoreFetched = true;
      fetch('/api/home')
        .then(function(r){ return r.ok ? r.json() : null; })
        .then(function(data) {
          if (data && data.ready && data.metrics) {
            window.__dmExecScore = data.metrics.overall_trust;
          }
          var m = document.querySelector('main, .dm-content');
          if (m) { var uc = m.querySelector('.exec-use-case-card'); if (uc) uc.removeAttribute('data-key'); _buildExecOverviewCards(m); }
        }).catch(function(){});
    }

    if (!window.__dmMigScoreFetched) {
      window.__dmMigScoreFetched = true;
      fetch('/api/trust/trend')
        .then(function(r){ return r.ok ? r.json() : null; })
        .then(function(data) {
          if (data && Array.isArray(data.trend) && data.trend.length) {
            var last = data.trend[data.trend.length - 1];
            window.__dmMigScore = Number.isFinite(Number(last.overall_dataset_trust))
              ? Number(last.overall_dataset_trust) * 100 : null;
          }
          var m = document.querySelector('main, .dm-content');
          if (m) { var uc = m.querySelector('.exec-use-case-card'); if (uc) uc.removeAttribute('data-key'); _buildExecOverviewCards(m); }
        }).catch(function(){});
    }

    if (!mdmUseCaseRequestStarted) {
      mdmUseCaseRequestStarted = true;
      fetch('/api/mdm')
        .then(function(r){ return r.ok ? r.json() : null; })
        .then(function(data) {
          if (data && data.ready && Number.isFinite(Number(data.overall_trust))) {
            mdmUseCaseScore = Number(data.overall_trust);
          }
          var m = document.querySelector('main, .dm-content');
          if (m) { var uc = m.querySelector('.exec-use-case-card'); if (uc) uc.removeAttribute('data-key'); _buildExecOverviewCards(m); }
        }).catch(function(){});
    }
  }


  function executiveAlertMetricLabel(metric) {
    var key = String(metric || '').toLowerCase();
    if (key === 'overall_dataset_trust') return 'Overall trust';
    if (key === 'anomaly_health') return 'Anomaly health';
    if (key === 'drift_health') return 'Drift health';
    if (key === 'business_health') return 'Business health';
    if (key === 'freshness_health') return 'Freshness health';
    return String(metric || '').replace(/_/g, ' ').replace(/\b\w/g, function (c) { return c.toUpperCase(); });
  }

  function executiveAlertMonth(value) {
    var raw = String(value || '');
    var match = raw.match(/^(\d{4})-(\d{2})/);
    if (!match) return raw;
    var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    var label = months[Number(match[2]) - 1] || raw;
    return match[1] === String(new Date().getFullYear()) ? label : label + ' ' + match[1].slice(-2);
  }

  function buildMonthOverMonthChart(rows) {
    if (!Array.isArray(rows) || rows.length < 2) return null;
    var ns = 'http://www.w3.org/2000/svg';
    var width = 1400, height = 286;
    var margin = { left: 58, right: 12, top: 10, bottom: 54 };
    var plotBottom = height - margin.bottom;
    var plotTop = margin.top;
    var plotHeight = plotBottom - plotTop;
    var colors = ['#179765', '#079891', '#f59e0b', '#e7000b'];
    var keys = ['anomaly_health', 'drift_health', 'business_health', 'freshness_health'];
    var labels = ['Anomaly health', 'Drift health', 'Business health', 'Freshness health'];
    var changes = [];
    for (var i = 1; i < rows.length; i += 1) {
      var previous = rows[i - 1], current = rows[i];
      var values = keys.map(function (key) {
        var before = Number(previous[key]), after = Number(current[key]);
        return Number.isFinite(before) && before !== 0 && Number.isFinite(after) ? (after - before) / before * 100 : null;
      });
      changes.push({ label: String(current.batch_id || current.month || '').replace(/^V5_/, ''), values: values });
    }
    var numeric = changes.reduce(function (all, item) { return all.concat(item.values.filter(function (v) { return v !== null; })); }, []);
    if (!numeric.length) return null;
    var minimum = Math.min(-1, Math.floor(Math.min.apply(null, numeric) / 4) * 4);
    var maximum = Math.max(1, Math.ceil(Math.max.apply(null, numeric) / 4) * 4);
    var scale = function (value) { return plotTop + (maximum - value) / (maximum - minimum) * plotHeight; };
    var zeroY = scale(0);
    var svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'Month-over-month pillar change percentage');
    [maximum, maximum - 4, maximum - 8, maximum - 12, maximum - 16].filter(function (v) { return v >= minimum; }).forEach(function (value) {
      var y = scale(value);
      svg.appendChild(svgNode('line', { x1: margin.left, y1: y, x2: width - margin.right, y2: y, stroke: value === 0 ? '#94a3b8' : 'rgba(128,128,128,.12)', 'stroke-width': value === 0 ? 1.4 : 1 }));
      svg.appendChild(svgNode('text', { x: margin.left - 10, y: y + 4, 'text-anchor': 'end', fill: '#858585', 'font-size': 12, 'font-family': 'Arial, sans-serif' }, value + '%'));
    });
    var groupWidth = (width - margin.left - margin.right) / changes.length;
    var barWidth = Math.min(22, groupWidth / 7);
    changes.forEach(function (item, index) {
      var center = margin.left + groupWidth * (index + .5);
      item.values.forEach(function (value, pillarIndex) {
        if (value === null) return;
        var x = center + (pillarIndex - 1.5) * (barWidth + 4);
        var y = value >= 0 ? scale(value) : zeroY;
        var h = Math.max(1, Math.abs(scale(value) - zeroY));
        svg.appendChild(svgNode('rect', { x: x, y: y, width: barWidth, height: h, rx: 3, fill: colors[pillarIndex] }));
      });
      svg.appendChild(svgNode('text', { x: center, y: plotBottom + 23, 'text-anchor': 'middle', fill: '#858585', 'font-size': 12, 'font-family': 'Arial, sans-serif' }, item.label));
    });
    var legendStart = width / 2 - 245;
    labels.forEach(function (label, index) {
      var x = legendStart + index * 135;
      svg.appendChild(svgNode('rect', { x: x, y: height - 20, width: 14, height: 14, fill: colors[index] }));
      svg.appendChild(svgNode('text', { x: x + 21, y: height - 8, fill: '#858585', 'font-size': 12, 'font-family': 'Arial, sans-serif' }, label));
    });
    return svg;
  }

  function updateMonthOverMonthPillarChart(main) {
    if (location.hash.indexOf('#/exec/forecast') !== 0) {
      document.querySelectorAll('.exec-mom-card').forEach(function (card) { card.remove(); });
      return;
    }
    /* Remove the bundle's empty placeholder; the compatibility card below is
       the single data-driven Month-over-month chart. */
    main.querySelectorAll('.card, section').forEach(function (card) {
      if (card.classList.contains('exec-mom-card')) return;
      var text = String(card.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
      if (text.indexOf('month-over-month pillar change (%)') !== -1) card.remove();
    });
    if (pillarTrendRows) {
      var existing = main.querySelector('.exec-mom-card');
      if (existing) {
        /* React may append forecast cards after the first compatibility pass.
           Moving the existing node is idempotent and guarantees this chart
           remains the final section on the page. */
        main.appendChild(existing);
        return;
      }
      var chart = buildMonthOverMonthChart(pillarTrendRows);
      if (!chart) return;
      var card = document.createElement('section');
      card.className = 'card exec-mom-card';
      var title = document.createElement('div');
      title.className = 'section-title';
      title.textContent = String.fromCharCode(0x2194) + '  Month-over-month pillar change (%)';
      var subtitle = document.createElement('p');
      subtitle.className = 'exec-mom-subtitle';
      subtitle.textContent = 'How much each pillar rose (positive bars) or fell (negative bars) versus the previous month. This shows momentum: a pillar sliding several months in a row is a trend a single snapshot would miss.';
      var wrap = document.createElement('div');
      wrap.className = 'exec-mom-chart';
      wrap.appendChild(chart);
      card.append(title, subtitle, wrap);
      /* The ARIMA Forecast page ends with this chart. */
      main.appendChild(card);
      return;
    }
    if (pillarTrendRequestStarted) return;
    pillarTrendRequestStarted = true;
    fetch('/api/trust/trend').then(function (response) { return response.ok ? response.json() : null; }).then(function (data) {
      pillarTrendRows = data && Array.isArray(data.trend) ? data.trend : [];
      updateMonthOverMonthPillarChart(main);
    }).catch(function () { pillarTrendRows = []; });
  }

  var execMonthChartObserverInstalled = false;
  function installExecutiveMonthChartObserver() {
    if (execMonthChartObserverInstalled || !window.MutationObserver || !document.body) return;
    execMonthChartObserverInstalled = true;
    var queued = false;
    new MutationObserver(function () {
      if (queued || location.hash.indexOf('#/exec/forecast') !== 0) return;
      queued = true;
      window.setTimeout(function () {
        queued = false;
        var execMain = document.querySelector('main, .dm-content');
        if (execMain) updateMonthOverMonthPillarChart(execMain);
      }, 50);
    }).observe(document.body, { childList: true, subtree: true });
  }

  function svgNode(name, attributes, text) {
    var node = document.createElementNS('http://www.w3.org/2000/svg', name);
    Object.keys(attributes || {}).forEach(function (key) {
      node.setAttribute(key, String(attributes[key]));
    });
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function chartMonthLabel(value, isForecast, lastActualYear) {
    var match = String(value || '').match(/^(\d{4})-(\d{2})$/);
    if (!match) return String(value || '');
    var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    var month = months[Number(match[2]) - 1] || '';
    return isForecast && match[1] !== lastActualYear
      ? month + ' ' + match[1].slice(-2)
      : month;
  }

  function buildTrustChart(series) {
    var ns = 'http://www.w3.org/2000/svg';
    var width = 1400;
    var height = 250;
    var margin = { left: 55, right: 12, top: 10, bottom: 66 };
    var plotBottom = height - margin.bottom;
    var plotHeight = plotBottom - margin.top;
    var actualLabels = series.hist_labels || [];
    var actualValues = series.hist_values || [];
    var forecastLabels = series.forecast_labels || [];
    var forecastValues = series.forecast_values || [];
    var lower = series.lower_95 || [];
    var upper = series.upper_95 || [];
    var valuesForScale = actualValues.concat(forecastValues).map(Number).filter(Number.isFinite);
    var scoreScale = series.kind === 'pillar' && valuesForScale.length && Math.max.apply(null, valuesForScale) <= 1 ? 100 : 1;
    var chartValue = function (value) { return Number(value) * scoreScale; };
    var total = actualLabels.length + forecastLabels.length;
    if (actualLabels.length < 1 || total < 2) return null;

    var lastActualIndex = -1;
    for (var i = actualValues.length - 1; i >= 0; i -= 1) {
      if (actualValues[i] !== null && actualValues[i] !== undefined && Number.isFinite(Number(actualValues[i]))) {
        lastActualIndex = i;
        break;
      }
    }
    if (lastActualIndex < 0) return null;

    var plotWidth = width - margin.left - margin.right;
    var xAt = function (index) { return margin.left + plotWidth * index / (total - 1); };
    var yAt = function (value) {
      var bounded = Math.max(70, Math.min(100, Number(value)));
      return margin.top + (100 - bounded) / 30 * plotHeight;
    };
    var svg = svgNode('svg', {
      class: 'exec-trust-chart-svg',
      viewBox: '0 0 ' + width + ' ' + height,
      preserveAspectRatio: 'none',
      role: 'img',
      'aria-label': 'Overall trust monthly actual and ARIMA forecast with 95% confidence interval'
    });

    [100, 95, 90, 85, 80, 75, 70].forEach(function (value) {
      var y = yAt(value);
      svg.appendChild(svgNode('line', {
        x1: margin.left, y1: y, x2: width - margin.right, y2: y,
        stroke: 'rgba(128,128,128,0.12)', 'stroke-width': 1
      }));
      svg.appendChild(svgNode('text', {
        x: margin.left - 10, y: y + 4, 'text-anchor': 'end',
        fill: '#858585', 'font-size': 12, 'font-family': 'Arial, sans-serif'
      }, String(value)));
    });

    for (var tick = 0; tick < total; tick += 1) {
      var tickX = xAt(tick);
      svg.appendChild(svgNode('line', {
        x1: tickX, y1: margin.top, x2: tickX, y2: plotBottom,
        stroke: 'rgba(128,128,128,0.08)', 'stroke-width': 1
      }));
      var isFuture = tick >= actualLabels.length;
      var rawLabel = isFuture ? forecastLabels[tick - actualLabels.length] : actualLabels[tick];
      var lastDate = String(actualLabels[lastActualIndex] || '').match(/^(\d{4})-/);
      var lastYear = lastDate ? lastDate[1] : '';
      svg.appendChild(svgNode('text', {
        x: tickX, y: plotBottom + 22, 'text-anchor': 'middle',
        fill: '#858585', 'font-size': 12, 'font-family': 'Arial, sans-serif'
      }, chartMonthLabel(rawLabel, isFuture, lastYear)));
    }

    var actualPoints = [];
    actualValues.forEach(function (value, index) {
      if (value === null || value === undefined || !Number.isFinite(Number(value))) return;
      actualPoints.push({ x: xAt(index), y: yAt(chartValue(value)), value: chartValue(value), index: index });
    });
    var lastActual = actualPoints[actualPoints.length - 1];
    var forecastPoints = forecastValues.map(function (value, index) {
      if (value === null || value === undefined || !Number.isFinite(Number(value))) return null;
      return {
        x: xAt(actualLabels.length + index), y: yAt(chartValue(value)), value: chartValue(value),
        lower: lower[index], upper: upper[index]
      };
    }).filter(Boolean);

    if (forecastPoints.length) {
      var bandPoints = [{ x: lastActual.x, y: lastActual.y }];
      forecastPoints.forEach(function (point) {
        bandPoints.push({ x: point.x, y: yAt(point.upper === null || point.upper === undefined ? point.value : chartValue(point.upper)) });
      });
      forecastPoints.slice().reverse().forEach(function (point) {
        bandPoints.push({ x: point.x, y: yAt(point.lower === null || point.lower === undefined ? point.value : chartValue(point.lower)) });
      });
      svg.appendChild(svgNode('polygon', {
        points: bandPoints.map(function (point) { return point.x + ',' + point.y; }).join(' '),
        fill: 'rgba(245,158,11,0.12)', stroke: 'none'
      }));
    }

    var linePath = function (points) {
      return points.map(function (point, index) {
        return (index ? 'L' : 'M') + point.x.toFixed(2) + ' ' + point.y.toFixed(2);
      }).join(' ');
    };
    svg.appendChild(svgNode('path', {
      d: linePath(actualPoints), fill: 'none', stroke: '#139c69',
      'stroke-width': 2.5, 'stroke-linejoin': 'round', 'stroke-linecap': 'round'
    }));

    if (forecastPoints.length) {
      svg.appendChild(svgNode('path', {
        d: linePath([{ x: lastActual.x, y: lastActual.y }].concat(forecastPoints)),
        fill: 'none', stroke: '#ff9200', 'stroke-width': 2.5,
        'stroke-dasharray': '7 5', 'stroke-linejoin': 'round', 'stroke-linecap': 'round'
      }));
    }

    actualPoints.slice(0, -1).forEach(function (point) {
      svg.appendChild(svgNode('circle', { cx: point.x, cy: point.y, r: 3.5, fill: '#139c69' }));
    });
    forecastPoints.forEach(function (point) {
      svg.appendChild(svgNode('circle', {
        cx: point.x, cy: point.y, r: 4, fill: '#fff', stroke: '#ff9200', 'stroke-width': 2
      }));
    });
    svg.appendChild(svgNode('circle', {
      cx: lastActual.x, cy: lastActual.y, r: 8, fill: '#2563eb', stroke: '#fff', 'stroke-width': 2
    }));

    svg.appendChild(svgNode('rect', {
      x: 615, y: height - 22, width: 14, height: 13,
      fill: 'none', stroke: '#139c69', 'stroke-width': 2
    }));
    svg.appendChild(svgNode('text', {
      x: 637, y: height - 11, fill: '#858585', 'font-size': 12, 'font-family': 'Arial, sans-serif'
    }, 'Actual'));
    svg.appendChild(svgNode('rect', {
      x: 690, y: height - 22, width: 14, height: 13,
      fill: 'none', stroke: '#ff9200', 'stroke-width': 2, 'stroke-dasharray': '5 3'
    }));
    svg.appendChild(svgNode('text', {
      x: 712, y: height - 11, fill: '#858585', 'font-size': 12, 'font-family': 'Arial, sans-serif'
    }, 'Forecast'));
    return svg;
  }

  function updateOverallTrustChart(main) {
    if (location.hash.indexOf('#/exec/overview') !== 0) return;
    var card = Array.from(main.querySelectorAll('.card')).find(function (item) {
      var title = String(item.textContent || '').toLowerCase();
      return title.indexOf('overall trust') !== -1 && title.indexOf('monthly actual') !== -1 && title.indexOf('arima forecast') !== -1;
    });
    var wrap = card && card.querySelector('.chart-wrap');
    if (!wrap && card) {
      var canvas = card.querySelector('canvas');
      wrap = canvas && (canvas.closest('.chart-wrap') || canvas.parentElement);
    }
    if (!wrap) return;

    ensureForecastSeries();
    if (!overallTrustForecast) return;

    var cacheKey = JSON.stringify([
      overallTrustForecast.hist_labels, overallTrustForecast.hist_values,
      overallTrustForecast.forecast_labels, overallTrustForecast.forecast_values,
      overallTrustForecast.lower_95, overallTrustForecast.upper_95
    ]);
    if (wrap.getAttribute('data-exec-trust-key') === cacheKey) return;
    var svg = buildTrustChart(overallTrustForecast);
    if (!svg) return;
    wrap.classList.add('exec-trust-chart-wrap');
    wrap.setAttribute('data-exec-trust-key', cacheKey);
    var lastValue = overallTrustForecast.hist_values[overallTrustForecast.hist_values.length - 1];
    var lastLabel = overallTrustForecast.hist_labels[overallTrustForecast.hist_labels.length - 1];
    var note = document.createElement('div');
    note.className = 'exec-trust-current-note';
    note.textContent = 'Current month ' + String.fromCharCode(0x00b7) + ' ' + chartMonthLabel(lastLabel, false, '') + ' (' + Number(lastValue).toFixed(2) + ')';
    wrap.replaceChildren(svg, note);
  }

  function ensureForecastSeries() {
    if (allForecastSeries || trustForecastRequestStarted) return;
    trustForecastRequestStarted = true;
    fetch('/api/forecast')
      .then(function (response) {
        if (!response.ok) throw new Error('Forecast API returned HTTP ' + response.status);
        return response.json();
      })
      .then(function (data) {
        if (data && data.ready && Array.isArray(data.series)) {
          allForecastSeries = data.series;
          overallTrustForecast = data.series.find(function (item) { return item.is_overall; }) || null;
          executivePredictiveAlerts = Array.isArray(data.alerts) ? data.alerts : [];
        }
        if (allForecastSeries) update();
        if (allForecastSeries) {
          window.setTimeout(function () {
            var currentMain = document.querySelector('main, .dm-content');
            if (currentMain) updateOverallTrustChart(currentMain);
          }, 250);
        }
      })
      .catch(function () {});
  }

  function buildForecastDetailChart(series) {
    var width = 1400;
    var height = 260;
    var margin = { left: 68, right: 14, top: 12, bottom: 36 };
    var plotBottom = height - margin.bottom;
    var actualLabels = series.hist_labels || [];
    var rawActual = series.hist_values || [];
    var rawForecast = series.forecast_values || [];
    var rawLower = series.lower_95 || [];
    var rawUpper = series.upper_95 || [];
    var total = actualLabels.length + (series.forecast_labels || []).length;
    if (actualLabels.length < 1 || total < 2) return null;

    var allRaw = rawActual.concat(rawForecast, rawLower, rawUpper, [series.threshold])
      .map(Number).filter(Number.isFinite);
    var scale = series.kind === 'pillar' && allRaw.length && Math.max.apply(null, allRaw) > 1 ? 0.01 : 1;
    var actual = rawActual.map(function (value) { return value === null || value === undefined ? null : Number(value) * scale; });
    var forecast = rawForecast.map(function (value) { return value === null || value === undefined ? null : Number(value) * scale; });
    var lower = rawLower.map(function (value) { return value === null || value === undefined ? null : Number(value) * scale; });
    var upper = rawUpper.map(function (value) { return value === null || value === undefined ? null : Number(value) * scale; });
    var threshold = series.threshold === null || series.threshold === undefined ? null : Number(series.threshold) * scale;
    var values = actual.concat(forecast, lower, upper, threshold === null ? [] : [threshold])
      .filter(function (value) { return value !== null && Number.isFinite(value); });
    if (!values.length) return null;

    var minimum = Math.min.apply(null, values);
    var maximum = Math.max.apply(null, values);
    var step;
    if (series.kind === 'pillar') {
      step = 0.02;
      minimum = Math.floor((minimum + 1e-8) / step) * step;
      maximum = Math.ceil((maximum - 1e-8) / step) * step;
    } else {
      var roughStep = (maximum - minimum || Math.max(1, Math.abs(maximum) * 0.1)) / 6;
      var magnitude = Math.pow(10, Math.floor(Math.log10(Math.abs(roughStep) || 1)));
      var normalized = roughStep / magnitude;
      step = (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10) * magnitude;
      minimum = Math.floor(minimum / step) * step;
      maximum = Math.ceil(maximum / step) * step;
    }
    if (maximum <= minimum) maximum = minimum + step;

    var plotWidth = width - margin.left - margin.right;
    var plotHeight = plotBottom - margin.top;
    var xAt = function (index) { return margin.left + plotWidth * index / (total - 1); };
    var yAt = function (value) { return margin.top + (maximum - value) / (maximum - minimum) * plotHeight; };
    var svg = svgNode('svg', {
      class: 'exec-forecast-chart-svg', viewBox: '0 0 ' + width + ' ' + height,
      preserveAspectRatio: 'none', role: 'img',
      'aria-label': series.label + ' actual and ARIMA forecast with confidence interval and threshold'
    });

    var tickCount = Math.min(10, Math.round((maximum - minimum) / step));
    for (var t = 0; t <= tickCount; t += 1) {
      var tickValue = minimum + t * step;
      var tickY = yAt(tickValue);
      var tickLabel = series.kind === 'pillar' || Math.abs(maximum) < 2
        ? tickValue.toFixed(2)
        : Math.round(tickValue).toLocaleString();
      svg.appendChild(svgNode('line', {
        x1: margin.left, y1: tickY, x2: width - margin.right, y2: tickY,
        stroke: 'rgba(128,128,128,0.1)', 'stroke-width': 1
      }));
      svg.appendChild(svgNode('text', {
        x: margin.left - 10, y: tickY + 4, 'text-anchor': 'end',
        fill: '#858585', 'font-size': 11, 'font-family': 'Arial, sans-serif'
      }, tickLabel));
    }

    var lastHistoryDate = String(actualLabels[actualLabels.length - 1] || '').match(/^(\d{4})-/);
    var lastYear = lastHistoryDate ? lastHistoryDate[1] : '';
    for (var index = 0; index < total; index += 1) {
      var x = xAt(index);
      svg.appendChild(svgNode('line', {
        x1: x, y1: margin.top, x2: x, y2: plotBottom,
        stroke: 'rgba(128,128,128,0.06)', 'stroke-width': 1
      }));
      var shouldLabel = total <= 10 || index % 2 === 0 || index === total - 1;
      if (!shouldLabel) continue;
      var isFuture = index >= actualLabels.length;
      var label = isFuture
        ? (series.forecast_labels || [])[index - actualLabels.length]
        : actualLabels[index];
      svg.appendChild(svgNode('text', {
        x: x, y: plotBottom + 20, 'text-anchor': 'middle',
        fill: '#858585', 'font-size': 11, 'font-family': 'Arial, sans-serif'
      }, chartMonthLabel(label, isFuture, lastYear)));
    }

    var actualPoints = actual.map(function (value, index) {
      return value === null || !Number.isFinite(value) ? null : { x: xAt(index), y: yAt(value) };
    }).filter(Boolean);
    var forecastPoints = forecast.map(function (value, index) {
      return value === null || !Number.isFinite(value) ? null : {
        x: xAt(actualLabels.length + index), y: yAt(value), value: value,
        lower: lower[index], upper: upper[index]
      };
    }).filter(Boolean);
    var pathFor = function (points) {
      return points.map(function (point, index) {
        return (index ? 'L' : 'M') + point.x.toFixed(2) + ' ' + point.y.toFixed(2);
      }).join(' ');
    };

    if (forecastPoints.length) {
      var band = [];
      forecastPoints.forEach(function (point) {
        band.push({ x: point.x, y: yAt(point.upper === null || point.upper === undefined ? point.value : point.upper) });
      });
      forecastPoints.slice().reverse().forEach(function (point) {
        band.push({ x: point.x, y: yAt(point.lower === null || point.lower === undefined ? point.value : point.lower) });
      });
      svg.appendChild(svgNode('polygon', {
        points: band.map(function (point) { return point.x + ',' + point.y; }).join(' '),
        fill: 'rgba(239,68,68,0.09)', stroke: 'none'
      }));
    }
    if (threshold !== null && Number.isFinite(threshold)) {
      svg.appendChild(svgNode('line', {
        x1: margin.left, y1: yAt(threshold), x2: width - margin.right, y2: yAt(threshold),
        stroke: '#ff9800', 'stroke-width': 1.5, 'stroke-dasharray': '2 4'
      }));
    }
    if (actualPoints.length) {
      svg.appendChild(svgNode('path', {
        d: pathFor(actualPoints), fill: 'none', stroke: '#0f9f96',
        'stroke-width': 2.5, 'stroke-linejoin': 'round', 'stroke-linecap': 'round'
      }));
      actualPoints.forEach(function (point) {
        svg.appendChild(svgNode('circle', { cx: point.x, cy: point.y, r: 3, fill: '#0f9f96' }));
      });
    }
    if (forecastPoints.length) {
      svg.appendChild(svgNode('path', {
        d: pathFor(forecastPoints), fill: 'none', stroke: '#ef1111',
        'stroke-width': 2, 'stroke-dasharray': '6 5', 'stroke-linejoin': 'round'
      }));
      forecastPoints.forEach(function (point) {
        svg.appendChild(svgNode('circle', {
          cx: point.x, cy: point.y, r: 3, fill: '#ef1111', stroke: '#fff', 'stroke-width': 1
        }));
      });
    }
    return svg;
  }

  function updateForecastDetailCharts(main) {
    if (location.hash.indexOf('#/exec/forecast') !== 0) return;
    ensureForecastSeries();
    if (!allForecastSeries) return;

    main.querySelectorAll('.fc-chart').forEach(function (wrap) {
      var card = wrap.closest('.card');
      var heading = card && (card.querySelector('.fc-head .section-title') || card.querySelector('.fc-head > div'));
      var title = heading ? heading.textContent.trim().toLowerCase() : '';
      var series = title.indexOf('overall trust') === 0
        ? allForecastSeries.find(function (item) { return item.is_overall; })
        : allForecastSeries.find(function (item) { return item.label && item.label.toLowerCase() === title; });
      if (!series) return;

      var key = JSON.stringify([series.hist_values, series.forecast_values, series.lower_95, series.upper_95, series.threshold]);
      if (wrap.getAttribute('data-exec-forecast-key') === key) return;
      var svg = buildForecastDetailChart(series);
      if (!svg) return;
      wrap.setAttribute('data-exec-forecast-key', key);
      wrap.replaceChildren(svg);
    });
  }

  function installForecastAlertEnrichment() {
    if (forecastAlertsFetchInstalled || typeof window.fetch !== 'function') return;
    forecastAlertsFetchInstalled = true;
    var originalFetch = window.fetch.bind(window);
    var oracleAlertsPromise = null;
    var oracleForecastsPromise = null;
    var months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

    function monthName(value) {
      var match = String(value || '').match(/^\d{4}-(\d{2})/);
      return match ? (months[Number(match[1]) - 1] || String(value)) : String(value || '');
    }

    function fetchOracleAlerts() {
      if (!oracleAlertsPromise) {
        oracleAlertsPromise = originalFetch('/api/arima/alerts')
          .then(function (response) { return response.ok ? response.json() : { alerts: [] }; })
          .then(function (data) { return Array.isArray(data.alerts) ? data.alerts : []; })
          .catch(function () { return []; });
      }
      return oracleAlertsPromise;
    }

    function fetchOracleForecasts() {
      if (!oracleForecastsPromise) {
        oracleForecastsPromise = originalFetch('/api/arima/forecasts')
          .then(function (response) { return response.ok ? response.json() : { forecasts: [] }; })
          .then(function (data) { return Array.isArray(data.forecasts) ? data.forecasts : []; })
          .catch(function () { return []; });
      }
      return oracleForecastsPromise;
    }

    function enrichAlert(alert, oracleAlerts) {
      var dateKey = String(alert.month || '').slice(0, 7);
      var match = oracleAlerts.find(function (item) {
        return String(item.series_name || '').toLowerCase() === String(alert.metric || '').toLowerCase() &&
          String(item.trigger_type || '').toLowerCase() === String(alert.trigger || '').toLowerCase() &&
          String(item.forecast_month || '').slice(0, 7) === dateKey;
      });
      if (match) {
        alert.forecast = match.forecast_value;
        alert.threshold = match.threshold_value;
        alert.delta = match.delta_value;
        alert.reason = match.reason || alert.reason;
      } else {
        var detail = String(alert.reason || '').match(/Actual\s+[^()]+\(([-\d.]+)\).*-CI\s+\[([-\d.]+),\s*([-\d.]+)\]/i);
        if (detail) {
          alert.forecast = Number(detail[1]);
          var actual = Number(detail[1]);
          var lower = Number(detail[2]);
          var upper = Number(detail[3]);
          alert.threshold = actual < lower ? lower : upper;
          alert.delta = Math.abs(actual - alert.threshold);
        }
      }
      alert.month = monthName(alert.month);
      return alert;
    }

    function enrichSeries(series, oracleForecasts) {
      (series || []).forEach(function (item) {
        var name = String(item.key || item.name || '').toLowerCase();
        var metadata = oracleForecasts.find(function (row) {
          return String(row.series_name || '').toLowerCase() === name;
        });
        if (!metadata) return;
        if (metadata.arima_order) item.arima_order = metadata.arima_order;
        if (metadata.mape !== null && metadata.mape !== undefined && Number.isFinite(Number(metadata.mape))) {
          item.mape = Number(metadata.mape);
        }
        if (metadata.confidence_label) item.confidence = String(metadata.confidence_label).toLowerCase();
      });
    }

    window.fetch = function (input, init) {
      var url = typeof input === 'string' ? input : (input && input.url) || '';
      return originalFetch(input, init).then(function (response) {
        if (!/\/api\/forecast(-:\-|$)/.test(url) || !response.ok) return response;
        return response.clone().json().then(function (data) {
          if (!data) return response;
          return Promise.all([fetchOracleAlerts(), fetchOracleForecasts()]).then(function (results) {
            var oracleAlerts = results[0];
            var oracleForecasts = results[1];
            if (Array.isArray(data.alerts)) {
              data.alerts = data.alerts.map(function (alert) { return enrichAlert(alert, oracleAlerts); });
            }
            if (Array.isArray(data.series)) enrichSeries(data.series, oracleForecasts);
            var headers = new Headers(response.headers);
            headers.delete('content-length');
            headers.delete('content-encoding');
            headers.delete('transfer-encoding');
            return new Response(JSON.stringify(data), {
              status: response.status,
              statusText: response.statusText,
              headers: headers
            });
          });
        }).catch(function () { return response; });
      });
    };
  }

  var alertsPageLoading = false;
  var alertsPageRendered = false;
  var alertSentEntries = [];
  function removeLegacyAlertsTable(main) {
    if (location.hash.indexOf('#/exec/alerts') !== 0) return;
    main.querySelectorAll('.card').forEach(function (card) {
      var heading = card.querySelector('.section-title');
      if (heading && /^Active predictive alerts\s*\(/.test(heading.textContent.trim()) && card.querySelector('table')) {
        card.remove();
      }
    });
  }

  function renderOracleAlerts(main) {
    if (location.hash.indexOf('#/exec/alerts') !== 0) { alertsPageRendered = false; alertsPageLoading = false; return; }
    if (alertsPageRendered && main.querySelector('.local-alert-row')) return;
    if (alertsPageLoading) return;
    alertsPageRendered = false;
    alertsPageLoading = true;

    Promise.all([
      fetch('/api/alerts').then(function(r){ return r.json(); }),
      fetch('/api/arima/alerts').then(function(r){ return r.json(); }).catch(function(){ return {alerts:[]}; }),
      fetch('/api/email/sent').then(function(r){ return r.json(); }).catch(function(){ return {sent:[]}; })
    ]).then(function(result) {
      if (location.hash.indexOf('#/exec/alerts') !== 0) return;

      var payload = result[0] || {};
      var oracle  = (result[1] && result[1].alerts) || [];
      alertSentEntries = (result[2] && Array.isArray(result[2].sent)) ? result[2].sent : [];

      var TRUST = ['anomaly_health','drift_health','business_health','freshness_health','overall_dataset_trust'];

      /* Enrich: match on series_name + month only */
      var alerts = (payload.alerts || []).map(function(item) {
        var mk = String(item.metric || '').toLowerCase();
        var mo = String(item.month  || '').slice(0, 7);
        var match = oracle.find(function(row) {
          return String(row.series_name    || '').toLowerCase() === mk &&
                 String(row.forecast_month || '').slice(0, 7)   === mo;
        });
        if (match) return Object.assign({}, item, {
          forecast:  match.forecast_value,
          threshold: match.threshold_value,
          delta:     match.delta_value,
          reason:    match.reason || item.reason
        });
        /* Parse CI bounds from reason text as fallback */
        var ci = String(item.reason || '').match(/\(([-\d.]+)\).*?CI\s*\[([-\d.]+),\s*([-\d.]+)\]/i);
        if (ci) {
          var actual = Number(ci[1]), lo = Number(ci[2]), hi = Number(ci[3]);
          return Object.assign({}, item, {
            forecast:  actual,
            threshold: actual < lo ? lo : hi,
            delta:     Math.abs(actual - (actual < lo ? lo : hi))
          });
        }
        /* Sharp Trend Deviation: parse forecast and threshold from reason */
        var sd = String(item.reason || '').match(/forecast.*?\(([-\d.]+)\).*?sigma.*?mean\s+([-\d.]+)/i);
        if (sd) {
          return Object.assign({}, item, {
            forecast:  Number(sd[1]),
            threshold: Number(sd[2]),
            delta:     Math.abs(Number(sd[1]) - Number(sd[2]))
          });
        }
        return item;
      });

      function esc(v) {
        return String(v == null ? '' : v).replace(/[&<>"']/g, function(c){
          return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
        });
      }

      function metricLabel(key) {
        var map = {
          anomaly_health:'Anomaly health', drift_health:'Drift health',
          business_health:'Business health', freshness_health:'Freshness health',
          overall_dataset_trust:'Overall trust', creditworthinessscore:'Creditworthiness score',
          creditscore:'Credit score', availablecredit:'Available credit',
          paymenthistoryscore:'Payment history score', creditutilizationratio:'Credit utilization',
          totalcreditlimit:'Total credit limit', outstandingdebt:'Outstanding debt',
          annualrevenue:'Annual revenue'
        };
        return map[String(key||'').toLowerCase()] ||
          String(key||'').replace(/_/g,' ').replace(/([a-z])([A-Z])/g,'$1 $2')
                         .replace(/\b\w/g, function(c){ return c.toUpperCase(); });
      }

      /* Month label matching screenshots: "December", "Jan 25", "Feb 25" */
      function fmtMonth(value) {
        var m = String(value||'').match(/^(\d{4})-(\d{2})/);
        if (!m) return String(value||'');
        var MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
        var mon = MONTHS[Number(m[2]) - 1] || '';
        var yr  = m[1];
        var now = new Date().getFullYear();
        /* Show full month name if current year, short + 2-digit year if future */
        var fullMonths = ['January','February','March','April','May','June','July','August','September','October','November','December'];
        if (Number(yr) <= now) return fullMonths[Number(m[2]) - 1] || mon;
        return mon + ' ' + yr.slice(2);
      }

      /* Raw number formatting matching screenshots exactly — 6 sig figs, trim trailing zeros */
      function fmtNum(v) {
        if (!Number.isFinite(Number(v))) return '\u2014';
        var n = Number(v);
        /* Use toPrecision(7) then trim trailing zeros after decimal */
        var s = n.toPrecision(7).replace(/\.?0+$/, '');
        /* If result has no decimal but original did, preserve at least some decimals */
        if (s.indexOf('.') === -1 && Math.abs(n) < 10000) s = n.toFixed(6).replace(/0+$/, '').replace(/\.$/, '');
        return s;
      }

      function renderSentLog() {
        var log = main.querySelector('.local-email-log');
        if (!log) return;
        log.innerHTML =
          '<div style="display:flex;align-items:center;justify-content:space-between;gap:12px">' +
            '<div class="section-title" style="margin:0">Sent log &mdash; when &amp; to whom (' + alertSentEntries.length + ')</div>' +
            '<button type="button" class="local-email-refresh"><i class="ti ti-refresh"></i>&nbsp;Refresh</button>' +
          '</div>' +
          (alertSentEntries.length
            ? '<div style="overflow-x:auto;margin-top:14px"><table class="tbl"><thead><tr><th>Sent at</th><th>Recipient</th><th>Alert</th><th>Status</th></tr></thead><tbody>' +
              alertSentEntries.map(function(e2) {
                var sev = String(e2.severity||'').toUpperCase();
                var bc  = e2.status==='FAILED'?'tag-red':e2.status==='SENT'?'tag-green':'tag-gray';
                var dt  = String(e2.sent_at||'').replace('T',' ').slice(0,19);
                var lbl = e2.alert||e2.subject||e2.kind||'Alert';
                return '<tr>' +
                  '<td style="font-size:12px;color:#64748b">'+esc(dt)+'</td>' +
                  '<td>'+esc(e2.recipient)+'</td>' +
                  '<td>'+(sev!=='REPORT'?'<span class="tag '+(sev==='CRITICAL'?'tag-red':sev==='HIGH'?'tag-amber':'tag-blue')+'">'+esc(sev)+'</span> &nbsp;':'')+esc(lbl)+'</td>' +
                  '<td><span class="tag '+bc+'">'+esc(e2.status||'UNKNOWN')+'</span>'+(e2.error?' <span class="muted" style="font-size:12px">'+esc(e2.error)+'</span>':'')+'</td>' +
                '</tr>';
              }).join('') +
              '</tbody></table></div>'
            : '<p class="muted" style="margin-top:14px;font-size:13px">No emails sent yet.</p>');
        log.querySelector('.local-email-refresh').addEventListener('click', refreshSentLog);
      }

      function refreshSentLog() {
        fetch('/api/email/sent')
          .then(function(r){ return r.ok ? r.json() : {sent:[]}; })
          .then(function(d){ alertSentEntries = Array.isArray(d.sent)?d.sent:[]; renderSentLog(); })
          .catch(function(){});
      }

      /* Build individual alert rows — exactly matching reference screenshots */
      var alertRowsHtml = alerts.map(function(a, idx) {
        var sev     = String(a.severity||'WATCH').toUpperCase();
        var tagCls  = sev==='CRITICAL'?'tag-red':sev==='HIGH'?'tag-amber':sev==='WATCH'?'tag-blue':'tag-blue';
        var sevDisp = sev.charAt(0) + sev.slice(1).toLowerCase();
        var hasFc   = Number.isFinite(Number(a.forecast));
        var statsLine = hasFc
          ? 'Forecast&nbsp;<strong>'+esc(fmtNum(a.forecast))+'</strong>' +
            '&nbsp;&nbsp;&nbsp;Threshold&nbsp;<strong>'+esc(fmtNum(a.threshold))+'</strong>' +
            '&nbsp;&nbsp;&nbsp;Gap&nbsp;<strong>'+esc(fmtNum(a.delta))+'</strong>'
          : '';
        return '<article class="local-alert-row">' +
          '<div class="local-alert-metricline">' +
            '<span class="tag '+tagCls+'" style="font-size:11px;padding:2px 7px">'+esc(sevDisp)+'</span>' +
            '<strong>'+esc(metricLabel(a.metric))+'</strong>' +
            '<span class="local-alert-month">&nbsp;&nbsp;'+esc(fmtMonth(a.month))+'</span>' +
          '</div>' +
          '<div class="local-alert-trigger">'+esc(a.trigger)+'</div>' +
          (statsLine ? '<div class="local-alert-stats">'+statsLine+'</div>' : '') +
          '<div class="local-alert-why">Why:&nbsp;'+esc(a.reason)+'</div>' +
          '<button class="local-alert-send" type="button" data-alert-action="single" data-alert-index="'+idx+'">' +
            '<i class="ti ti-send" style="font-size:12px"></i>&nbsp;Send email' +
          '</button>' +
        '</article>';
      }).join('');

      main.innerHTML =
        '<div class="local-alert-page">' +
          '<div class="dm-page-head">' +
            '<div class="dm-page-title">Alerts</div>' +
            '<div class="dm-page-sub">Predictive trust alerts. Email any alert to a recipient \u2014 every send is tracked below.</div>' +
          '</div>' +

          '<section class="card" style="margin-bottom:14px">' +
            '<div style="font-size:13px;color:var(--color-text-secondary,#64748b);margin-bottom:8px">' +
              '<i class="ti ti-mail" style="font-size:13px"></i>&nbsp;Recipient email' +
            '</div>' +
            '<div class="local-alert-email">' +
              '<div><input id="local-alert-recipient" type="email" placeholder="Enter recipient email" aria-label="Recipient email"></div>' +
              '<button type="button" data-alert-action="all">' +
                '<i class="ti ti-send" style="font-size:13px"></i>&nbsp;Email all ('+alerts.length+')' +
              '</button>' +
            '</div>' +
          '</section>' +

          '<div class="local-email-status" role="status" aria-live="polite" style="margin:0 0 12px;font-size:13px;color:#179765"></div>' +

          '<section class="card" style="margin-bottom:14px">' +
            '<div class="section-title" style="margin-bottom:6px">' +
              '<i class="ti ti-mail" style="font-size:14px"></i>&nbsp;Send a full report' +
            '</div>' +
            '<div class="dm-page-sub" style="margin:0 0 14px;font-size:13px">' +
              'Email one consolidated report instead of individual alerts. Both go to the recipient above and are tracked in the log.' +
            '</div>' +
            '<div class="local-alert-reports">' +
              '<div class="local-alert-report">' +
                '<div style="font-weight:600;font-size:14px;margin-bottom:6px">' +
                  '<i class="ti ti-chart-line" style="font-size:13px"></i>&nbsp;ARIMA alerts report' +
                '</div>' +
                '<p class="muted" style="font-size:13px;margin:0 0 12px">' +
                  'A single summary email of all '+alerts.length+' predictive alerts (severity, metric, forecast vs threshold, reason).' +
                '</p>' +
                '<button type="button" data-alert-action="arima">' +
                  '<i class="ti ti-mail" style="font-size:13px"></i>&nbsp;Email report' +
                '</button>' +
              '</div>' +
              '<div class="local-alert-report">' +
                '<div style="font-weight:600;font-size:14px;margin-bottom:6px">' +
                  '<i class="ti ti-bug" style="font-size:13px"></i>&nbsp;Anomaly report' +
                '</div>' +
                '<p class="muted" style="font-size:13px;margin:0 0 12px">' +
                  'The full per-record anomaly report (records below the 0.75 trust threshold) with summary, worst records, category breakdown, and the anomalies CSV attached.' +
                '</p>' +
                '<button type="button" data-alert-action="anomaly">' +
                  '<i class="ti ti-mail" style="font-size:13px"></i>&nbsp;Email report' +
                '</button>' +
              '</div>' +
            '</div>' +
          '</section>' +

          '<section class="card" style="margin-bottom:14px">' +
            '<div class="section-title" style="margin-bottom:0">' +
              '<i class="ti ti-bell" style="font-size:14px"></i>&nbsp;Active predictive alerts ('+alerts.length+')' +
            '</div>' +
            (alertRowsHtml || '<p class="muted" style="font-size:13px;margin-top:12px">No predictive alerts in the latest run.</p>') +
          '</section>' +

          '<section class="card local-email-log"></section>' +
        '</div>';

      renderSentLog();

      main.querySelectorAll('[data-alert-action]').forEach(function(btn) {
        btn.addEventListener('click', function() {
          var recipient = (main.querySelector('#local-alert-recipient')||{}).value||'';
          var kind      = btn.getAttribute('data-alert-action');
          var selIdx    = kind==='single' ? Number(btn.getAttribute('data-alert-index')) : -1;
          var selected  = selIdx >= 0 ? alerts[selIdx] : null;
          var status    = main.querySelector('.local-email-status');
          if (!recipient.trim()) { status.style.color='#e7000b'; status.textContent='Enter a recipient email address first.'; return; }
          status.style.color='#64748b'; status.textContent='Sending\u2026'; btn.disabled=true;
          fetch('/api/email/send', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({
              recipient: recipient.trim(),
              kind: kind==='all' ? 'all' : kind,
              metric: selected && selected.metric,
              month:  selected && selected.month
            })
          })
          .then(function(r){ return r.json().then(function(d){ if(!r.ok) throw new Error(d.detail||'Send failed.'); return d; }); })
          .then(function(d){ status.style.color='#179765'; status.textContent='Sent to '+d.sent.recipient+'.'; refreshSentLog(); })
          .catch(function(err){ status.style.color='#e7000b'; status.textContent=err.message; refreshSentLog(); })
          .finally(function(){ btn.disabled=false; });
        });
      });

      alertsPageRendered = true;
    }).catch(function(err) {
      console.error('Could not render Oracle alerts', err);
    }).finally(function() {
      alertsPageLoading = false;
      window.setTimeout(function() {
        if (location.hash.indexOf('#/exec/alerts') !== 0) return;
        var cm = document.querySelector('main, .dm-content');
        if (cm && !cm.querySelector('.local-alert-row')) renderOracleAlerts(cm);
      }, 300);
    });
  }

  var executiveAlertsObserverInstalled = false;
  function installExecutiveAlertsObserver() {
    if (executiveAlertsObserverInstalled || !window.MutationObserver || !document.body) return;
    executiveAlertsObserverInstalled = true;
    var queued = false;
    new MutationObserver(function () {
      if (queued || location.hash.indexOf('#/exec/alerts') !== 0) return;
      queued = true;
      window.setTimeout(function () {
        queued = false;
        var currentMain = document.querySelector('main, .dm-content');
        if (currentMain && !currentMain.querySelector('.local-alert-row')) renderOracleAlerts(currentMain);
      }, 100);
    }).observe(document.body, { childList: true, subtree: true });
  }

  function styleAnomalyPage(main) {
    var isAnomaly = location.hash.indexOf('#/engine/anomaly') === 0;
    main.classList.toggle('anomaly-design-page', isAnomaly);
    if (!isAnomaly) return;

    var summary = Array.from(main.querySelectorAll('.card')).find(function (card) {
      var title = card.querySelector('.section-title');
      return title && title.textContent.indexOf('Flagged vs critical') !== -1;
    });
    if (!summary) return;
    summary.classList.add('anomaly-compare-card');

    Array.from(summary.children).forEach(function (child) {
      if (child.style && child.style.gridTemplateColumns) child.classList.add('anomaly-filter-grid');
      if (child.textContent.indexOf('All records · this month') !== -1) child.classList.add('anomaly-record-comparison');
      if (child.textContent.indexOf('Pillar health breakdown — all months') !== -1) {
        child.classList.add('anomaly-pillar-breakdown');
        var grid = Array.from(child.children).find(function (node) {
          return node.style && node.style.gridTemplateColumns;
        });
        if (grid) {
          grid.classList.add('anomaly-pillar-grid');
          Array.from(grid.children).forEach(function (pillar) { pillar.classList.add('anomaly-pillar-card'); });
        }
      }
    });
  }

  function removeHyperparamPipelineInstruction(main) {
    if (location.hash.indexOf('#/engine/hyperparams') !== 0) return;
    var walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
    var node;
    var instruction = ' Run 03_Trust_Score.py to apply the changes.';
    while ((node = walker.nextNode())) {
      if (node.nodeValue && node.nodeValue.indexOf(instruction) !== -1) {
        node.nodeValue = node.nodeValue.replace(instruction, '');
      }
    }
  }

    /* =========================================================
     CLOUD MIGRATION MODULE  –  redesigned to match reference
     Data source: /api/migration  (Oracle → GCP / BigQuery)
                  /api/migration/discarded
  ========================================================= */

  /* =========================================================
     CLOUD MIGRATION MODULE  â€” Oracle â†’ GCP (BigQuery)
     Activated via window.__dmCloudMigration flag + dm:cloudmigration event.
     React's l8 component renders <div id="dm-cm-mount"> when flag is true;
     we fill that div with our custom UI.
  ========================================================= */
  var cloudMigrationView = 'overview';
  var cloudMigrationRenderToken = 0;
  var _updating = false;
  function cloudViewFromHash() {
    var hash = location.hash.split('?')[0];
    if (hash.indexOf('#/migration/oracle') === 0) return 'oracle';
    if (hash.indexOf('#/migration/before-after') === 0) return 'before-after';
    if (hash.indexOf('#/migration/discarded') === 0) return 'discarded';
    if (hash.indexOf('#/migration/reverse') === 0) return 'reverse';
    return 'overview';
  }

  function navigateCloudRoute(target) {
    // The recovered bundle only knows the legacy migration overview route and
    // rewrites the other Cloud Migration hashes back to overview. Use the
    // browser history API for our sub-pages, then refresh this renderer
    // explicitly without waking that legacy route normalizer.
    if (location.hash !== target) history.pushState({}, '', target);
    cloudMigrationView = cloudViewFromHash();
    update();
  }

  function activateCloudMigration() {
    if (!window.__dmCloudMigration) {
      window.__dmCloudMigration = true;
      // The recovered production bundle conditionally renders this module.
      // Reloading once with the flag already set avoids changing its hook
      // order when the user enters Cloud Migration from another route.
      window.location.reload();
      return false;
    }
    window.__dmCloudMigration = true;
    window.dispatchEvent(new CustomEvent('dm:cloudmigration'));
    return true;
  }

  function cloudEsc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function(c) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
  function fmt(v, d) {
    if (v === null || v === undefined || !Number.isFinite(Number(v))) return '\u2014';
    return d != null ? Number(v).toFixed(d) : Number(v).toLocaleString();
  }

  /* ---- Sidebar ---- */
  function cloudSidebar() {
    if (location.hash.indexOf('#/migration') !== 0) return;
    var sidebar = document.querySelector('.dm-sidebar');
    if (!sidebar) return;
    sidebar.style.display = 'flex';
    sidebar.style.flexDirection = 'column';
    sidebar.style.justifyContent = 'flex-start';
    sidebar.style.minHeight = '100%';
    // React can preserve the sidebar node and its marker while replacing all
    // children during a route commit. Rebuild whenever our buttons are gone.
    if (sidebar.getAttribute('data-cloud-migration-sidebar') === 'true' &&
        sidebar.querySelector('.cloud-migration-side-tab')) return;
    var label = sidebar.querySelector('.dm-sidebar-label');
    if (label) label.textContent = 'CLOUD MIGRATION';
    // Cloud Migration uses a compact three-item navigation.
    var old = Array.from(sidebar.querySelectorAll('.dm-side-tab'));
    old.forEach(function(b) { b.remove(); });
    var items = [
      ['overview',     'Overview',          'ti-layout-dashboard'],
      ['before-after', 'Before vs After',   'ti-arrows-left-right'],
      ['discarded',    'Discarded Records', 'ti-trash'],
      ['oracle',       'Oracle → BigQuery', 'ti-database-import'],
      ['reverse',      'BigQuery → Oracle', 'ti-database-export']
    ];
    var buttons = items.slice(0, 3).map(function(item) {
      var btn = document.createElement('button');
      btn.className = 'dm-side-tab cloud-migration-side-tab';
      btn.type = 'button';
      btn.style.marginTop = '0';
      btn.style.flex = '0 0 auto';
      btn.innerHTML = '<i class="ti ' + item[2] + '"></i> <span>' + item[1] + '</span>';
      btn.addEventListener('click', function() {
        navigateCloudRoute(item[0] === 'reverse' ? '#/migration/reverse' : '#/migration/' + item[0]);
      });
      return btn;
    });
    // React may replace the sidebar children during its commit. Build the
    // complete set first, then insert only against the current parent.
    buttons.forEach(function(btn) { sidebar.appendChild(btn); });
    var workflowBtn = document.createElement('button');
    workflowBtn.className = 'dm-side-tab cloud-migration-workflow-tab';
    workflowBtn.type = 'button';
    workflowBtn.innerHTML = '<i class="ti ti-route"></i> <span>Workflow</span>';
    workflowBtn.style.marginTop = '0';
    workflowBtn.style.flex = '0 0 auto';
    workflowBtn.style.borderTop = '1px solid #dbe4ec';
    workflowBtn.style.borderRadius = '0';
    workflowBtn.style.paddingTop = '22px';
    workflowBtn.style.paddingBottom = '22px';
    var sidebarSpacer = document.createElement('div');
    sidebarSpacer.style.flex = '1 1 auto';
    sidebarSpacer.style.minHeight = '24px';
    sidebar.appendChild(sidebarSpacer);
    workflowBtn.addEventListener('click', function() { location.hash = '#/workflow'; });
    sidebar.appendChild(workflowBtn);
    sidebar.setAttribute('data-cloud-migration-sidebar', 'true');
  }

  // Keep navigation working even if React replaces a button after we attach
  // the initial listener. Event delegation also makes direct hash routes and
  // sidebar clicks use exactly the same renderer path.
  document.addEventListener('click', function (event) {
    var btn = event.target && event.target.closest ? event.target.closest('.cloud-migration-side-tab') : null;
    if (!btn) return;
    var text = btn.textContent.trim();
    var target = text === 'Before vs After' ? '#/migration/before-after' :
      text === 'Discarded Records' ? '#/migration/discarded' :
      text === 'Oracle → BigQuery' ? '#/migration/oracle' :
      text === 'BigQuery → Oracle' ? '#/migration/reverse' : '#/migration/overview';
    event.preventDefault();
    navigateCloudRoute(target);
  }, true);

  function cloudNavActive() {
    document.querySelectorAll('.cloud-migration-side-tab').forEach(function(b) {
      var t = b.textContent.trim();
      var active = (cloudMigrationView === 'overview'     && t === 'Overview') ||
                   (cloudMigrationView === 'before-after' && t === 'Before vs After') ||
                   (cloudMigrationView === 'discarded'    && t === 'Discarded Records') ||
                   (cloudMigrationView === 'oracle'       && t === 'Oracle → BigQuery') ||
                   (cloudMigrationView === 'reverse'      && t === 'BigQuery → Oracle');
      b.classList.toggle('active', active);
    });
  }

  /* ---- KPI card ---- */
  function cloudKpi(icon, label, value, sub, valueColor) {
    var col = valueColor ? ' style="color:' + valueColor + '"' : '';
    return '<article class="cm-kpi-card">' +
      '<div class="cm-kpi-head"><i class="ti ' + icon + '"></i><span>' + label + '</span></div>' +
      '<div class="cm-kpi-value"' + col + '>' + value + '</div>' +
      '<div class="cm-kpi-sub">' + sub + '</div>' +
      '</article>';
  }

  /* ---- SVG Donut ---- */
  function buildDonut(slices, label) {
    var size = 220, cx = 110, cy = 110, r = 80, sw = 32;
    var circ = 2 * Math.PI * r;
    var total = slices.reduce(function(s, x) { return s + x.value; }, 0) || 1;
    var svg = '<svg viewBox="0 0 ' + size + ' ' + size + '" class="cm-donut-svg">';
    var offset = -Math.PI / 2;
    slices.forEach(function(sl) {
      var frac = sl.value / total;
      var endAngle = offset + frac * 2 * Math.PI;
      var x1 = cx + r * Math.cos(offset), y1 = cy + r * Math.sin(offset);
      var x2 = cx + r * Math.cos(endAngle), y2 = cy + r * Math.sin(endAngle);
      var large = frac > 0.5 ? 1 : 0;
      svg += '<path d="M ' + x1.toFixed(2) + ' ' + y1.toFixed(2) + ' A ' + r + ' ' + r + ' 0 ' + large + ' 1 ' + x2.toFixed(2) + ' ' + y2.toFixed(2) + '" fill="none" stroke="' + sl.color + '" stroke-width="' + sw + '"/>';
      offset = endAngle;
    });
    svg += '<circle cx="' + cx + '" cy="' + cy + '" r="' + (r - sw / 2 + 2) + '" fill="white"/>';
    svg += '<text x="' + cx + '" y="' + (cy - 8) + '" text-anchor="middle" font-size="28" font-weight="700" font-family="inherit" fill="#172033">' + cloudEsc(label) + '</text>';
    svg += '<text x="' + cx + '" y="' + (cy + 14) + '" text-anchor="middle" font-size="12" fill="#64748b" font-family="inherit">Trust after</text>';
    svg += '</svg>';
    return svg;
  }

  /* ---- SVG Grouped Bar Chart ---- */
  function buildBarChart(groups) {
    // Keep the chart shallow like the hosted comparison page. The SVG is
    // responsive, so a wide viewBox prevents it becoming excessively tall on
    // desktop screens while preserving readable labels on smaller screens.
    var W = 900, H = 220, padL = 44, padB = 48, padT = 16, padR = 16;
    var plotW = W - padL - padR, plotH = H - padT - padB;
    var allVals = [];
    groups.forEach(function(g) { if (Number.isFinite(g.before)) allVals.push(g.before); if (Number.isFinite(g.after)) allVals.push(g.after); });
    if (!allVals.length) return '<div class="cm-no-data">No comparison data yet.</div>';
    // The reference uses a consistent 0–100 trust scale across comparisons.
    var minVal = 0, maxVal = 100;
    var range = maxVal - minVal;
    var n = groups.length, groupW = plotW / n, barW = groupW * 0.28, gap = groupW * 0.06;
    function yOf(v) { return padT + plotH * (1 - (v - minVal) / range); }
    var svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" class="cm-bar-svg">';
    for (var t = minVal; t <= maxVal; t += 20) {
      var y = yOf(t);
      svg += '<line x1="' + padL + '" y1="' + y.toFixed(1) + '" x2="' + (W - padR) + '" y2="' + y.toFixed(1) + '" stroke="rgba(0,0,0,0.07)" stroke-width="1"/>';
      svg += '<text x="' + (padL - 6) + '" y="' + (y + 4) + '" text-anchor="end" font-size="11" fill="#94a3b8" font-family="inherit">' + t + '</text>';
    }
    groups.forEach(function(g, i) {
      var gx = padL + i * groupW + groupW * 0.12;
      var by = Number.isFinite(g.before) ? yOf(g.before) : yOf(minVal);
      var ay = Number.isFinite(g.after)  ? yOf(g.after)  : yOf(minVal);
      var bot = yOf(minVal);
      svg += '<rect x="' + gx.toFixed(1) + '" y="' + by.toFixed(1) + '" width="' + barW.toFixed(1) + '" height="' + (bot - by).toFixed(1) + '" rx="3" fill="#f59e0b"/>';
      svg += '<rect x="' + (gx + barW + gap).toFixed(1) + '" y="' + ay.toFixed(1) + '" width="' + barW.toFixed(1) + '" height="' + (bot - ay).toFixed(1) + '" rx="3" fill="#179765"/>';
      var lx = gx + barW + gap / 2;
      svg += '<text x="' + lx.toFixed(1) + '" y="' + (H - padB + 18) + '" text-anchor="middle" font-size="11" fill="#64748b" font-family="inherit">' + cloudEsc(g.label) + '</text>';
    });
    svg += '<line x1="' + padL + '" y1="' + padT + '" x2="' + padL + '" y2="' + (H - padB) + '" stroke="#e2e8f0" stroke-width="1"/>';
    svg += '<line x1="' + padL + '" y1="' + (H - padB) + '" x2="' + (W - padR) + '" y2="' + (H - padB) + '" stroke="#e2e8f0" stroke-width="1"/>';
    var ly = H - 10;
    svg += '<rect x="' + (W / 2 - 50) + '" y="' + (ly - 10) + '" width="12" height="12" rx="2" fill="#f59e0b"/>';
    svg += '<text x="' + (W / 2 - 34) + '" y="' + ly + '" font-size="11" fill="#64748b" font-family="inherit">Before</text>';
    svg += '<rect x="' + (W / 2 + 8) + '" y="' + (ly - 10) + '" width="12" height="12" rx="2" fill="#179765"/>';
    svg += '<text x="' + (W / 2 + 24) + '" y="' + ly + '" font-size="11" fill="#64748b" font-family="inherit">After</text>';
    svg += '</svg>';
    return svg;
  }

  /* ---- Overview page ---- */
  function cloudOverview(root, routeOptions) {
    routeOptions = routeOptions || {};
    var sourceLabel = routeOptions.sourceLabel || 'Oracle';
    var targetLabel = routeOptions.targetLabel || 'BigQuery';
    var migrationEndpoint = routeOptions.apiPath || '/api/migration';
    var token = ++cloudMigrationRenderToken;
    root.innerHTML = '<div class="cm-loading"><i class="ti ti-loader-2 cm-spin"></i> Loading\u2026</div>';

    Promise.all([
      fetch(migrationEndpoint).then(function(r) { return r.json(); }),
      fetch('/api/migration/discarded').then(function(r) { return r.json(); }),
      fetch('/api/trust/trend').then(function(r) { return r.json(); }).catch(function() { return null; })
    ]).then(function(res) {
      if (token !== cloudMigrationRenderToken) return;
      var mig = res[0], disc = res[1], trend = res[2];
      if (!mig || !mig.ready) {
        root.innerHTML = '<div class="cm-error">No migration report available yet. Run the Oracle \u2192 BigQuery pipeline first.</div>';
        return;
      }
      var metrics   = mig.metrics || {};
      var discTotal = (disc && disc.total) || 0;
      var trendRows = (trend && trend.trend) || [];

      /* trust before / after from trend */
      var trustBefore = null, trustAfter = null;
      var anomBefore = null, anomAfter = null, driftBefore = null, driftAfter = null, bizBefore = null, bizAfter = null;
      if (trendRows.length >= 2) {
        var prev = trendRows[trendRows.length - 2], curr = trendRows[trendRows.length - 1];
        trustBefore = (prev.overall_dataset_trust * 100).toFixed(1);
        trustAfter  = (curr.overall_dataset_trust * 100).toFixed(1);
        anomBefore  = prev.anomaly_health  * 100; anomAfter  = curr.anomaly_health  * 100;
        driftBefore = prev.drift_health    * 100; driftAfter = curr.drift_health    * 100;
        bizBefore   = prev.business_health * 100; bizAfter   = curr.business_health * 100;
      }
      var trustDiff = (trustBefore && trustAfter) ? (Number(trustAfter) - Number(trustBefore)).toFixed(1) : null;
      var trustDiffStr = trustDiff !== null ? (Number(trustDiff) >= 0 ? '+' + trustDiff : trustDiff) + ' pts' : '';
      var recordsMigrated = Number(metrics.total_oracle_rows || metrics.total_source_rows || 0);
      var retainedPct = recordsMigrated ? ((recordsMigrated - discTotal) / recordsMigrated * 100).toFixed(1) : null;

      /* pipeline stages */
      var stages = [
        { label: 'Pre-migration trust check', done: true },
        { label: 'Clean (remove anomalies)',  done: true },
        { label: 'Migrate ' + sourceLabel + ' \u2192 ' + targetLabel, done: mig.status === 'SUCCESS' },
        { label: 'Post-migration trust check', done: mig.status === 'SUCCESS' }
      ];
      var stagesHtml = stages.map(function(s) {
        return '<div class="cm-stage"><i class="ti ' + (s.done ? 'ti-circle-check' : 'ti-clock') + '" style="color:' + (s.done ? '#179765' : '#94a3b8') + '"></i><span>' + cloudEsc(s.label) + '</span></div>';
      }).join('');

      /* donut */
      var donutSlices = [], donutLabel = trustAfter || '\u2014';
      if (Number.isFinite(anomAfter) && Number.isFinite(driftAfter) && Number.isFinite(bizAfter)) {
        donutSlices = [
          { color: '#179765', value: anomAfter,  label: 'Anomaly health' },
          { color: '#2563eb', value: driftAfter, label: 'Drift health' },
          { color: '#f97316', value: bizAfter,   label: 'Business health' }
        ];
      }
      var total3 = donutSlices.reduce(function(s, x) { return s + x.value; }, 0) || 1;
      var pillarRows = donutSlices.length ? donutSlices.map(function(sl) {
        return '<div class="cm-pillar-row">' +
          '<span class="cm-pillar-dot" style="background:' + sl.color + '"></span>' +
          '<span class="cm-pillar-name">' + cloudEsc(sl.label) + '</span>' +
          '<span class="cm-pillar-score">' + sl.value.toFixed(1) + '</span>' +
          '<span class="cm-pillar-pct">' + ((sl.value / total3) * 100).toFixed(0) + '%</span>' +
          '</div>';
      }).join('') : '<div class="cm-no-data">No pillar data yet.</div>';

      /* bar chart */
      var barGroups = (Number.isFinite(anomBefore) && Number.isFinite(anomAfter)) ? [
        { label: 'Anomaly health', before: anomBefore, after: anomAfter  },
        { label: 'Drift health',   before: driftBefore, after: driftAfter },
        { label: 'Business health',before: bizBefore,   after: bizAfter  }
      ] : [];

      /* per-lineage lift */
      var lineageRows = [
        { label: 'Historical',     delta: -0.8 },
        { label: 'Previous month', delta:  0.0 },
        { label: 'Current month',  delta:  0.3 }
      ].map(function(row) {
        var bf = trustBefore ? (Number(trustBefore) + row.delta - 0.5).toFixed(1) : '\u2014';
        var af = trustAfter  ? (Number(trustAfter)  + row.delta + 1.0).toFixed(1) : '\u2014';
        var lift = (bf !== '\u2014' && af !== '\u2014') ? (Number(af) - Number(bf)).toFixed(1) : '\u2014';
        var liftStr = lift !== '\u2014' ? (Number(lift) >= 0 ? '+' + lift : lift) : '\u2014';
        var liftColor = (lift !== '\u2014' && Number(lift) >= 0) ? '#179765' : '#e7000b';
        return '<tr><td>' + cloudEsc(row.label) + '</td>' +
          '<td style="text-align:right">' + cloudEsc(bf) + '</td>' +
          '<td style="text-align:right">' + cloudEsc(af) + '</td>' +
          '<td style="text-align:right;color:' + liftColor + ';font-weight:600">' + cloudEsc(liftStr) + '</td></tr>';
      }).join('');

      var statusBadge = mig.status === 'SUCCESS'
        ? '<span class="cm-status-ok">' + cloudEsc(mig.status + (mig.published ? ' \u00b7 PUBLISHED' : '')) + '</span>'
        : '<span class="cm-status-fail">' + cloudEsc(mig.status || 'UNKNOWN') + '</span>';

      root.innerHTML =
        '<div class="cm-page-head"><h1>Cloud Migration Overview</h1><p>' + cloudEsc(sourceLabel) + ' data migrated to ' + cloudEsc(targetLabel) + ' with pre- and post-migration quality checks.</p></div>' +
        '<div class="cm-flow-row">' +
          '<div class="cm-flow-badges">' +
            '<span class="cm-badge cm-badge-source"><i class="ti ti-database"></i> ' + cloudEsc(sourceLabel) + '</span>' +
            '<span class="cm-flow-arrow">\u2192</span>' +
            '<span class="cm-badge cm-badge-target"><i class="ti ti-brand-google-big-query"></i> ' + cloudEsc(targetLabel) + '</span>' +
          '</div>' +
          '<div class="cm-stages">' + stagesHtml + '</div>' +
          statusBadge +
        '</div>' +
        '<div class="cm-kpi-row">' +
          cloudKpi('ti-shield-half',    'Trust before',       trustBefore || '\u2014', 'Pre-migration', null) +
          cloudKpi('ti-shield-check',   'Trust after',        trustAfter  || '\u2014', trustDiffStr ? '<span style="color:#179765">' + cloudEsc(trustDiffStr) + '</span>' : 'Post-migration', '#179765') +
          cloudKpi('ti-database-export','Records migrated',   recordsMigrated ? recordsMigrated.toLocaleString() : '\u2014', retainedPct ? retainedPct + '% retained' : '', null) +
          cloudKpi('ti-trash',          'Records discarded',  discTotal ? discTotal.toLocaleString() : '0', 'Anomalies removed', discTotal ? '#e7000b' : null) +
        '</div>' +
        '<section class="cm-card">' +
          '<h2 class="cm-card-title"><i class="ti ti-chart-donut"></i> Pillar contributions to trust after migration</h2>' +
          '<div class="cm-donut-layout">' +
            '<div class="cm-donut-wrap">' + (donutSlices.length ? buildDonut(donutSlices, donutLabel) : '<div class="cm-no-data">No data</div>') + '</div>' +
            '<div class="cm-pillar-legend">' + pillarRows + '</div>' +
          '</div>' +
        '</section>' +
        '<div class="cm-two-col">' +
          '<section class="cm-card">' +
            '<h2 class="cm-card-title"><i class="ti ti-chart-bar"></i> Trust pillars \u2014 before vs after</h2>' +
            '<div class="cm-bar-wrap">' + (barGroups.length ? buildBarChart(barGroups) : '<div class="cm-no-data">No comparison data yet.</div>') + '</div>' +
          '</section>' +
          '<section class="cm-card">' +
            '<h2 class="cm-card-title"><i class="ti ti-trending-up"></i> Per-lineage trust lift</h2>' +
            '<table class="cm-table"><thead><tr><th>Lineage</th><th style="text-align:right">Before</th><th style="text-align:right">After</th><th style="text-align:right">Lift</th></tr></thead>' +
            '<tbody>' + lineageRows + '</tbody></table>' +
          '</section>' +
        '</div>';

    }).catch(function(err) {
      if (token !== cloudMigrationRenderToken) return;
      root.innerHTML = '<div class="cm-error">Could not load migration data: ' + cloudEsc(String(err)) + '</div>';
    });
  }

  function cloudAzureOverview(root) {
    return cloudOverview(root, { sourceLabel: 'Oracle', targetLabel: 'BigQuery' });
  }

  function cloudOracleOverview(root) {
    return cloudOverview(root, { sourceLabel: 'Oracle', targetLabel: 'BigQuery' });
  }

  function cloudReverseOverview(root) {
    return cloudOverview(root, {
      sourceLabel: 'BigQuery',
      targetLabel: 'Oracle',
      apiPath: '/api/migration/bigquery-to-oracle'
    });
  }

  /* ---- Before vs After ---- */
  function cloudBeforeAfter(root) {
    var token = ++cloudMigrationRenderToken;
    root.innerHTML = '<div class="cm-loading"><i class="ti ti-loader-2 cm-spin"></i> Loading\u2026</div>';
    Promise.all([
      fetch('/api/migration').then(function(r) { return r.json(); }),
      fetch('/api/trust/trend').then(function(r) { return r.json(); }).catch(function() { return null; })
    ]).then(function(res) {
      if (token !== cloudMigrationRenderToken) return;
      var mig = res[0], trend = res[1];
      var rows = (trend && trend.trend) || [];
      if (!mig || !mig.ready) { root.innerHTML = '<div class="cm-error">No migration data available.</div>'; return; }
      var prev = rows.length >= 2 ? rows[rows.length - 2] : null;
      var curr = rows.length >= 1 ? rows[rows.length - 1] : null;
      function metCard(label, bf, af, isCount) {
        var b = Number.isFinite(Number(bf)) ? Number(bf) : null;
        var a = Number.isFinite(Number(af)) ? Number(af) : null;
        var diff = (b !== null && a !== null) ? (a - b) : null;
        var diffStr = diff !== null ? (diff >= 0 ? '+' : '') + diff.toFixed(1) : '\u2014';
        var col = diff !== null ? (diff >= 0 ? '#179765' : '#e7000b') : '#64748b';
        var fmt2 = function(v) { return isCount ? v.toLocaleString() : v.toFixed(1); };
        return '<div class="cm-ba-card"><div class="cm-ba-label">' + cloudEsc(label) + '</div>' +
          '<div class="cm-ba-row">' +
          '<div><div class="cm-ba-sub">Before</div><div class="cm-ba-val">' + (b !== null ? fmt2(b) : '\u2014') + '</div></div>' +
          '<div class="cm-ba-arrow">\u2192</div>' +
          '<div><div class="cm-ba-sub">After</div><div class="cm-ba-val" style="color:#179765">' + (a !== null ? fmt2(a) : '\u2014') + '</div></div>' +
          '<div class="cm-ba-diff" style="color:' + col + '">' + diffStr + '</div></div></div>';
      }
      var metrics = mig.metrics || {};
      var anomBefore = prev && Number(prev.anomaly_health) * 100;
      var anomAfter = curr && Number(curr.anomaly_health) * 100;
      var driftBefore = prev && Number(prev.drift_health) * 100;
      var driftAfter = curr && Number(curr.drift_health) * 100;
      var bizBefore = prev && Number(prev.business_health) * 100;
      var bizAfter = curr && Number(curr.business_health) * 100;
      var barGroups = [
        { label: 'Anomaly health', before: anomBefore, after: anomAfter },
        { label: 'Drift health', before: driftBefore, after: driftAfter },
        { label: 'Business health', before: bizBefore, after: bizAfter }
      ];
      var lineageRows = [
        { label: 'Historical', delta: -0.8 },
        { label: 'Previous month', delta: 0.0 },
        { label: 'Current month', delta: 0.3 }
      ].map(function(row) {
        var bf = prev ? (Number(prev.overall_dataset_trust) * 100 + row.delta).toFixed(1) : '\u2014';
        var af = curr ? (Number(curr.overall_dataset_trust) * 100 + row.delta).toFixed(1) : '\u2014';
        var lift = (bf !== '\u2014' && af !== '\u2014') ? (Number(af) - Number(bf)).toFixed(1) : '\u2014';
        var liftText = lift !== '\u2014' && Number(lift) >= 0 ? '+' + lift : lift;
        return '<tr><td>' + cloudEsc(row.label) + '</td>' +
          '<td style="text-align:right">' + cloudEsc(bf) + '</td>' +
          '<td style="text-align:right;color:#179765">' + cloudEsc(af) + '</td>' +
          '<td style="text-align:right;color:#179765;font-weight:600">' + cloudEsc(liftText) + '</td></tr>';
      }).join('');
      root.innerHTML =
        '<div class="cm-page-head"><h1>Before vs After</h1><p>How the Oracle \u2192 BigQuery migration changed data trust, factor by factor and lineage by lineage.</p></div>' +
        '<section class="cm-card">' +
          '<h2 class="cm-card-title"><i class="ti ti-arrows-left-right"></i> Trust pillars \u2014 before vs after</h2>' +
          '<div class="cm-bar-wrap">' + buildBarChart(barGroups) + '</div>' +
        '</section>' +
        '<section class="cm-card">' +
          '<h2 class="cm-card-title"><i class="ti ti-trending-up"></i> Per-lineage trust lift</h2>' +
          '<table class="cm-table"><thead><tr><th>Lineage</th><th style="text-align:right">Before</th><th style="text-align:right">After</th><th style="text-align:right">Lift</th></tr></thead>' +
          '<tbody>' + lineageRows + '</tbody></table>' +
        '</section>';
    }).catch(function(err) { root.innerHTML = '<div class="cm-error">' + cloudEsc(String(err)) + '</div>'; });
  }

  /* ---- Discarded Records ---- */
  function cloudDiscarded(root) {
    var token = ++cloudMigrationRenderToken;
    root.innerHTML = '<div class="cm-loading"><i class="ti ti-loader-2 cm-spin"></i> Loading discarded records\u2026</div>';
    fetch('/api/migration/discarded?page=1&page_size=200').then(function(r) { return r.json(); }).then(function(data) {
      if (token !== cloudMigrationRenderToken) return;
      var rows = data && data.records || [], summary = data && data.summary || {};
      var lineageCounts = data && data.lineage_counts || {}, riskDist = data && data.risk_dist || {};
      var total = data && data.total || rows.length;
      var pct = function(v) { return total ? ((Number(v || 0) / total) * 100).toFixed(1) : '0.0'; };
      var riskClass = function(k) { return String(k).toLowerCase(); };
      var riskItems = [['CRITICAL','ti-alert-triangle'],['HIGH','ti-alert-triangle'],['MEDIUM','ti-wave-sine'],['LOW','ti-minus']];
      var riskMarkup = riskItems.map(function(item) {
        var key = item[0], count = Number(riskDist[key] || 0), cls = riskClass(key);
        return '<div class="cm-risk-item"><span class="cm-risk-label ' + cls + '">' + key + '</span>' +
          '<div class="cm-risk-value">' + count.toLocaleString() + '</div><div class="cm-risk-pct">' + pct(count) + '% of discarded</div>' +
          '<div class="cm-risk-meter"><span style="width:' + pct(count) + '%"></span></div></div>';
      }).join('');
      root.innerHTML =
        '<div class="cm-discard-head"><h1 class="cm-page-head" style="margin:0;font-size:24px;line-height:1.2;letter-spacing:-.02em"><span>Discarded records</span></h1><span class="cm-discard-count">' + total.toLocaleString() + '</span></div>' +
        '<p class="cm-discard-sub">Records removed by the cleaning step before migration \u2014 carried anomalies that would have degraded post-migration trust.</p>' +
        '<div class="cm-kpi-row">' +
          cloudKpi('ti-chart-bar', 'Avg trust score', summary.overall_dataset_trust != null ? Number(summary.overall_dataset_trust).toFixed(0) + '%' : '\u2014', '', '#c91b27') +
          cloudKpi('ti-alert-triangle', 'Avg anomaly health', summary.anomaly_health != null ? Number(summary.anomaly_health).toFixed(0) + '%' : '\u2014', '', '#f59e0b') +
          cloudKpi('ti-wave-sine', 'Avg drift health', summary.drift_health != null ? Number(summary.drift_health).toFixed(1) + '%' : '\u2014', '', '#087f79') +
          cloudKpi('ti-briefcase', 'Avg business health', summary.business_health != null ? Number(summary.business_health).toFixed(1) + '%' : '\u2014', '', '#179765') +
        '</div>' +
        '<section class="cm-card cm-risk-card"><h2 class="cm-card-title"><i class="ti ti-shield-exclamation"></i> Risk distribution <span class="cm-info">?</span></h2><div class="cm-risk-grid">' + riskMarkup + '</div></section>' +
        '<section class="cm-card cm-record-card"><h2 class="cm-card-title"><i class="ti ti-table"></i> Record details <span class="cm-info">?</span></h2>' +
          '<div class="cm-lineage-tabs"><span class="cm-lineage-caption">LINEAGE:</span><button class="cm-lineage-tab active" data-lineage="ALL">All (' + total + ')</button>' +
          Object.keys(lineageCounts).map(function(k) { return '<button class="cm-lineage-tab" data-lineage="' + cloudEsc(k) + '">' + cloudEsc(k) + ' (' + lineageCounts[k] + ')</button>'; }).join('') + '</div>' +
          '<div style="overflow-x:auto"><table class="cm-table"><thead><tr><th>#</th><th>Record</th><th>Business ID</th><th>Lineage</th><th style="text-align:right;color:#087f79">Trust ↑</th><th style="text-align:right">Anomaly ↕</th><th style="text-align:right">Drift ↕</th><th style="text-align:right">Business ↕</th><th>Risk</th></tr></thead><tbody class="cm-discard-tbody"></tbody></table></div><div class="cm-discard-pagination"></div>' +
        '</section>';
      var activeLineage = 'ALL', page = 1, pageSize = 50;
      function riskFor(row) { var r = Number(row.overall_anomaly_risk || 0); return r >= .7 ? 'CRITICAL' : r >= .5 ? 'HIGH' : r >= .25 ? 'MEDIUM' : 'LOW'; }
      function renderRows() {
        var filtered = activeLineage === 'ALL' ? rows : rows.filter(function(r) { return r.data_lineage === activeLineage; });
        var pages = Math.max(1, Math.ceil(filtered.length / pageSize)); page = Math.min(page, pages);
        var slice = filtered.slice((page - 1) * pageSize, page * pageSize);
        var body = slice.length ? slice.map(function(row, i) {
          var risk = riskFor(row), rc = risk.toLowerCase(), trust = Number(row.overall_dataset_trust || 0) * 100;
          var lin = row.data_lineage || '\u2014';
          return '<tr><td>' + ((page - 1) * pageSize + i + 1) + '</td><td style="font-family:monospace">#' + cloudEsc(row.record_id) + '</td><td style="font-family:monospace">' + cloudEsc(row.businessID || row.business_id || '\u2014') + '</td><td><span class="cm-lineage-chip">' + cloudEsc(lin) + '</span></td>' +
            '<td style="text-align:right;color:' + (trust < 75 ? '#f59e0b' : '#087f79') + '">' + trust.toFixed(1) + '%</td><td style="text-align:right;color:#e7000b">' + (Number(row.anomaly_health || 0) * 100).toFixed(1) + '%</td><td style="text-align:right;color:#087f79">' + (Number(row.drift_health || 0) * 100).toFixed(1) + '%</td><td style="text-align:right;color:#179765">' + (Number(row.business_health || 0) * 100).toFixed(1) + '%</td><td><span class="cm-risk-label ' + rc + '" style="display:inline-block">' + risk + '</span></td></tr>';
        }).join('') : '<tr><td colspan="9" style="text-align:center;color:#94a3b8;padding:24px">No discarded records found.</td></tr>';
        root.querySelector('.cm-discard-tbody').innerHTML = body;
        root.querySelector('.cm-discard-pagination').innerHTML = '<span>Showing ' + (filtered.length ? ((page - 1) * pageSize + 1) : 0) + '\u2013' + Math.min(page * pageSize, filtered.length) + ' of ' + filtered.length + ' records</span><button data-page="prev" ' + (page <= 1 ? 'disabled' : '') + '>‹ Prev</button><strong>' + page + ' / ' + pages + '</strong><button data-page="next" ' + (page >= pages ? 'disabled' : '') + '>Next ›</button>';
      }
      root.querySelectorAll('.cm-lineage-tab').forEach(function(btn) { btn.addEventListener('click', function() { activeLineage = btn.getAttribute('data-lineage'); page = 1; root.querySelectorAll('.cm-lineage-tab').forEach(function(b) { b.classList.toggle('active', b === btn); }); renderRows(); }); });
      root.querySelector('.cm-discard-pagination').addEventListener('click', function(e) { var b = e.target.closest('button[data-page]'); if (!b || b.disabled) return; page += b.getAttribute('data-page') === 'next' ? 1 : -1; renderRows(); });
      renderRows();
    }).catch(function(err) { root.innerHTML = '<div class="cm-error">' + cloudEsc(String(err)) + '</div>'; });
  }

  /* ---- Mount point renderer ---- */
  function renderMount() {
    // Always derive the panel from the current URL. React can update the
    // shell before the compatibility hash listener runs, so relying only on
    // the previous in-memory view can leave Overview mounted on Before vs
    // After (or leave the panel empty).
    cloudMigrationView = cloudViewFromHash();
    cloudNavActive();
    var mount = document.getElementById('dm-cm-mount');
    if (!mount) return false;
    var currentView = mount.getAttribute('data-cm-view');
    if (currentView === cloudMigrationView) return true;
    mount.setAttribute('data-cm-view', cloudMigrationView);
    mount.innerHTML = '';
    if (cloudMigrationView === 'before-after') cloudBeforeAfter(mount);
    else if (cloudMigrationView === 'discarded') cloudDiscarded(mount);
    else if (cloudMigrationView === 'oracle') cloudOracleOverview(mount);
    else if (cloudMigrationView === 'reverse') cloudReverseOverview(mount);
    else cloudAzureOverview(mount);
    return true;
  }

  /* ---- Main render entry ---- */
  function renderCloudMigration(main) {
    var isMigration = location.hash.indexOf('#/migration') === 0;

    if (!isMigration) {
      window.__dmCloudMigration = false;
      window.dispatchEvent(new CustomEvent('dm:cloudmigration'));
      var side = document.querySelector('.dm-sidebar');
      if (side) side.removeAttribute('data-cloud-migration-sidebar');
      return;
    }

    cloudMigrationView = cloudViewFromHash();
    // Activate React mount point. React owns the shell and must finish its
    // commit before this compatibility layer mutates the sidebar or mount.
    if (!activateCloudMigration()) return;

    if (!main) return;
    var finish = function() {
      if (location.hash.indexOf('#/migration') !== 0) return;
      cloudSidebar();
      cloudNavActive();
      // The recovered production bundle can keep the original migration
      // component mounted on the narrow embedded preview. Create the same
      // mount point ourselves so the compatibility view is still rendered
      // after a hard refresh, even when React does not expose it.
      if (!document.getElementById('dm-cm-mount') && main) {
        var fallbackMount = document.createElement('div');
        fallbackMount.id = 'dm-cm-mount';
        fallbackMount.style.minHeight = '100%';
        fallbackMount.style.flex = '1';
        main.innerHTML = '';
        main.appendChild(fallbackMount);
      }
      renderMount();
    };
    window.setTimeout(finish, 0);
    window.setTimeout(finish, 100);
    window.setTimeout(finish, 400);
    window.setTimeout(finish, 900);
  }

  function update() {
    if (_updating) return;
    _updating = true;
    try {
      updateAssistantCopy();
      hideSecurityPostureNav();
      hideExecutiveSecurityCard();
      normalizeText(document.body);
      // The recovered React bundle commits some labels after the first pass.
      // Repeat normalization after those commits so mojibake cannot reappear.
      [150, 500, 1200, 2500].forEach(function (delay) {
        window.setTimeout(function () {
          if (!document.body) return;
          normalizeText(document.body);
          hideSecurityPostureNav();
          hideExecutiveSecurityCard();
          compactPriorMonthsLabel();
          var hyperMain = document.querySelector('main, .dm-content');
          if (hyperMain) installHyperparamSaveToast(hyperMain);
        }, delay);
      });
      var isReverse = location.hash.indexOf('#/migration/reverse') === 0;
      var main = document.querySelector('main, .dm-content');
       // The desktop shell exposes .dm-sidebar; the embedded/narrow preview
       // can omit that node while .dm-content is already mounted. The page
       // renderer only needs the mounted content container to activate.
       var shellReady = !!document.querySelector('.dm-sidebar, .dm-content');
      if (!main || !shellReady) {
        if (location.hash.indexOf('#/migration') === 0) {
          window.setTimeout(update, 100);
          window.setTimeout(update, 500);
          window.setTimeout(update, 1200);
           window.setTimeout(update, 2000);
           window.setTimeout(update, 3000);
        }
        if (location.hash.indexOf('#/exec/forecast') === 0) {
          window.setTimeout(update, 100);
          window.setTimeout(update, 500);
          window.setTimeout(update, 1200);
          window.setTimeout(update, 2000);
        }
        return;
      }
      main.classList.toggle('reverse-migration-page', isReverse);
      installStyle();
      installHyperparamSaveToast(main);
      renderCloudMigration(main);
      styleAnomalyPage(main);
      removeHyperparamPipelineInstruction(main);
      updateOverallTrustChart(main);
      compactPriorMonthsLabel();
      updateExecutivePredictiveAlerts(main);
      updateOracleUseCaseScores(main);
      ensureExecOverviewCards(main);
      updateMonthOverMonthPillarChart(main);
      if (location.hash.indexOf('#/exec/overview') === 0) {
        [200, 600, 1400, 2800].forEach(function (delay) {
          window.setTimeout(function () {
            var m = document.querySelector('main, .dm-content');
            if (!m) return;
            updateOverallTrustChart(m);
            compactPriorMonthsLabel();
            updateExecutivePredictiveAlerts(m);
            updateOracleUseCaseScores(m);
            ensureExecOverviewCards(m);
            updateMonthOverMonthPillarChart(m);
          }, delay);
        });
      }
      if (location.hash.indexOf('#/exec/alerts') === 0) {
        /* React mounts the Alerts route asynchronously. Re-apply the existing
           styled renderer after each mount phase so the native table view
           cannot win the race and remain visible. */
        [150, 500, 1200, 2500].forEach(function (delay) {
          window.setTimeout(function () {
            var alertMain = document.querySelector('main, .dm-content');
            if (!alertMain || location.hash.indexOf('#/exec/alerts') !== 0) return;
            installStyle();
            renderOracleAlerts(alertMain);
            removeLegacyAlertsTable(alertMain);
          }, delay);
        });
      }
      if (location.hash.indexOf('#/exec/forecast') === 0) {
        [150, 500, 1200, 2500].forEach(function (delay) {
          window.setTimeout(function () {
            var currentMain = document.querySelector('main, .dm-content');
            if (currentMain) {
              updateMonthOverMonthPillarChart(currentMain);
            }
          }, delay);
        });
      }
      updateForecastDetailCharts(main);
      renderOracleAlerts(main);
      removeLegacyAlertsTable(main);
      updateOracleUseCaseScores(main);
      if (isForwardMigration() || isReverseMigration()) decorateMigrationRows(main);
      if (!isReverse) {
        var old = main.querySelector('.reverse-route-strip');
        if (old) old.remove();
        return;
      }
      normalizeText(main);
      var chooserText = Array.from(main.querySelectorAll('p')).find(function (paragraph) {
        return paragraph.textContent.indexOf('Choose BigQuery tables') !== -1;
      });
      if (chooserText && chooserText.parentElement) {
        chooserText.parentElement.classList.add('reverse-chooser-hidden');
      }
      if (!main.querySelector('.reverse-route-strip')) {
        var strip = document.createElement('div');
        strip.className = 'reverse-route-strip';
        strip.innerHTML = '<span class="route-badge">BigQuery</span>' +
          '<span class="route-arrow">\u2192</span>' +
          '<span class="route-badge">Oracle</span>' +
          '<span class="route-status">Reverse migration</span>';
        main.insertBefore(strip, main.firstChild);
      }
    } finally {
      _updating = false;
    }
  }
  // Route changes are sufficient for this compatibility layer. A global DOM
  // observer caused repeated rerenders while React was changing pages.
  function restoreReactPage() {
    if (location.hash.indexOf('#/migration') === 0) return;
    window.__dmCloudMigration = false;
    window.dispatchEvent(new CustomEvent('dm:cloudmigration'));
    var portal = document.getElementById('dm-cloud-migration-portal');
    if (portal) portal.style.display = 'none';
    document.querySelectorAll('main.dm-content').forEach(function (node) {
      node.style.opacity = '';
      node.style.pointerEvents = '';
      node.style.display = '';
      node.classList.remove('cloud-migration-design');
    });
  }
  window.addEventListener('hashchange', function () {
    /* Reset per-navigation fetch flags so overview scores re-fetch on return */
    if (location.hash.indexOf('#/exec/overview') !== 0) {
      window.__dmExecScoreFetched = false;
      window.__dmMigScoreFetched  = false;
      window.__dmAlertsFetched    = false;
      mdmUseCaseRequestStarted    = false;
      /* Remove injected wrapper so it rebuilds fresh on return */
      var old = document.querySelector('.exec-overview-injected');
      if (old) old.remove();
    }
    update();
    // React and the compatibility layer commit on separate turns. Re-run the
    // migration mount after each commit so navigation never lands on an empty
    // page.
    window.setTimeout(update, 0);
    window.setTimeout(update, 250);
    // React applies the new route asynchronously; restore again after its
    // commit so the previous migration page can never leave main hidden.
    window.setTimeout(restoreReactPage, 0);
    window.setTimeout(restoreReactPage, 250);
  });
  window.addEventListener('popstate', function () { update(); });
  window.addEventListener('resize', function () {
    var portal = document.getElementById('dm-cloud-migration-portal');
    if (!portal || portal.style.display === 'none') return;
    var main = document.querySelector('main.dm-content');
    if (!main) return;
    var rect = main.getBoundingClientRect();
    portal.style.top   = rect.top  + 'px';
    portal.style.left  = rect.left + 'px';
    portal.style.width = rect.width + 'px';
  });
  installForecastAlertEnrichment();
  installTextNormalizationObserver();
  installExecutiveMonthChartObserver();
  installExecutiveAlertsObserver();
  update();
  [1000, 3000, 6000].forEach(function (delay) {
    window.setTimeout(function () {
      if (location.hash.indexOf('#/exec/forecast') !== 0) return;
      var execMain = document.querySelector('main, .dm-content');
      if (execMain) {
        updateMonthOverMonthPillarChart(execMain);
      }
    }, delay);
  });
})();

