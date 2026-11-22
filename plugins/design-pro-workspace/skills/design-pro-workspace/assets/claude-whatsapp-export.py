#!/usr/bin/env python3
"""Read-only export of recent WhatsApp chats for the Design Pro Workspace (WhatsApp desktop app on a Mac).

The Mac texts helper ("Claude Texts Export", which has its own Full Disk Access) snapshots WhatsApp's ChatStorage.sqlite
and runs this script after the texts export. It adds the WhatsApp chats to the texts file, each marked "app": "whatsapp",
so the page and the scheduled updates read them exactly like texts. It never writes to WhatsApp's database.

Usage: python3 claude-whatsapp-export.py SNAPSHOT.sqlite [hours=48] [IANA time zone] --merge claude-texts.json > out.json
Without --merge it prints {"threads": [...]} with the WhatsApp chats alone.
Optional: claude-contacts-map.csv (handle,name,organization) next to this script labels senders by phone number.
On a problem it prints one plain sentence to stderr and exits 1 (the helper then keeps the texts file as it was)."""
import csv, json, os, re, sqlite3, sys, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
EPOCH = 978307200  # WhatsApp (Core Data) dates count seconds from 2001-01-01


def fail(msg):
    sys.stderr.write(msg.strip() + '\n'); sys.exit(1)


args = sys.argv[1:]
merge = None
if '--merge' in args:
    i = args.index('--merge')
    if i + 1 >= len(args): fail('--merge needs the texts file')
    merge = args[i + 1]; del args[i:i + 2]
args = [a for a in args if not a.startswith('--')]
if not args: fail('give the WhatsApp database snapshot to read')
SNAP = args[0]
try: HOURS = float(args[1]) if len(args) > 1 else 48
except ValueError: fail('hours must be a number')
TZ = None
if len(args) > 2 and args[2].strip():
    try:
        from zoneinfo import ZoneInfo
        TZ = ZoneInfo(args[2].strip())
    except Exception: fail('unknown time zone "%s"' % args[2][:40])
NOW = dt.datetime.now(dt.timezone.utc)


def stamp(ts):
    d = dt.datetime.fromtimestamp(ts, tz=TZ) if TZ else dt.datetime.fromtimestamp(ts).astimezone()
    return d.strftime('%Y-%m-%d %H:%M %Z').strip()


names = {}
try:
    for r in csv.DictReader(open(os.path.join(HERE, 'claude-contacts-map.csv'), encoding='utf-8')):
        names[r['handle'].strip().lower()] = (r['name'].strip(), (r.get('organization') or '').strip())
except Exception: names = {}


def digits(jid):
    d = re.sub(r'\D', '', str(jid or '').split('@')[0])
    return d[-10:] if len(d) >= 10 else d


def label(jid, fallback=''):
    k = digits(jid); n = names.get(k)
    if n: return n[0] + (' (' + n[1] + ')' if n[1] else '')
    if fallback: return fallback
    if len(k) == 10: return '(%s) %s-%s' % (k[:3], k[3:6], k[6:])
    return ('+' + k) if k else 'WhatsApp'


try:
    # a snapshot never changes: open it as immutable (no -wal/-shm files needed, nothing is ever written)
    db = sqlite3.connect('file:' + SNAP + '?mode=ro&immutable=1', uri=True)
    since = NOW.timestamp() - HOURS * 3600 - EPOCH
    chats = db.execute("""select c.Z_PK, c.ZCONTACTJID, c.ZPARTNERNAME, c.ZSESSIONTYPE from ZWACHATSESSION c
        where c.ZLASTMESSAGEDATE > ? and coalesce(c.ZREMOVED,0)=0 and coalesce(c.ZHIDDEN,0)=0""", (since,)).fetchall()
    out = []
    for pk, jid, partner, stype in chats:
        jid = str(jid or '')
        if not jid or jid.startswith('status@') or jid.endswith('@broadcast'): continue
        group = jid.endswith('@g.us')
        rows = db.execute("""select m.ZISFROMME, m.ZMESSAGEDATE, m.ZTEXT, m.ZFROMJID, m.ZPUSHNAME, gm.ZMEMBERJID, gm.ZCONTACTNAME
            from ZWAMESSAGE m left join ZWAGROUPMEMBER gm on gm.Z_PK = m.ZGROUPMEMBER
            where m.ZCHATSESSION = ? and m.ZMESSAGEDATE > ? and coalesce(m.ZTEXT,'') <> ''
            order by m.ZMESSAGEDATE desc limit 4""", (pk, since)).fetchall()
        msgs = []
        for me, d, text, frm, push, mjid, mname in reversed(rows):
            if me: who = 'Me'
            elif group: who = label(mjid or frm, (mname or push or '').strip())
            else: who = label(jid, (partner or '').strip())
            msgs.append({'me': bool(me), 'from': who, 'at': stamp(d + EPOCH), 'text': str(text).strip()[:300]})
        if not msgs: continue
        handle = '' if group else digits(jid)
        out.append({'app': 'whatsapp', 'chat': 'wa:' + jid, 'group': group, 'title': (partner or '') if group else '',
                    'handle': handle, 'name': (partner or 'WhatsApp group') if group else label(jid, (partner or '').strip()),
                    'known': bool(handle and handle in names), 'lastFromMe': msgs[-1]['me'], 'lastAt': msgs[-1]['at'], 'messages': msgs})
except sqlite3.Error as e:
    fail('WhatsApp database: %s' % e)

out.sort(key=lambda x: x['lastAt'], reverse=True)
out = out[:40]
if merge:
    try: base = json.load(open(merge, encoding='utf-8'))
    except Exception as e: fail("can't read the texts file to add WhatsApp to (%s)" % str(e)[:80])
    threads = [t for t in (base.get('threads') or []) if t.get('app') != 'whatsapp'] + out
    threads.sort(key=lambda x: x.get('lastAt') or '', reverse=True)
    base['threads'] = threads[:90]
    base['whatsapp'] = {'chats': len(out), 'at': NOW.isoformat(timespec='seconds')}
    print(json.dumps(base, ensure_ascii=False))
else:
    print(json.dumps({'generatedAt': NOW.isoformat(timespec='seconds'), 'hours': HOURS, 'threads': out}, ensure_ascii=False))
