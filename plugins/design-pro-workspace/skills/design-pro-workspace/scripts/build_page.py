#!/usr/bin/env python3
"""Build a person's Design Pro Workspace page from the template.

Usage: python3 build_page.py config.json page.html capabilities.json [--assets DIR]
(--assets: use the newest template files fetched from the Design Pro Workspace Kit instead of the bundled ones)

config.json keys:
  name, first, role ("pm" | "owner" | "ops": the starting role; the person can change it in the page's Setup screen), email,
  jtOrg (JobTread organization id), team ([[name, membershipId], ...]),
  office ([[name, membershipId], ...]: who "Assign to office" in Job Lists gives JobTread to-dos to; may be empty),
  middayTask, hubSyncTask, budgetTask (scheduled task ids, "" until created),
  driveFolder (Google Drive folder id),
  excludeJobs (optional list of job numbers or address words to hide from the Operations views, e.g. ["1234", "lakeside"]),
  servers: {gmail, granola, calendar, jobtread, ccr, drive, sheets}  (exact connector names in this account),
  org (the franchise's team settings), texts, tasks, timeZone, autoUpdate, kitVersion (the version this page is built from)
Writes the page body to publish and the capabilities JSON to declare on publish, and prints the
"capabilities id" (save it as config.capsId; the daily updater only republishes when it is unchanged).
"""
import hashlib, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, '..', 'assets')
if '--assets' in sys.argv:
    i = sys.argv.index('--assets'); ASSETS = sys.argv[i + 1]; del sys.argv[i:i + 2]
DEFAULT_SERVERS = {'gmail': 'Gmail', 'granola': 'Granola', 'calendar': 'Google Calendar',
                   'jobtread': 'JobTread', 'ccr': 'Claude Code Remote', 'drive': 'Google Drive',
                   'sheets': 'Google Sheets'}

def main(cfg_path, page_out, caps_out):
    cfg = json.load(open(cfg_path))
    for k in ('name', 'first', 'role', 'jtOrg', 'driveFolder'):
        if not cfg.get(k):
            sys.exit('config is missing "%s"' % k)
    if cfg['role'] not in ('pm', 'owner', 'ops'):
        sys.exit('role must be "pm", "owner" or "ops"')
    servers = dict(DEFAULT_SERVERS, **(cfg.get('servers') or {}))
    page_cfg = {'name': cfg['name'], 'first': cfg['first'], 'role': cfg['role'],
                'middayTask': cfg.get('middayTask', ''), 'hubSyncTask': cfg.get('hubSyncTask', ''),
                'budgetTask': cfg.get('budgetTask', ''), 'driveFolder': cfg['driveFolder'],
                'jtOrg': cfg['jtOrg'], 'team': cfg.get('team') or [], 'office': cfg.get('office') or [],
                'exclude': cfg.get('excludeJobs') or [], 'feedbackAdmins': cfg.get('feedbackAdmins') or [],
                # org = this franchise's team settings (suppliers, domains, JobTread field names...), passed through as-is
                'org': cfg.get('org') or {}, 'texts': cfg.get('texts') or 'disabled', 'tasks': cfg.get('tasks') or {},
                'timeZone': cfg.get('timeZone') or '', 'autoUpdate': cfg.get('autoUpdate', True) is not False}

    # the prompts version these tasks should run; the page shows a notice when review/today was written by older ones
    try:
        page_cfg['promptsVersion'] = 0 if cfg.get('tasksCheck') is False else int(json.load(open(os.path.join(ASSETS, 'prompts.json'))).get('version') or 0)
    except Exception:
        page_cfg['promptsVersion'] = 0
    if cfg.get('kitVersion'):  # only when set, so pages built without it stay byte-identical (tools/build.mjs mirrors this)
        page_cfg['kitVersion'] = str(cfg['kitVersion'])
    if cfg.get('channel') == 'beta':  # stable is the default and isn't written, for the same reason
        page_cfg['channel'] = 'beta'
    if cfg.get('holdVersion'):
        page_cfg['holdVersion'] = str(cfg['holdVersion'])
    page = open(os.path.join(ASSETS, 'workspace-template.html')).read()
    page, n = re.subn(r'/\*DP_CONFIG_START\*/.*?/\*DP_CONFIG_END\*/',
                      lambda m: json.dumps(page_cfg, ensure_ascii=False).replace('</', '<\\/'), page, count=1, flags=re.S)
    assert n == 1, 'config marker not found'
    caps_raw = open(os.path.join(ASSETS, 'capabilities-template.json'), 'rb').read()
    caps = caps_raw.decode('utf-8')
    for key, val in servers.items():
        page = page.replace('@@SRV:%s@@' % key, val.replace('"', '\\"'))
        caps = caps.replace('@@SRV:%s@@' % key, val.replace('"', '\\"'))
    assert '@@SRV:' not in page and '@@SRV:' not in caps
    open(page_out, 'w').write(page)
    json.loads(caps)
    open(caps_out, 'w').write(caps)
    print('page: %s (%d KB)\ncapabilities: %s\ncapabilities id: %s' % (page_out, len(page) // 1024, caps_out, hashlib.sha256(caps_raw).hexdigest()[:12]))

if __name__ == '__main__':
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
