"""Generate synthetic MDM source records and insert them directly into Oracle."""
import uuid, random, os
from datetime import datetime, timedelta
from dataclasses import asdict
from models import CustomerRecord
from oracle_db import connect

NUM_CUSTOMERS = int(os.getenv("MDM_NUM_CUSTOMERS", "1000"))
SOURCE_SYSTEMS = ["CRM", "eCommerce", "Loyalty", "POS", "ERP"]
FIRST_NAMES = ["Priya", "John", "Amit", "Sara"]
LAST_NAMES = ["Sharma", "Smith", "Patel"]

def _uid(): return str(uuid.uuid4())[:12].upper()
def _ts(days=365): return (datetime.now() - timedelta(days=random.randint(1, days))).strftime("%Y-%m-%dT%H:%M:%SZ")
def corrupt_name(name):
    r=random.random()
    if r<.2: return name.upper()
    if r<.4: return name.lower()
    if r<.55: return name.replace("a","@")
    if r<.7: return name+" "
    if r<.8: return name[:-1]
    return name
def corrupt_email(email):
    r=random.random()
    if r<.2: return email.upper()
    if r<.35: return email.replace("@"," @")
    if r<.5: return email.replace(".",",")
    if r<.65: return email+" "
    return email

def generate():
    records=[]
    for _ in range(NUM_CUSTOMERS):
        cluster_id=_uid(); first=random.choice(FIRST_NAMES); last=random.choice(LAST_NAMES)
        email=f"{first.lower()}.{last.lower()}@gmail.com"
        phone=f"{random.randint(200,999)}-{random.randint(200,999)}-{random.randint(1000,9999)}"
        systems=random.sample(SOURCE_SYSTEMS, random.randint(3,5))
        for i, source in enumerate(systems):
            fn,ln,em=(first,last,email) if i==0 else (corrupt_name(first),corrupt_name(last),corrupt_email(email))
            records.append(CustomerRecord(record_id=_uid(), source_system=source, first_name=fn, last_name=ln,
                email=em, phone=phone, date_of_birth="1990-01-01", gender=random.choice(["M","F",None]),
                address_line1="123 Main St", city="Austin", state="TX", postal_code="78701",
                country=random.choice(["US","USA"]), loyalty_tier=random.choice(["Gold","Silver","Bronze",None]),
                customer_since="2020-01-01", last_purchase_date=_ts(180), total_lifetime_value=round(random.uniform(100,10000),2),
                is_active=True, created_at=_ts(1000), updated_at=_ts(30), cluster_id=cluster_id))
    return records

def run():
    records=generate()
    sql="""INSERT INTO MDM_CUSTOMER_STG (RECORD_ID,SOURCE_SYSTEM,FIRST_NAME,LAST_NAME,EMAIL,PHONE,DATE_OF_BIRTH,GENDER,ADDRESS_LINE1,CITY,STATE,POSTAL_CODE,COUNTRY,LOYALTY_TIER,CUSTOMER_SINCE,LAST_PURCHASE_DATE,TOTAL_LIFETIME_VALUE,IS_ACTIVE,CREATED_AT,UPDATED_AT,CLUSTER_ID) VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10,:11,:12,:13,:14,:15,:16,:17,:18,:19,:20,:21)"""
    with connect() as conn:
        with conn.cursor() as cur:
            # Start a clean demo run so repeated execution does not duplicate old synthetic data.
            cur.execute("DELETE FROM MDM_CUSTOMER_GOLDEN")
            cur.execute("DELETE FROM MDM_CUSTOMER_SCORES")
            cur.execute("DELETE FROM MDM_CUSTOMER_STG")
            rows=[]
            for r in records:
                d=asdict(r)
                rows.append((d['record_id'],d['source_system'],d['first_name'],d['last_name'],d['email'],d['phone'],
                    d['date_of_birth'],d['gender'],d['address_line1'],d['city'],d['state'],d['postal_code'],d['country'],
                    d['loyalty_tier'],d['customer_since'],d['last_purchase_date'],d['total_lifetime_value'],
                    1 if d['is_active'] else 0,d['created_at'],d['updated_at'],d['cluster_id']))
            cur.executemany(sql, rows)
            cur.execute("INSERT INTO MDM_RUN_LOG (RUN_ID,STEP_NAME,STATUS,RECORD_COUNT,DETAILS) VALUES (SYS_GUID(),'GENERATE','SUCCESS',:n,:d)", n=len(rows), d='Generated synthetic customer source records directly in Oracle')
        conn.commit()
    print(f"Inserted {len(records)} records directly into Oracle table MDM_CUSTOMER_STG. No CSV/GCP/S3 used.")
if __name__ == '__main__': run()
