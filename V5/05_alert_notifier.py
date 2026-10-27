import os
import html
from collections import Counter
import oracledb
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from python_http_client.exceptions import HTTPError

ORACLE_USER='DELTAMAX_V5'
ORACLE_PASSWORD='DeltaMaxV5@2026'
ORACLE_DSN='localhost:1521/FREEPDB1'
ALERT_TABLE='DM_V5_ARIMA_ALERTS'
TRUST_THRESHOLD=0.75

def get_connection():
    print('Connecting to Oracle...')
    conn=oracledb.connect(user=ORACLE_USER,password=ORACLE_PASSWORD,dsn=ORACLE_DSN)
    print('Connected to Oracle successfully.')
    return conn

def get_latest_run_id(conn):
    cur=conn.cursor()
    try:
        cur.execute(f'''SELECT RUN_ID FROM (SELECT RUN_ID FROM {ALERT_TABLE} ORDER BY CREATED_AT DESC) WHERE ROWNUM=1''')
        row=cur.fetchone()
        return row[0] if row else None
    finally: cur.close()

def load_alerts(conn, run_id):
    cur=conn.cursor()
    try:
        cur.execute(f'''
        SELECT RUN_ID,SERIES_NAME,TRIGGER_TYPE,MONTH_AHEAD,FORECAST_MONTH,
               FORECAST_VALUE,THRESHOLD_VALUE,DELTA_VALUE,SEVERITY,REASON,CREATED_AT
        FROM {ALERT_TABLE} WHERE RUN_ID=:run_id
        ORDER BY CASE SEVERITY WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'WATCH' THEN 3 ELSE 4 END,
                 FORECAST_MONTH,SERIES_NAME''', {'run_id':run_id})
        cols=[c[0].lower() for c in cur.description]
        return [dict(zip(cols,row)) for row in cur.fetchall()]
    finally: cur.close()

def sev_color(s):
    return {'CRITICAL':'#d32f2f','HIGH':'#f57c00','WATCH':'#fbc02d'}.get(s,'#757575')

def fmt(v):
    if v is None: return '-'
    try:
        v=float(v); return f'{v:.4f}' if abs(v)<1 else f'{v:,.4f}'
    except: return html.escape(str(v))

def build_html(run_id, alerts):
    counts=Counter(str(r['severity']).upper() for r in alerts)
    badges=''.join(f'<span style="display:inline-block;background:{sev_color(s)};color:white;padding:8px 14px;border-radius:5px;margin-right:8px;">{s}: {counts.get(s,0)}</span>' for s in ('CRITICAL','HIGH','WATCH'))
    rows=[]
    for r in alerts:
        s=str(r['severity']).upper()
        rows.append(f'''<tr>
        <td style="padding:8px;border-bottom:1px solid #ddd;"><b>{html.escape(str(r['series_name']))}</b></td>
        <td style="padding:8px;border-bottom:1px solid #ddd;">{html.escape(str(r['forecast_month']))}</td>
        <td style="padding:8px;border-bottom:1px solid #ddd;text-align:right;">{fmt(r['forecast_value'])}</td>
        <td style="padding:8px;border-bottom:1px solid #ddd;"><span style="background:{sev_color(s)};color:white;padding:4px 9px;border-radius:10px;">{s}</span></td>
        <td style="padding:8px;border-bottom:1px solid #ddd;">{html.escape(str(r['trigger_type']))}</td>
        <td style="padding:8px;border-bottom:1px solid #ddd;">{html.escape(str(r['reason']))}</td>
        </tr>''')
    return f'''<html><body style="font-family:Arial;color:#222;max-width:1100px;margin:auto;">
    <div style="background:#263238;color:white;padding:20px;border-radius:6px;"><h2>DeltaMax V5 - Predictive Trust Alert</h2><p>ARIMA predictive alert notification</p></div>
    <p><b>Run ID:</b> {html.escape(str(run_id))}</p><p><b>Total alerts:</b> {len(alerts)}</p><p><b>Trust threshold:</b> {TRUST_THRESHOLD:.2f}</p>
    <div style="margin:20px 0;">{badges}</div>
    <h3>Alert Details</h3><table style="border-collapse:collapse;width:100%;font-size:13px;">
    <thead><tr style="background:#37474f;color:white;"><th style="padding:9px;text-align:left;">Series</th><th style="padding:9px;text-align:left;">Forecast Month</th><th style="padding:9px;text-align:right;">Forecast Value</th><th style="padding:9px;">Severity</th><th style="padding:9px;text-align:left;">Trigger</th><th style="padding:9px;text-align:left;">Reason</th></tr></thead>
    <tbody>{''.join(rows)}</tbody></table>
    <p style="margin-top:25px;color:#777;font-size:12px;">Source: DM_V5_ARIMA_ALERTS in Oracle. No CSV or S3 used.</p>
    </body></html>'''

