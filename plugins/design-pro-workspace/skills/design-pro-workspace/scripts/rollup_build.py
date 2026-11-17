#!/usr/bin/env python3
"""Team roll-up helper for the Design Pro Workspace's end-of-day scheduled update (plugin file; never fetched from the Kit).

  python3 -I rollup_build.py build DIR TODAY
      DIR holds what the run saved with ArtifactData (review/today.json, sitesched/current.json, rollup/contacts.json,
      hub_jobs/*.json). Writes DIR/rollup_rows.json (rows of 13 strings) and prints "ROWS <n> HASH <h> BYTES <b>".
      Exits 2 with "ERROR ..." when review/today or the hub jobs are missing.

  python3 -I rollup_build.py readers --master FILE --perms FILE --owner EMAIL --me EMAIL --domains "a.com,b.com"
                                     [--state FILE] [--team FILE] [--max 3]
      Decides, from data alone, whom this person's own roll-up sheet may be shared with. Prints one JSON object:
      {"trusted": bool, "why": "...", "notes": "on"|"off", "share": [<at most --max emails>], "check": [<emails whose
       JobTread role still has to be looked up>], "keep": [...], "drop": [...], "skipped": [{"email", "why"}]}.
      Index rows follow app/parts/21-team.js: ["reader", email, name, signedBy, at, "active"|"removed"] and
      ["removed", email, name, signedBy, at]; for each email the last row signed by the sheet's owner wins.
      A reader is used only when ALL of these hold:
        - the team sheet (master) is owned by an address on one of the company's email domains, and nobody else can
          edit it (so every row in it was written by its owner; a sheet others can edit is trusted for nothing);
        - its last owner-signed row says active (a "removed" row, or status "removed", takes it away);
        - the reader's address is on one of the company's email domains and is not this person's own;
        - the reader was never dropped before (state "removed"): a removed reader is not shared again automatically;
        - JobTread (--team: the organization's memberships for those addresses) shows an active membership whose role
          is Owner, Admin or Operations.
      Readers already shared with that no longer pass are listed in "drop" (Drive can't unshare from here: the run
      tells the person to remove them by hand).
"""
import datetime as dt
import glob
import hashlib
import json
import math
import os
import re
import sys

# ---------------------------------------------------------------- build

def S(v, n=90):
    """One short line for a spreadsheet cell. Leading = + - @ (and tabs or line breaks) are stripped so a cell can
    never be read as a formula."""
    s = re.sub(r'\s+', ' ', str(v if v is not None else '')).strip()
    s = s.lstrip("=+-@'\t\r ").strip()
    return s[:n]


def num(v):
    m = re.fullmatch(r'(?:job\s*#?\s*)?(\d{3,6})', str(v or '').strip(), re.I)
    return m.group(1) if m else ''


def L(v):
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def Dd(v):
    return v if isinstance(v, dict) else dict()


def N(v):
    try:
        return round(float(str(v).replace(',', '').replace('$', '')))
    except Exception:
        return 0


