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
sys.path.insert(0, HERE)  # dpw_config.py sits next to this script (python3 -I leaves the script's folder off the path)
import dpw_config  # noqa: E402

ASSETS = os.path.join(HERE, '..', 'assets')
if '--assets' in sys.argv:
    i = sys.argv.index('--assets')
    if i + 1 >= len(sys.argv):
        sys.exit('build_page: --assets needs a folder')
    ASSETS = sys.argv[i + 1]; del sys.argv[i:i + 2]


def caps_id(caps_text):
    """The capabilities id: a hash of the FILLED capabilities (connector names included), so renaming a connector
    counts as a permissions change too. The updater compares the id build_page.py prints with config.capsId."""
    return hashlib.sha256(json.dumps(json.loads(caps_text), sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:12]


def main(cfg_path, page_out, caps_out):
    try:
        cfg = json.load(open(cfg_path, encoding='utf-8'))
    except (OSError, ValueError) as e:
        sys.exit('build_page: can\'t read %s as JSON (%s)' % (cfg_path, str(e)[:120]))
    # every input is checked before anything is written, so a bad value never leaves a half-built page behind
    v = dpw_config.run(lambda: dpw_config.check(cfg), 'build_page')
    servers = v['servers']
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
        page_cfg['promptsVersion'] = 0 if cfg.get('tasksCheck') is False else int(json.load(open(os.path.join(ASSETS, 'prompts.json'), encoding='utf-8')).get('version') or 0)
    except Exception:
        page_cfg['promptsVersion'] = 0
    if cfg.get('kitVersion'):  # only when set, so pages built without it stay byte-identical (tools/build.mjs mirrors this)
        page_cfg['kitVersion'] = str(cfg['kitVersion'])
    if cfg.get('channel') == 'beta':  # stable is the default and isn't written, for the same reason
        page_cfg['channel'] = 'beta'
    if cfg.get('holdVersion'):
        page_cfg['holdVersion'] = str(cfg['holdVersion'])
    try:
        page = open(os.path.join(ASSETS, 'workspace-template.html'), encoding='utf-8').read()
        caps = open(os.path.join(ASSETS, 'capabilities-template.json'), 'rb').read().decode('utf-8')
    except (OSError, UnicodeDecodeError) as e:
        sys.exit('build_page: can\'t read the template files in %s (%s)' % (ASSETS, str(e)[:120]))
    page, n = re.subn(r'/\*DP_CONFIG_START\*/.*?/\*DP_CONFIG_END\*/',
                      lambda m: json.dumps(page_cfg, ensure_ascii=False).replace('</', '<\\/'), page, count=1, flags=re.S)
    if n != 1:
        sys.exit('build_page: the page template has no config marker')
    for key, val in servers.items():
        # server names are plain words (checked above); escaped as a JSON string body all the same
        page = page.replace('@@SRV:%s@@' % key, json.dumps(val)[1:-1])
        caps = caps.replace('@@SRV:%s@@' % key, json.dumps(val)[1:-1])
    if '@@SRV:' in page or '@@SRV:' in caps:
        sys.exit('build_page: the templates name a connector this script doesn\'t know (an @@SRV: placeholder is left)')
    try:
        cid = caps_id(caps)
    except ValueError as e:
        sys.exit('build_page: the filled capabilities aren\'t valid JSON (%s)' % str(e)[:120])
    open(page_out, 'w', encoding='utf-8').write(page)
    open(caps_out, 'w', encoding='utf-8').write(caps)
    print('page: %s (%d KB)\ncapabilities: %s\ncapabilities id: %s' % (page_out, len(page) // 1024, caps_out, cid))

if __name__ == '__main__':
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
