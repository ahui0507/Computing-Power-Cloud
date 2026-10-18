"""Renew the site's IP leaf certificate without changing the client trust anchor."""
from datetime import datetime, timezone
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess

TLS = Path('/etc/cpcloud/tls')
CA = Path('/home/system/cpcloud-operations/https-20261017/ca')
STATE = Path('/home/system/cpcloud-operations/https-20261017/certificate-renewal.json')
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--force', action='store_true', help='Renew now and verify the deployment path')
args = parser.parse_args()

def run(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError(args[0] + ' failed: ' + result.stderr[-1200:])
    return result.stdout

with Path('/run/cpcloud-tls-renew.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    result = subprocess.run(['openssl', 'x509', '-checkend', str(45 * 86400), '-noout', '-in', str(TLS / 'server.pem')], capture_output=True)
    if result.returncode == 0 and not args.force:
        STATE.write_text(json.dumps({'checked_at': datetime.now(timezone.utc).isoformat(), 'renewed': False}))
    else:
        # Require the CA to remain valid beyond the new leaf's lifetime.
        run('openssl', 'x509', '-checkend', str(400 * 86400), '-noout', '-in', str(CA / 'root-ca.pem'))
        candidate = TLS / 'server.next.pem'
        previous = (TLS / 'server.pem').read_bytes()
        try:
            run('openssl', 'x509', '-req', '-sha256', '-days', '397', '-in', str(TLS / 'server.csr'), '-CA', str(CA / 'root-ca.pem'), '-CAkey', str(CA / 'root-ca.key'), '-CAserial', str(CA / 'root-ca.srl'), '-extfile', str(TLS / 'server-extensions.cnf'), '-out', str(candidate))
            run('openssl', 'verify', '-CAfile', str(CA / 'root-ca.pem'), '-verify_ip', '10.72.63.42', '-purpose', 'sslserver', str(candidate))
            os.replace(candidate, TLS / 'server.pem')
            run('nginx', '-t')
            run('systemctl', 'reload', 'nginx')
            STATE.write_text(json.dumps({'checked_at': datetime.now(timezone.utc).isoformat(), 'renewed': True, 'certificate': run('openssl', 'x509', '-in', str(TLS / 'server.pem'), '-noout', '-dates', '-serial')}))
        except BaseException:
            candidate.write_bytes(previous)
            os.replace(candidate, TLS / 'server.pem')
            run('nginx', '-t')
            run('systemctl', 'reload', 'nginx')
            raise
        finally:
            candidate.unlink(missing_ok=True)
