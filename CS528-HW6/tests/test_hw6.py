import copy
from datetime import datetime
import json
from pathlib import Path
import tempfile
import sqlite3
import unittest
from unittest.mock import patch

import config as C
import database
import infra
from models import PrefixCountry, features, income_split


def fixture():
    requests=[]
    for i in range(2):
        requests.append(dict(request_id=str(i),request_time=f"2026-10-21 00:00:0{i}",run_id=C.RUN_ID,
            method="GET",requested_file="data/0.html",client_ip=f"10.20.30.{i+1}",country="Example",
            peer_ip="127.0.0.1",gender="Female",age="26-35",income="20k-40k",is_banned=False,
            client_time="2026-10-21 12:00:00",time_of_day="12:00:00",http_status=200 if i==0 else 404))
    return {"requests":requests,"failed_requests":[dict(request_time=requests[1]["request_time"],requested_file="data/0.html",error_code=404)],
        "request_timings":[dict(request_id=str(i),extract_ns=1,storage_ns=2,response_ns=3,database_ns=4,total_ns=11,storage_attempted=True,response_sent=True) for i in range(2)]}


class DataIntegrityTests(unittest.TestCase):
    def test_real_transfer_queries_preserve_rows_and_are_repeatable(self):
        # Exercise the submitted transfer statements against real SQL tables.
        # SQLite verifies transfer logic; actual MySQL DDL still needs cloud validation.
        data=fixture()
        with sqlite3.connect(':memory:') as conn:
            conn.execute("ATTACH DATABASE ':memory:' AS hw5")
            conn.execute("ATTACH DATABASE ':memory:' AS hw6")
            for name,rows in data.items():
                columns=list(rows[0])
                key='request_time' if name=='failed_requests' else 'request_id'
                defs=[k+(' INTEGER' if isinstance(rows[0][k],(int,bool)) else ' TEXT')+(' PRIMARY KEY' if k==key else '') for k in columns]
                conn.execute(f"CREATE TABLE hw5.{name} ({','.join(defs)})")
                conn.executemany(f"INSERT INTO hw5.{name} VALUES ({','.join('?' for _ in columns)})",[[r[k] for k in columns] for r in rows])
            conn.execute('CREATE TABLE hw6.countries(country TEXT PRIMARY KEY,is_banned INTEGER)')
            conn.execute('CREATE TABLE hw6.clients(client_ip TEXT PRIMARY KEY,country TEXT)')
            fields=[k for k in data['requests'][0] if k not in ('country','is_banned','time_of_day')]
            conn.execute('CREATE TABLE hw6.requests ('+','.join(k+(' INTEGER' if k=='http_status' else ' TEXT')+(' PRIMARY KEY' if k=='request_id' else '') for k in fields)+')')
            conn.execute('CREATE TABLE hw6.request_timings AS SELECT * FROM hw5.request_timings WHERE 0')
            for _ in range(2):
                for sql in database.sql_statements('migrate.sql'): conn.execute(sql,{'run_id':C.RUN_ID})
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM hw6.requests').fetchone()[0],2)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM hw6.clients').fetchone()[0],2)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM hw6.countries').fetchone()[0],1)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM hw6.request_timings').fetchone()[0],2)
            self.assertEqual(conn.execute('SELECT r.income,c.country,co.is_banned FROM hw6.requests r JOIN hw6.clients c USING(client_ip) JOIN hw6.countries co USING(country) ORDER BY r.request_id').fetchall(), [('20k-40k','Example',0)]*2)

    def test_valid_source_and_counts(self):
        self.assertEqual(database.audit_source(fixture(),expected=2)["clients"],2)

    def test_conflicting_ip_rejected(self):
        data=fixture();data["requests"][1].update(client_ip="10.20.30.1",country="Elsewhere")
        with self.assertRaisesRegex(ValueError,"IP -> country"): database.audit_source(data,expected=2)

    def test_country_policy_conflict_rejected(self):
        data=fixture();data["requests"][1]["is_banned"]=True
        with self.assertRaisesRegex(ValueError,"country ->"): database.audit_source(data,expected=2)

    def test_derived_time_mismatch_rejected(self):
        data=fixture();data["requests"][1]["time_of_day"]="09:00:00"
        with self.assertRaisesRegex(ValueError,"time_of_day"): database.audit_source(data,expected=2)

    def test_unrecoverable_failure_row_rejected(self):
        data=fixture();data["failed_requests"][0]["requested_file"]="different.html"
        with self.assertRaisesRegex(ValueError,"Failure rows"): database.audit_source(data,expected=2)

    def test_missing_timing_rejected(self):
        data=fixture();data["request_timings"].pop()
        with self.assertRaisesRegex(ValueError,"Timing records"): database.audit_source(data,expected=2)

    def test_field_hash_detects_changes_but_handles_mysql_types(self):
        data=fixture();other=copy.deepcopy(data)
        for row in other["requests"]:
            row["request_time"]=datetime.fromisoformat(row["request_time"])
            row["is_banned"]=int(row["is_banned"])
        self.assertEqual(database.hashes(data),database.hashes(other))
        other["requests"][0]["income"]="0-10k"
        self.assertNotEqual(database.hashes(data),database.hashes(other))


