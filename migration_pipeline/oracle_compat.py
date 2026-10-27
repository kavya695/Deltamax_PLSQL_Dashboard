"""Oracle-backed adapter. pandas CSV calls are virtual Oracle-stage reads/writes."""
import os, json, math, uuid
from datetime import date, datetime
import pandas as pd
import oracledb
_BASE_DIR=os.path.dirname(os.path.abspath(__file__))
_INSTALLED=False
_ORIG_EXISTS=os.path.exists
_ORIG_GETSIZE=os.path.getsize

def connect():
    user=os.getenv('MIG_DB_USER','DELTAMAX_V5'); password=os.getenv('MIG_DB_PASSWORD')
    if not password: raise RuntimeError('Set MIG_DB_PASSWORD before running the migration pipeline.')
    dsn=f"{os.getenv('MIG_DB_HOST','localhost')}:{os.getenv('MIG_DB_PORT','1521')}/{os.getenv('MIG_DB_SERVICE','FREEPDB1')}"
    return oracledb.connect(user=user,password=password,dsn=dsn)

def normalize_key(path):
    raw=os.fspath(path).replace('\\','/')
    if raw.startswith('oracle://'): raw=raw[len('oracle://'):]
    if os.path.isabs(raw):
        try: raw=os.path.relpath(raw,_BASE_DIR).replace('\\','/')
        except Exception: raw=os.path.basename(raw)
    raw=raw.lstrip('./')
    marker=raw.find('results/')
    if marker>=0: raw=raw[marker:]
    elif '/' in raw and raw.split('/')[-1].startswith('credit_bureau_data_'): raw=raw.split('/')[-1]
    return raw

def active_run_id():
    with connect() as c: row=c.cursor().execute("SELECT RUN_ID FROM MIGR_CONTROL WHERE CONTROL_KEY='ACTIVE'").fetchone()
    if not row: raise RuntimeError('No active migration run. Run 1datagen.py first or use run_all_oracle.py.')
    return row[0]

def log_step(run_id,step,status,count,details):
    """Write step tracking through the compiled MIGRATION_PKG."""
    with connect() as c:
        cur=c.cursor()
        cur.callproc('MIGRATION_PKG.LOG_STEP', [
            run_id, str(step)[:100], str(status).upper()[:20],
            int(count) if count is not None else None, str(details or '')[:2000]
        ])

def begin_new_run():
    """Create the run through MIGRATION_PKG and set the returned run active."""
    with connect() as c:
        cur=c.cursor()
        run_var=cur.var(oracledb.DB_TYPE_VARCHAR, size=32)
        cur.callproc('MIGRATION_PKG.START_MIGRATION', [
            'Original nine-script migration pipeline; Oracle persistence', run_var
        ])
        run_id=run_var.getvalue()
    print('[Oracle/MIGRATION_PKG] New RUN_ID:',run_id)
    return run_id

def validate_stage(run_id, file_key):
    """Validate Oracle stage metadata and row count via MIGRATION_PKG."""
    with connect() as c:
        cur=c.cursor()
        actual=cur.var(oracledb.DB_TYPE_NUMBER)
        expected=cur.var(oracledb.DB_TYPE_NUMBER)
        status=cur.var(oracledb.DB_TYPE_VARCHAR, size=20)
        cur.callproc('MIGRATION_PKG.VALIDATE_STAGE', [run_id, file_key, actual, expected, status])
        return int(actual.getvalue()), int(expected.getvalue()), status.getvalue()

def copy_stage(run_id, source_key, target_key):
    """Copy an Oracle stage through MIGRATION_PKG.COPY_STAGE."""
    with connect() as c:
        c.cursor().callproc('MIGRATION_PKG.COPY_STAGE', [run_id, source_key, target_key])
    actual, expected, status = validate_stage(run_id, target_key)
    if status != 'SUCCESS':
        raise RuntimeError(f'Oracle package stage copy validation failed for {target_key}: {actual}/{expected}')
    return actual

def _clean(v):
    if v is None: return None
    if hasattr(v,'item'):
        try: v=v.item()
        except Exception: pass
    if isinstance(v,float) and (math.isnan(v) or math.isinf(v)): return None
    try:
        if pd.isna(v): return None
    except Exception: pass
    if isinstance(v,(datetime,date)): return v.isoformat()
    return v

def write_frame(path,df):
    run_id=active_run_id(); key=normalize_key(path)[-250:]; frame=df.copy()
    cols=json.dumps([str(c) for c in frame.columns],ensure_ascii=False)
    rows=[(run_id,key,i,json.dumps({str(k):_clean(v) for k,v in row.items()},ensure_ascii=False,default=str,allow_nan=False)) for i,(_,row) in enumerate(frame.iterrows())]
    with connect() as c:
        cur=c.cursor(); cur.execute('DELETE FROM MIGR_ROWS WHERE RUN_ID=:1 AND FILE_KEY=:2',[run_id,key])
        cur.execute('UPDATE MIGR_FILES SET COLUMNS_JSON=:1, ROW_COUNT=:2, UPDATED_AT=SYSTIMESTAMP WHERE RUN_ID=:3 AND FILE_KEY=:4',[cols,len(frame),run_id,key])
        if cur.rowcount == 0:
            cur.execute('INSERT INTO MIGR_FILES(RUN_ID,FILE_KEY,COLUMNS_JSON,ROW_COUNT) VALUES(:1,:2,:3,:4)',[run_id,key,cols,len(frame)])
        if rows:
            cur.setinputsizes(None,None,None,oracledb.DB_TYPE_CLOB)
            cur.executemany('INSERT INTO MIGR_ROWS(RUN_ID,FILE_KEY,ROW_NUM,PAYLOAD) VALUES(:1,:2,:3,:4)',rows)
        # Persist the stage before opening another connection for LOG_STEP.
        c.commit()
    log_step(run_id,'STORE:'+key[:90],'SUCCESS',len(frame),'Dataframe persisted in Oracle; virtual CSV path only')
    print(f'[Oracle] Stored {len(frame)} rows -> {key}')
    return len(frame)