def send_email(run_id, alerts):
    api_key=os.getenv('DELTAMAX_SENDGRID_API_KEY')
    sender=os.getenv('DELTAMAX_ALERT_SENDER')
    receiver=os.getenv('DELTAMAX_ALERT_RECEIVER')
    missing=[n for n,v in [('DELTAMAX_SENDGRID_API_KEY',api_key),('DELTAMAX_ALERT_SENDER',sender),('DELTAMAX_ALERT_RECEIVER',receiver)] if not v]
    if missing: raise RuntimeError('Missing required environment variable(s): '+', '.join(missing))
    c=Counter(str(r['severity']).upper() for r in alerts)
    subject=f"DeltaMax V5 Predictive Trust Alerts - {c.get('CRITICAL',0)} Critical / {c.get('HIGH',0)} High / {c.get('WATCH',0)} Watch"
    message=Mail(from_email=sender,to_emails=receiver,subject=subject,html_content=build_html(run_id,alerts))
    print('\nSending email notification...')
    try:
        response=SendGridAPIClient(api_key).send(message)
    except HTTPError as e:
        body=e.body.decode('utf-8', errors='replace') if isinstance(e.body, bytes) else str(e.body)
        raise RuntimeError(f'SendGrid returned status {e.status_code}: {body}') from e
    if response.status_code not in (200,201,202): raise RuntimeError(f'SendGrid returned status {response.status_code}: {response.body}')
    print(f'[OK] Alert email sent successfully. SendGrid status: {response.status_code}')

def main():
    print('='*78); print('DELTAMAX V5 - ORACLE PREDICTIVE ALERT NOTIFIER'); print('='*78)
    conn=None
    try:
        conn=get_connection()
        run_id=os.getenv('DELTAMAX_ARIMA_RUN_ID') or get_latest_run_id(conn)
        if not run_id:
            print('\n[INFO] No ARIMA alerts found in Oracle.\nNo email sent.'); return
        print(f'\nARIMA run: {run_id}')
        alerts=load_alerts(conn,run_id)
        print(f'Alerts found in Oracle: {len(alerts)}')
        if not alerts: print('[INFO] No alerts for this run.\nNo email sent.'); return
        c=Counter(str(r['severity']).upper() for r in alerts)
        print(f"\nCRITICAL : {c.get('CRITICAL',0)}\nHIGH     : {c.get('HIGH',0)}\nWATCH    : {c.get('WATCH',0)}")
        send_email(run_id,alerts)
        print('\n'+'='*78+'\nPREDICTIVE ALERT NOTIFICATION COMPLETED\n'+'='*78)
        print('Source: Oracle DM_V5_ARIMA_ALERTS'); print('No CSV files used.'); print('No S3 operations performed.')
    except Exception as e:
        print(f'\n[ERROR] Notification failed: {e}'); raise
    finally:
        if conn: conn.close(); print('\nOracle connection closed.')

if __name__=='__main__': main()