def build(D, today):
    TODAY = dt.date.fromisoformat(today)

    def J(p):
        try:
            x = json.load(open(os.path.join(D, p), encoding='utf-8'))
            return x if isinstance(x, dict) else None
        except Exception:
            return None

    def iso(v):
        v = str(v or '')
        if re.match(r'\d{4}-\d\d-\d\d', v):
            return v[:10]
        for f in ('%b %d %Y', '%B %d %Y'):
            try:
                d = dt.datetime.strptime(v.strip() + ' ' + str(TODAY.year), f).date()
                return (d.replace(year=d.year - 1) if d > TODAY + dt.timedelta(days=30) else d).isoformat()
            except Exception:
                pass
        return ''

    days = lambda n: (TODAY + dt.timedelta(days=n)).isoformat()
    jobs, rows, used = {}, [], set()

    def add(kind, n, date, title, detail='', who='', status='', src='', data=None):
        j = jobs.get(n)
        if not n or not j or not S(title) or (kind not in ('cost', 'ask') and not re.fullmatch(r'\d{4}-\d\d-\d\d', str(date or ''))):
            return
        used.add(n)
        rows.append([kind, n, '', '', '', str(date or ''), S(title), S(detail, 80), S(who, 50), S(status, 20), S(src, 10), '',
                     json.dumps(data, separators=(',', ':')) if data else ''])

    hubs = [h for h in (J(os.path.relpath(f, D)) for f in sorted(glob.glob(os.path.join(D, 'hub_jobs', '*.json')))) if h]
    rv = J('review/today.json')
    if not rv or not hubs:
        print('ROWS 0 HASH none ERROR missing review/today.json or hub_jobs files')
        return 2
    first = lambda h: num((L(h.get('jobs')) or [dict()])[0].get('number'))
    for h in hubs:
        for j in L(h.get('jobs')):
            if num(j.get('number')):
                jobs[num(j['number'])] = (S(h.get('customer'), 60), S(h.get('address'), 80), S(j.get('id'), 40))
    slug = dict((str(h.get('slug')), first(h)) for h in hubs)
    for e in L(Dd(J('sitesched/current.json')).get('entries')):
        n = num(e.get('jobNumber')) or slug.get(str(e.get('job')), '')
        d0 = iso(e.get('date'))
        if days(0) <= d0 <= days(13):
            who = ' '.join(x for x in [S(e.get('who'), 40), ('(' + S(e.get('company'), 40) + ')') if e.get('company') and e.get('company') != e.get('who') else ''] if x)
            add('site', n, d0, e.get('what'), e.get('time'), who, e.get('status'), e.get('src'))
    for c in L(rv.get('cards')):
        n = num(c.get('job'))
        for i in L(c.get('items')):
            if i.get('kind') in ('email', 'text') and i.get('who'):
                add('ask', n, iso(i.get('date')), i.get('text'), '', i.get('who'), 'urgent' if i.get('urgent') else '', i.get('kind'))
    for x in L(Dd(J('rollup/contacts.json')).get('entries')):
        if iso(x.get('date')) >= days(-45):
            add('contact', num(x.get('job')), iso(x.get('date')), x.get('title'), x.get('detail'), x.get('who'), '', x.get('src'))
    for h in hubs:
        n = first(h)
        m = Dd(Dd(h.get('costing')).get('margin'))
        if N(m.get('approvedPrice')):
            p = m.get('forecastMarginPct', m.get('budgetMarginPct'))
            add('cost', n, '', 'Job costing', data=dict(approved=N(m.get('approvedPrice')), spent=N(m.get('currentSpend')), left=N(m.get('remainingBudget')),
                                                     marginPct=round(float(p), 1) if isinstance(p, (int, float)) and not isinstance(p, bool) and math.isfinite(p) else None,
                                                     goodPct=N(m.get('goodPct')) or 30))
        o = [x for x in L(h.get('orders')) if str(x.get('status')).lower() in ('requested', 'quoted', 'approved', 'ordered', 'backordered') and iso(x.get('date')) >= days(-30)]
        for x in sorted(o, key=lambda x: str(x.get('date')), reverse=True)[:2]:
            add('order', n, iso(x.get('date')), ': '.join(t for t in [S(x.get('vendor'), 40), S(x.get('items'), 70)] if t), x.get('note'), '', x.get('status'), x.get('source'))
        s = [x for x in L(h.get('selections')) if str(x.get('status')).lower() in ('pending', 'proposed', 'needs decision') and iso(x.get('date')) >= days(-45)]
        for x in sorted(s, key=lambda x: str(x.get('date')), reverse=True)[:3]:
            add('selection', n, iso(x.get('date')), ' '.join(t for t in [S(x.get('area'), 30), S(x.get('item'), 60)] if t), x.get('choice'), '', x.get('status'), x.get('source'))
    order = dict(site=0, ask=1, contact=2, cost=3, order=4, selection=5)
    rows.sort(key=lambda r: (order[r[0]], r[5]))
    rows = rows[:100]
    rows = [['job', n, jobs[n][2], jobs[n][0], jobs[n][1], '', '', '', '', '', '', '', ''] for n in sorted(used) if any(r[1] == n for r in rows)] + rows
    h = hashlib.sha1(json.dumps(rows).encode()).hexdigest()[:12]
    out = os.path.join(D, 'rollup_rows.json')
    json.dump(rows, open(out, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('ROWS', len(rows), 'HASH', h, 'BYTES', os.path.getsize(out))
    return 0

# ---------------------------------------------------------------- readers

EMAIL = re.compile(r'[a-z0-9._%+\-]{1,64}@([a-z0-9.\-]{1,190}\.[a-z]{2,24})')
EDIT_ROLES = ('writer', 'fileorganizer', 'organizer', 'owner')
READER_ROLE = re.compile(r'owner|admin|operat', re.I)


def load(path):
    if not path:
        return None
    try:
        return json.load(open(path, encoding='utf-8'))
    except Exception:
        return None


def rows_of(x):
    """get_values answers come in a few shapes: a list of rows, {values}, {valueRange: {values}}, {content: {values}}."""
    if isinstance(x, dict):
        for k in ('values', 'valueRange', 'content', 'result'):
            if k in x:
                return rows_of(x[k])
        return []
    return [r for r in x if isinstance(r, list)] if isinstance(x, list) else []


def perms_of(x):
    if isinstance(x, dict):
        for k in ('permissions', 'items', 'result', 'content'):
            if k in x:
                return perms_of(x[k])
        return []
    return [p for p in x if isinstance(p, dict)] if isinstance(x, list) else []


def addr(v):
    v = str(v or '').strip().lower()
    m = EMAIL.fullmatch(v)
    return (v, m.group(1)) if m else ('', '')


def team_of(x):
    """JobTread memberships ({organization: {memberships: {nodes: [...]}}}, or just the nodes): email -> role name."""
    if isinstance(x, dict):
        if isinstance(x.get('nodes'), list):
            x = x['nodes']
        else:
            for k in ('organization', 'memberships', 'result', 'data'):
                if k in x:
                    return team_of(x[k])
            return None
    if not isinstance(x, list):
        return None
    out = {}
    for n in x:
        if not isinstance(n, dict):
            continue
        u = n.get('user') if isinstance(n.get('user'), dict) else {}
        e, _ = addr(u.get('emailAddress') or u.get('email') or n.get('email'))
        role = n.get('role')
        role = role.get('name') if isinstance(role, dict) else role
        if e and n.get('isActive', True) is not False:
            out[e] = str(role or '')
    return out


def readers(a):
    domains = sorted({d.strip().lower().lstrip('@') for d in str(a.get('domains') or '').split(',') if d.strip()})
    me, _ = addr(a.get('me'))
    owner, odom = addr(a.get('owner'))
    state = load(a.get('state'))
    state = state if isinstance(state, dict) else {}
    shared = {addr(x)[0] for x in (state.get('sharedWith') or []) if addr(x)[0]}
    removed = {addr(x)[0] for x in (state.get('removed') or []) if addr(x)[0]}
    try:
        cap = max(0, min(3, int(a.get('max') or 3)))
    except ValueError:
        cap = 3
    res = {'trusted': False, 'why': '', 'notes': 'off', 'share': [], 'check': [], 'keep': [], 'drop': [], 'skipped': []}

    def done(why):
        res['why'] = why
        # nothing new is shared and nothing is marked removed: the sheet's existing sharing is left as it is
        return res

    if not domains:
        return done('the team settings list no email domains')
    if not owner or odom not in domains:
        return done("the team sheet's owner isn't on the company's email domain")
    perms = perms_of(load(a.get('perms')))
    if not perms:
        return done("the team sheet's sharing couldn't be read")
    for p in perms:
        role = str(p.get('role') or '').lower().replace('_', '')
        who, _ = addr(p.get('emailAddress') or p.get('email') or p.get('emailaddress'))
        kind = str(p.get('type') or 'user').lower()
        if role in EDIT_ROLES and (kind in ('anyone', 'domain', 'group') or who != owner):
            return done('someone besides its owner can edit the team sheet')
    res['trusted'] = True
    rows = rows_of(load(a.get('master')))
    # the index contract (app/parts/21-team.js): ["reader", email, name, signedBy, at, "active"|"removed"] and
    # ["removed", email, name, signedBy, at]; only rows signed by the sheet's owner count, and the last one per email wins
    last = {}
    for r in rows:
        t = str(r[0] if r else '').strip()
        if t == 'setting' and len(r) > 2 and str(r[1]).strip() == 'jobtreadNotes':
            res['notes'] = 'on' if str(r[2]).strip().lower() == 'on' else 'off'
        elif t in ('reader', 'removed') and len(r) > 1:
            e, d = addr(r[1])
            if not e:
                res['skipped'].append({'email': str(r[1])[:80], 'why': 'not an email address'})
                continue
            if addr(r[3] if len(r) > 3 else '')[0] != owner:
                res['skipped'].append({'email': e, 'why': "not signed by the team sheet's owner"})
                continue
            gone = t == 'removed' or str(r[5] if len(r) > 5 else '').strip().lower() == 'removed'
            last[e] = (d, gone)
    want = {}
    for e, (d, gone) in last.items():
        if e == me:
            continue
        if gone:
            res['skipped'].append({'email': e, 'why': 'removed by the owner'})
        elif d not in domains:
            res['skipped'].append({'email': e, 'why': "not on the company's email domain"})
        else:
            want[e] = True
    # a reader skipped above only for an older unsigned row is reported once, not once per row
    seen, out = set(), []
    for x in res['skipped']:
        k = (x['email'], x['why'])
        if k not in seen and not (x['why'] == "not signed by the team sheet's owner" and x['email'] in last):
            seen.add(k); out.append(x)
    res['skipped'] = out
    team = team_of(load(a.get('team'))) if a.get('team') else None
    for e in sorted(want):
        if e in removed:
            res['skipped'].append({'email': e, 'why': 'removed earlier; share by hand if this is right'})
            continue
        if team is None:
            if e not in shared:
                res['check'].append(e)
            else:
                res['keep'].append(e)
            continue
        role = team.get(e)
        if role is None or not READER_ROLE.search(role):
            res['skipped'].append({'email': e, 'why': 'JobTread role is not Owner, Admin or Operations' if role is not None else 'no active JobTread membership'})
            continue
        if e in shared:
            res['keep'].append(e)
        elif len(res['share']) < cap:
            res['share'].append(e)
        else:
            res['skipped'].append({'email': e, 'why': 'over the limit of %d new shares a run; next run' % cap})
    ok = set(res['keep']) | set(res['share']) | set(res['check'])
    res['drop'] = sorted(e for e in shared if e not in ok and not (team is None and e in want))
    if team is None:
        res['why'] = 'look up the JobTread roles of the addresses in "check", save them with --team and run this again' if res['check'] else 'ok'
    else:
        res['why'] = 'ok'
    return res


def main(argv):
    if len(argv) >= 1 and argv[0] == 'build' and len(argv) == 3:
        try:
            dt.date.fromisoformat(argv[2])
        except ValueError:
            print('ROWS 0 HASH none ERROR the date must look like 2026-11-17')
            return 2
        return build(argv[1], argv[2])
    if len(argv) >= 1 and argv[0] == 'readers':
        a, it = {}, iter(argv[1:])
        for k in it:
            if not k.startswith('--'):
                print(json.dumps({'trusted': False, 'why': 'unexpected argument %s' % k[:40], 'share': [], 'check': [], 'keep': [], 'drop': [], 'skipped': [], 'notes': 'off'}))
                return 2
            a[k[2:]] = next(it, '')
        print(json.dumps(readers(a)))
        return 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
