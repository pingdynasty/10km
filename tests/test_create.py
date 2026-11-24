"""10km create (R339-R341)."""
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: E402  (test config, no caller env: tests/testenv.py)
from testenv import BIN, CODE  # noqa: E402
from tenkm import config, create, presets, runloop  # noqa: E402


class CreateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="10km-create-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.env = dict(testenv.clean_env(), **testenv.GIT_ID, **testenv.HOST_GIT_OFF)
        self.src = os.path.join(self.tmp, "src")  # a 10km checkout with an origin
        testenv.loop_repo(self.src)
        self.git(self.src, "remote", "add", "origin", "https://example.com/10km.git")

    def git(self, cwd, *args):
        p = subprocess.run(["git", "-C", cwd, *args], env=self.env, capture_output=True,
                           text=True)
        self.assertEqual(p.returncode, 0, f"git {' '.join(args)}: {p.stderr}")
        return p.stdout.strip()

    def create(self, name="myloop", *args, source=None):
        """Run the source's own bin/10km create; the result."""
        source = source or self.src
        return subprocess.run([os.path.join(source, "bin", "10km"), "create",
                               os.path.join(self.tmp, name), *args],
                              env=self.env, capture_output=True, text=True)

    def loop(self, name="myloop"):
        return os.path.join(self.tmp, name, "central", "loop")


class TestCreate(CreateCase):
    def test_clones_onto_the_loops_own_branch(self):  # R339 R340
        p = self.create("myloop", "--agent", "kiro")
        self.assertEqual(p.returncode, 0, p.stderr)
        loop = self.loop()
        self.assertEqual(self.git(loop, "symbolic-ref", "--short", "HEAD"), "myloop")
        self.assertEqual(self.git(loop, "config", "tenkm.mainBranch"), "myloop")
        self.assertEqual(self.git(loop, "rev-parse", "myloop"), self.git(self.src, "rev-parse", "HEAD"))
        self.assertEqual(os.path.realpath(self.git(loop, "remote", "get-url", "local")),
                         os.path.realpath(self.src))
        self.assertEqual(self.git(loop, "remote", "get-url", "origin"),
                         "https://example.com/10km.git")
        for remote in ("origin", "local"):
            self.assertEqual(self.git(loop, "remote", "get-url", "--push", remote), "no-push")
        self.assertIn("10km kickoff", p.stdout)

    def test_writes_host_env_and_initialises(self):  # R341
        self.assertEqual(self.create("myloop", "--agent", "kiro").returncode, 0)
        root = os.path.join(self.tmp, "myloop")
        with open(os.path.join(root, "host.env")) as f:
            self.assertIn(presets.command("kiro", "LOOP_AGENT"), f.read())
        env = dict(self.env, LOOP_ROOT=root)
        env.pop("LOOP_CONFIG")
        p = subprocess.run([os.path.join(self.loop(), "bin", "10km"), "status"], env=env,
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("Loop: stopped", p.stdout)
        self.assertTrue(os.path.exists(os.path.join(root, ".10km", "loop.db")))

    def test_without_an_agent_says_so(self):  # R341
        p = self.create("myloop")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("no agent commands yet", p.stdout)

    def test_refusals(self):  # R339
        cases = [(["--agent", "nope"], "presets: claude"), (["--branch", "main"], "not main"),
                 (["--branch", "a..b"], "can't be the loop's branch")]
        for args, message in cases:
            p = self.create("refused", *args)
            self.assertEqual(p.returncode, 1)
            self.assertIn(message, p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "refused", "central")))
        self.assertEqual(self.create("again").returncode, 0)
        p = self.create("again")
        self.assertIn("already exists", p.stderr)
        plain = os.path.join(self.tmp, "plain")
        shutil.copytree(self.src, plain, ignore=shutil.ignore_patterns(".git"))
        with self.assertRaises(create.CreateError):
            create.run(os.path.join(self.tmp, "x"), source=plain, out=lambda *a: None)

    def test_source_without_origin_gives_only_local(self):  # R340
        self.git(self.src, "remote", "remove", "origin")
        self.assertEqual(self.create().returncode, 0)
        self.assertEqual(self.git(self.loop(), "remote").split(), ["local"])

    def image(self, name, shallow):
        """A copy of the source as an image carries it: a clone, depth 1 if shallow."""
        path = os.path.join(self.tmp, name)
        depth = ["--depth", "1"] if shallow else []
        subprocess.run(["git", "clone", "-q", *depth, f"file://{self.src}", path],
                       env=self.env, check=True, capture_output=True)
        return path

    def change(self, repo, name, message):
        with open(os.path.join(repo, name), "w") as f:
            f.write(f"{message}\n")
        self.git(repo, "add", name)
        self.git(repo, "commit", "-q", "-m", message)

    def assertMerges(self, loop, ref):
        self.git(loop, "merge", "-q", "--no-edit", ref)
        for name in ("UPSTREAM.md", "LOCAL.md"):
            self.assertTrue(os.path.exists(os.path.join(loop, name)), name)

    def test_a_full_image_updates_through_local(self):  # R339 R340
        self.assertEqual(self.create(source=self.image("image1", False)).returncode, 0)
        loop = self.loop()
        self.change(loop, "LOCAL.md", "loop change")
        self.change(self.src, "UPSTREAM.md", "upstream fix")
        self.git(loop, "remote", "set-url", "local", self.image("image2", False))
        self.git(loop, "fetch", "-q", "local")
        self.assertMerges(loop, "local/main")

    def test_a_shallow_image_updates_through_origin(self):  # R339 R340
        """From a shallow source, create warns; a later shallow copy can't update it
        (git takes the new commit for a second root), but origin can."""
        self.git(self.src, "remote", "set-url", "origin", f"file://{self.src}")
        p = self.create(source=self.image("image1", True))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("shallow", p.stdout)
        loop = self.loop()
        self.change(loop, "LOCAL.md", "loop change")
        self.change(self.src, "UPSTREAM.md", "upstream fix")
        self.git(loop, "fetch", "-q", "--unshallow", "origin")
        self.assertMerges(loop, "origin/main")

