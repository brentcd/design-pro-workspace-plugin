#!/usr/bin/env python3
"""Fill the scheduled-task instruction templates for one person.

Usage: python3 fill_prompts.py config.json out_dir [--assets DIR]

Needs in config.json (besides the build_page.py keys):
  email, workspaceUrl, jtOrgName, jtMembershipId, pcFieldId,
  timeZone (IANA name such as America/Chicago; required, or org.timeZone),
  weatherPlace / weatherLat / weatherLon (required, or the same three keys in org),
  texts ("enabled" | "disabled"), exclusions (optional free text),
  org (the franchise's team settings: companyName, region, suppliers, vendors, engineers, utilities, jtFields)
Writes out_dir/<task>.txt for hub_sync, morning, midday, eod, texts_relay and updater, and out_dir/schedules.json.
Fails if any {{PLACEHOLDER}} is left, except HUB_SYNC_TASK_ID before that task exists
(fill_prompts can be re-run once it does).
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, '..', 'assets')
if '--assets' in sys.argv:
    i = sys.argv.index('--assets'); ASSETS = sys.argv[i + 1]; del sys.argv[i:i + 2]

OLD = ('This looks like a config saved by an older version. Look the value up (do not guess), '
       'add it to config.json and to the page\'s setup/config, then run this again.')
# the franchise-standard JobTread template; a franchise overrides these in org.jtFields
JT_DEFAULTS = {'pm': {'name': 'Project Consultant', 'ignore': ['No preference']},
               'flow': {'name': 'JOB FLOW (Kanban View)', 'active': ['✅ Approved, Planning', '⏳ Work In Progress', '🔜 Final 5%']},
               'newBuild': {'name': 'Remodel Type', 'value': 'New Home Construction'}, 'permits': None}


def stop(msg):
    sys.exit('fill_prompts: ' + msg)

def need(cfg, key, what):
    v = cfg.get(key)
    if v in (None, ''):
        stop('config is missing "%s" (%s). %s' % (key, what, OLD))
    return str(v)

def clean(v, limit=80):
    """Team settings are data that ends up inside instructions: one line, no braces, bounded length."""
    s = re.sub(r'[\x00-\x1f\x7f{}<>]+', ' ', str(v))
    return re.sub(r'\s+', ' ', s).strip()[:limit]

def names(lst, limit=40):
    out = []
    for x in lst or []:
        if isinstance(x, (list, tuple)):
            x = x[0] if x else ''
        elif isinstance(x, dict):
            x = x.get('name', '')
        x = clean(x)
        if x and x not in out:
            out.append(x)
    return out[:limit]

def time_zone(cfg, org):
    tz = cfg.get('timeZone') or org.get('timeZone')
    if not tz:
        stop('config is missing "timeZone" (the person\'s IANA time zone, for example America/Chicago; '
             'take it from their calendar or computer). ' + OLD)
    tz = str(tz).strip()
    if not re.fullmatch(r'[A-Za-z]+(?:/[A-Za-z0-9_+\-]+){1,2}', tz):
        stop('"timeZone" must be an IANA name such as America/Chicago, not "%s".' % tz[:40])
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(tz)
    except ImportError:
        pass
    except Exception:
        stop('"timeZone" is not a known IANA time zone: "%s".' % tz)
    return tz

def weather_vals(cfg, org):
    """Place, lat and lon are required and must come from the same place (the person's config, else the
    team settings), so a forecast is never fetched for one place and shown under another's name."""
    keys = ('weatherPlace', 'weatherLat', 'weatherLon')
    src = cfg if any(cfg.get(k) not in (None, '') for k in keys) else org
    missing = [k for k in keys if src.get(k) in (None, '')]
    if missing:
        stop('config is missing %s (the office\'s weather location: weatherPlace like "City, ST ZIP" plus '
             'weatherLat and weatherLon to 2 decimals, from the company address). %s' % (', '.join('"%s"' % k for k in missing), OLD))
    try:
        place, lat, lon = clean(src['weatherPlace']), float(src['weatherLat']), float(src['weatherLon'])
    except (TypeError, ValueError):
        stop('"weatherLat" and "weatherLon" must be numbers.')
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (abs(lat) < 0.01 and abs(lon) < 0.01):
        stop('"weatherLat"/"weatherLon" look wrong: %s, %s' % (lat, lon))
    return {'WEATHER_PLACE': place, 'WEATHER_LAT': '%.2f' % lat, 'WEATHER_LON': '%.2f' % lon}

def jt_fields(org):
    got = org.get('jtFields') if isinstance(org.get('jtFields'), dict) else {}
    out = {}
    for k, dflt in JT_DEFAULTS.items():
        v = got.get(k, dflt)
        out[k] = dict(dflt, **v) if isinstance(dflt, dict) and isinstance(v, dict) else v
    return out

