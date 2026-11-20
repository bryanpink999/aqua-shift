from datetime import datetime, timedelta, time as day_time
import logging
import os
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

import discord
from discord import app_commands
from discord.ext import tasks
from rotation import Store, Rule, minutes, hours, clock

log = logging.getLogger("shifts")
TEST_GUILD = 1573064240598618252
GUILD = int(os.environ.get("GUILD_ID","0"))
db = Store(os.environ.get("DB_PATH","rotation.sqlite3"))
def now():
    return int(time.time())

def stamp(n):
    return f"<t:{n}:t>"

def span(a,b):
    return f"{stamp(a)}–{stamp(b)}"

def clean(s):
    return discord.utils.escape_markdown(discord.utils.escape_mentions(s)) or "Any platform"

def mention(uid):
    return f"<@{uid}>"

QUIET=discord.AllowedMentions.none()

def buttons(*items):
    view=discord.ui.View(timeout=None)
    for label, action in items:
        view.add_item(discord.ui.Button(label=label,custom_id="ms:"+action,style=discord.ButtonStyle.secondary))
    return view

async def reply(i,msg,view=None):
    kwargs=dict(ephemeral=True,allowed_mentions=QUIET)
    if view is not None:
        kwargs["view"]=view
    if i.response.is_done():
        return await i.followup.send(msg,**kwargs)
    await i.response.send_message(msg,**kwargs)

def admin(i):
    if not i.permissions.manage_guild:
        raise Rule("Manage Server permission is required.")

def guard(i):
    if i.guild_id!=GUILD:
        raise Rule("Use this bot in its configured server.")

def maprow(mid):
    return db.one("select * from maps where id=?",mid)

def instance(sid):
    if int(sid)<0:
        return db.one("select -id as id,map,a,b,1 as cap from practice where id=?",-int(sid))
    return db.one("select * from shifts where id=?",sid)

def roles(member):
    return {r.id for r in member.roles}

def window(g):
    return f"{maprow(instance(g['shift'])['map'])['name']} · seat {g['seat']} · <t:{g['a']}:f> → <t:{g['b']}:f>"

def member_maps(member):
    return [r["name"] for r in db.rows("select * from maps") if r["role"] in roles(member)]

class Form(discord.ui.Modal):
    def __init__(self,title,fields,submit):
        super().__init__(title=title,timeout=600)
        self.submit=submit
        for label,placeholder,default,required in fields:
            self.add_item(discord.ui.TextInput(label=label,placeholder=placeholder,default=default or None,
                                               required=required,max_length=160))
    async def on_submit(self,i):
        try:
            guard(i)
            await self.submit(i,*[str(f.value).strip() for f in self.children])
        except (Rule,ValueError) as e:
            await reply(i,str(e))
    async def on_error(self,i,error):
        log.exception("Form failed",exc_info=error)
        await reply(i,"Could not finish this action. Check the current roster and try again.")

def field(label,hint="",default="",required=True):
    return label,hint,default,required

def comment(default=""):
    return field("Platform / comment (optional)","E.g. bottom lane, 3F/4F, or any platform",default,False)

class Client(discord.Client):
    async def setup_hook(self):
        with db.tx():
            stored=db.rows("select * from identity")
            if stored and stored[0]["guild"]!=GUILD:
                raise RuntimeError("Use a separate DB_PATH for each server.")
            db.run("insert or ignore into identity values(?)",GUILD)
        target=discord.Object(id=GUILD)
        tree.copy_global_to(guild=target)
        synced=await tree.sync(guild=target)
        log.info("Registered guild commands: %s", ", ".join(c.name for c in synced))
        scheduler.start()

intents=discord.Intents.none()
intents.guilds=True
intents.members=True
client=Client(intents=intents,allowed_mentions=QUIET)
tree=app_commands.CommandTree(client)

@tree.error
async def command_error(i,error):
    error=getattr(error,"original",error)
    if isinstance(error,(Rule,ValueError,app_commands.CheckFailure)):
        await reply(i,str(error))
    else:
        log.error("Command failed",exc_info=error)
        await reply(i,"Action failed. Check the roster and bot log.")

@tree.command(name="map_setup",description="Admin: connect a map, role, channel and timetable timezone")
@app_commands.checks.has_permissions(manage_guild=True)
async def setup(i:discord.Interaction,name:str,role:discord.Role,channel:discord.TextChannel,timezone:str="Asia/Singapore"):
    guard(i)
    try:
        ZoneInfo(timezone)
    except (ValueError,ZoneInfoNotFoundError):
        raise Rule("Use an IANA timezone such as Asia/Singapore or UTC.")
    if role.is_default() or role.managed or len(name.strip()) not in range(1,41):
        raise Rule("Choose an ordinary map role and a map name of 1–40 characters.")
    perms=channel.permissions_for(i.guild.me)
    if not (perms.view_channel and perms.send_messages and perms.read_message_history and (role.mentionable or perms.mention_everyone)):
        raise Rule("Grant channel view, send and history access, plus permission to mention the selected role.")
    with db.tx():
        other=db.rows("select * from maps where role=? and name!=? collate nocase",role.id,name.strip())
        if other: raise Rule("That role is already mapped.")
        db.run("""insert into maps(name,role,channel,tz) values(?,?,?,?) on conflict(name) do update set
                  role=excluded.role,channel=excluded.channel,tz=excluded.tz""",name.strip(),role.id,channel.id,timezone)
    await reply(i,"Map saved. Open /manage to set the daily rotation.")

