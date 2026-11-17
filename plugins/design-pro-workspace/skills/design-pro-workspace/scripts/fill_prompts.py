#!/usr/bin/env python3
"""Fill the scheduled-task instruction templates for one person.

Usage: python3 fill_prompts.py config.json out_dir [--assets DIR]

Needs in config.json (besides the build_page.py keys):
  email, workspaceUrl, jtOrgName, jtMembershipId, pcFieldId,
  timeZone (IANA name such as America/Chicago; required, or org.timeZone),
  weatherPlace / weatherLat / weatherLon (required, or the same three keys in org),
  texts ("enabled" | "disabled"), exclusions (optional free text), servers.ccr (the scheduled-task tools' server name),
  org (the franchise's team settings: companyName, region, suppliers, vendors, engineers, utilities, jtFields,
  emailDomains, and statusSheet: the shared beta status sheet's id, or empty to share no status)
Every value is checked first (dpw_config.py); nothing is written when one is wrong.
Writes out_dir/<task>.txt for hub_sync, morning, midday, eod, light, texts_relay and updater, and out_dir/schedules.json.
Fails if any {{PLACEHOLDER}} is left, except HUB_SYNC_TASK_ID before that task exists
(fill_prompts can be re-run once it does).
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # dpw_config.py sits next to this script (python3 -I leaves the script's folder off the path)
import dpw_config  # noqa: E402

ASSETS = os.path.join(HERE, '..', 'assets')
if '--assets' in sys.argv:
    i = sys.argv.index('--assets')
    if i + 1 >= len(sys.argv):
        sys.exit('fill_prompts: --assets needs a folder')
    ASSETS = sys.argv[i + 1]; del sys.argv[i:i + 2]

OLD = ('This looks like a config saved by an older version. Look the value up (do not guess), '
       'add it to config.json and to the page\'s setup/config, then run this again.')
# the franchise-standard JobTread template; a franchise overrides these in org.jtFields
JT_DEFAULTS = {'pm': {'name': 'Project Consultant', 'ignore': ['No preference']},
               'flow': {'name': 'JOB FLOW (Kanban View)', 'active': ['✅ Approved, Planning', '⏳ Work In Progress', '🔜 Final 5%']},
               'newBuild': {'name': 'Remodel Type', 'value': 'New Home Construction'}, 'permits': None}


def stop(msg):
    sys.exit('fill_prompts: ' + msg)

def clean(v, limit=80):
    """Team settings are data that ends up inside instructions: one line, no braces, bounded length."""
    s = re.sub(r'[\x00-\x1f\x7f{}<>]+', ' ', str(v))
    return re.sub(r'\s+', ' ', s).strip()[:limit]

def names(lst, limit=40):
    """A list of names from team settings, whatever shape it was saved in (one name, a list, [name, email] pairs, a map)."""
    if isinstance(lst, (str, int, float)) and not isinstance(lst, bool):
        lst = [lst]
    elif isinstance(lst, dict):
        lst = list(lst.keys())
    elif not isinstance(lst, (list, tuple)):
        lst = []
    out = []
    for x in lst:
        if isinstance(x, (list, tuple)):
            x = x[0] if x else ''
        elif isinstance(x, dict):
            x = x.get('name', '')
        if not isinstance(x, (str, int, float)) or isinstance(x, bool):
            continue
        x = clean(x)
        if x and x not in out:
            out.append(x)
    return out[:limit]

def time_zone(cfg, org):
    tz = cfg.get('timeZone') or org.get('timeZone')
    if not tz:
        stop('config is missing "timeZone" (the person\'s IANA time zone, for example America/Chicago; '
             'take it from their calendar or computer). ' + OLD)
    if not isinstance(tz, str):
        stop('"timeZone" must be text, an IANA name such as America/Chicago.')
    tz = tz.strip()
    if tz != 'UTC' and not re.fullmatch(r'[A-Za-z]+(?:/[A-Za-z0-9_+\-]+){1,2}', tz):
        stop('"timeZone" must be an IANA name such as America/Chicago, not "%s".' % tz[:40])
    try:
        from zoneinfo import ZoneInfo, available_timezones
    except ImportError:  # Python before 3.9: the pattern above is all we can check
        return tz
    try:
        ZoneInfo(tz)
    except Exception:
        # a computer without a time zone database knows no zones at all: then the pattern above has to do
        try:
            known = available_timezones()
        except Exception:
            known = set()
        if known:
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
    if any(isinstance(src[k], bool) or not isinstance(src[k], (int, float, str)) for k in ('weatherLat', 'weatherLon')):
        stop('"weatherLat" and "weatherLon" must be numbers.')
    try:
        place, lat, lon = clean(src['weatherPlace']), float(src['weatherLat']), float(src['weatherLon'])
    except (TypeError, ValueError):
        stop('"weatherLat" and "weatherLon" must be numbers.')
    if lat != lat or lon != lon:  # NaN
        stop('"weatherLat" and "weatherLon" must be numbers.')
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (abs(lat) < 0.01 and abs(lon) < 0.01):
        stop('"weatherLat"/"weatherLon" look wrong: %s, %s' % (lat, lon))
    return {'WEATHER_PLACE': place, 'WEATHER_LAT': '%.2f' % lat, 'WEATHER_LON': '%.2f' % lon}

def jt_fields(org):
    got = org.get('jtFields') if isinstance(org.get('jtFields'), dict) else {}
    out = {}
    for k, dflt in JT_DEFAULTS.items():
        v = got.get(k, dflt)
        if isinstance(dflt, dict):
            if isinstance(v, str) and v.strip():
                v = {'name': v}  # just the field's name
            if not isinstance(v, dict):
                v = {'name': dflt['name'], 'value': ''} if k == 'newBuild' and v is None else dflt
            v = dict(dflt, **v)
            if not isinstance(v.get('name'), str) or not v['name'].strip():
                v['name'] = dflt['name']
        out[k] = v
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
    if isinstance(nb, dict) and nb.get('name') and nb.get('value'):
        f.append('new builds are jobs whose "%s" is "%s"' % (clean(nb['name']), clean(nb.get('value') or '')))
    if permits:
        p = names(list(permits.values()) if isinstance(permits, dict) else permits)
        if p: f.append('permit fields: %s' % ', '.join(p))
    parts.append('JobTread fields: %s.' % '; '.join(f))
    return ' '.join(parts)

def status_sheet(org):
    """The shared beta status sheet (and the updater's Sheets check) only when the team settings name one."""
    v = org.get('statusSheet')
    return v.strip() if isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9_\-]{20,100}', v.strip()) else ''