def org_notes(org, jt):
    """A compact, one-paragraph text block of the team's settings for the scheduled runs."""
    parts = []
    region = clean(org.get('region') or '')
    if region:
        parts.append('Region: %s.' % region)
    sup, ven, eng = names(org.get('suppliers')), names(org.get('vendors')), names(org.get('engineers'))
    ven = [v for v in ven if v not in sup]
    if sup: parts.append('Suppliers: %s.' % ', '.join(sup))
    if ven: parts.append('Other vendors: %s.' % ', '.join(ven))
    if eng: parts.append('Engineers: %s.' % ', '.join(eng))
    ut = org.get('utilities') if isinstance(org.get('utilities'), dict) else {}
    u = ['%s: %s' % (kind, ', '.join(n)) for kind in ('electric', 'gas', 'water') for n in [names(ut.get(kind))] if n]
    if u: parts.append('Utilities: %s.' % '; '.join(u))
    areas = names(org.get('serviceAreas'))
    if areas: parts.append('Service areas: %s.' % ', '.join(areas))
    pm, flow, nb, permits = jt['pm'], jt['flow'], jt['newBuild'], jt.get('permits')
    f = ['project manager field "%s"' % clean(pm['name'])]
    ign = names(pm.get('ignore'))
    if ign: f[-1] += ' (ignore the values: %s)' % ', '.join(ign)
    f.append('job stage field "%s" with active values: %s' % (clean(flow['name']), ', '.join(names(flow.get('active'))) or 'none listed'))
    if isinstance(nb, dict) and nb.get('name'):
        f.append('new builds are jobs whose "%s" is "%s"' % (clean(nb['name']), clean(nb.get('value', ''))))
    if permits:
        p = names(permits.values() if isinstance(permits, dict) else permits)
        if p: f.append('permit fields: %s' % ', '.join(p))
    parts.append('JobTread fields: %s.' % '; '.join(f))
    return ' '.join(parts)

def main(cfg_path, out_dir):
    cfg = json.load(open(cfg_path))
    kit = json.load(open(os.path.join(ASSETS, 'prompts.json')))
    if not isinstance(cfg, dict):
        stop('config.json must be one JSON object.')
    if not isinstance(cfg.get('org'), dict) or not cfg['org']:
        sys.exit('config is missing "org" (the team settings for this company). Build it as SKILL.md section D says, save it in the config and run this again.')
    org = cfg['org']
    role = need(cfg, 'role', 'owner, pm or ops')
    if role not in ('owner', 'pm', 'ops'):
        stop('"role" must be owner, pm or ops.')
    jt = jt_fields(org)
    tz = time_zone(cfg, org)
    vals = {'NAME': need(cfg, 'name', 'their name as JobTread spells it'), 'FIRST': need(cfg, 'first', 'first name'),
            'EMAIL': need(cfg, 'email', 'their Gmail address'),
            'WORKSPACE_URL': need(cfg, 'workspaceUrl', 'the link of their published page'),
            'JT_ORG_ID': need(cfg, 'jtOrg', 'JobTread organization id'), 'JT_ORG_NAME': need(cfg, 'jtOrgName', 'JobTread organization name'),
            'JT_MEMBERSHIP_ID': need(cfg, 'jtMembershipId', 'their JobTread membership id'),
            'PC_FIELD_ID': need(cfg, 'pcFieldId', 'id of the JobTread job field that names the project manager'),
            'DRIVE_FOLDER_ID': need(cfg, 'driveFolder', 'Google Drive folder id'), 'TEXTS_ENABLED': cfg.get('texts') or 'disabled',
            'HUB_SYNC_TASK_ID': cfg.get('hubSyncTask') or '{{HUB_SYNC_TASK_ID}}',
            'TIME_ZONE': tz, 'COMPANY_NAME': clean(org.get('companyName') or 'Design Pro Remodeling'),
            'PM_FIELD_NAME': clean(jt['pm']['name']), 'FLOW_FIELD_NAME': clean(jt['flow']['name']),
            'FLOW_ACTIVE': ', '.join('"%s"' % n for n in names(jt['flow'].get('active'))) or '(none listed)',
            'ORG_NOTES': org_notes(org, jt), 'KIT_URL': kit.get('kitUrl') or '',
            **weather_vals(cfg, org)}
    sr = kit['scope_rules']
    scope = ' '.join([sr['_header'], sr['owner'], sr['pm'], sr['ops']]).replace('{{ROLE}}', role)
    if (cfg.get('exclusions') or '').strip():
        scope += ' Also leave out entirely (jobs, emails, meetings, calendar events, texts): ' + clean(cfg['exclusions'], 400)
    def fill(s):
        s = s.replace('{{SCOPE_RULES}}', scope)
        for k, v in vals.items():
            s = s.replace('{{%s}}' % k, v)
        return s
    os.makedirs(out_dir, exist_ok=True)
    left = {}
    for name, tpl in kit['prompts'].items():
        s = fill(tpl)
        rest = set(re.findall(r'\{\{[A-Z_]+\}\}', s))
        if rest:
            left[name] = sorted(rest)
        open(os.path.join(out_dir, name + '.txt'), 'w', encoding='utf-8').write(s)
    json.dump(kit['schedules'], open(os.path.join(out_dir, 'schedules.json'), 'w'), indent=1)
    print('wrote', ', '.join(n + '.txt' for n in kit['prompts']))
    if left:
        print('STILL UNFILLED:', json.dumps(left))
        if any(x != '{{HUB_SYNC_TASK_ID}}' for v in left.values() for x in v):
            sys.exit(1)

if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
