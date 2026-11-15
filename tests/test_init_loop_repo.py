"""Tests for tenkm.init.create_loop_repo: what goes into a new loop repo (R11, R12).

From a git checkout only tracked files are copied, so a loop root or other
untracked files in the checkout stay out; a source without .git (the container
image) is copied whole, less .git, caches, databases and editor files."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: E402  (test config, no caller env: tests/testenv.py)

from tenkm import init  # noqa: E402

ENV = dict(os.environ, **testenv.GIT_ID, **testenv.HOST_GIT_OFF)


def write(path, text="x\n", mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    if mode is not None:
        os.chmod(path, mode)


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], env=ENV, check=True,
                          capture_output=True, text=True).stdout


def files(root):
    """Paths under root, relative, without .git."""
    found = set()
    for d, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if x != ".git"]
        for n in names + [x for x in dirs if os.path.islink(os.path.join(d, x))]:
            found.add(os.path.relpath(os.path.join(d, n), root))
    return found


def add_loop_root(root):
    """An untracked loop root in root, as an operator's checkout may hold one."""
    write(os.path.join(root, "myloop", "central", "loop", "config.env"))
    write(os.path.join(root, "myloop", "run", "s1", "prompt.txt"))
    write(os.path.join(root, "myloop", "loop.db"))
    write(os.path.join(root, "notes.md"))


class CreateLoopRepoTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="10km-looprepo-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.src = os.path.join(self.base, "src")
        self.dest = os.path.join(self.base, "loop")
        write(os.path.join(self.src, "README.md"), "committed\n")
        write(os.path.join(self.src, "bin", "tool"), "#!/bin/sh\n", 0o755)
        write(os.path.join(self.src, "gone.txt"))
        os.symlink("bin/tool", os.path.join(self.src, "link"))

    def create(self):
        saved = dict(os.environ)
        try:  # create_loop_repo reads the git identity from os.environ
            os.environ.update(testenv.GIT_ID, **testenv.HOST_GIT_OFF)
            init.create_loop_repo(self.dest, source=self.src)
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def make_checkout(self):
        git(self.base, "init", "-q", "-b", "main", self.src)
        git(self.src, "add", "-A")
        git(self.src, "commit", "-q", "-m", "start")

    def assert_common(self):
        self.assertTrue(os.access(os.path.join(self.dest, "bin", "tool"), os.X_OK))
        self.assertEqual(os.readlink(os.path.join(self.dest, "link")), "bin/tool")
        self.assertEqual(git(self.dest, "status", "--porcelain"), "")
        self.assertEqual(git(self.dest, "rev-list", "--count", "HEAD").strip(), "1")

    def test_checkout_copies_tracked_files_only_from_the_working_copy(self):
        self.make_checkout()
        add_loop_root(self.src)
        write(os.path.join(self.src, "README.md"), "edited\n")    # uncommitted edit
        write(os.path.join(self.src, "staged.txt"))               # added, not committed
        git(self.src, "add", "staged.txt")
        os.remove(os.path.join(self.src, "gone.txt"))              # deleted, not committed
        self.create()
        self.assertEqual(files(self.dest),
                         {"README.md", "bin/tool", "link", "staged.txt"})
        self.assertEqual(testenv.read(os.path.join(self.dest, "README.md")), "edited\n")
        self.assert_common()

    def test_subdirectory_of_a_checkout_is_copied_whole(self):
        """Only the top of a work tree counts as a checkout: a source inside an
        unrelated repo is copied as a plain tree."""
        git(self.base, "init", "-q", "-b", "main", self.base)
        write(os.path.join(self.src, "untracked.txt"))
        self.create()
        self.assertIn("untracked.txt", files(self.dest))
        self.assert_common()

    def test_source_without_git_is_copied_less_caches_and_databases(self):
        write(os.path.join(self.src, "loop.db"))
        write(os.path.join(self.src, "tenkm", "__pycache__", "x.pyc"))
        write(os.path.join(self.src, "README.md~"))
        write(os.path.join(self.src, "extra.txt"))
        self.create()
        self.assertEqual(files(self.dest),
                         {"README.md", "bin/tool", "gone.txt", "link", "extra.txt"})
        self.assert_common()


if __name__ == "__main__":
    unittest.main()
