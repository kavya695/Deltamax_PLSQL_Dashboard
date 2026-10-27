"""Read MDM source records from Oracle, run the existing trust engine, save scores to Oracle."""
from datetime import datetime
from models import CustomerRecord
from trust_score_engine import TrustScoreEngine
from oracle_db import connect

SELECT_SQL = """SELECT RECORD_ID,SOURCE_SYSTEM,FIRST_NAME,LAST_NAME,EMAIL,PHONE,DATE_OF_BIRTH,GENDER,ADDRESS_LINE1,CITY,STATE,POSTAL_CODE,COUNTRY,LOYALTY_TIER, CUSTOMER_SINCE,LAST_PURCHASE_DATE,TOTAL_LIFETIME_VALUE,IS_ACTIVE,CREATED_AT,UPDATED_AT,CLUSTER_ID FROM MDM_CUSTOMER_STG ORDER BY CLUSTER_ID,RECORD_ID"""

def _str(v):
    if v is None: return None
    if hasattr(v,'strftime'): return v.strftime('%Y-%m-%dT%H:%M:%SZ')
    return str(v)

def run():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(SELECT_SQL)
            names=[x[0].lower() for x in cur.description]
            rows=[dict(zip(names,row)) for row in cur.fetchall()]
    if not rows:
        print('No MDM source records found. Run 1generate_data.py first.'); return
    records=[]
    for row in rows:
        for k in ('date_of_birth','customer_since','last_purchase_date','created_at','updated_at'):
            row[k]=_str(row[k])
        row['is_active']=bool(row['is_active']) if row['is_active'] is not None else None
        if row['total_lifetime_value'] is not None: row['total_lifetime_value']=float(row['total_lifetime_value'])
        records.append(CustomerRecord(**row))
    reports=TrustScoreEngine().score_all(records)
    report_map={x.record_id:x for x in reports}
    insert_sql="""INSERT INTO MDM_CUSTOMER_SCORES (RECORD_ID,SOURCE_SYSTEM,CLUSTER_ID,RULES_SCORE,DRIFT_SCORE,ANOMALY_SCORE,TRUST_SCORE,IS_GOLDEN,SURVIVORSHIP_REASON,ANOMALY_FLAGS,DRIFT_DETAIL,SCORED_AT) VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10,:11,SYSTIMESTAMP)"""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM MDM_CUSTOMER_GOLDEN')
            cur.execute('DELETE FROM MDM_CUSTOMER_SCORES')
            out=[]
            for r in records:
                rp=report_map.get(r.record_id)
                if not rp: continue
                flags=', '.join(rp.anomaly_result.flags) if rp.anomaly_result else None
                detail=rp.drift_result.detail if rp.drift_result else None
                out.append((r.record_id,r.source_system,r.cluster_id,rp.rules_score,rp.drift_score,rp.anomaly_score,rp.trust_score,
                    1 if rp.is_golden else 0,rp.survivorship_reason,flags,detail))
            cur.executemany(insert_sql,out)
            cur.execute("INSERT INTO MDM_RUN_LOG (RUN_ID,STEP_NAME,STATUS,RECORD_COUNT,DETAILS) VALUES (SYS_GUID(),'SCORING','SUCCESS',:n,:d)", n=len(out), d='Existing Python trust engine scored Oracle records; results persisted in Oracle')
        conn.commit()
    print(f'Scored {len(out)} records. Results saved to Oracle table MDM_CUSTOMER_SCORES.')
if __name__ == '__main__': run()