async def choose_map(i,action):
    guard(i)
    if action=="manage": admin(i)
    rows=db.rows("select * from maps order by name")
    if not rows:
        return await reply(i,"No maps are set up yet. Ask a shift admin to use /map_setup.")
    await page(i,"maps",action,0,rows,lambda r:(r["name"],f"{action}:{r['id']}:0"),"Choose a map.")

async def page(i,kind,key,num,rows,button,title,extra=()):
    start=num*8
    options=[button(r) for r in rows[start:start+8]]
    if start: options.append(("Previous",f"page:{kind}:{key}:{num-1}"))
    if start+8<len(rows): options.append(("Next",f"page:{kind}:{key}:{num+1}"))
    options.extend(extra)
    await reply(i,title,buttons(*options) if options else None)

ZONE_CHOICES = ("Asia/Singapore", "Asia/Seoul", "Asia/Tokyo", "Asia/Manila",
                "Asia/Kolkata", "Australia/Sydney", "Europe/London", "Europe/Paris",
                "America/New_York", "America/Chicago", "America/Los_Angeles", "UTC")
ZONE_NAMES = sorted(available_timezones())

def ensure_zone_table(store):
    store.run("create table if not exists admin_zones(user integer primary key, zone text not null)")

ensure_zone_table(db)

def personal_zone(uid):
    rows=db.rows("select zone from admin_zones where user=?",uid)
    return rows[0]["zone"] if rows else None

