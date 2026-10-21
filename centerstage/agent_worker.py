"""Agent-neutral JSON/stdin adapter loop. Never execute commands from video/source data."""
import json
import subprocess
import time

import httpx


def work(url, command, once=False, job_id=None):
    if not command: raise ValueError('请在 -- 后指定你自己的本地 Agent 适配命令')
    backoff={}
    with httpx.Client(base_url=url,timeout=15) as client:
        while True:
            try:
                response=client.get('/api/agent/requests');response.raise_for_status()
                tasks=response.json()['requests']
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                print(json.dumps({'status':'retry_later','error':type(exc).__name__}),flush=True)
                if once:return
                time.sleep(3)
                continue
            for task in tasks:
                if job_id and task['job_id']!=job_id:continue
                key=(task['job_id'],task['type'])
                if backoff.get(key,0)>time.monotonic():continue
                try:
                    context=client.get(f"/api/jobs/{task['job_id']}/agent-context");context.raise_for_status()
                    # The executable comes only from local CLI configuration.
                    # Untrusted filenames, captions and links are JSON input.
                    evidence=context.json()
                    request={'schema_version':1,'task':task,'context':evidence}
                    result=subprocess.run(command,input=json.dumps(request,ensure_ascii=False),text=True,
                                          capture_output=True,timeout=120,shell=False)
                    if result.returncode:raise ValueError(f'Agent adapter exited {result.returncode}')
                    output=json.loads(result.stdout)
                    if not isinstance(output, dict):raise ValueError('Adapter must return a JSON object')
                    if task['type'] not in ('source_roster', 'person_annotations'):
                        raise ValueError('Unsupported Agent task type')
                    endpoint='roster' if task['type']=='source_roster' else 'annotations'
                    if endpoint=='annotations' and 'review' in evidence:
                        # Bind the result to the input actually seen, not the later video progress.
                        output.update(mode='merge',base_revision=evidence['job'].get('annotation_revision',0),
                                      reviewed=evidence['review'])
                    saved=client.put(f"/api/jobs/{task['job_id']}/{endpoint}",json=output);saved.raise_for_status()
                    print(json.dumps({'job_id':task['job_id'],'type':task['type'],'status':'saved'}),flush=True)
                except (OSError,ValueError,httpx.HTTPError,subprocess.TimeoutExpired) as exc:
                    backoff[key]=time.monotonic()+60
                    # Do not echo subprocess output, which may contain credentials.
                    print(json.dumps({'job_id':task['job_id'],'type':task['type'],'status':'retry_later','error':type(exc).__name__}),flush=True)
            if once:return
            time.sleep(3)
