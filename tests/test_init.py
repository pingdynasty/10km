"""Tests for 10km init's hook setup (tenkm.init.install_hooks).

Each test uses its own GIT_CONFIG_GLOBAL and no system config."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: E402,F401  (test config, no caller env: tests/testenv.py)
from test_scripts import ScriptLoop  # noqa: E402
from unittest import mock  # noqa: E402

from tenkm import gitutil, init, msm  # noqa: E402

HOOK = "#!/bin/sh\n{}\n"


class InitHooksTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="10km-init-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.inherited = os.path.join(self.base, "inherited-hooks")
        os.makedirs(self.inherited)
        self.global_config = os.path.join(self.base, "gitconfig")
        self.marker = os.path.join(self.base, "marker")

    def write_hook(self, name, body):
        path = os.path.join(self.inherited, name)
        with open(path, "w") as f:
            f.write(HOOK.format(body))
        os.chmod(path, 0o755)

    def make_loop(self, hooks_path=None):
        """A test loop whose global config sets core.hooksPath to hooks_path. Write
        the inherited hooks afterwards: the setup commits run before init."""
        with open(self.global_config, "w") as f:
            if hooks_path:
                f.write(f"[core]\n\thooksPath = {hooks_path}\n")
        self.loop = ScriptLoop(os.path.join(self.base, "loop"), GIT_CONFIG_NOSYSTEM="1",
                               GIT_CONFIG_GLOBAL=self.global_config)
        self.project = os.path.join(self.loop.central, "project")
        self.hooks = os.path.join(self.project, ".git", "tenkm-hooks")
        return self.loop

    def generated(self):
        return sorted(os.listdir(self.hooks))

    def config(self, key):
        p = subprocess.run(["git", "-C", self.project, "config", "--local", "--get", key],
                           env=self.loop.env, capture_output=True, text=True)
        return p.stdout.strip() if p.returncode == 0 else None

    def commit(self, branch="s1", check=True):
        self.loop.git(self.project, "checkout", "-q", "-B", branch)
        p = subprocess.run(["git", "-C", self.project, "commit", "-q", "--allow-empty",
                            "-m", "work"], env=self.loop.env, capture_output=True, text=True)
        if check:
            self.assertEqual(p.returncode, 0, p.stderr)
        return p

    def message(self):
        return self.loop.git(self.project, "log", "-1", "--format=%B")

    def test_chains_to_inherited_hooks(self):
        self.make_loop(self.inherited)
        self.write_hook("pre-commit", f"echo pre-commit >> '{self.marker}'")
        self.write_hook("prepare-commit-msg",
                        'git interpret-trailers --in-place --trailer "Inherited: $2" "$1"')
        self.assertEqual(self.config("core.hooksPath"), self.hooks)
        self.loop.ok("10km", "init")
        self.assertEqual(self.generated(), ["pre-commit", "prepare-commit-msg"])
        self.commit()
        message = self.message()
        self.assertIn("Loop-Session: s1", message)
        self.assertIn("Inherited: message", message)
        with open(self.marker) as f:
            self.assertEqual(f.read(), "pre-commit\n")

    def test_failing_inherited_hook_fails(self):
        self.make_loop(self.inherited)
        self.write_hook("commit-msg", "exit 1")
        self.loop.ok("10km", "init")
        before = self.loop.git(self.project, "rev-parse", "HEAD")
        self.assertNotEqual(self.commit(check=False).returncode, 0)
        self.assertEqual(self.loop.git(self.project, "rev-parse", "HEAD"), before)

    def test_inherited_hook_gets_args_and_stdin(self):
        self.make_loop(self.inherited)
        self.write_hook("pre-push", f"{{ echo \"$*\"; cat; }} > '{self.marker}'")
        self.loop.ok("10km", "init")
        p = subprocess.run([os.path.join(self.hooks, "pre-push"), "origin", "url"],
                           cwd=self.project, env=self.loop.env, input="refs\n", text=True)
        self.assertEqual(p.returncode, 0)
        with open(self.marker) as f:
            self.assertEqual(f.read(), "origin url\nrefs\n")

    def test_never_chains_to_itself(self):
        self.make_loop(self.inherited)
        with open(self.global_config, "w") as f:
            f.write(f"[core]\n\thooksPath = {self.hooks}\n")
        self.loop.ok("10km", "init")
        self.assertEqual(self.config("core.hooksPath"), self.hooks)
        self.assertEqual(self.generated(), ["prepare-commit-msg"])
        self.commit()
        self.assertIn("Loop-Session: s1", self.message())

    def test_no_inherited_hooks(self):
        self.make_loop()
        self.assertEqual(self.config("core.hooksPath"), self.hooks)
        self.assertEqual(self.generated(), ["prepare-commit-msg"])
        self.commit()
        self.assertIn("Loop-Session: s1", self.message())

    def test_chains_repo_hooks_dir_and_relative_hooks_path(self):
        self.make_loop()
        repo_hooks = os.path.join(self.project, ".git", "hooks")
        os.makedirs(repo_hooks, exist_ok=True)
        self.inherited = repo_hooks
        self.write_hook("pre-commit", f"echo repo >> '{self.marker}'")
        self.loop.ok("10km", "init")
        self.commit()
        with open(self.global_config, "w") as f:
            f.write("[core]\n\thooksPath = .githooks\n")
        self.inherited = os.path.join(self.project, ".githooks")
        os.makedirs(self.inherited)
        self.write_hook("pre-commit", f"echo relative >> '{self.marker}'")
        self.loop.ok("10km", "init")
        self.commit("s2")
        with open(self.marker) as f:
            self.assertEqual(f.read(), "repo\nrelative\n")

    def test_rerun_picks_up_new_inherited_hook(self):
        self.make_loop(self.inherited)
        self.assertEqual(self.generated(), ["prepare-commit-msg"])
        self.write_hook("post-commit", f"echo post-commit >> '{self.marker}'")
        self.loop.ok("10km", "init")
        self.loop.ok("10km", "init")
        self.assertEqual(self.config("core.hooksPath"), self.hooks)
        self.assertEqual(self.generated(), ["post-commit", "prepare-commit-msg"])
        self.commit()
        with open(self.marker) as f:
            self.assertEqual(f.read(), "post-commit\n")
        os.remove(os.path.join(self.inherited, "post-commit"))
        self.loop.ok("10km", "init")
        self.assertEqual(self.generated(), ["prepare-commit-msg"])

    def test_existing_local_hooks_path_untouched(self):
        self.make_loop(self.inherited)
        self.write_hook("pre-commit", "true")
        self.loop.git(self.project, "config", "--local", "core.hooksPath", self.inherited)
        self.loop.ok("10km", "init")
        self.assertEqual(self.config("core.hooksPath"), self.inherited)
        self.assertEqual(self.generated(), ["prepare-commit-msg"])

    def test_old_git_fails_without_touching_hooks_path(self):
        self.make_loop()
        self.loop.git(self.project, "config", "--local", "core.hooksPath", self.inherited)
        old_git = (129, "", "error: unknown option `show-scope'")
        with mock.patch.object(gitutil, "run", return_value=old_git):
            with self.assertRaisesRegex(msm.MSMError, "git 2.26"):
                init.install_hooks(None, self.project, self.inherited)
        self.assertEqual(self.config("core.hooksPath"), self.inherited)


if __name__ == "__main__":
    unittest.main()
