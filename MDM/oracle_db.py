"""Oracle connection helpers for MDM. No CSV or cloud storage is used."""
import os
import oracledb


def connect():
    user = os.getenv("MDM_DB_USER", "DELTAMAX_V5")
    password = os.getenv("MDM_DB_PASSWORD")
    host = os.getenv("MDM_DB_HOST", "localhost")
    port = int(os.getenv("MDM_DB_PORT", "1521"))
    service = os.getenv("MDM_DB_SERVICE", "FREEPDB1")
    if not password:
        raise RuntimeError("Set MDM_DB_PASSWORD to your Oracle schema password before running MDM scripts.")
    dsn = oracledb.makedsn(host, port, service_name=service)
    return oracledb.connect(user=user, password=password, dsn=dsn)
