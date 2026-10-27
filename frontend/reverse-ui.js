(function () {
  var styleId = 'reverse-migration-ui-style';

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
      row.classList.add('migration-detail-row');
      row.tabIndex = 0;
      row.setAttribute('role', 'button');
      row.setAttribute('aria-label', 'View migration details for ' + row.cells[0].textContent.trim());
    });
  }

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
      node.nodeValue = node.nodeValue
        .replace(/Google BigQuery/g, 'BigQuery')
        .replace(/Oracle Database/g, 'Oracle')
        .replace(/Selected tables/g, 'Transferred tables');
    }
  }

  function updateAssistantCopy() {
    document.querySelectorAll('.agent-foot-note').forEach(function (note) {
      var text = note.textContent || '';
      if (text.indexOf('Connected to BigQuery') !== -1 || text.indexOf('BigQuery agent is not configured') !== -1) {
        note.textContent = 'Connected to Oracle-backed dashboard data · answers use the selected dashboard agent.';
      }
    });
  }

  function update() {
    updateAssistantCopy();
    var isReverse = location.hash.indexOf('#/migration/reverse') === 0;
    var main = document.querySelector('main');
    if (!main) return;
    main.classList.toggle('reverse-migration-page', isReverse);
    installStyle();
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
        '<span class="route-arrow">→</span>' +
        '<span class="route-badge">Oracle</span>' +
        '<span class="route-status">Reverse migration</span>';
      main.insertBefore(strip, main.firstChild);
    }
  }

  new MutationObserver(update).observe(document.documentElement, { childList: true, subtree: true });
  window.addEventListener('hashchange', update);
  update();
})();