def email_domains(org):
    ds = [d.lower() for d in names(org.get('emailDomains'), 10) if re.fullmatch(r'[a-z0-9.\-]+\.[a-z]{2,24}', d.lower())]
    return ', '.join(ds) or '(none listed)'

def main(cfg_path, out_dir):
    try:
        cfg = json.load(open(cfg_path, encoding='utf-8'))
    except (OSError, ValueError) as e:
        stop('can\'t read %s as JSON (%s)' % (cfg_path, str(e)[:120]))
    try:
        kit = json.load(open(os.path.join(ASSETS, 'prompts.json'), encoding='utf-8'))
    except (OSError, ValueError) as e:
        stop('can\'t read prompts.json in %s (%s)' % (ASSETS, str(e)[:120]))
    # every value is checked before anything is written (the same checks build_page.py runs)
    try:
        v = dpw_config.check(cfg, for_prompts=True)
    except dpw_config.ConfigError as e:
        msg = str(e)
        stop(msg + (' ' + OLD if 'is missing' in msg else ''))
    org, role = v['org'], v['role']
    jt = jt_fields(org)
    tz = time_zone(cfg, org)
    vals = {'NAME': clean(v['name']), 'FIRST': clean(v['first']), 'EMAIL': clean(v['email'], 254),
            'WORKSPACE_URL': v['workspaceUrl'],
            'JT_ORG_ID': v['jtOrg'], 'JT_ORG_NAME': clean(v['jtOrgName']),
            'JT_MEMBERSHIP_ID': v['jtMembershipId'], 'PC_FIELD_ID': v['pcFieldId'],
            'DRIVE_FOLDER_ID': v['driveFolder'], 'TEXTS_ENABLED': v['texts'],
            'HUB_SYNC_TASK_ID': cfg.get('hubSyncTask') or '{{HUB_SYNC_TASK_ID}}',
            'CCR': v['servers']['ccr'], 'STATUS_SHEET': status_sheet(org), 'EMAIL_DOMAINS': email_domains(org),
            'TIME_ZONE': tz, 'COMPANY_NAME': clean(org.get('companyName') or 'Design Pro Remodeling'),
            'PM_FIELD_NAME': clean(jt['pm']['name']), 'FLOW_FIELD_NAME': clean(jt['flow']['name']),
            'FLOW_ACTIVE': ', '.join('"%s"' % n for n in names(jt['flow'].get('active'))) or '(none listed)',
            'ORG_NOTES': org_notes(org, jt), 'KIT_URL': kit.get('kitUrl') or '',
            **weather_vals(cfg, org)}
    sr = kit['scope_rules']
    scope = ' '.join([sr['_header'], sr['owner'], sr['pm'], sr['ops']]).replace('{{ROLE}}', role)
    excl = cfg.get('exclusions')
    if isinstance(excl, str) and excl.strip():
        scope += ' Also leave out entirely (jobs, emails, meetings, calendar events, texts): ' + clean(excl, 400)
    def fill(s):
        s = s.replace('{{SCOPE_RULES}}', scope)
        for k, val in vals.items():
            s = s.replace('{{%s}}' % k, val)
        return s
    filled, left = {}, {}
    for name, tpl in kit['prompts'].items():
        s = fill(tpl)
        rest = set(re.findall(r'\{\{[A-Z_]+\}\}', s))
        if rest:
            left[name] = sorted(rest)
        filled[name] = s
    if any(x != '{{HUB_SYNC_TASK_ID}}' for v2 in left.values() for x in v2):
        print('STILL UNFILLED:', json.dumps(left))
        stop('these instructions need values this script doesn\'t fill (the plugin may be older than the Kit); nothing was written.')
    os.makedirs(out_dir, exist_ok=True)
    for name, s in filled.items():
        open(os.path.join(out_dir, name + '.txt'), 'w', encoding='utf-8').write(s)
    json.dump(kit['schedules'], open(os.path.join(out_dir, 'schedules.json'), 'w'), indent=1)
    print('wrote', ', '.join(n + '.txt' for n in kit['prompts']))
    if left:
        print('STILL UNFILLED:', json.dumps(left))

if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
