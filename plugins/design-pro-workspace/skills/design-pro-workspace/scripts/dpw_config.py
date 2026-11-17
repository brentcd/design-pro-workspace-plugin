"""Shared checks for config.json, used by build_page.py and fill_prompts.py before either writes anything.

A config is data saved on the person's page (setup/config) and copied from a team settings file in Drive, so every
value is checked for its type and shape here, and a problem stops the script with one plain sentence naming the key.
"""
import re, sys

SERVER_KEYS = ('gmail', 'granola', 'calendar', 'jobtread', 'ccr', 'drive', 'sheets')
DEFAULT_SERVERS = {'gmail': 'Gmail', 'granola': 'Granola', 'calendar': 'Google Calendar',
                   'jobtread': 'JobTread', 'ccr': 'Claude Code Remote', 'drive': 'Google Drive',
                   'sheets': 'Google Sheets'}
SERVER_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9 _.\-]{0,59}')
ID = re.compile(r'[A-Za-z0-9_\-]{1,120}')
# a person's name or a company name: one line, no quotes, braces, angle brackets or backslashes
PLAIN = re.compile(r'[^\x00-\x1f\x7f"<>{}\\]{1,80}')
EMAIL = re.compile(r'[^@\s"<>{}\\]{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,24}')


class ConfigError(Exception):
    pass


def bad(msg):
    raise ConfigError(msg)


def text(cfg, key, what, pattern=PLAIN, required=True):
    v = cfg.get(key)
    if v in (None, ''):
        if required:
            bad('config is missing "%s" (%s).' % (key, what))
        return ''
    if not isinstance(v, str):
        bad('"%s" must be text (%s), not %s.' % (key, what, type(v).__name__))
    v = v.strip()
    if not pattern.fullmatch(v):
        bad('"%s" has characters it can\'t contain (quotes, brackets, backslashes or line breaks) or is too long: %s' % (key, what))
    return v


def servers(cfg):
    s = cfg.get('servers')
    if s in (None, ''):
        return dict(DEFAULT_SERVERS)
    if not isinstance(s, dict):
        bad('"servers" must be an object like {"gmail": "Gmail", ...}.')
    out = dict(DEFAULT_SERVERS)
    for k, v in s.items():
        if k not in SERVER_KEYS:
            bad('"servers" has an unknown key "%s" (known: %s).' % (str(k)[:30], ', '.join(SERVER_KEYS)))
        if v in (None, ''):
            continue
        if not isinstance(v, str) or not SERVER_NAME.fullmatch(v.strip()):
            bad('"servers.%s" must be a connector name made of letters, digits, spaces, dots, dashes or underscores.' % k)
        out[k] = v.strip()
    return out


def pairs(cfg, key):
    v = cfg.get(key)
    if v in (None, ''):
        return []
    if not isinstance(v, list) or not all(isinstance(x, (list, tuple)) and len(x) >= 2 and all(isinstance(y, str) for y in x[:2]) for x in v):
        bad('"%s" must be a list of [name, membershipId] pairs.' % key)
    return [[x[0], x[1]] for x in v]


def strings(cfg, key):
    v = cfg.get(key)
    if v in (None, ''):
        return []
    if isinstance(v, str):
        return [v]
    if not isinstance(v, list) or not all(isinstance(x, (str, int)) for x in v):
        bad('"%s" must be a list of words or numbers.' % key)
    return [str(x) for x in v]


