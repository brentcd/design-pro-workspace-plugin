#!/usr/bin/env python3
"""Read-only export of recent Messages threads for the Design Pro Workspace.
Lives in ~/Library/Messages next to chat.db.
Usage: python3 claude-texts-export.py [hours=48] [IANA time zone, e.g. America/Chicago] [--state FILE] [--quiet-sunday] > out.json
Times are written in the given zone, or in this computer's own zone when none is given.
Optional: claude-contacts-map.csv (handle,name,organization) in the same folder labels senders.
--state FILE: remembers what the last export held; when nothing changed and the last export is under 110 minutes old,
  prints nothing, says "unchanged" on stderr and exits 3 (the caller then has nothing to upload).
--quiet-sunday: on Sundays from 6 AM (in the given zone) it says "Sunday: not needed" on stderr and exits 4 without
  reading anything (one early-morning export a Sunday is enough).
On a problem it prints one plain sentence to stderr and exits 1."""
import sqlite3, csv, hashlib, json, os, re, sys, datetime as dt
HERE=os.path.dirname(os.path.abspath(__file__))
def fail(msg):
    sys.stderr.write(msg.strip()+'\n'); sys.exit(1)
ARGS=[];STATE=None;QUIET_SUNDAY=False
_a=sys.argv[1:]
while _a:
    x=_a.pop(0)
    if x=='--state':
        if not _a: fail('--state needs a file name')
        STATE=_a.pop(0)
    elif x=='--quiet-sunday': QUIET_SUNDAY=True
    elif x.startswith('--'): pass  # unknown options are ignored, so a newer caller never breaks an older script (or the reverse)
    else: ARGS.append(x)
try: hours=float(ARGS[0]) if ARGS else 48
except ValueError: fail('hours must be a number, got "%s"'%ARGS[0][:20])
TZ=None  # None = this computer's local zone
if len(ARGS)>1 and ARGS[1].strip():
    try:
        from zoneinfo import ZoneInfo
        TZ=ZoneInfo(ARGS[1].strip())
    except Exception: fail('unknown time zone "%s"'%ARGS[1][:40])
NOW=dt.datetime.now(dt.timezone.utc)
if QUIET_SUNDAY:
    _l=NOW.astimezone(TZ) if TZ else NOW.astimezone()
    if _l.weekday()==6 and _l.hour>=6:
        sys.stderr.write('Sunday: not needed\n'); sys.exit(4)
def stamp(ts):
    d=dt.datetime.fromtimestamp(ts,tz=TZ) if TZ else dt.datetime.fromtimestamp(ts).astimezone()
    return d.strftime('%Y-%m-%d %H:%M %Z').strip()
names={}
try:
    for r in csv.DictReader(open(os.path.join(HERE,'claude-contacts-map.csv'),encoding='utf-8')):
        names[r['handle'].strip().lower()]=(r['name'].strip(),(r.get('organization') or '').strip())
except Exception as e: names={}
def key(h):
    h=(h or '').strip().lower()
    if '@' in h: return h
    d=re.sub(r'\D','',h)
    return d[-10:] if len(d)>=10 else d
def label(h):
    k=key(h); n=names.get(k)
    if n: return n[0]+(' ('+n[1]+')' if n[1] else '')
    if len(k)==10 and k.isdigit(): return '(%s) %s-%s'%(k[:3],k[3:6],k[6:])
    return h
def body(t,ab):
    """The message text; for newer messages it sits inside attributedBody (a typedstream). A message whose body
    can't be read becomes '' (and is skipped) instead of stopping the whole export."""
    if t: return t
    if not ab: return ''
    try: return _body(ab)
    except Exception: return ''
def _body(ab):
    b=bytes(ab); i=b.find(b'NSString')
    if i<0: return ''
    s=b[i+8:]; j=s.find(b'+')
    if j<0 or j>8: return ''
    s=s[j+1:]
    if not s: return ''
    n=s[0]
    if n==0x81: n=int.from_bytes(s[1:3],'little'); s=s[3:]
    elif n==0x82: n=int.from_bytes(s[1:4],'little'); s=s[4:]
    else: s=s[1:]
    return s[:n].decode('utf-8','ignore')
EPOCH=978307200
try:
    db=sqlite3.connect('file:'+os.path.join(HERE,'chat.db')+'?mode=ro',uri=True)  # read-only: never writes to chat.db
    since=(NOW.timestamp()-hours*3600-EPOCH)*1e9
    chats=db.execute("""select c.ROWID,c.chat_identifier,c.display_name,max(m.date) from chat c join chat_message_join cm on cm.chat_id=c.ROWID join message m on m.ROWID=cm.message_id where m.date>? group by c.ROWID""",(since,)).fetchall()
    out=[]
    for cid,ident,dname,last in chats:
        parts=[r[0] for r in db.execute("select h.id from chat_handle_join j join handle h on h.ROWID=j.handle_id where j.chat_id=?",(cid,))]
        if parts and all(len(key(p))<10 and '@' not in p for p in parts): continue  # short codes
        rows=db.execute("""select m.is_from_me,m.date,m.text,m.attributedBody,h.id from message m join chat_message_join cm on cm.message_id=m.ROWID left join handle h on h.ROWID=m.handle_id where cm.chat_id=? and coalesce(m.associated_message_type,0)=0 order by m.date desc limit 6""",(cid,)).fetchall()
        msgs=[]
        for fm,d,t,ab,h in reversed(rows):
            txt=body(t,ab).replace('￼','').strip()
            if not txt: continue
            msgs.append({'me':bool(fm),'from':'Me' if fm else label(h),'at':stamp(d/1e9+EPOCH),'text':txt[:300]})
        if not msgs: continue
        first=parts[0] if len(parts)==1 else None
        out.append({'chat':ident,'group':len(parts)>1,'title':dname or '','handle':key(first) if first else '',
          'name':label(first) if first else ', '.join(label(p) for p in parts)[:200],
          'known':bool(first and key(first) in names),'lastFromMe':msgs[-1]['me'],'lastAt':msgs[-1]['at'],'messages':msgs})
except sqlite3.Error as e:
    fail('Messages database: %s'%e)
out.sort(key=lambda x:x['lastAt'],reverse=True)
out=out[:60]
if STATE:
    h=hashlib.sha256(json.dumps([out,len(names)],sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:16]
    try:
        st=json.load(open(STATE))
        last=dt.datetime.fromisoformat(st['writtenAt'])
        if st.get('hash')==h and 0<=(NOW-last).total_seconds()<110*60:
            sys.stderr.write('unchanged\n'); sys.exit(3)
    except SystemExit: raise
    except Exception: pass
    try: json.dump({'hash':h,'writtenAt':NOW.isoformat(timespec='seconds')},open(STATE,'w'))
    except Exception: pass
print(json.dumps({'generatedAt':NOW.isoformat(timespec='seconds'),'hours':hours,'contacts':len(names),'threads':out},ensure_ascii=False))
