"""One read of a source at a time: a second read steps aside and the rows stay. Made-up sources only."""
import json, os, subprocess, sys, threading, time, unittest
from unittest import mock
from tests import fixture
from ctx import collect, signed_in


def row(i):
    return json.dumps({"id": "ZL" + i, "src": "zlock", "ts": "2026-01-01T00:00:00Z", "title": "", "text": "made-up " + i}) + "\n"


class Lock(unittest.TestCase):
    def tearDown(self):
        for p in (collect._part("zlock"), collect._part("zlock") + ".new", os.path.join(collect.LOCKS, "zlock.lock")):
            if os.path.exists(p):
                os.remove(p)

    def lockfile(self, text, age=0):
        os.makedirs(collect.LOCKS, exist_ok=True)
        p = os.path.join(collect.LOCKS, "zlock.lock")
        with open(p, "w") as f:
            f.write(text)
        if age:
            os.utime(p, (time.time() - age,) * 2)
        return p

    def test_a_lock_is_one_at_a_time_and_given_back(self):
        a = collect.take_lock("zlock")
        self.assertTrue(a and os.path.exists(a))
        self.assertIsNone(collect.take_lock("zlock"))
        other = collect.take_lock("zlock_other")                       # another source is not held up
        self.assertTrue(other)
        collect.drop_lock(other)
        collect.drop_lock(a)
        b = collect.take_lock("zlock")
        self.assertTrue(b)
        collect.drop_lock(b)
        self.assertFalse(os.path.exists(b))

    def test_a_lock_left_by_a_read_that_died_is_taken_over(self):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        self.lockfile("%d %f" % (dead.pid, time.time()))
        got = collect.take_lock("zlock")
        self.assertTrue(got)
        with open(got) as f:
            self.assertEqual(int(f.read().split()[0]), os.getpid())
        collect.drop_lock(got)

    def test_a_lock_too_old_to_be_a_read_is_taken_over_even_if_its_number_is_in_use(self):
        self.lockfile("%d %f" % (os.getpid(), time.time() - collect.LOCK_STALE - 5))
        got = collect.take_lock("zlock")
        self.assertTrue(got)
        collect.drop_lock(got)

    def test_a_live_read_in_another_process_holds_it(self):
        self.lockfile("%d %f" % (os.getppid(), time.time() - 60))
        self.assertIsNone(collect.take_lock("zlock"))

    def test_a_damaged_lock_holds_only_while_it_is_fresh(self):
        self.lockfile("")
        self.assertIsNone(collect.take_lock("zlock"))                  # may be half-written by a read that is starting
        self.lockfile("not a lock", age=60)
        got = collect.take_lock("zlock")
        self.assertTrue(got)
        collect.drop_lock(got)

    def test_a_second_read_of_a_source_steps_aside_and_the_rows_stay(self):
        started, go = threading.Event(), threading.Event()

        def slow(days, out):
            for i in "abc":
                out.write(row(i))
            started.set()
            go.wait(20)
            return 3
        with open(collect._part("zlock"), "w") as f:                    # what the last read left
            f.write(row("a") + row("b"))
        first = {}
        try:
            with mock.patch.dict(collect.BY_NAME, {"zlock": (collect.D, slow)}), mock.patch.object(collect, "assemble", lambda g: None), \
                    mock.patch.object(collect, "_save_status", lambda n, st: None):
                t = threading.Thread(target=lambda: first.update(collect.collect_one("zlock", join=False)))
                t.start()
                self.assertTrue(started.wait(20))
                st = collect.collect_one("zlock", join=False)           # while the first is still writing zlock.jsonl.new
                self.assertEqual(st, {"rows": 2, "new": 0, "skipped": collect.BUSY})
                self.assertTrue(os.path.exists(collect._part("zlock") + ".new"))      # the first read's file was not touched
                go.set()
                t.join(20)
                self.assertEqual((first["rows"], first["new"]), (3, 1))
                self.assertEqual(collect._count(collect._part("zlock")), 3)
                self.assertFalse(os.path.exists(os.path.join(collect.LOCKS, "zlock.lock")))
                self.assertEqual(collect.collect_one("zlock", join=False)["rows"], 3)       # and the next read goes ahead
        finally:
            go.set()

    def test_a_read_that_breaks_gives_the_lock_back(self):
        def broken(days, out):
            raise RuntimeError("made-up failure")
        with mock.patch.dict(collect.BY_NAME, {"zlock": (collect.D, broken)}), mock.patch.object(collect, "assemble", lambda g: None), \
                mock.patch.object(collect, "_save_status", lambda n, st: None):
            self.assertIn("skipped", collect.collect_one("zlock", join=False))
        self.assertFalse(os.path.exists(os.path.join(collect.LOCKS, "zlock.lock")))

    def test_a_signed_in_read_steps_aside_too(self):
        held = collect.take_lock("signed_in_x_likes")
        try:
            with mock.patch.object(signed_in, "_x_list", side_effect=AssertionError("must not read")):
                r = signed_in.x_likes()
            self.assertEqual((r["state"], r["detail"], r["new"]), ("skipped", collect.BUSY, 0))
        finally:
            collect.drop_lock(held)


class Status(unittest.TestCase):
    def test_two_processes_saving_results_both_keep_their_lines(self):
        names = [n for n, _, _ in collect.TABLE][:16]
        home = os.path.join(fixture.HOME, "status-race")
        os.makedirs(home, exist_ok=True)
        code = ("import sys\nfrom ctx import collect\nfor k in range(25):\n    for n in sys.argv[1:]:\n        collect._save_status(n, {'rows': k})\n")
        env = dict(os.environ, CTX_HOME=home, PYTHONPATH=fixture.REPO)
        ps = [subprocess.Popen([sys.executable, "-c", code] + names[i::2], env=env, cwd=fixture.REPO, stderr=subprocess.PIPE) for i in (0, 1)]
        for p in ps:
            self.assertEqual(p.wait(120), 0, p.stderr.read().decode()[-400:])
            p.stderr.close()
        with open(os.path.join(home, "status.json")) as f:
            got = json.load(f)
        self.assertEqual({n: got.get(n) for n in names}, {n: {"rows": 24} for n in names})
        self.assertEqual([f for f in os.listdir(home) if ".new" in f], [])


if __name__ == "__main__":
    unittest.main()