def minute_offset(source, target, instant):
    def offset(zone):
        return datetime.fromtimestamp(instant, ZoneInfo(zone)).utcoffset()
    return int((offset(target)-offset(source)).total_seconds() // 60)

async def zone_prompt(i):
    admin(i)
    saved=personal_zone(i.user.id)
    choices=list(dict.fromkeys(([saved] if saved else []) + list(ZONE_CHOICES)))
    await reply(i,"Choose your timezone for entering daily shifts. For another city, use the timezone option on /manage.",
                buttons(*[(z,"zone:"+z) for z in choices]))

async def choose_zone(i, zone):
    admin(i)
    if zone not in ZONE_NAMES:
        raise Rule("Choose a timezone from the suggestions, e.g. Asia/Seoul.")
    with db.tx():
        db.run("insert or replace into admin_zones values(?,?)",i.user.id,zone)
    await choose_map(i,"manage")

@tree.command(description="Admin: choose your timezone and edit the daily rotation")
@app_commands.describe(timezone="Your timezone for entering shifts. Search by city.")
async def manage(i:discord.Interaction,timezone:str=None):
    guard(i)
    admin(i)
    if timezone: return await choose_zone(i,timezone)
    if personal_zone(i.user.id): return await choose_map(i,"manage")
    await zone_prompt(i)

@manage.autocomplete("timezone")
async def suggest_zone(i:discord.Interaction,current:str):
    query=current.casefold().replace(" ","_")
    names=[z for z in ZONE_NAMES if query in z.casefold()] if query else ZONE_CHOICES
    return [app_commands.Choice(name=z,value=z) for z in names[:25]]

@tree.command(description="Sign yourself up as a main or substitute for a shift")
async def sign_up(i:discord.Interaction):
    await choose_map(i,"sign_up")

def daily_window(row,t):
    zone=ZoneInfo(row["tz"])
    today=datetime.fromtimestamp(t,zone).date()
    for day in (today-timedelta(days=1),today,today+timedelta(days=1)):
        def local(minute,date):
            return int(datetime.combine(date,day_time(minute//60,minute%60),zone).timestamp())
        a=local(row["a"],day)
        b=local(row["b"],day+timedelta(days=int(row["b"]<=row["a"])))
        if b>t:
            return a,b

def roster_entries(mid, t, days=1):
    """Read-only preview: existing bookings override recurring occurrences."""
    end=t+days*86400
    entries=[]
    fixed=db.rows("select * from shifts where map=? and b>? and a<? order by a",mid,t,end)
    for r in fixed:
        players=db.rows("select user,seat,a,b,note from seats where shift=? and b>? and a<? and b>a order by seat,a",r["id"],t,end)
        lines=[]
        for seat in range(1,r["cap"]+1):
            holders=[p for p in players if p["seat"]==seat]
            for p in holders:
                note=f" · {clean(p['note'])}" if p["note"] else ""
                timing=f" · {span(p['a'],p['b'])}" if (p["a"],p["b"])!=(r["a"],r["b"]) else ""
                lines.append(f"{seat}. {mention(p['user'])}{note}{timing}")
            gaps=db.rows("select a,b from gaps where shift=? and seat=? and claimed=0 and b>? and a<? order by a",r["id"],seat,t,end)
            for g in gaps:
                lines.append(f"{seat}. **Open** · {span(g['a'],g['b'])}")
            if not holders and not gaps: lines.append(f"{seat}. **Open**")
        subs=db.rows("select user from subs where shift=? order by user",r["id"])
        entries.append((r["a"],r["b"],lines,subs,False))
    for r in db.rows("select live.*,maps.tz from live join maps on maps.id=live.map where map=?",mid):
        for offset in range(-1,days+2):
            a,b=db.dates(r,t,offset)
            if b<=t or a>=end: continue
            # Published changes take effect after frozen occurrences finish.
            overlaps=[f for f in fixed if f["a"]<b and f["b"]>a]
            if overlaps:
                a=max(f["b"] for f in overlaps)
                if a>=b or a>=end: continue
            people=db.rows("select user,kind,note from regular where slot=? order by rowid",r["slot"])
            mains=[p for p in people if p["kind"]=="main"]
            lines=[f"{n}. {mention(p['user'])}"+(f" · {clean(p['note'])}" if p["note"] else "") for n,p in enumerate(mains,1)]
            lines += [f"{n}. **Open**" for n in range(len(mains)+1,r["cap"]+1)]
            entries.append((a,b,lines,[p for p in people if p["kind"]=="sub"],True))
    return sorted(entries,key=lambda e:e[0])

async def overview(i,zone,page_num,mid=None,days=1):
    guard(i)
    if zone != "local" and zone not in ZONE_NAMES: raise Rule("Choose a timezone from the city suggestions.")
    horizon="24 hours" if days==1 else "7 days"
    t=now()
    maps=db.rows("select * from maps order by name")
    if not maps: return await reply(i,"No parties are configured yet.")
    if mid is None:
        channel=getattr(i,"channel_id",None)
        matches=[m for m in maps if m["channel"]==channel]
        if len(matches)!=1:
            active={r["map"] for r in db.rows("select distinct shifts.map from seats join shifts on shifts.id=seats.shift where user=? and seats.a<=? and seats.b>?",i.user.id,t,t)}
            matches=[m for m in maps if m["id"] in active]
        if len(matches)!=1: matches=[m for m in maps if m["role"] in roles(i.user)]
        if len(matches)!=1:
            if len(maps)==1: matches=maps
            else:
                return await reply(i,f"Choose a party · next {horizon}",buttons(*[(m["name"],f"overview:{zone}:0:{m['id']}:{days}") for m in maps[:25]]))
        mid=matches[0]["id"]
    m=maprow(mid)
    sections=[]
    for a,b,lines,subs,projected in roster_entries(mid,t,days):
        label="Now" if a<=t else "Upcoming"
        if projected: label+=" · planned"
        if zone=="local":
            heading=f"**{label}** · <t:{a}:f> → <t:{b}:t>"
        else:
            def fmt(x): return datetime.fromtimestamp(x,ZoneInfo(zone)).strftime("%a %d %b %H:%M")
            heading=f"**{label}** · {fmt(a)} → {fmt(b)}"
        if subs: lines=lines+["Subs: "+", ".join(mention(p["user"]) for p in subs)]
        section=heading
        for line in lines:
            if len(section)+len(line)>3500:
                sections.append(section)
                section=heading+" (continued)"
            section+="\n"+line
        sections.append(section)
    pages=[""]
    for section in sections:
        if len(pages[-1])+len(section)+2>3900: pages.append("")
        pages[-1]+=section+"\n\n"
    n=min(max(page_num,0),len(pages)-1)
    embed=discord.Embed(title=f"{m['name']} · Next {horizon}",description=pages[n].strip() or f"No shifts in the next {horizon}.",color=0x279C97)
    tz_label="Times shown in your local timezone" if zone=="local" else zone
    embed.set_footer(text=f"{tz_label} · Page {n+1}/{len(pages)} · /sign_up to join")
    nav=[]
    if n: nav.append(("Previous",f"overview:{zone}:{n-1}:{mid}:{days}"))
    if n+1<len(pages): nav.append(("Next",f"overview:{zone}:{n+1}:{mid}:{days}"))
    args=dict(embed=embed,view=buttons(*nav) if nav else None,allowed_mentions=QUIET)
    if getattr(i,"type",None)==discord.InteractionType.component:
        return await i.response.edit_message(**args)
    if not nav: args.pop("view")
    await i.response.send_message(ephemeral=True,**args)

@tree.command(description="See this party’s current and upcoming shifts within 24 hours")
@app_commands.describe(timezone="Optional timezone. Otherwise times appear in your local timezone.")
async def roster(i:discord.Interaction,timezone:str=None):
    await overview(i,timezone or "local",0)

roster.autocomplete("timezone")(suggest_zone)

@tree.command(description="See this party’s dated roster for the next seven days")
@app_commands.describe(timezone="Optional timezone. Otherwise times appear in your local timezone.")
async def roster7d(i:discord.Interaction,timezone:str=None):
    await overview(i,timezone or "local",0,days=7)

roster7d.autocomplete("timezone")(suggest_zone)

async def panel(i,mid,editing,num=0):
    m=maprow(mid)
    zone=m["tz"]
    delta=0
    if editing:
        admin(i)
        zone=personal_zone(i.user.id)
        if not zone: return await zone_prompt(i)
        delta=minute_offset(m["tz"],zone,now())
        rows=db.rows("select id,a,b,cap from slots where map=? and deleted=0 order by a",mid)
        rows=sorted(rows,key=lambda r:(r["a"]+delta)%1440)
        extra=[("Change my timezone","zones"),("Add shift",f"edit:{mid}:0"),("Publish timetable",f"publish:{mid}")]
    else:
        rows=db.rows("select slot id,a,b,cap from live where map=? order by a",mid)
        extra=[("Join this shift only",f"current:{mid}")]
        if not rows:
            return await reply(i,f"No daily shifts published for {m['name']} yet. A shift admin can publish the timetable in /manage.",buttons(*extra))
    key="manage" if editing else "sign_up"
    await page(i,key,mid,num,rows,lambda r:(f"{clock((r['a']+delta)%1440)}–{clock((r['b']+delta)%1440)} · {r['cap']} seats",f"slot:{r['id']}:{int(editing)}"),
               f"**{m['name']}** · {zone} · "+("daily timetable draft" if editing else "Pick a time for daily signup, or join this shift only."),extra)

async def edit_slot(i,mid,slot):
    admin(i)
    zone=personal_zone(i.user.id)
    if not zone: return await zone_prompt(i)
    map_zone=maprow(mid)["tz"]
    delta=minute_offset(map_zone,zone,now())
    r=db.one("select * from slots where id=? and map=? and deleted=0",slot,mid) if slot else None
    async def save(j,a,b,cap):
        admin(j)
        if maprow(mid)["tz"]!=map_zone:
            raise Rule("Map timezone changed. Reopen the shift form.")
        a,b=(minutes(a)-delta)%1440,(minutes(b)-delta)%1440
        if not cap.isdecimal() or not 1<=int(cap)<=10000:
            raise Rule("Enter a positive seat count up to 10000.")
        with db.tx():
            if slot:
                db.one("select id from slots where id=? and deleted=0",slot)
                db.run("update slots set a=?,b=?,cap=? where id=?",a,b,int(cap),slot)
            else:
                db.run("insert into slots(map,a,b,cap) values(?,?,?,?)",mid,a,b,int(cap))
        await reply(j,f"Draft saved · {clock((a+delta)%1440)}–{clock((b+delta)%1440)} {zone} = {clock(a)}–{clock(b)} {map_zone}. The daily rotation follows {map_zone}.",buttons(("Back to timetable",f"manage:{mid}:0")))
    await i.response.send_modal(Form(("Daily shift · "+zone)[:45],[
        field("Start time","23:00",clock((r["a"]+delta)%1440) if r else ""),
        field("End time","03:00",clock((r["b"]+delta)%1440) if r else ""),
        field("Party seats","4",str(r["cap"]) if r else "")],save))

def slot_actions(slot,editing):
    base=[("Join as main",f"reg:{slot}:main"),("Join as sub",f"reg:{slot}:sub"),("Leave recurring roster",f"reg:{slot}:leave")]
    if editing:
        mid=db.one("select map from slots where id=?",slot)["map"]
        base = [("Assign main",f"pick:{slot}:main"),("Assign sub",f"pick:{slot}:sub"),
                 ("Remove member",f"pick:{slot}:leave"),("Edit timing / seats",f"edit:{mid}:{slot}"),
                 ("Remove from draft",f"remove:{slot}"),("Back",f"manage:{mid}:0")]
    return buttons(*base)

async def list_text(i,title,lines,view=None):
    chunks=[title]
    for line in lines:
        if len(chunks[-1])+len(line)>1850: chunks.append("")
        chunks[-1]+="\n"+line
    for chunk in chunks[:-1]: await reply(i,chunk)
    await reply(i,chunks[-1],view)

async def registration(i,slot,user,kind,staff=False):
    if staff: admin(i)
    async def save(j,note=""):
        if staff: admin(j)
        with db.tx(): db.assign(slot,user,kind,note)
        await reply(j,"Recurring roster updated. Shifts already open for check-in keep their own roster.")
    if kind=="leave": return await save(i)
    await i.response.send_modal(Form("Daily "+kind+" assignment",[comment()],save))

class Picker(discord.ui.UserSelect):
    def __init__(self,slot,kind):
        super().__init__(placeholder="Choose a guild member")
        self.slot,self.kind=slot,kind
    async def callback(self,i):
        try:
            guard(i)
            if not isinstance(self.values[0],discord.Member) or self.values[0].bot:
                raise Rule("Choose a human guild member.")
            await registration(i,self.slot,self.values[0].id,self.kind,True)
        except Rule as e: await reply(i,str(e))

@tree.command(description="Miss one upcoming shift and call its substitutes")
async def cant_make_it(i:discord.Interaction):
    guard(i)
    await absence_menu(i,0,0)

async def absence_menu(i,week,page_num):
    choices=db.upcoming(i.user.id,now(),week)
    rows=choices[page_num*6:page_num*6+6]
    lines=[f"**{index}. {name}** · <t:{a}:F> → <t:{b}:f>" for index,(a,b,slot,name) in enumerate(rows,1)]
    actions=[(f"{index}. {name}"[:80],f"absent:{slot}:{a}:{b}") for index,(a,b,slot,name) in enumerate(rows,1)]
    if page_num: actions.append(("Previous page",f"absence:{week}:{page_num-1}"))
    if len(choices)>(page_num+1)*6: actions.append(("Next page",f"absence:{week}:{page_num+1}"))
    if week: actions.append(("Earlier week",f"absence:{week-1}:0"))
    actions.append(("Later week",f"absence:{week+1}:0"))
    title="Choose the shift you’ll miss." if rows else "You have no upcoming main seats in this week."
    title+=f" Week {week+1} · Use Later week for shifts 7 or more days ahead."
    await reply(i,"\n".join([title,*lines]),buttons(*actions))

async def absence_form(i,slot,a,b):
    async def save(j,note):
        with db.tx(): db.early_decline(j.user.id,slot,a,b,note,now())
        await reply(j,f"Sub search queued for <t:{a}:F>. Your regular signup stays in place.")
    await i.response.send_modal(Form("Find a sub for this shift",[comment()],save))

def available_openings(i):
    matches=[]
    t=now()
    for g in db.rows("select * from gaps where stage=1 and claimed=0 and b>? order by a",t):
        if i.user.id in recipients(i.guild,g,"lf",t):
            matches.append(g)
    return matches

async def lf_matches(i,num):
    matches=available_openings(i)
    await page(i,"lfmatches","all",num,matches,lambda g:(f"{maprow(instance(g['shift'])['map'])['name']} · opening #{g['id']}",f"gap:{g['id']}"),"Choose a matching opening." if matches else "No matching openings right now.")

async def lf_form(i):
    if not member_maps(i.user): raise Rule("Get a configured map role from a guild admin first.")
    async def save(j,duration,delay,note):
        maps=member_maps(j.user)
        if not maps: raise Rule("You need a map role.")
        try:
            delay_hours=float(delay or "0")
        except ValueError:
            raise Rule("Enter your start delay in hours, e.g. 0 for now or 0.5 for 30 minutes.")
        wait=0 if delay_hours==0 else hours(delay_hours)
        start=now()+wait
        end=start+hours(duration)
        with db.tx():
            db.run("insert or replace into lf(user,until,note,starts) values(?,?,?,?)",j.user.id,end,note,start)
        matches=available_openings(j)
        if matches:
            await reply(j,f"You're listed for {span(start,end)}. An opening overlaps your availability:\n{window(matches[0])}",
                        buttons(("View opening",f"gap:{matches[0]['id']}"),("All matches","lfmatches:all:0"),("Edit availability","lf"),("Stop looking","stop")))
            return
        await reply(j,f"Looking for {' / '.join(maps)} · {span(start,end)} · {clean(note)}",
                    buttons(("Matching openings","lfmatches:all:0"),("Edit availability","lf"),("Stop looking","stop")))
    await i.response.send_modal(Form("Looking for a seat",[
        field("How long are you available for?","Hours you can play after starting, e.g. 2"),
        field("How long from now are you available?","Hours until you can start: 0 = now, 0.5 = 30 min","0"),
        comment()],save))

@tree.command(description="Tell the guild when you can start and how long you can grind")
async def lf(i:discord.Interaction):
    guard(i)
    await lf_form(i)

async def give_up(i,kind):
    guard(i)
    t=now()
    seats=db.rows("select id from seats where shift>0 and user=? and a<=? and b>? order by a limit 1",i.user.id,t,t)
    if seats:
        return await release_form(i,seats[0]["id"],kind)
    await choose_map(i,"practice_"+kind)

async def practice_form(i,mid,kind):
    if kind not in ("cover","replace"):
        raise Rule("Choose cover or replacement.")
    m=maprow(mid)
    async def save(j,duration,note):
        t=now()
        end=t+hours(duration)
        with db.tx():
            sid=-db.run("insert into practice(map,a,b) values(?,?,?)",mid,t,end)
            db.run("""insert into subs(shift,user,note) select ?,sub.user,sub.note from subs sub
                      join shifts s on s.id=sub.shift where s.map=? and s.a<=? and s.b>?""",sid,mid,t,t)
            db.gap(sid,1,t,end,j.user.id,kind,note,t)
        await reply(j,f"{m['name']} {kind} request queued for {span(t,end)}.")
    await i.response.send_modal(Form("Request "+kind,[field("Hours of cover" if kind=="cover" else "Hours remaining in the shift","0.5 = 30 minutes"),comment()],save))

async def release_form(i,seat,kind):
    s=db.one("select * from seats where id=? and user=? and b>?",seat,i.user.id,now())
    async def save(j,*values):
        duration=hours(values[0]) if kind=="cover" else None
        with db.tx(): db.release(seat,j.user.id,kind,values[-1],now(),duration)
        await reply(j,"Opening posted to the delivery queue. The roster now shows the gap.")
    fields=[field("Hours of cover needed","0.5 = 30 minutes")] if kind=="cover" else []
    await i.response.send_modal(Form("Request "+kind,fields+[comment(s["note"])],save))

@tree.command(description="Find someone for the rest of your current booking")
async def replace(i:discord.Interaction):
    await give_up(i,"replace")

@tree.command(description="Find temporary cover and reserve your return time")
async def cover(i:discord.Interaction):
    await give_up(i,"cover")

async def board(i,sid):
    s=instance(sid)
    used=db.one("select count(distinct seat) n from (select seat from seats where shift=? union select seat from gaps where shift=?)",sid,sid)["n"]
    lines=[f"{s['cap']-used} vacant full-shift seat(s)"] if used<s["cap"] else []
    for r in db.rows("select * from seats where shift=? and b>? and b>a order by seat,a",sid,now()):
        lines.append(f"Seat {r['seat']} · {mention(r['user'])} · {span(r['a'],r['b'])} · {r['status']} · {clean(r['note'])}")
    for g in db.rows("select * from gaps where shift=? and claimed=0 and b>? order by seat,a",sid,now()):
        lines.append(f"Open · seat {g['seat']} · <t:{g['a']}:f> → <t:{g['b']}:f> · {clean(g['note'])}")
    for r in db.rows("select * from subs where shift=?",sid):
        lines.append(f"Sub · {mention(r['user'])} · {clean(r['note'])}")
    await list_text(i,f"**{maprow(s['map'])['name']}** · {span(s['a'],s['b'])} · {s['cap']} seats",lines,buttons(
        ("Join vacant seat",f"join:{sid}:main"),("Join as sub",f"join:{sid}:sub"),("Leave sub list",f"join:{sid}:leave"),
        ("Find open handoffs",f"gaps:{sid}:0"),("Request cover","give:cover"),("Request replacement","give:replace")))

async def join(i,sid,kind):
    async def save(j,note=""):
        u=j.user.id
        with db.tx():
            s=instance(sid)
            if s["b"]<=now(): raise Rule("Shift ended.")
            if kind=="leave": db.run("delete from subs where shift=? and user=?",sid,u)
            elif kind=="sub":
                if db.rows("select 1 from seats where shift=? and user=? and b>?",sid,u,now()):
                    raise Rule("You already hold a seat in this shift.")
                db.run("insert or replace into subs values(?,?,?)",sid,u,note)
            else:
                a=max(s["a"],now())
                if not db.available(u,a,s["b"]): raise Rule("You already hold a seat in this interval.")
                used={r["seat"] for r in db.rows("select seat from seats where shift=? union select seat from gaps where shift=?",sid,sid)}
                num=next((n for n in range(1,s["cap"]+1) if n not in used),None)
                if num is None: raise Rule("No vacant full seat. Check open handoffs.")
                db.seat(sid,num,a,s["b"],u,note,"confirmed")
                db.run("delete from subs where shift=? and user=?",sid,u)
        await reply(j,"This shift’s roster was updated.")
    if kind=="leave": return await save(i)
    await i.response.send_modal(Form("Join this shift",[comment()],save))

async def claim_form(i,gid):
    g=db.one("select * from gaps where id=? and claimed=0 and b>?",gid,now())
    s=instance(g["shift"])
    async def save(j,duration,note):
        t=now()
        with db.tx():
            listed=db.rows("select * from lf where user=? and until>?",j.user.id,t)
            is_sub=j.user.id in registered_subs(g,t)
            if s["id"]>0 and j.guild_id!=TEST_GUILD and not is_sub and maprow(s["map"])["role"] not in roles(j.user):
                raise Rule("You need the map role or a sub registration for this shift.")
            start=max(t,g["a"],listed[0]["starts"] if listed else 0)
            end=g["b"] if not duration else start+hours(duration)
            if listed: end=min(end,listed[0]["until"])
            a,b=db.claim(gid,j.user.id,t,end,note,starts=start)
        await reply(j,f"You have seat {g['seat']} for {span(a,b)} · {clean(note)}.")
    av=db.rows("select * from lf where user=? and until>?",i.user.id,now())
    prefs=db.rows("select note from subs where shift=? and user=?",s["id"],i.user.id)
    default=av[0]["note"] if av else prefs[0]["note"] if prefs else ""
    await i.response.send_modal(Form("Claim seat "+str(g["seat"]),[
        field("How long are you available for?","Hours from your start; blank = all available","",False),comment(default)],save))

async def dispatch(i,cmd,p):
    uid=i.user.id
    if cmd=="absence": return await absence_menu(i,*map(int,p))
    if cmd=="absent": return await absence_form(i,*map(int,p))
    if cmd=="lfmatches": return await lf_matches(i,int(p[1]))
    if cmd.startswith("practice_"): return await practice_form(i,int(p[0]),cmd[9:])
    if cmd=="overview": return await overview(i,p[0],int(p[1]),int(p[2]) if len(p)>2 else None,int(p[3]) if len(p)>3 else 1)
    if cmd=="zones": return await zone_prompt(i)
    if cmd=="zone": return await choose_zone(i,p[0])
    if cmd=="lf": return await lf_form(i)
    if cmd=="stop":
        with db.tx(): db.run("delete from lf where user=?",uid)
        return await reply(i,"You’ve stopped looking. Existing claims stay booked.")
    if cmd=="page":
        kind,key,num=p
        if kind=="maps":
            rows=db.rows("select * from maps order by name")
            return await page(i,kind,key,int(num),rows,lambda r:(r["name"],f"{key}:{r['id']}:0"),"Choose a map.")
        return await dispatch(i,kind,[key,num])
    if cmd in ("manage","roster","sign_up"):
        return await panel(i,int(p[0]),cmd=="manage",int(p[1]))
    if cmd=="edit": return await edit_slot(i,*map(int,p))
    if cmd=="publish":
        admin(i)
        with db.tx(): db.publish(int(p[0]), allow_gaps=i.guild_id==TEST_GUILD)
        return await reply(i,"Published. Already opened shifts finish on their existing timetable.")
    if cmd=="remove":
        admin(i)
        with db.tx(): db.run("update slots set deleted=1 where id=?",int(p[0]))
        return await reply(i,"Removed from draft. Publish the complete timetable to apply.")
    if cmd=="slot":
        slot,editing=map(int,p)
        if editing: admin(i)
        r=db.one("select * from slots where id=?" if editing else "select * from live where slot=?",slot)
        map_zone=maprow(r["map"])["tz"]
        zone=(personal_zone(uid) if editing else None) or map_zone
        delta=minute_offset(map_zone,zone,now())
        title=f"**Daily {clock((r['a']+delta)%1440)}–{clock((r['b']+delta)%1440)} {zone} · {r['cap']} seats**"
        lines=[f"{x['kind']} · {mention(x['user'])} · {clean(x['note'])}" for x in db.rows("select * from regular where slot=? order by kind",slot)]
        return await list_text(i,title,lines,slot_actions(slot,editing))
    if cmd=="reg": return await registration(i,int(p[0]),uid,p[1])
    if cmd=="pick":
        admin(i)
        v=discord.ui.View(timeout=180)
        v.add_item(Picker(int(p[0]),p[1]))
        return await reply(i,"Choose a member for the daily roster.",v)
    if cmd=="current":
        rows=db.rows("select * from shifts where map=? and b>? order by a",int(p[0]),now())
        return await page(i,"current",p[0],int(p[1]) if len(p)>1 else 0,rows,
                          lambda r:(f"Shift #{r['id']} · "+("current" if r["a"]<=now() else "checking in"),f"board:{r['id']}"),
                          "Open shift rosters" if rows else "No shift open yet.")
    if cmd=="board": return await board(i,int(p[0]))
    if cmd=="join": return await join(i,int(p[0]),p[1])
    if cmd=="give": return await give_up(i,p[0])
    if cmd=="decline": return await release_form(i,int(p[0]),"decline")
    if cmd=="yes":
        with db.tx():
            s=db.one("select * from seats where id=? and user=? and b>? and b>a",int(p[0]),uid,now())
            db.run("update seats set status='confirmed' where id=?",s["id"])
        return await reply(i,"You’re confirmed.",buttons(("View roster",f"board:{s['shift']}")))
    if cmd=="gaps":
        sid,num=map(int,p)
        rows=db.rows("select * from gaps where shift=? and claimed=0 and b>? order by a",sid,now())
        return await page(i,cmd,sid,num,rows,lambda r:(f"Seat {r['seat']} · opening #{r['id']}",f"gap:{r['id']}"),
                          "Choose an opening." if rows else "No open handoffs.")
    if cmd=="gap":
        g=db.one("select * from gaps where id=? and claimed=0 and b>?",int(p[0]),now())
        return await reply(i,window(g)+" · "+clean(g["note"]),gap_buttons(g))
    if cmd=="claim": return await claim_form(i,int(p[0]))
    if cmd=="ping":
        with db.tx(): db.ping(int(p[0]),now())
        return await reply(i,"Map-role ping queued.")
    if cmd=="lfpool":
        mid=int(p[0])
        m=maprow(mid)
        lines=[]
        for av in db.rows("select * from lf where until>? order by until",now()):
            member=i.guild.get_member(av["user"])
            if member and m["role"] in roles(member):
                lines.append(f"{mention(member.id)} · {span(max(now(),av['starts']),av['until'])} · {clean(av['note'])}")
        return await list_text(i,f"**{m['name']} · looking for a seat**",lines or ["Nobody currently listed."])

@client.event
async def on_interaction(i):
    if i.type!=discord.InteractionType.component: return
    key=i.data.get("custom_id","")
    if not key.startswith("ms:"): return
    try:
        guard(i)
        cmd,*p=key.split(":")[1:]
        await dispatch(i,cmd,p)
    except (Rule,ValueError) as e: await reply(i,str(e))
    except Exception:
        log.exception("Button failed")
        await reply(i,"Action failed. Check the roster and bot log.")

def gap_buttons(g):
    items=[("Claim all or part",f"claim:{g['id']}")]
    if not g["pinged"]: items.append(("Ping map role",f"ping:{g['id']}"))
    items.append(("View roster",f"board:{g['shift']}"))
    return buttons(*items)

def registered_subs(g,t):
    shift=instance(g["shift"])
    users={row["user"] for row in db.rows("select user from subs where shift=?",shift["id"])}
    if g["kind"] not in ("cover","replace","handoff"):
        return users
    start=max(t,g["a"])
    for row in db.rows("""select regular.user,live.a,live.b,maps.tz from regular
                          join live using(slot) join maps on maps.id=live.map
                          where live.map=? and regular.kind='sub'""",shift["map"]):
        if shift["id"]<0 or GUILD==TEST_GUILD:
            users.add(row["user"])
            continue
        days=(g["b"]-start)//86400+3
        for offset in range(-1,days):
            a,b=db.dates(row,start,offset)
            if a<g["b"] and b>start:
                users.add(row["user"])
                break
    return users

def recipients(guild,g,mode,t):
    sid=g["shift"]
    rid=maprow(instance(sid)["map"])["role"]
    a=max(t,g["a"])
    candidates=set()
    if mode!="lf":
        for user in registered_subs(g,t):
            # A registered Discord ID can be mentioned even on a cold member cache.
            if sid<0 or db.available(user,a,min(g["b"],a+1)):
                candidates.add(user)
    if mode=="lf" or (mode=="open" and g["stage"]):
        for row in db.rows("select * from lf where until>? and starts<?",a,g["b"]):
            member=guild.get_member(row["user"])
            start=max(a,row["starts"])
            if member and rid in roles(member) and db.available(member.id,start,min(row["until"],g["b"])):
                candidates.add(member.id)
    candidates.discard(g["owner"])
    return sorted(candidates)

async def deliver(job,guild):
    t=now()
    kind,ref=job["kind"],job["ref"]
    if kind=="board":
        s=instance(ref)
    elif kind in ("check","return"):
        seat=db.one("select * from seats where id=?",ref)
        s=instance(seat["shift"])
        if seat["b"]<=t or seat["b"]<=seat["a"]: return
        if kind=="check" and seat["status"]!="pending": return
    else:
        g=db.one("select * from gaps where id=?",ref)
        s=instance(g["shift"])
        if g["b"]<=t or (g["claimed"] and kind!="taken"): return
    if s["b"]<=t: return
    m=maprow(s["map"])
    channel=guild.get_channel(m["channel"])
    if channel is None: raise RuntimeError(f"Map channel missing for {m['name']}")
    if kind=="board":
        return await channel.send(f"**{m['name']} shift** · {span(s['a'],s['b'])} · {s['cap']} seats",
                                  view=buttons(("View / join roster",f"board:{ref}"),("Looking for a seat",f"lfpool:{m['id']}")))
    if kind in ("check","return"):
        u=seat["user"]
        msg="Are you showing up?" if kind=="check" else "Your temporary cover is ending. Are you back?"
        return await channel.send(f"{mention(u)} · {m['name']} seat {seat['seat']} · {span(seat['a'],seat['b'])} · {clean(seat['note'])}\n{msg}",
            allowed_mentions=discord.AllowedMentions(users=[discord.Object(u)]),
            view=buttons(("I’m showing up" if kind=="check" else "I’m back",f"yes:{ref}"),("I can’t make it",f"decline:{ref}")))
    if kind=="taken":
        post=db.rows("select * from posts where gap=?",ref)
        if post:
            old=guild.get_channel(post[0]["channel"])
            if old:
                try: await old.get_partial_message(post[0]["message"]).edit(view=buttons(("View updated roster",f"board:{s['id']}")))
                except discord.NotFound: pass
        claim=db.one("select * from claims where gap=?",ref)
        return await channel.send(f"{mention(claim['user'])} takes **{m['name']} seat {g['seat']}** · {span(claim['a'],claim['b'])} · {clean(claim['note'])}",view=buttons(("View handoff times",f"board:{s['id']}")))
    prefix="Open " if s["id"]<0 else ""
    msg=f"**{prefix}{g['kind'].title()} · {window(g)}**\nRequested platform / comment · {clean(g['note'])}"
    if kind=="role":
        role=guild.get_role(m["role"])
        if role is None: raise RuntimeError("Configured map role missing")
        return await channel.send(f"{role.mention} · {msg}",allowed_mentions=discord.AllowedMentions(roles=[role]),view=gap_buttons(g))
    targets=recipients(guild,g,kind,t)
    if kind=="open" and g["kind"] in ("cover","replace"):
        subs=recipients(guild,g,"subs",t)
        msg+=f"\nPinged {len(subs)} available {m['name']} sub(s)." if subs else f"\nNo available {m['name']} subs. Checking /lf now."
    if kind=="open" and g["stage"]==0 and not targets:
        with db.tx():
            db.run("update gaps set stage=1 where id=?",ref)
        targets=recipients(guild,db.one("select * from gaps where id=?",ref),"lf",t)
    if kind=="lf" and not targets: return
    for start in range(0,max(1,len(targets)),50):
        fresh=db.one("select * from gaps where id=?",ref)
        if fresh["claimed"] or fresh["b"]<=now(): return
        batch=targets[start:start+50]
        sent=await channel.send(msg+"\n"+" ".join(map(mention,batch)),allowed_mentions=discord.AllowedMentions(users=[discord.Object(x) for x in batch]),view=gap_buttons(fresh))
        if kind=="open" and start==0:
            db.run("insert or replace into posts values(?,?,?)",ref,channel.id,sent.id)

@tasks.loop(seconds=10)
async def scheduler():
    guild=client.get_guild(GUILD)
    if guild is None: return
    try:
        with db.tx(): db.tick(now())
        for job in db.rows("""select jobs.* from jobs left join retries on retries.job=jobs.id
                              where coalesce(retries.after,0)<=? order by jobs.id limit 100""",now()):
            try:
                await deliver(job,guild)
                with db.tx():
                    db.run("delete from jobs where id=?",job["id"])
                    db.run("delete from retries where job=?",job["id"])
            except Exception:
                log.exception("Delivery failed for job %s",job["id"])
                db.run("insert or replace into retries values(?,?)",job["id"],now()+60)
    except Exception: log.exception("Scheduler tick failed")

@scheduler.before_loop
async def ready():
    await client.wait_until_ready()

if __name__=="__main__":
    logging.basicConfig(level=logging.INFO)
    if not GUILD or not os.getenv("DISCORD_TOKEN"):
        raise SystemExit("Set GUILD_ID and DISCORD_TOKEN first. See ADMIN-GUIDE.md.")
    client.run(os.environ["DISCORD_TOKEN"])
