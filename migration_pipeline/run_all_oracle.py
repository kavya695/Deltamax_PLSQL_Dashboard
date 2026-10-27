"""Run the nine original migration stages with MIGRATION_PKG tracking."""
import os,sys,subprocess
BASE=os.path.dirname(os.path.abspath(__file__))
SCRIPTS=['1datagen.py','2HAB.py','3pre-migration_check.py','4cleaning.py','5Data_check_cleaned.py','6inject_anomalies.py','7migrate_azure_to_gcp.py','8post-migration_check.py','9post_migration_with_anomalies.py']
sys.path.insert(0, BASE)
from oracle_compat import active_run_id, begin_new_run, connect, finish_run, log_step, validate_stage

def main():
    # A run is created by MIGRATION_PKG.START_MIGRATION from script 1.
    # Each stage below is logged through MIGRATION_PKG.LOG_STEP.
    run_id=None
    for index, script in enumerate(SCRIPTS, start=1):
        print('\n'+'='*72+'\nRUNNING '+script+'\n'+'='*72,flush=True)
        if index == 1:
            # 1datagen.py starts the run through MIGRATION_PKG itself.
            pass
        else:
            run_id=active_run_id()
            log_step(run_id, script, 'RUNNING', None, f'Stage {index}/9 started')
        p=subprocess.run([sys.executable,os.path.join(BASE,script)],cwd=BASE)
        try:
            run_id=active_run_id()
        except Exception:
            run_id=None
        if p.returncode:
            if run_id:
                try: log_step(run_id, script, 'FAILED', None, f'Exited with code {p.returncode}')
                finally: finish_run('FAILED',f'{script} exited with code {p.returncode}')
            raise SystemExit(p.returncode)
        if run_id:
            log_step(run_id, script, 'SUCCESS', None, f'Stage {index}/9 completed')

    run_id=active_run_id()
    # Validate every stage recorded for this run using MIGRATION_PKG.VALIDATE_STAGE.
    with connect() as c:
        keys=[row[0] for row in c.cursor().execute(
            'SELECT FILE_KEY FROM MIGR_FILES WHERE RUN_ID=:1 ORDER BY FILE_KEY',[run_id]).fetchall()]
    failures=[]
    for key in keys:
        try:
            actual, expected, status=validate_stage(run_id,key)
            print(f'[MIGRATION_PKG] Validate {key}: {status} ({actual}/{expected})')
            if status != 'SUCCESS': failures.append(f'{key}: {actual}/{expected}')
        except Exception as exc:
            failures.append(f'{key}: {exc}')
    if failures:
        details='Stage validation failed: ' + '; '.join(failures)[:1700]
        finish_run('FAILED',details)
        raise SystemExit(details)
    finish_run('SUCCESS','All nine stages completed; MIGRATION_PKG tracked and validated Oracle stages')
    print('All nine stages completed successfully; MIGRATION_PKG run status is SUCCESS.')

if __name__=='__main__':
    main()