def read_frame(path,**kwargs):
    run_id=active_run_id(); key=normalize_key(path)
    with connect() as c:
        cur=c.cursor(); meta=cur.execute('SELECT COLUMNS_JSON FROM MIGR_FILES WHERE RUN_ID=:1 AND FILE_KEY=:2',[run_id,key]).fetchone()
        if not meta: raise FileNotFoundError(f'Oracle stage not found for virtual path: {key}. Run prior steps first.')
        cols=json.loads(meta[0].read() if hasattr(meta[0],'read') else meta[0]); vals=cur.execute('SELECT PAYLOAD FROM MIGR_ROWS WHERE RUN_ID=:1 AND FILE_KEY=:2 ORDER BY ROW_NUM',[run_id,key]).fetchall()
        # Read CLOBs while the connection that created the LOB locators is open.
        data=[json.loads(v[0].read() if hasattr(v[0],'read') else v[0]) for v in vals]
    df=pd.DataFrame(data,columns=cols)
    for col in df.columns:
        try:
            if df[col].notna().any(): df[col]=pd.to_numeric(df[col],errors='ignore')
        except Exception: pass
    return df

def source_columns(month):
    """Return the original source schema for a generated month stage."""
    key=f'credit_bureau_data_{str(month).lower()}_.csv'
    with connect() as c:
        row=c.cursor().execute(
            'SELECT COLUMNS_JSON FROM MIGR_FILES WHERE RUN_ID=:1 AND FILE_KEY=:2',
            [active_run_id(),key]
        ).fetchone()
        if not row:
            raise FileNotFoundError(f'Oracle source schema not found for month: {month}')
        payload=row[0].read() if hasattr(row[0],'read') else row[0]
    return json.loads(payload)

def missingness_flags(frame):
    """Flag nulls only in fields that existed in each row's source month."""
    ignored={'businessID','data_lineage','source_month'}
    if 'source_month' not in frame.columns:
        cols=[col for col in frame.columns if col not in ignored]
        return frame[cols].isna().any(axis=1) if cols else pd.Series(False,index=frame.index)

    flags=pd.Series(False,index=frame.index,dtype=bool)
    for month, group in frame.groupby('source_month',dropna=False):
        if pd.isna(month):
            raise ValueError('source_month is missing; cannot distinguish structural nulls from missing data')
        expected=set(source_columns(month))
        cols=[col for col in frame.columns if col in expected and col not in ignored]
        if cols:
            flags.loc[group.index]=group[cols].isna().any(axis=1)
    return flags

def exists_virtual(path):
    try:
        key=normalize_key(path)
        with connect() as c:
            cur=c.cursor()
            if str(path).lower().endswith('.json'):
                return bool(cur.execute('SELECT 1 FROM MIGR_JSON_LOGS WHERE RUN_ID=:1 AND LOG_NAME=:2',[active_run_id(),key]).fetchone())
            return bool(cur.execute('SELECT 1 FROM MIGR_FILES WHERE RUN_ID=:1 AND FILE_KEY=:2',[active_run_id(),key]).fetchone())
    except Exception: return False

def save_json(name,obj):
    run_id=active_run_id(); key=normalize_key(name); payload=json.dumps(obj,ensure_ascii=False,default=str)
    with connect() as c:
        cur=c.cursor()
        cur.execute('UPDATE MIGR_JSON_LOGS SET PAYLOAD=:1, CREATED_AT=SYSTIMESTAMP WHERE RUN_ID=:2 AND LOG_NAME=:3',[payload,run_id,key])
        if cur.rowcount == 0: cur.execute('INSERT INTO MIGR_JSON_LOGS(RUN_ID,LOG_NAME,PAYLOAD) VALUES(:1,:2,:3)',[run_id,key,payload])
        c.commit()
    log_step(run_id,'JSON_LOG:'+key[:80],'SUCCESS',1,'JSON log persisted in Oracle')

def read_json(name):
    with connect() as c:
        row=c.cursor().execute('SELECT PAYLOAD FROM MIGR_JSON_LOGS WHERE RUN_ID=:1 AND LOG_NAME=:2',[active_run_id(),normalize_key(name)]).fetchone()
        if not row: raise FileNotFoundError(f'Oracle JSON log not found: {name}')
        payload=row[0].read() if hasattr(row[0],'read') else row[0]
    return json.loads(payload)

def finish_run(status='SUCCESS',details='Pipeline completed'):
    run_id=active_run_id()
    with connect() as c:
        c.cursor().callproc('MIGRATION_PKG.FINISH_MIGRATION', [run_id, status, details[:2000]])


def install():
    """Patch filesystem checks for virtual Oracle stage files."""
    global _INSTALLED

    if _INSTALLED:
        return

    def ex(p):
        if isinstance(p, (str, os.PathLike)):
            path = os.fspath(p)
            if path.lower().endswith(('.csv', '.json')):
                # Keep real files accessible, including Google credentials.
                if _ORIG_EXISTS(path):
                    return True
                return exists_virtual(path)

        return _ORIG_EXISTS(p)

    def gs(p):
        if isinstance(p, (str, os.PathLike)):
            path = os.fspath(p)
            if path.lower().endswith('.csv') and not _ORIG_EXISTS(path):
                return 1 if exists_virtual(path) else 0

        return _ORIG_GETSIZE(p)

    os.path.exists = ex
    os.path.getsize = gs
    _INSTALLED = True
