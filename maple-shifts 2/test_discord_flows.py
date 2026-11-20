"""Exercise real discord.py command/modal objects against an offline Discord transport."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DB_PATH",":memory:")
import bot
from rotation import Store, Rule


class DiscordFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.t=2_000_000_000
        self.db=Store(":memory:")
        self.addCleanup(self.db.db.close)
        self.addCleanup(patch.stopall)
        patch.object(bot,"db",self.db).start()
        patch.object(bot,"GUILD",123).start()
        patch.object(bot,"now",return_value=self.t).start()
        self.members={u:SimpleNamespace(id=u,roles=[SimpleNamespace(id=r) for r in rs])
                      for u,rs in [(1,[10]),(2,[10]),(3,[11]),(4,[10,11]),(5,[])]}
        self.guild=SimpleNamespace(get_member=self.members.get)
        for mid in [1,2]:
            self.db.run("insert into maps values(?,?,?,?,?)",mid,["DSG","FH"][mid-1],mid+9,20,"UTC")
        self.db.run("insert into shifts values(1,1,1,?,?,4)",self.t-300,self.t+10800)
        self.seat=self.db.seat(1,1,self.t-300,self.t+10800,1,"3F","confirmed")
        self.db.run("insert into subs values(1,5,'left')")

    def interaction(self,u=1):
        return SimpleNamespace(guild_id=123,user=self.members[u],guild=self.guild,
            permissions=SimpleNamespace(manage_guild=False),
            response=SimpleNamespace(send_modal=AsyncMock(),send_message=AsyncMock(),is_done=lambda:False))

    async def modal(self,i,call,*values):
        await call
        form=i.response.send_modal.await_args.args[0]
        self.assertIsNotNone(form.to_dict())
        await form.submit(i,*values)

    async def test_lf_roles_form_and_partial_claim(self):
        i=self.interaction(4)
        await self.modal(i,bot.lf.callback(i),"1.5","bottom")
        self.assertIn("DSG / FH",i.response.send_message.await_args.args[0])
        main=self.interaction()
        await self.modal(main,bot.replace.callback(main),"3F/4F")
        gap=self.db.one("select * from gaps")
        self.assertEqual(bot.recipients(self.guild,gap,"open",self.t),[5])
        await self.modal(i,bot.claim_form(i,gap["id"]),"","bottom")
        rest=self.db.one("select * from gaps where claimed=0")
        self.assertEqual((rest["a"],rest["note"]),(self.t+5400,"3F/4F"))
        self.assertEqual(bot.recipients(self.guild,rest,"open",self.t),[5])

    async def test_lf_needs_map_role(self):
        with self.assertRaises(Rule): await bot.lf.callback(self.interaction(5))

    async def test_cover_from_button(self):
        i=self.interaction()
        await self.modal(i,bot.dispatch(i,"give",["cover"]),"0.5","bottom")
        g=self.db.one("select * from gaps")
        self.assertEqual(g["b"],self.t+1800)
        self.assertEqual(self.db.one("select a from seats where status='return'")[0],g["b"])

    async def test_global_button_and_claim_eligibility(self):
        g=self.db.release(self.seat,1,"replace","bottom",self.t)
        outside=self.interaction(3)
        await bot.dispatch(outside,"ping",[str(g)])
        with self.assertRaises(Rule):
            await self.modal(outside,bot.claim_form(outside,g),"","")
        sub=self.interaction(5)
        await self.modal(sub,bot.claim_form(sub,g),"","left")
        self.assertEqual(self.db.one("select user from seats where status='confirmed' order by id desc limit 1")[0],5)

    async def test_recurring_admin_button_checks_permission(self):
        with self.assertRaises(Rule): await bot.dispatch(self.interaction(4),"publish",["1"])

    async def test_notification_mentions_and_clickable_buttons(self):
        channel=SimpleNamespace(id=20,send=AsyncMock(return_value=SimpleNamespace(id=999)))
        role=SimpleNamespace(id=10,mention="<@&10>")
        self.guild.get_channel=lambda _:channel
        self.guild.get_role=lambda _:role
        g=self.db.release(self.seat,1,"replace","3F @everyone",self.t)
        await bot.deliver(dict(kind="open",ref=g),self.guild)
        args=channel.send.await_args
        self.assertIn("<@5>",args.args[0])
        self.assertNotIn("@everyone",args.args[0])
        self.assertIn("ms:ping:",str(args.kwargs["view"].to_components()))
        await bot.dispatch(self.interaction(3),"ping",[str(g)])
        await bot.deliver(dict(kind="role",ref=g),self.guild)
        args=channel.send.await_args
        self.assertEqual(args.kwargs["allowed_mentions"].roles,[role])

    async def test_checkin_is_personal(self):
        self.db.run("update seats set status='pending' where id=?",self.seat)
        with self.assertRaises(Rule): await bot.dispatch(self.interaction(4),"yes",[str(self.seat)])
        await bot.dispatch(self.interaction(),"yes",[str(self.seat)])
        self.assertEqual(self.db.one("select status from seats")[0],"confirmed")

    async def test_personal_zones_and_overnight_edit(self):
        bot.ensure_zone_table(self.db)
        i=self.interaction(1)
        i.permissions.manage_guild=True
        await bot.manage.callback(i)
        self.assertIn("Choose your timezone",i.response.send_message.await_args.args[0])
        await bot.choose_zone(i,"Asia/Seoul")
        self.assertIsNone(bot.personal_zone(2))
        self.db.run("update maps set tz='Asia/Singapore' where id=1")
        await self.modal(i,bot.edit_slot(i,1,0),"00:00","04:00","4")
        slot=self.db.one("select * from slots")
        self.assertEqual((slot["a"],slot["b"]),(1380,180))
        await bot.edit_slot(i,1,slot["id"])
        fields=i.response.send_modal.await_args.args[0].children
        self.assertEqual([f.default for f in fields[:2]],["00:00","04:00"])
        await bot.choose_zone(i,"Asia/Kolkata")
        await self.modal(i,bot.edit_slot(i,1,slot["id"]),"20:30","00:30","5")
        self.assertEqual(tuple(self.db.one("select a,b,cap from slots")),(1380,180,5))

    async def test_sign_up_without_role_or_manage_permission(self):
        member=self.interaction(5)
        self.assertFalse(member.user.roles)
        cmd=bot.tree.get_command("sign_up")
        self.assertIsNotNone(bot.tree.get_command("roster"))
        await cmd.callback(member)
        def actions():
            return {c.custom_id for c in member.response.send_message.await_args.kwargs["view"].children}
        self.assertIn("ms:sign_up:1:0",actions())
        await bot.dispatch(member,"sign_up",["1","0"])
        self.assertIn("No daily shifts published",member.response.send_message.await_args.args[0])
        slot=self.db.run("insert into slots(map,a,b,cap) values(1,1380,60,4)")
        manager=self.interaction(1)
        manager.permissions.manage_guild=True
        with self.assertRaisesRegex(Rule,"Gap"):
            await bot.dispatch(manager,"publish",["1"])
        manager.guild_id=1573064240598618252
        await bot.dispatch(manager,"publish",["1"])
        await bot.dispatch(member,"sign_up",["1","0"])
        self.assertIn(f"ms:slot:{slot}:0",actions())
        await bot.dispatch(member,"slot",[str(slot),"0"])
        self.assertIn(f"ms:reg:{slot}:main",actions())
        for kind in ["main","sub"]:
            await self.modal(member,bot.dispatch(member,"reg",[str(slot),kind]),"bottom")
            self.assertEqual(self.db.one("select kind from regular where slot=? and user=?",slot,5)[0],kind)

    async def test_practice_handoffs_without_role_or_shift(self):
        self.db.run("delete from shifts")
        for kind in ("cover","replace"):
            i=self.interaction(5)
            await bot.tree.get_command(kind).callback(i)
            action=i.response.send_message.await_args.kwargs["view"].children[0].custom_id
            _,cmd,*parts=action.split(":")
            await self.modal(i,bot.dispatch(i,cmd,parts),"0.5","bottom")
            g=self.db.one("select * from gaps order by id desc limit 1")
            self.assertEqual(bot.instance(g["shift"])["map"],1)
            self.assertEqual(g["kind"],kind)
            other=self.interaction(3)
            await self.modal(other,bot.claim_form(other,g["id"]),"","")
        self.assertFalse(self.db.rows("select * from shifts"))

    async def test_roster_selects_current_party_only(self):
        i=self.interaction(1)
        await bot.roster.callback(i,"Asia/Singapore")
        embed=i.response.send_message.await_args.kwargs["embed"]
        self.assertIn("DSG",embed.title)
        self.assertNotIn("FH",embed.description)
        self.assertIn("<@1>",embed.description)
        self.assertIn("<@5>",embed.description)
        self.assertIn("Asia/Singapore",embed.footer.text)

    async def test_roster_ambiguous_party_prompts(self):
        i=self.interaction(5)
        await bot.roster.callback(i)
        kwargs=i.response.send_message.await_args.kwargs
        self.assertNotIn("embed",kwargs)
        self.assertEqual(len(kwargs["view"].children),2)

    async def test_roster_channel_wins_and_default_local(self):
        self.db.run("update maps set channel=21 where id=2")
        i=self.interaction(1)
        i.channel_id=21
        await bot.roster.callback(i)
        embed=i.response.send_message.await_args.kwargs["embed"]
        self.assertIn("FH",embed.title)
        self.assertIn("No shifts",embed.description)
        self.assertIn("local timezone",embed.footer.text)

    async def test_roster_horizon_and_actual_roster(self):
        self.db.run("insert into shifts values(2,1,2,?,?,4)",self.t+86400,self.t+90000)
        self.db.run("insert into shifts values(3,1,3,?,?,4)",self.t-10000,self.t)
        self.db.run("insert into shifts values(4,1,4,?,?,4)",self.t+86399,self.t+95000)
        self.db.run("insert into live values(1,1,0,0,4)")
        self.db.run("insert into regular values(1,999,'main','')")
        rows=bot.roster_entries(1,self.t)
        self.assertFalse(any(a==self.t+86400 or b==self.t for a,b,*_ in rows))
        self.assertTrue(any(a==self.t+86399 for a,*_ in rows))
        current=[e for e in rows if e[0]<=self.t<e[1]]
        self.assertEqual(len(current),1)
        self.assertNotIn("<@999>",str(current))
        self.assertFalse(self.db.rows("select * from jobs"))

    async def test_roster_overnight_occurrence_not_duplicated(self):
        self.db.run("delete from shifts")
        self.db.run("insert into live values(7,1,1380,60,4)")
        r=self.db.one("select live.*,maps.tz from live join maps on maps.id=live.map")
        a,b=self.db.dates(r,self.t,0)
        t=a+1800
        self.db.run("insert into shifts values(7,1,7,?,?,4)",a,b)
        self.db.seat(7,1,a,b,2,"left","confirmed")
        self.db.run("insert into regular values(7,999,'main','')")
        rows=bot.roster_entries(1,t)
        self.assertEqual(len([r for r in rows if r[0]==a]),1)
        self.assertIn("<@2>",str(rows[0]))
        self.assertNotIn("<@999>",str(rows[0]))
        self.assertTrue(any(r[0]==a+86400 for r in rows))

    async def test_advance_absence_call_and_reminder(self):
        db=self.db
        slot=db.run("insert into slots(map,a,b,cap) values(2,0,180,4)")
        db.publish(2,allow_gaps=True)
        db.assign(slot,3,"main","left")
        db.assign(slot,4,"sub","")
        a,b,_,_=db.upcoming(3,self.t)[2]
        i=self.interaction(3)
        await bot.cant_make_it.callback(i)
        await self.modal(i,bot.absence_form(i,slot,a,b),"left")
        g=db.one("select * from gaps")
        self.assertEqual((g["stage"],g["a"],g["b"]),(0,a,b))
        self.assertEqual(bot.recipients(self.guild,g,"open",self.t),[4])
        self.assertFalse(db.rows("select * from jobs where kind='check'"))
        with self.assertRaises(Rule), db.tx(): db.early_decline(3,slot,a,b,"",self.t)
        db.tick(self.t+301)
        db.run("insert into lf values(?,?,?)",4,b,"")
        self.assertEqual([x["id"] for x in bot.available_openings(self.interaction(4))],[g["id"]])
        db.claim(g["id"],4,self.t+301,a+3600,"")
        self.assertEqual(db.one("select a from gaps where claimed=0")[0],a+3600)
        db.tick(a-1800)
        self.assertTrue(db.rows("select * from jobs join seats on ref=seats.id where jobs.kind='check' and user=4"))
        self.assertTrue(db.rows("select * from regular where kind='main' and user=3"))
        self.assertEqual(len(db.rows("select * from shifts where map=2 and a=?",a)),1)

    async def test_open_requests_without_running_shift_ping_subs_before_lf(self):
        self.db.run("delete from subs")
        self.db.run("delete from shifts")
        self.db.run("insert into live values(101,1,0,0,4)")
        self.db.run("insert into regular values(101,5,'sub','')")
        self.db.run("insert into lf values(2,?,'')",self.t+3600)
        channel=SimpleNamespace(id=20,send=AsyncMock(return_value=SimpleNamespace(id=999)))
        self.guild.get_channel=lambda _:channel
        for kind in ("replace","cover"):
            i=self.interaction(3)
            await self.modal(i,bot.practice_form(i,1,kind),"1","bottom")
            gap=self.db.one("select * from gaps order by id desc limit 1")
            await bot.deliver(dict(kind="open",ref=gap["id"]),self.guild)
            self.assertEqual([u.id for u in channel.send.await_args.kwargs["allowed_mentions"].users],[5])
            self.db.tick(self.t+300)
            await bot.deliver(dict(kind="lf",ref=gap["id"]),self.guild)
            self.assertEqual([u.id for u in channel.send.await_args.kwargs["allowed_mentions"].users],[2])

    async def test_open_request_mentions_planned_sub_even_if_uncached_or_booked(self):
        minute=(self.t//60+600)%1440
        self.db.run("insert into live values(101,1,?,?,4)",minute,(minute+60)%1440)
        self.db.run("insert into regular values(101,5,'sub','')")
        self.db.run("delete from subs")
        self.db.seat(1,2,self.t,self.t+3600,5,"","confirmed")
        self.guild.get_member=lambda _:None
        channel=SimpleNamespace(id=20,send=AsyncMock(return_value=SimpleNamespace(id=999)))
        self.guild.get_channel=lambda _:channel
        for kind in ("replace","cover"):
            i=self.interaction(3)
            await self.modal(i,bot.practice_form(i,1,kind),"1","help")
            gap=self.db.one("select * from gaps order by id desc limit 1")
            await bot.deliver(dict(kind="open",ref=gap["id"]),self.guild)
            args=channel.send.await_args
            self.assertIn("<@5>",args.args[0])
            self.assertEqual([u.id for u in args.kwargs["allowed_mentions"].users],[5])
