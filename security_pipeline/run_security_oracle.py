from __future__ import annotations
import argparse, importlib.util, json, os, sys, traceback
from pathlib import Path
from datetime import datetime, date
import numpy as np
import pandas as pd
import oracledb

ROOT = Path(__file__).resolve().parent
SEC = ROOT / "security"

def load_module(filename, name):
    path = SEC / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

gen = load_module("1_generate_breach_data.py", "security_generator")
dspm_mod = load_module("2_dspm_scan.py", "security_dspm")
fraud_mod = load_module("4_fraud_signals_scan.py", "security_fraud")
tamper_mod = load_module("5_tamper_scan.py", "security_tamper")
score_mod = load_module("6_security_score.py", "security_score")

def json_default(v):
    if isinstance(v, (np.integer,)): return int(v)
    if isinstance(v, (np.floating,)): return float(v)
    if isinstance(v, (np.bool_,)): return bool(v)
    if isinstance(v, (pd.Timestamp, datetime, date)): return v.isoformat()
    if pd.isna(v): return None
    return str(v)

def frame_records(df):
    if df is None or df.empty: return []
    return json.loads(df.to_json(orient="records", date_format="iso"))

def connect():
    user=os.getenv("ORACLE_USER","DELTAMAX_V5")
    password=os.getenv("ORACLE_PASSWORD")
    dsn=os.getenv("ORACLE_DSN","localhost:1521/FREEPDB1")
    if not password:
        raise RuntimeError("Set ORACLE_PASSWORD environment variable before running.")
    return oracledb.connect(user=user, password=password, dsn=dsn)

def package_call_start(conn):
    with conn.cursor() as cur:
        out=cur.var(str, size=32)
        cur.callproc("SECURITY_PKG.START_RUN", ["Security pipeline run from Python", out])
        return out.getvalue()

def log_step(conn, run_id, step, status, count=None, details=None):
    with conn.cursor() as cur:
        cur.callproc("SECURITY_PKG.LOG_STEP", [run_id, step, status, count, details])

def save_dataset(conn, run_id, key, df):
    rows=frame_records(df)
    columns=list(df.columns) if df is not None else []
    with conn.cursor() as cur:
        cur.execute("DELETE FROM SEC_ROWS WHERE RUN_ID=:r AND DATASET_KEY=:k", r=run_id, k=key)
        cur.execute("DELETE FROM SEC_DATASETS WHERE RUN_ID=:r AND DATASET_KEY=:k", r=run_id, k=key)
        cur.execute("""INSERT INTO SEC_DATASETS(RUN_ID,DATASET_KEY,ROW_COUNT,COLUMNS_JSON)
                       VALUES(:r,:k,:n,:c)""",
                    r=run_id,k=key,n=len(rows),c=json.dumps(columns))
        batch=[]
        for i,row in enumerate(rows,1):
            rid=row.get("record_id")
            payload=json.dumps(row, default=json_default, ensure_ascii=False)
            batch.append({"r":run_id,"k":key,"i":i,"rid":str(rid)[:100] if rid is not None else None,"p":payload})
            if len(batch)>=500:
                cur.executemany("""INSERT INTO SEC_ROWS(RUN_ID,DATASET_KEY,ROW_NUM,RECORD_ID,PAYLOAD)
                                   VALUES(:r,:k,:i,:rid,:p)""",batch)
                batch=[]
        if batch:
            cur.executemany("""INSERT INTO SEC_ROWS(RUN_ID,DATASET_KEY,ROW_NUM,RECORD_ID,PAYLOAD)
                               VALUES(:r,:k,:i,:rid,:p)""",batch)
    conn.commit()
    return len(rows)

def save_summary(conn, run_id, summary):
    with conn.cursor() as cur:
        cur.execute("MERGE INTO SEC_SUMMARY s USING (SELECT :r RUN_ID FROM dual) x ON (s.RUN_ID=x.RUN_ID) "
                    "WHEN MATCHED THEN UPDATE SET s.SUMMARY_JSON=:j "
                    "WHEN NOT MATCHED THEN INSERT(RUN_ID,SUMMARY_JSON) VALUES(:r,:j)",
                    r=run_id,j=json.dumps(summary,default=json_default,ensure_ascii=False))
    conn.commit()