class ModelingTests(unittest.TestCase):
    def test_country_generalizes_to_unseen_ip_and_falls_back(self):
        model=PrefixCountry().fit(["10.20.30.1","10.20.31.1","20.1.1.1"],["A","A","B"])
        pred,levels=model.predict_with_level(["10.20.30.99","10.20.99.99","20.9.9.9","90.1.1.1"])
        self.assertEqual(pred,["A","A","B","A"]);self.assertEqual(levels,[24,16,8,0])

    def test_fixed_splits_are_disjoint_and_order_independent(self):
        rows=[{"request_id":str(i)} for i in range(100)]
        split=income_split(rows)
        self.assertEqual(split,income_split(list(reversed(rows))))
        ids=[{r["request_id"] for r in part} for part in split]
        self.assertEqual([len(s) for s in ids],[60,20,20])
        self.assertFalse(ids[0]&ids[1] or ids[1]&ids[2] or ids[0]&ids[2])

    def test_income_features_do_not_depend_on_target_or_request_id(self):
        rows=fixture()["requests"];other=copy.deepcopy(rows)
        for r in other: r.update(income="changed",request_id="changed",http_status=999)
        self.assertTrue(features(rows).equals(features(other)))


class CleanupTests(unittest.TestCase):
    def test_resume_download_failure_still_cleans_up_without_printing(self):
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory)/"state.json"
            state.write_text(json.dumps({"project":C.PROJECT,"run":"20261103-015057-b504",
                "vm":"cs528-hw6-20261103-015057-b504",
                "output_uri":f"gs://{C.BUCKET}/cs528-hw6/runs/20261103-015057-b504/"}))
            with patch.object(infra,"download_outputs",side_effect=RuntimeError("checksum mismatch")),patch.object(infra,"cleanup") as cleanup,patch.object(infra,"print_outputs") as printed:
                with self.assertRaisesRegex(RuntimeError,"checksum mismatch"): infra.resume(state)
                cleanup.assert_called_once_with(state)
                printed.assert_not_called()

    def test_leftover_boot_disk_prevents_verified_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory)/"state.json"
            state.write_text(json.dumps({"project":C.PROJECT,"vm":"cs528-hw6-test"}))
            def describe(parts):
                return {"name":"cs528-hw6-test"} if parts[:3]==["compute","disks","describe"] else None
            with patch.object(infra,"sql_status",return_value={"state":"STOPPED","settings":{"activationPolicy":"NEVER"}}),patch.object(infra,"describe",side_effect=describe):
                with self.assertRaisesRegex(RuntimeError,"Cleanup incomplete"): infra.cleanup(state)
            evidence=json.loads((state.parent/"cleanup.json").read_text())
            self.assertFalse(evidence["boot_disk_absent"])
            self.assertFalse(evidence["verified"])

    def test_sql_failure_does_not_skip_vm_removal(self):
        calls=[]
        def describe(parts):
            if parts[:3]==["compute","instances","describe"]: return {"description":C.MARKER}
            return None
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory)/"state.json"
            state.write_text(json.dumps({"project":C.PROJECT,"vm":"cs528-hw6-test","sql_start_intent":True}))
            with patch.object(infra,"sql_status",side_effect=RuntimeError("simulated SQL outage")),patch.object(infra,"describe",side_effect=describe),patch.object(infra,"cloud",side_effect=lambda p,**kw:calls.append(p)):
                with self.assertRaisesRegex(RuntimeError,"Cleanup incomplete"): infra.cleanup(state)
            self.assertTrue(any(c[:3]==["compute","instances","delete"] for c in calls))
            self.assertFalse(json.loads((state.parent/"cleanup.json").read_text())["verified"])

    def test_resource_with_wrong_owner_is_not_deleted(self):
        with self.assertRaisesRegex(RuntimeError,"ownership marker"):
            infra.check_owned({"description":"someone else's VM"})


if __name__=="__main__": unittest.main()