def check(cfg, for_prompts=False):
    """Checks everything both scripts read. Returns a dict of cleaned values; raises ConfigError."""
    if not isinstance(cfg, dict):
        bad('config.json must be one JSON object, not %s.' % type(cfg).__name__)
    out = {'name': text(cfg, 'name', 'their name as JobTread spells it'),
           'first': text(cfg, 'first', 'first name'),
           'jtOrg': text(cfg, 'jtOrg', 'JobTread organization id', ID),
           'driveFolder': text(cfg, 'driveFolder', 'Google Drive folder id', ID)}
    role = cfg.get('role')
    if role in (None, ''):
        bad('config is missing "role" (owner, pm or ops).')
    if role not in ('owner', 'pm', 'ops'):
        bad('"role" must be owner, pm or ops.')
    out['role'] = role
    out['servers'] = servers(cfg)
    out['team'], out['office'] = pairs(cfg, 'team'), pairs(cfg, 'office')
    out['excludeJobs'] = strings(cfg, 'excludeJobs')
    out['feedbackAdmins'] = strings(cfg, 'feedbackAdmins')
    t = cfg.get('texts')
    if t not in (None, '', 'enabled', 'disabled'):
        bad('"texts" must be "enabled" or "disabled".')
    out['texts'] = t or 'disabled'
    for k in ('tasks',):
        v = cfg.get(k)
        if v not in (None, '') and (not isinstance(v, dict) or not all(isinstance(x, str) or x is None for x in v.values())):
            bad('"%s" must be an object of scheduled task ids.' % k)
    for k in ('middayTask', 'hubSyncTask', 'budgetTask'):
        v = cfg.get(k)
        if v not in (None, '') and (not isinstance(v, str) or not ID.fullmatch(v)):
            bad('"%s" must be a scheduled task id.' % k)
    org = cfg.get('org')
    if org not in (None, '') and not isinstance(org, dict):
        bad('"org" (the team settings) must be one JSON object.')
    out['org'] = org or {}
    for k in ('kitVersion', 'holdVersion'):
        v = cfg.get(k)
        if v not in (None, '') and not (isinstance(v, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}[a-z]', v)):
            bad('"%s" must look like 2026-11-11a.' % k)
    if for_prompts:
        if not out['org']:
            bad('config is missing "org" (the team settings for this company). Build it as SKILL.md section D says, save it in the config and run this again.')
        out['email'] = text(cfg, 'email', 'their Gmail address', EMAIL)
        out['jtOrgName'] = text(cfg, 'jtOrgName', 'JobTread organization name')
        out['jtMembershipId'] = text(cfg, 'jtMembershipId', 'their JobTread membership id', ID)
        out['pcFieldId'] = text(cfg, 'pcFieldId', 'id of the JobTread job field that names the project manager', ID)
        w = cfg.get('workspaceUrl')
        if w in (None, ''):
            bad('config is missing "workspaceUrl" (the link of their published page).')
        if not isinstance(w, str) or not re.fullmatch(r'https://claude\.ai/[A-Za-z0-9_\-/]{1,120}', w.strip()):
            bad('"workspaceUrl" must be the page\'s claude.ai/artifact/... link.')
        out['workspaceUrl'] = w.strip()
        jt = out['org'].get('jtFields')
        if jt not in (None, '') and not isinstance(jt, dict):
            bad('"org.jtFields" must be an object.')
        for k, v in (jt or {}).items():
            if k == 'permits':
                if v not in (None, '') and not isinstance(v, (dict, list, str)):
                    bad('"org.jtFields.permits" must be a list or object of field names.')
                continue
            if v is None:
                continue
            if isinstance(v, str):  # just the field's name
                continue
            if not isinstance(v, dict) or not isinstance(v.get('name', ''), str):
                bad('"org.jtFields.%s" must be an object like {"name": "..."}.' % k)
            for sub in ('ignore', 'active'):
                if sub in v and not isinstance(v[sub], (list, str, type(None))):
                    bad('"org.jtFields.%s.%s" must be a list of values.' % (k, sub))
            if 'value' in v and not isinstance(v['value'], (str, type(None))):
                bad('"org.jtFields.%s.value" must be text.' % k)
    return out


def run(fn, prefix):
    """Calls fn(); a ConfigError ends the script with one plain sentence (exit 1)."""
    try:
        return fn()
    except ConfigError as e:
        sys.exit('%s: %s' % (prefix, e))
