"""Run the Oracle-backed MDM pipeline in order."""
import subprocess, sys
for script in ('1generate_data.py','2run_scoring.py','3run_golden.py'):
    print(f'\n===== Running {script} =====', flush=True)
    subprocess.run([sys.executable, script], check=True)
print('\nMDM pipeline completed. Source, score and golden records are stored in Oracle.')
