"""Independent node watchdog. Uses only Python stdlib, systemd, HTTPS and restricted SSH."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import socket
import subprocess
import tempfile
import time
from urllib.request import build_opener,HTTPSHandler,ProxyHandler
from http.client import HTTPResponse
import uuid

TITLES={
 'platform-api':('平台接口异常','登录、实例管理或调度接口暂不可用。','critical'),
 'platform-entry':('平台 HTTPS 入口异常','平台的 HTTPS 入口检查失败，请核查入口服务。','critical'),
 'worker-progress':('资源处理进度异常','后台资源处理未按预期完成，请检查自动释放和排队进度。','critical'),
 'compute-unreachable':('计算节点监测中断','无法获取计算节点的新状态，请核查节点和网络。','critical'),
 'compute-services':('计算节点服务异常','计算节点的执行服务、监控或 GPU 启动检查异常。','critical'),
 'compute-gpu':('GPU 状态异常','GPU 查询或内核检查发现异常，请检查计算节点。','critical'),
 'compute-temperature':('GPU 温度过高','GPU 温度持续超过运行阈值。','warning'),
 'disk-control':('控制节点磁盘空间不足','控制节点可用空间持续低于设定阈值。','warning'),
 'disk-compute':('计算节点磁盘空间不足','计算节点临时磁盘空间持续不足，可能影响实例运行。','warning'),
 'monitor-control':('独立监测进度异常','独立监测入口没有提供有效的新状态。','critical'),
}


def atomic_json(path,data,mode=0o644):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,prefix='.next-',delete=False) as handle:
        temporary=Path(handle.name);json.dump(data,handle,ensure_ascii=False)
        handle.flush();os.fchmod(handle.fileno(),mode)
    try:temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)


def load_json(path,default):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError):return default


def command(arguments,timeout=8):
    result=subprocess.run(arguments,capture_output=True,text=True,timeout=timeout)
    if result.returncode:raise RuntimeError(arguments[0]+' returned '+str(result.returncode))
    return result.stdout


def update_incidents(state,checks,now,failures=3,recoveries=2):
    counters=state.setdefault('counters',{});events=state.setdefault('incidents',[])
    for code,check in checks.items():
        counter=counters.setdefault(code,{'bad':0,'good':0})
        active=next((e for e in reversed(events) if e['code']==code and e['active']),None)
        if check['ok']:
            counter['bad']=0;counter['good']+=1
            if active and counter['good']>=recoveries:active.update(active=False,resolved_at=now,last_seen=now)
            continue
        if counter['bad']==0:counter['first_bad']=now
        counter['bad']+=1;counter['good']=0
        title,message,severity=TITLES[code]
        severity=check.get('severity',severity)
        if active and severity=='critical' and active['severity']!='critical':
            active.update(active=False,resolved_at=now)
            active=None;counter['first_bad']=now
        if active:active['last_seen']=now
        elif counter['bad']>=failures:
            events.append({'id':uuid.uuid4().hex,'code':code,'title':title,'message':message,'severity':severity,
                           'active':True,'first_seen':counter['first_bad'],'last_seen':now,'resolved_at':None})
    state['incidents']=[e for e in events if e['active'] or now-e.get('resolved_at',now)<7*86400][-200:]
    state['updated_at']=now
    return state


def public_incidents(events):
    # Merge reports of the same overlapping outage from both observers.
    merged=[]
    for event in sorted(events,key=lambda e:e['first_seen']):
        end=event.get('resolved_at') or float('inf')
        previous=next((e for e in reversed(merged) if e['code']==event['code']
                       and (e.get('resolved_at') or float('inf'))>=event['first_seen']),None)
        if previous:
            previous['active']=previous['active'] or event['active']
            previous['last_seen']=max(previous['last_seen'],event['last_seen'])
            previous['resolved_at']=None if previous['active'] else max(previous['resolved_at'],end)
            if event['severity']=='critical':previous['severity']='critical'
        else:merged.append({k:event[k] for k in ('id','code','title','message','severity','active','first_seen','last_seen','resolved_at')})
    return merged[-200:]


def collect(config):
    checks={};peer_events=[];role=config['role'];now=time.time()
    def probe(code,operation,severity=None):
        try:
            ok,detail=operation();checks[code]={'ok':bool(ok),'detail':detail}
        except Exception as error:checks[code]={'ok':False,'detail':type(error).__name__}
        if severity:checks[code]['severity']=severity
    context=ssl.create_default_context(cafile=config['ca_file'])
    opener=build_opener(ProxyHandler({}),HTTPSHandler(context=context))
    def http(path):
        with opener.open(config['site_url'].rstrip('/')+path,timeout=5) as response:
            return json.load(response)
    probe('platform-api',lambda:(http('/api/health').get('status')=='healthy','internal API health check'))
    if role=='control':
        def tls_entry():
            # Local PROXY listener mirrors the trusted ingress path and validates the certificate.
            with socket.create_connection(('127.0.0.1',8443),timeout=5) as raw:
                raw.sendall(b'PROXY TCP4 10.240.0.1 127.0.0.1 12345 8443\r\n')
                with context.wrap_socket(raw,server_hostname=config['tls_server_name']) as channel:
                    channel.sendall(b'GET /ops-alerts/status.json HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
                    response=HTTPResponse(channel);response.begin()
                    data=json.loads(response.read(262144))
                    return response.status==200 and now-data.get('generated_at',0)<120,'local trusted TLS entry'
        probe('platform-entry',tls_entry)
        def progress():
            active=command(['systemctl','is-active','computing-platform-backend']).strip()=='active'
            marker=load_json(config['heartbeat_file'],{})
            completed=marker.get('last_completed_at')
            stamp=datetime.fromisoformat(completed.replace('Z','+00:00')).timestamp() if completed else 0
            return active and 0<=now-stamp<config.get('heartbeat_ttl',120) and marker.get('state')!='error' and marker.get('errors',0)==0, 'background heartbeat'
        probe('worker-progress',progress)
        def remote():
            output=command(['ssh','-F','/dev/null','-i',config['ssh_key'],'-o','BatchMode=yes',
                '-o','IdentitiesOnly=yes','-o','ConnectTimeout=4','-o','StrictHostKeyChecking=yes',
                '-o','UserKnownHostsFile='+config['known_hosts'],config['compute_target'],'status'],timeout=8)
            peer=json.loads(output)
            if now-peer.get('updated_at',0)>120:raise RuntimeError('Remote status stale')
            peer_events.extend(peer.get('incidents',[]))
            return True,'restricted SSH status'
        probe('compute-unreachable',remote)
    else:
        def monitor():
            value=http('/ops-alerts/status.json')
            return now-value.get('generated_at',0)<120,'independent control status'
        probe('monitor-control',monitor)
        services=['k3s-agent','cpcloud-gpu-domains','platform-monitor-agent','platform-worker-agent','cpcloud-pod-ipv6-guard']
        probe('compute-services',lambda:(all(command(['systemctl','is-active',s]).strip()=='active' for s in services),'node services'))
        def gpu():
            lines=command(['nvidia-smi','--query-gpu=index,temperature.gpu','--format=csv,noheader,nounits'],timeout=12).strip().splitlines()
            config_gpu=load_json('/etc/cpcloud/gpu-domains.json',{}).get('gpus',[])
            healthy=len(lines)==len(config_gpu)==8
            healthy=healthy and all((Path('/sys/bus/pci/devices')/r['pci']/'iommu_group/type').read_text().strip()=='identity' for r in config_gpu)
            checks['compute-temperature']={'ok':all(float(line.split(',')[1])<85 for line in lines),'detail':'GPU temperature'}
            errors=command(['journalctl','-k','-b','--since=-2min','-n','500','--no-pager'])
            healthy=healthy and not re.search(r'DMAR.*(?:fault|PTE)|NVRM: Xid|AER:.*(?:error|fatal)',errors,re.I)
            return healthy,'GPU count, domains and recent kernel errors'
        probe('compute-gpu',gpu)
    disk_code='disk-'+role
    def disk():
        usages=[shutil.disk_usage(path) for path in config['local_disks']]
        maximum=max(100*(1-usage.free/usage.total) for usage in usages)
        return maximum<85,round(maximum,1)
    probe(disk_code,disk)
    if isinstance(checks[disk_code].get('detail'),(int,float)) and checks[disk_code]['detail']>=95:
        checks[disk_code]['severity']='critical'
    return checks,peer_events


def run_once(config):
    root=Path(config['state_directory']);state=load_json(root/'state.json',{})
    checks,peer_events=collect(config);state=update_incidents(state,checks,time.time(),config.get('confirm_failures',3))
    if config['role']=='control' and checks['compute-unreachable']['ok']:
        # Compute owns its diagnostics. Preserve its last records when SSH is down.
        state['peer_incidents']=[e for e in peer_events if e['code']!='platform-api']
    state['checks']=checks;state['role']=config['role']
    atomic_json(root/'state.json',state,0o600)
    atomic_json(root/'status.json',state)
    if config['role']=='control':
        public={'generated_at':state['updated_at'],'incidents':public_incidents(state['incidents']+state.get('peer_incidents',[]))}
        atomic_json(root/'public/status.json',public)
    print(json.dumps({'role':config['role'],'failed_checks':[k for k,v in checks.items() if not v['ok']],
                      'active_incidents':sum(e['active'] for e in state['incidents'])}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['check','status'])
    parser.add_argument('--config',type=Path,default=Path('/etc/cpcloud-watchdog/config.json'));args=parser.parse_args()
    if args.action=='status':print(Path('/var/lib/cpcloud-watchdog/status.json').read_text())
    else:
        import fcntl
        with Path('/run/cpcloud-watchdog/check.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            run_once(json.loads(args.config.read_text()))
