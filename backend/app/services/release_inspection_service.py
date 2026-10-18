"""Owner-scoped inspection and short-lived confirmation for manual releases."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time

from jose import jwt, JWTError
from kubernetes.stream import stream
from app.core.config import settings
from app.core.exceptions import ResourceConflictError
from app.core.workspace import persistent_path
from app.infrastructure.kubernetes.client import create_clients
from app.infrastructure.kubernetes.gateway import KubernetesGateway
from app.models import AllocationStatus, Image
from app.services.access_service import AccessService
from app.services.job_service import JobService


class ReleaseInspectionService:
    @staticmethod
    def inspect_runtime(allocation):
        empty = dict(pod_uid=None, processes_checked=False, processes=[], notebooks_checked=False,
                     notebooks=[], tmux_checked=False, tmux_sessions=[])
        if not settings.INSTANCE_SAFETY_ENABLED:
            return empty
        core = network = None
        try:
            core, network = create_clients()
            namespace = AccessService.allocation_options(allocation).get('namespace', settings.K8S_NAMESPACE)
            pod = core.read_namespaced_pod(allocation.pod_name, namespace, _request_timeout=settings.K8S_REQUEST_TIMEOUT_SECONDS)
            KubernetesGateway._check_owner(pod, allocation.id, allocation.user_id)
            empty['pod_uid'] = pod.metadata.uid
            code = Path(__file__).resolve().parents[1].joinpath('assets/inspect_processes.py').read_text()
            channel = stream(core.connect_get_namespaced_pod_exec, allocation.pod_name, namespace,
                            command=['python', '-I', '-c', code], stderr=True, stdin=False, stdout=True,
                            tty=False, _request_timeout=10, _preload_content=False)
            output = ''
            deadline = time.monotonic()+12
            try:
                while channel.is_open():
                    if time.monotonic() > deadline:
                        raise TimeoutError('Inspection deadline exceeded')
                    channel.update(timeout=1)
                    output += channel.read_stdout(timeout=0) + channel.read_stderr(timeout=0)
                    if len(output) > 1024*1024:
                        raise ValueError('Inspection output exceeded limit')
                if channel.returncode not in (None, 0):
                    raise ValueError('Inspection process failed')
            finally:
                channel.close()
            line = next(s[len('INSTANCE_INSPECTION='):] for s in output.splitlines() if s.startswith('INSTANCE_INSPECTION='))
            data = json.loads(line)
            for key in ('processes', 'notebooks', 'tmux_sessions'):
                if not isinstance(data[key], list) or len(data[key]) > 200:
                    raise ValueError('Invalid runtime inspection')
            for key in ('processes_checked', 'notebooks_checked', 'tmux_checked'):
                if not isinstance(data[key], bool):
                    raise ValueError('Invalid inspection state')
            # Keep only fixed fields; raw command arguments, environment and credentials are never exposed.
            processes = [dict(pid=int(p['pid']), start_ticks=int(p['start_ticks']), name=str(p['name'])[:120],
                              category=p['category'] if p['category'] in ('program', 'notebook', 'terminal') else 'program',
                              elapsed_seconds=max(0, int(p['elapsed_seconds']))) for p in data['processes']]
            notebooks = [dict(id=str(k['id'])[:120], name=str(k['name'])[:120], state=str(k['state'])[:30],
                              connections=max(0, int(k['connections']))) for k in data['notebooks']]
            sessions = [dict(name=str(t['name'])[:120], windows=max(0, int(t['windows'])), attached=max(0, int(t['attached']))) for t in data['tmux_sessions']]
            return dict(empty, processes=processes, notebooks=notebooks, tmux_sessions=sessions,
                        **{k:data[k] for k in ('processes_checked', 'notebooks_checked', 'tmux_checked')})
        except Exception:
            return empty
        finally:
            if core:
                core.api_client.close()
            if network and network.api_client is not core.api_client:
                network.api_client.close()

    @staticmethod
    def collect(db, allocation):
        try:
            jobs = [j for j in JobService.list(db, allocation.user_id)
                    if j['container_id'] == allocation.container_id and j['status'] in ('pending', 'running')]
            jobs_checked = True
        except (OSError, ValueError, ResourceConflictError):
            jobs, jobs_checked = [], False
        runtime = ReleaseInspectionService.inspect_runtime(allocation) if allocation.status in (
            AllocationStatus.ACTIVE, AllocationStatus.APPROVED) else dict(pod_uid=None,
            processes_checked=True, processes=[], notebooks_checked=True, notebooks=[], tmux_checked=True, tmux_sessions=[])
        result = dict(runtime, jobs_checked=jobs_checked,
                      active_jobs=[dict(name=j['name'], job_id=j['job_id']) for j in jobs],
                      saving_image=bool(db.query(Image.id).filter_by(source_container_id=allocation.container_id, snapshot_status='saving').first()),
                      persistent_path=persistent_path(AccessService.allocation_options(allocation)),
                      checked_at=datetime.now(timezone.utc).isoformat(),
                      message='检查平台任务、实例内可见进程、SSH/tmux 会话和 Notebook 内核。释放会终止所有程序，请先保存成果。')
        result['checks_complete'] = all(result[k] for k in ('jobs_checked', 'processes_checked', 'notebooks_checked', 'tmux_checked'))
        return result

    @staticmethod
    def digest(check):
        identities = dict(pod_uid=check['pod_uid'], jobs_checked=check['jobs_checked'],
                          processes_checked=check['processes_checked'], notebooks_checked=check['notebooks_checked'],
                          tmux_checked=check['tmux_checked'], saving_image=check['saving_image'],
                          jobs=sorted(j['job_id'] for j in check['active_jobs']),
                          processes=sorted((p['pid'], p['start_ticks'], p['name'], p['category']) for p in check['processes']),
                          notebooks=sorted((k['id'], k['state']) for k in check['notebooks']),
                          sessions=sorted((s['name'], s['windows']) for s in check['tmux_sessions']))
        return hashlib.sha256(json.dumps(identities, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def prepare(db, allocation):
        check = ReleaseInspectionService.collect(db, allocation)
        check['confirmation_token'] = jwt.encode(dict(type='release-confirmation', sub=str(allocation.user_id),
            allocation_id=allocation.id, digest=ReleaseInspectionService.digest(check),
            exp=datetime.now(timezone.utc)+timedelta(minutes=5)), settings.SECRET_KEY, algorithm=settings.ALGORITHM) if settings.INSTANCE_SAFETY_ENABLED else None
        return check

    @staticmethod
    def validate(db, allocation, token, confirm_unchecked):
        if not settings.INSTANCE_SAFETY_ENABLED or allocation.status not in (AllocationStatus.ACTIVE, AllocationStatus.APPROVED):
            return
        try:
            claims = jwt.decode(token or '', settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            if claims.get('type') != 'release-confirmation' or claims.get('sub') != str(allocation.user_id) or claims.get('allocation_id') != allocation.id:
                raise ValueError('Wrong confirmation')
        except (JWTError, ValueError, TypeError):
            raise ResourceConflictError('请重新检查当前进程并确认释放；原检查可能已过期')
        check = ReleaseInspectionService.collect(db, allocation)
        if claims.get('digest') != ReleaseInspectionService.digest(check):
            raise ResourceConflictError('实例进程或任务状态已变化，请重新检查后确认释放')
        if not check['checks_complete'] and not confirm_unchecked:
            raise ResourceConflictError('部分运行状态未能确认，请重新检查，或明确确认仍要终止所有程序')