class TestContainer(CreateCase):
    def test_install_agent_knows_the_presets_and_checks_names_first(self):  # R341
        script = os.path.join(CODE, "docker", "install-agent.sh")
        with open(script) as f:
            names = re.search(r"^    ([a-z|]+)\) ;;$", f.read(), re.M).group(1).split("|")
        self.assertEqual(sorted(names), sorted(presets.PRESETS))
        p = subprocess.run(["bash", script, "claude", "nope"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)  # before installing anything
        self.assertIn("unknown agent: nope", p.stderr)

    def fake_harness(self, command):
        """A fake harness on PATH, so install-agent has nothing to download."""
        bindir = os.path.join(self.tmp, "fakebin")
        os.makedirs(bindir, exist_ok=True)
        path = os.path.join(bindir, command)
        with open(path, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(path, 0o755)
        return dict(self.env, PATH=bindir + os.pathsep + self.env["PATH"])

    def test_install_agent_leaves_an_installed_harness_alone(self):
        script = os.path.join(CODE, "docker", "install-agent.sh")
        env = dict(self.fake_harness("kiro-cli"), HOME=self.tmp)
        p = subprocess.run(["bash", script, "kiro"], env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("kiro is installed", p.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".local")))

    def start_container(self, root):
        """Run container-start as the image does; wait for its run-loop; stop it."""
        env = dict(self.fake_harness("kiro-cli"), TENKM_SOURCE=self.src, LOOP_ROOT=root,
                   AGENT="kiro", LOOP_NAME="myloop")
        env.pop("LOOP_CONFIG")
        log = os.path.join(self.tmp, "container.log")
        with open(log, "w") as f:
            p = subprocess.Popen([os.path.join(BIN, "container-start")], env=env, stdout=f,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        self.addCleanup(lambda: p.poll() is None and os.killpg(p.pid, signal.SIGKILL))
        cfg = config.Config(LOOP_ROOT=root)
        self.assertTrue(testenv.wait_for(lambda: runloop.running(cfg)), testenv.read(log))
        os.killpg(p.pid, signal.SIGTERM)
        p.wait(timeout=testenv.DEADLINE)
        return testenv.read(log)

    def test_container_start_creates_the_loop_once(self):  # R339 R341
        root = os.path.join(self.tmp, "home", "loop")
        os.makedirs(root)
        out = self.start_container(root)
        self.assertIn("kiro is installed", out)
        self.assertIn("Created the loop", out)
        loop = os.path.join(root, "central", "loop")
        self.assertEqual(self.git(loop, "symbolic-ref", "--short", "HEAD"), "myloop")
        with open(os.path.join(root, "host.env")) as f:
            self.assertIn(presets.command("kiro", "LOOP_AGENT"), f.read())
        self.assertNotIn("Created the loop", self.start_container(root))


if __name__ == "__main__":
    unittest.main()