def main():
    ap=argparse.ArgumentParser(description="Run all security pipeline scripts with Oracle persistence (no CSV outputs).")
    ap.add_argument("--rows", type=int, default=400, help="Number of synthetic base records (default 400)")
    ap.add_argument("--seeded", type=int, default=6, help="Seed parameter passed to the generator (default 6)")
    args=ap.parse_args()
    conn=connect()
    run_id=None
    try:
        run_id=package_call_start(conn)
        print("Oracle security RUN_ID:",run_id)

        # Stage 1: same generator logic as the supplied script, but keep data in memory.
        log_step(conn,run_id,"1_generate_breach_data.py","RUNNING",None,"Generating synthetic security dataset in memory")
        rows=gen.build_clean_rows(args.rows, datetime.now())
        for row in rows: row["row_hash"]=gen._row_hash(row)
        baseline=pd.DataFrame(rows).copy(deep=True)
        gt=[]
        per_cat=max(50,args.seeded//3)
        gen.seed_category_1(rows,gt,per_cat)
        gen.seed_category_3(rows,gt,per_cat)
        gen.seed_category_4(rows,gt,per_cat)
        for row in rows: row["row_hash"]=gen._row_hash(row)
        live=pd.DataFrame(rows)
        groundtruth=pd.DataFrame(gt)
        save_dataset(conn,run_id,"breach_baseline",baseline)
        save_dataset(conn,run_id,"breach_dataset",live)
        save_dataset(conn,run_id,"breach_groundtruth",groundtruth)
        log_step(conn,run_id,"1_generate_breach_data.py","SUCCESS",len(live),"Synthetic baseline, live dataset and ground truth persisted in Oracle")

        # Stage 2: DSPM sensitive data scanner
        log_step(conn,run_id,"2_dspm_scan.py","RUNNING",None,"Scanning for sensitive-data exposure")
        dspm=dspm_mod.scan_dataframe(live.copy())
        save_dataset(conn,run_id,"security_findings_dspm",dspm)
        log_step(conn,run_id,"2_dspm_scan.py","SUCCESS",len(dspm),"DSPM findings persisted in Oracle")

        # Stage 3: fraud / abuse scanner
        log_step(conn,run_id,"4_fraud_signals_scan.py","RUNNING",None,"Scanning fraud and abuse signals")
        findings=[]
        findings += fraud_mod.find_synthetic_identity(live.copy())
        findings += fraud_mod.find_future_dated(live.copy())
        findings += fraud_mod.find_mass_duplicate_value(live.copy())
        findings += fraud_mod.find_extreme_outliers(live.copy())
        fraud=pd.DataFrame(findings)
        save_dataset(conn,run_id,"security_findings_fraud",fraud)
        log_step(conn,run_id,"4_fraud_signals_scan.py","SUCCESS",len(fraud),"Fraud/abuse findings persisted in Oracle")

        # Stage 4: tamper / integrity scanner, preserving string values for hash checks.
        log_step(conn,run_id,"5_tamper_scan.py","RUNNING",None,"Scanning row hashes, silent edits and broken references")
        live_str=live.fillna("").astype(str)
        base_str=baseline.fillna("").astype(str)
        tamper_findings=[]
        for _, row in live_str.iterrows():
            d=row.to_dict()
            expected=d.get("row_hash")
            actual=tamper_mod.row_hash(d)
            if expected != actual:
                tamper_findings.append({"record_id":row["record_id"],"type":"row_hash_mismatch",
                    "detail":f"stored={expected}, recomputed={actual}","severity":"critical"})
        base_idx=base_str.set_index("record_id")
        overlap=live_str[live_str["record_id"].isin(base_idx.index)]
        for _,row in overlap.iterrows():
            b=base_idx.loc[row["record_id"]]
            changed=(row["lifetime_value"]!=b["lifetime_value"]) or (row["ref_country"]!=b["ref_country"])
            if changed and row["updated_at"]==b["updated_at"]:
                tamper_findings.append({"record_id":row["record_id"],"type":"silent_edit",
                    "detail":"content changed but updated_at is identical to baseline","severity":"high"})
        bad_fk=live_str[~live_str["ref_country"].isin(tamper_mod.VALID_REF_COUNTRIES)]
        for _,row in bad_fk.iterrows():
            tamper_findings.append({"record_id":row["record_id"],"type":"broken_fk",
                "detail":f"ref_country='{row['ref_country']}' not in reference table","severity":"high"})
        tamper=pd.DataFrame(tamper_findings)
        save_dataset(conn,run_id,"security_findings_tamper",tamper)
        log_step(conn,run_id,"5_tamper_scan.py","SUCCESS",len(tamper),"Tamper/integrity findings persisted in Oracle")

        # Stage 5: scoring and rollups. Keep same policy as original security scoring script.
        log_step(conn,run_id,"6_security_score.py","RUNNING",None,"Aggregating findings and calculating per-record scores")
        parts=[]
        for df,scanner,category,cat_id in [
            (dspm,"dspm","Sensitive data exposure",1),
            (fraud,"fraud","Fraud / abuse signals",2),
            (tamper,"tamper","Tamper / integrity",3)]:
            if df is None or df.empty: continue
            x=df.copy()
            if scanner=="dspm":
                if "column" not in x.columns: x["column"]=""
                if "match" not in x.columns: x["match"]=""
                x["detail"]="column="+x["column"].astype(str)+": "+x["match"].astype(str)
            for c in ["record_id","type","detail","severity"]:
                if c not in x.columns: x[c]=None
            x["scanner"]=scanner; x["category"]=category; x["category_id"]=cat_id
            parts.append(x[["record_id","scanner","category","category_id","type","detail","severity"]])
        findings=pd.concat(parts,ignore_index=True) if parts else pd.DataFrame(columns=["record_id","scanner","category","category_id","type","detail","severity"])
        findings["penalty"]=findings["severity"].map(score_mod.SEV_PENALTY).fillna(0)
        record_penalty=findings.groupby("record_id")["penalty"].sum().clip(upper=100) if not findings.empty else pd.Series(dtype=float)
        records=live[["record_id"]].copy()
        records["security_score"]=(100-records["record_id"].map(record_penalty).fillna(0)).clip(lower=0)
        if not findings.empty:
            worst=(findings.sort_values("penalty",ascending=False).drop_duplicates("record_id")[["record_id","category","severity"]])
            records=records.merge(worst,on="record_id",how="left")
        else:
            records["category"]=None; records["severity"]=None
        records["category"]=records["category"].fillna("—")
        records["severity"]=records["severity"].fillna("none")
        save_dataset(conn,run_id,"security_findings",findings.drop(columns=["penalty"],errors="ignore"))
        save_dataset(conn,run_id,"security_records",records)

        n_total=len(live)
        n_affected=int(records["record_id"].isin(findings["record_id"]).sum()) if not findings.empty else 0
        overall=round(float(records["security_score"].mean()),1) if n_total else 0
        by_category=findings.groupby("category").size().sort_values(ascending=False).to_dict() if not findings.empty else {}
        by_severity=findings.groupby("severity").size().to_dict() if not findings.empty else {}
        by_type=findings.groupby(["category","type"]).size().reset_index(name="count").sort_values("count",ascending=False) if not findings.empty else pd.DataFrame()
        top_types=[{"category":r["category"],"type":r["type"],"count":int(r["count"])} for _,r in by_type.head(8).iterrows()] if not by_type.empty else []
        by_column=[]
        if not dspm.empty and "column" in dspm.columns:
            cc=dspm.groupby(["column","type"]).size().reset_index(name="count").sort_values("count",ascending=False)
            by_column=[{"column":r["column"],"type":r["type"],"count":int(r["count"])} for _,r in cc.head(10).iterrows()]
        examples={}
        if not findings.empty:
            for cat in by_category.keys():
                sub=findings[findings["category"]==cat].sort_values("penalty",ascending=False).head(10)
                examples[cat]=[{"record_id":r["record_id"],"type":r["type"],"detail":str(r["detail"])[:120],"severity":r["severity"]} for _,r in sub.iterrows()]
        summary={"total_records":int(n_total),"records_with_findings":n_affected,
            "exposure_rate_pct":round(n_affected/n_total*100,1) if n_total else 0,
            "overall_security_score":overall,"by_category":{k:int(v) for k,v in by_category.items()},
            "by_severity":{k:int(v) for k,v in by_severity.items()},"top_types":top_types,
            "by_column":by_column,"examples_by_category":examples}
        save_summary(conn,run_id,summary)
        log_step(conn,run_id,"6_security_score.py","SUCCESS",len(records),
                 f"Scored {len(records)} records; {n_affected} records with findings; overall score {overall}/100")
        with conn.cursor() as cur:
            cur.callproc("SECURITY_PKG.FINISH_RUN",[run_id,"SUCCESS","All security scripts completed; results persisted in Oracle"])
        print(json.dumps({"run_id":run_id,"status":"SUCCESS","summary":summary},indent=2,default=json_default))
    except Exception as exc:
        if run_id:
            try:
                with conn.cursor() as cur:
                    cur.callproc("SECURITY_PKG.FINISH_RUN",[run_id,"FAILED",str(exc)[:1800]])
            except Exception: pass
        traceback.print_exc()
        raise
    finally:
        conn.close()

if __name__=="__main__":
    main()
