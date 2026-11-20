"""Single-guild rotation store. Each public mutation runs inside Store.tx()."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo


class Rule(ValueError):
    pass


def minutes(value):
    try:
        h, m = map(int, value.strip().split(":"))
        if 0 <= h < 24 and 0 <= m < 60:
            return h * 60 + m
    except ValueError:
        pass
    raise Rule("Enter a 24-hour time such as 23:30.")


def clock(n):
    return f"{n // 60:02}:{n % 60:02}"


def hours(value):
    try:
        n = round(float(value) * 3600)
        if 60 <= n <= 7 * 86400:
            return n
    except (ValueError, OverflowError):
        pass
    raise Rule("Enter hours, e.g. 0.5 for 30 minutes (1 minute to 7 days).")


def validate(rows, *, allow_gaps=False):
    if not rows:
        raise Rule("Add at least one shift before publishing.")
    occupied = [0] * 1440
    for r in rows:
        for i in range((r["b"] - r["a"]) % 1440 or 1440):
            occupied[(r["a"] + i) % 1440] += 1
    for i, count in enumerate(occupied):
        if count > 1 or (count == 0 and not allow_gaps):
            raise Rule(f"{'Overlap' if count else 'Gap'} at {clock(i)}. Edit the draft before publishing.")


SCHEMA = """
pragma journal_mode=WAL;
create table if not exists identity(guild integer primary key);
create table if not exists posts(gap integer primary key,channel integer,message integer);
create table if not exists retries(job integer primary key,after integer);
create table if not exists maps(id integer primary key,name text unique collate nocase,role integer unique,channel integer,tz text);
create table if not exists slots(id integer primary key,map integer,a integer,b integer,cap integer,deleted integer default 0);
create table if not exists live(slot integer primary key,map integer,a integer,b integer,cap integer);
create table if not exists regular(slot integer,user integer,kind text,note text,primary key(slot,user));
create table if not exists shifts(id integer primary key,map integer,slot integer,a integer,b integer,cap integer,unique(map,a));
create table if not exists practice(id integer primary key,map integer,a integer,b integer);
create table if not exists subs(shift integer,user integer,note text,primary key(shift,user));
create table if not exists seats(id integer primary key,shift integer,seat integer,a integer,b integer,user integer,note text,status text);
create table if not exists gaps(id integer primary key,shift integer,seat integer,a integer,b integer,owner integer,kind text,note text,stage integer,escalate integer,pinged integer default 0,claimed integer default 0);
create table if not exists lf(user integer primary key,until integer,note text);
create table if not exists claims(gap integer primary key,user integer,a integer,b integer,note text);
create table if not exists delayed(kind text,ref integer,due integer,primary key(kind,ref));
create table if not exists jobs(id integer primary key,kind text,ref integer,unique(kind,ref));
"""
class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        with self.tx():
            columns = {row["name"] for row in self.rows("pragma table_info(lf)")}
            if "starts" not in columns:
                self.run("alter table lf add column starts integer not null default 0")

    @contextmanager
    def tx(self):
        self.db.execute("begin immediate")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def rows(self, sql, *args):
        return self.db.execute(sql, args).fetchall()

    def one(self, sql, *args):
        row = self.db.execute(sql, args).fetchone()
        if row is None:
            raise Rule("This item is no longer available.")
        return row

    def run(self, sql, *args):
        return self.db.execute(sql, args).lastrowid

    def job(self, kind, ref):
        self.run("insert or ignore into jobs(kind,ref) values(?,?)", kind, ref)

    def publish(self, mid, *, allow_gaps=False):
        rows = self.rows("select * from slots where map=? and deleted=0", mid)
        validate(rows, allow_gaps=allow_gaps)
        for r in rows:
            count = self.one("select count(*) n from regular where slot=? and kind='main'", r["id"])["n"]
            if count > r["cap"]:
                raise Rule(f"Remove {count-r['cap']} main(s) from slot #{r['id']} before publishing.")
        self.run("delete from live where map=?", mid)
        self.run("insert into live select id,map,a,b,cap from slots where map=? and deleted=0", mid)

    def assign(self, slot, user, kind, note):
        s = self.one("select * from slots where id=? and deleted=0", slot)
        if kind == "main":
            counts = self.one("select count(*) n from regular where slot=? and kind='main' and user!=?", slot,user)
            caps = [s["cap"]] + [r["cap"] for r in self.rows("select cap from live where slot=?",slot)]
            if counts["n"] >= min(caps):
                raise Rule("All recurring main seats are filled.")
        self.run("delete from regular where slot=? and user=?",slot,user)
        if kind != "leave":
            self.run("insert into regular values(?,?,?,?)",slot,user,kind,note)

    def available(self, user, a, b):
        return not self.rows("select 1 from seats where shift>0 and user=? and b>a and a<? and b>? limit 1",user,b,a)

    def seat(self, sid, number, a, b, user, note, status):
        return self.run("insert into seats(shift,seat,a,b,user,note,status) values(?,?,?,?,?,?,?)",
                        sid,number,a,b,user,note,status)

    def dates(self, slot, now, offset):
        zone = ZoneInfo(slot["tz"])
        day = datetime.fromtimestamp(now, zone).date() + timedelta(days=offset)
        def instant(day, minute):
            return int(datetime.combine(day, time(minute//60, minute%60), zone).timestamp())
        return instant(day, slot["a"]), instant(day + timedelta(days=slot["b"] <= slot["a"]), slot["b"])

    def upcoming(self, user, now, week=0):
        choices = []
        for r in self.rows("""select live.*, maps.tz,maps.name from live join maps on maps.id=live.map
                              join regular using(slot) where regular.user=? and regular.kind='main'""", user):
            for offset in range(7*week, 7*week+7):
                a,b=self.dates(r,now,offset)
                if a<=now or self.rows("select 1 from shifts where map=? and a<? and b>?",r["map"],b,a):
                    continue
                choices.append((a,b,r["slot"],r["name"]))
        for r in self.rows("""select seats.a,seats.b,shifts.slot,maps.name,maps.tz from seats
                join shifts on shifts.id=seats.shift join maps on maps.id=shifts.map
                where user=? and seats.a>? and seats.b>seats.a""",user,now):
            zone=ZoneInfo(r["tz"])
            offset=(datetime.fromtimestamp(r["a"],zone).date()-datetime.fromtimestamp(now,zone).date()).days
            if 7*week<=offset<7*week+7:
                choices.append(tuple(r)[:4])
        return sorted(choices)

    def early_decline(self,user,slot,a,b,note,now):
        if a<=now: raise Rule("This shift has started. Use /replace.")
        seats=self.rows("""select seats.id from seats join shifts on shifts.id=seats.shift
                           where user=? and slot=? and seats.a=? and seats.b=?""",user,slot,a,b)
        if not seats:
            r=self.one("""select live.*,maps.tz from live join maps on maps.id=live.map
                          join regular using(slot) where slot=? and user=? and kind='main'""",slot,user)
            zone=ZoneInfo(r["tz"])
            offset=(datetime.fromtimestamp(a,zone).date()-datetime.fromtimestamp(now,zone).date()).days
            if self.dates(r,now,offset)!=(a,b) or self.rows("select 1 from shifts where map=? and a<? and b>?",r["map"],b,a):
                raise Rule("This occurrence changed or was already released. Open /cant_make_it again.")
            sid=self.open_shift(r,a,b,now,early=True)
            seats=self.rows("select id from seats where shift=? and user=? and b>a",sid,user)
            if not seats: raise Rule("You do not hold a seat in this occurrence.")
        return self.release(seats[0]["id"],user,"decline",note,now)

    def open_shift(self,r,a,b,now,early=False):
        def schedule(kind,ref,start):
            if early and start-1800>now:
                self.run("insert or ignore into delayed values(?,?,?)",kind,ref,start-1800)
            else:
                self.job(kind,ref)
        sid=self.run("insert into shifts(map,slot,a,b,cap) values(?,?,?,?,?)",r["map"],r["slot"],a,b,r["cap"])
        number=0
        for p in self.rows("select * from regular where slot=? order by rowid",r["slot"]):
            if p["kind"]=="sub":
                self.run("insert into subs values(?,?,?)",sid,p["user"],p["note"])
            else:
                number+=1
                if self.available(p["user"],a,b):
                    seat=self.seat(sid,number,a,b,p["user"],p["note"],"pending")
                    schedule("check",seat,a)
                else:
                    self.gap(sid,number,a,b,0,"vacancy","Recurring main already booked.",now)
        schedule("board",sid,a)
        return sid

    def tick(self, now):
        for m in self.rows("select * from maps"):
            windows = []
            for r in self.rows("select * from live where map=?",m["id"]):
                for offset in (-1,0,1):
                    a,b=self.dates(dict(r,tz=m["tz"]),now,offset)
                    if b>now and a<=now+1800:
                        windows.append((a,b,r))
            for a,b,r in sorted(windows,key=lambda w:w[0]):
                last = self.one("select coalesce(max(b),0) t from shifts where map=? and a<?",m["id"],b)["t"]
                a = max(a,last)
                if a>=b or a>now+1800:
                    continue
                self.open_shift(r,a,b,now)
        for job in self.rows("select * from delayed where due<=?",now):
            self.job(job["kind"],job["ref"])
            self.run("delete from delayed where kind=? and ref=?",job["kind"],job["ref"])
        for g in self.rows("select * from gaps where claimed=0 and stage=0 and escalate<=? and b>?",now,now):
            self.run("update gaps set stage=1 where id=?",g["id"])
            self.job("lf",g["id"])
        for r in self.rows("select id from seats where status='return' and a<=? and b>?",now,now):
            self.run("update seats set status='return due' where id=?",r["id"])
            self.job("return",r["id"])
        self.run("delete from lf where until<=?",now)

    def gap(self,sid,num,a,b,owner,kind,note,now):
        subs = self.rows("select 1 from subs where shift=? and user!=?",sid,owner)
        stage = 0 if kind in ("replace","cover") or (kind=="decline" and subs) else 1
        gid=self.run("insert into gaps(shift,seat,a,b,owner,kind,note,stage,escalate) values(?,?,?,?,?,?,?,?,?)",
                     sid,num,a,b,owner,kind,note,stage,now+300)
        self.job("open",gid)
        return gid

    def release(self,seat,user,kind,note,now,length=None):
        s=self.one("select * from seats where id=? and user=? and b>? and b>a",seat,user,now)
        if kind=="decline" and s["a"]<=now:
            kind="replace"
        if kind in ("cover","replace") and s["a"]>now:
            raise Rule("This seat has not started yet.")
        a=max(now,s["a"])
        b=min(s["b"],a+length) if kind=="cover" else s["b"]
        if kind=="cover" and b>=s["b"]:
            raise Rule("Cover must finish before your booking ends. Use Replace for the remainder.")
        self.run("update seats set b=? where id=?",a,seat)
        if kind=="cover":
            self.seat(s["shift"],s["seat"],b,s["b"],user,s["note"],"return")
        return self.gap(s["shift"],s["seat"],a,b,user,kind,note or s["note"],now)

    def claim(self,gid,user,now,until,note,starts=0):
        g=self.one("select * from gaps where id=? and claimed=0 and b>?",gid,now)
        original_start=max(g["a"],now)
        a=max(original_start,starts)
        b=min(until,g["b"])
        if b<=a or user==g["owner"]:
            raise Rule("Choose another open seat or adjust your availability.")
        if g["shift"]>0 and not self.available(user,a,b):
            raise Rule("You already hold a seat during this time.")
        self.run("update gaps set claimed=1 where id=?",gid)
        pending=g["shift"]>0 and a>now+1800
        seat=self.seat(g["shift"],g["seat"],a,b,user,note,"pending" if pending else "confirmed")
        if pending:
            self.run("insert into delayed values('check',?,?)",seat,a-1800)
        self.run("insert into claims values(?,?,?,?,?)",gid,user,a,b,note)
        self.job("taken",gid)
        if a>original_start:
            self.gap(g["shift"],g["seat"],original_start,a,g["owner"],"handoff",g["note"],now)
        if b<g["b"]:
            self.gap(g["shift"],g["seat"],b,g["b"],g["owner"],"handoff",g["note"],now)
        return a,b

    def ping(self,gid,now):
        changed=self.db.execute("update gaps set pinged=1 where id=? and claimed=0 and pinged=0 and b>?",(gid,now)).rowcount
        if not changed:
            raise Rule("This gap was filled, expired, or already pinged.")
        self.job("role",gid)
