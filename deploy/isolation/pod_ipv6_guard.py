"""Deny Pod bridge IPv6 on this IPv4-only cluster; leave host interfaces intact."""
import argparse
import fcntl
import json
from pathlib import Path
import subprocess

CHAIN = "CPCLOUD-POD-IPV6"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--remove', action='store_true')
args = parser.parse_args()

def run(command, check=True):
    result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    if check and result.returncode:
        raise RuntimeError(command[0] + ' failed: ' + result.stderr[-1200:])
    return result

with Path('/run/cpcloud-pod-ipv6.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    if args.remove:
        for parent in ('INPUT', 'FORWARD'):
            while run(['ip6tables', '-w', '5', '-C', parent, '-i', 'cni0', '-j', CHAIN], check=False).returncode == 0:
                run(['ip6tables', '-w', '5', '-D', parent, '-i', 'cni0', '-j', CHAIN])
        if run(['ip6tables', '-w', '5', '-S', CHAIN], check=False).returncode == 0:
            run(['ip6tables', '-w', '5', '-F', CHAIN])
            run(['ip6tables', '-w', '5', '-X', CHAIN])
    else:
        run(['modprobe', 'br_netfilter'])
        run(['sysctl', '-w', 'net.bridge.bridge-nf-call-ip6tables=1'])
        if run(['ip6tables', '-w', '5', '-S', CHAIN], check=False).returncode:
            run(['ip6tables', '-w', '5', '-N', CHAIN])
        if run(['ip6tables', '-w', '5', '-C', CHAIN, '-j', 'DROP'], check=False).returncode:
            run(['ip6tables', '-w', '5', '-A', CHAIN, '-j', 'DROP'])
        for parent in ('INPUT', 'FORWARD'):
            if run(['ip6tables', '-w', '5', '-C', parent, '-i', 'cni0', '-j', CHAIN], check=False).returncode:
                run(['ip6tables', '-w', '5', '-I', parent, '1', '-i', 'cni0', '-j', CHAIN])
    print(json.dumps({'ipv6_pod_bridge_blocked': not args.remove, 'interface': 'cni0'}))
