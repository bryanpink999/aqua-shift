import os
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from rotation import Store, Rule, hours, minutes, validate

def utc(h,m=0):
    return int(datetime(2026,11,20,h,m,tzinfo=timezone.utc).timestamp())

class RotationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=os.path.join(self.tmp.name,"test.db")
        self.db=Store(self.path)
        self.addCleanup(self.db.db.close)
        self.db.run("insert into maps values(1,'DSG',10,20,'UTC')")
        self.slot=self.db.run("insert into slots(map,a,b,cap) values(1,0,720,4)")
        self.night=self.db.run("insert into slots(map,a,b,cap) values(1,720,0,4)")
        self.db.publish(1)
        self.db.assign(self.slot,11,"main","bottom")
        self.db.assign(self.slot,22,"sub","3F")
        self.db.tick(utc(0))
        self.main=self.db.one("select * from seats")

    def gap(self,kind="replace",duration=None):
        return self.db.release(self.main["id"],11,kind,"left platform",utc(1),duration)

    def test_clock(self):
        self.assertEqual(minutes("23:59"),1439)
        self.assertEqual(hours(".5"),1800)
        for value in ["NaN","inf","0","-1","foo"]:
            with self.assertRaises(Rule): hours(value)

    def test_full_day_and_midnight(self):
        validate([dict(a=1380,b=180),dict(a=180,b=1380)])
        validate([dict(a=60,b=60)])
        for starts in [(0,601),(0,599)]:
            with self.assertRaises(Rule):
                validate([dict(a=starts[0],b=600),dict(a=starts[1],b=0)])

    def test_party_size_and_change_kind(self):
        for u in [12,13,14]: self.db.assign(self.slot,u,"main","")
        with self.assertRaises(Rule): self.db.assign(self.slot,15,"main","")
        self.db.assign(self.slot,14,"sub","")
        self.db.assign(self.slot,15,"main","top")
        self.assertEqual(len(self.db.rows("select * from regular where kind='main'")),4)

    def test_partial_cover_preserves_return_and_notes(self):
        g=self.gap("cover",3600)
        self.db.claim(g,22,utc(1),utc(1,30),"can do left")
        tail=self.db.one("select * from gaps where claimed=0")
        self.assertEqual((tail["a"],tail["b"],tail["note"]),(utc(1,30),utc(2),"left platform"))
        self.db.claim(tail["id"],33,utc(1),utc(5),"left")
        self.db.tick(utc(2))
        self.db.tick(utc(2))
        self.assertEqual(len(self.db.rows("select * from jobs where kind='return'")),1)
        self.assertEqual(self.db.one("select * from seats where status='return due'")["user"],11)

    def test_replacement_only_today(self):
        g=self.gap()
        self.db.claim(g,22,utc(1),utc(16),"top")
        self.assertEqual(self.db.one("select user from regular where kind='main'")[0],11)
        self.db.tick(utc(0)+86400)
        self.assertEqual(self.db.one("select user from seats where a=?",utc(0)+86400)[0],11)

    def test_foreign_decline(self):
        with self.assertRaises(Rule): self.db.release(self.main["id"],22,"decline","",utc(1))

    def test_double_decline_before_start(self):
        self.db.assign(self.night,44,"main","")
        self.db.tick(utc(11,30))
        seat=self.db.one("select id from seats where user=44")[0]
        self.db.release(seat,44,"decline","",utc(11,32))
        with self.assertRaises(Rule): self.db.release(seat,44,"decline","",utc(11,32))

    def test_decline_subs_first_then_lf(self):
        self.db.assign(self.night,44,"main","")
        self.db.assign(self.night,55,"sub","")
        self.db.tick(utc(11,30))
        seat=self.db.one("select id from seats where user=44")[0]
        g=self.db.release(seat,44,"decline","",utc(11,32))
        self.assertEqual(self.db.one("select stage from gaps where id=?",g)[0],0)
        self.db.ping(g,utc(11,32))
        self.db.tick(utc(11,37))
        self.assertEqual(len(self.db.rows("select id from jobs where kind='lf'")),1)

    def test_one_map_ping_per_open_gap(self):
        g=self.gap()
        self.db.ping(g,utc(1))
        with self.assertRaises(Rule): self.db.ping(g,utc(1))
        self.db.claim(g,22,utc(1),utc(2),"")
        with self.assertRaises(Rule): self.db.ping(g,utc(1))

    def test_exclusive_claim_using_two_connections(self):
        g=self.gap()
        barrier=threading.Barrier(2)
        outcomes=[]
        def claim(uid):
            db=Store(self.path)
            barrier.wait()
            try:
                with db.tx(): db.claim(g,uid,utc(1),utc(12),"")
                outcomes.append("won")
            except Rule: outcomes.append("lost")
            finally: db.db.close()
        ts=[threading.Thread(target=claim,args=(i,)) for i in [22,33]]
        for t in ts:t.start()
        for t in ts:t.join()
        self.assertCountEqual(outcomes,["won","lost"])

    def test_cross_map_conflict(self):
        g=self.gap()
        self.db.seat(900,1,utc(2),utc(3),22,"other map","confirmed")
        with self.assertRaises(Rule): self.db.claim(g,22,utc(1),utc(4),"")
        self.db.claim(g,22,utc(1),utc(2),"")

    def test_expired_claim_and_owner(self):
        g=self.gap()
        for uid,t,end in [(11,utc(1),utc(4)),(22,utc(12),utc(16)),(22,utc(1),utc(1))]:
            with self.assertRaises(Rule): self.db.claim(g,uid,t,end,"")

    def test_cover_too_long_preserves_seat(self):
        with self.assertRaises(Rule): self.gap("cover",12*3600)
        self.assertEqual(self.db.one("select b from seats")[0],utc(12))

    def test_restart_dedup(self):
        db=Store(self.path)
        try:
            db.tick(utc(0,1))
            self.assertEqual(len(db.rows("select id from jobs where kind='check'")),1)
            self.assertEqual(len(db.rows("select id from shifts")),1)
        finally: db.db.close()

    def test_draft_does_not_move_live_shift(self):
        self.db.run("update slots set b=660 where id=?",self.slot)
        with self.assertRaises(Rule): self.db.publish(1)
        self.db.run("update slots set a=660 where id=?",self.night)
        self.db.publish(1)
        self.db.tick(utc(11,40))
        current=self.db.rows("select a,b from shifts order by a")
        self.assertEqual(current[0]["b"],utc(12))
        self.assertEqual(current[1]["a"],utc(12))

    def test_reminder_window(self):
        self.db.assign(self.night,44,"main","")
        self.db.tick(utc(11,29))
        self.assertFalse(self.db.rows("select * from seats where user=44"))
        self.db.tick(utc(11,30))
        self.assertTrue(self.db.rows("select * from seats where user=44"))

    def test_expiring_lf(self):
        self.db.run("insert into lf values(33,?,'any')",utc(2))
        self.db.tick(utc(2))
        self.assertFalse(self.db.rows("select * from lf"))

    def test_cancelled_future_seat_does_not_block_other_map(self):
        self.db.assign(self.night,44,"main","")
        self.db.tick(utc(11,30))
        seat=self.db.one("select id from seats where user=44")[0]
        self.db.release(seat,44,"decline","",utc(11,32))
        self.assertTrue(self.db.available(44,utc(11),utc(13)))

    def test_singapore_midnight(self):
        self.db.run("insert into maps values(2,'FH',11,21,'Asia/Singapore')")
        for a,b in [(1380,180),(180,1380)]:
            self.db.run("insert into slots(map,a,b,cap) values(2,?,?,6)",a,b)
        self.db.publish(2)
        self.db.tick(utc(16,30))  # 00:30 Saturday in Singapore
        s=self.db.one("select * from shifts where map=2")
        self.assertEqual((s["a"],s["b"],s["cap"]),(utc(15),utc(19),6))

    def test_test_server_still_rejects_overlap_and_empty_draft(self):
        with self.assertRaisesRegex(Rule,"Overlap"):
            validate([dict(a=1380,b=60),dict(a=30,b=90)],allow_gaps=True)
        with self.assertRaises(Rule): validate([],allow_gaps=True)
