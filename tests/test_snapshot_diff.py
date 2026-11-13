import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import snapshot_diff  # noqa: E402


def write_snapshot(output_dir, name, files):
    """files: {relative folder ('' = root): [(size, abs path), ...]}"""
    for rel, rows in files.items():
        folder = os.path.join(output_dir, name, rel)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "disk_usage.txt"), "w") as f:
            for size, path in rows:
                f.write(f"{size}\t{path}\n")


class SnapshotDiffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = self.tmp.name
        write_snapshot(self.out, "2026-11-01_10-00-00", {
            "": [("10G", "/u"), ("6G", "/u/lib"), ("3G", "/u/dev")],
            "lib": [("6G", "/u/lib"), ("5G", "/u/lib/caches")],
        })
        write_snapshot(self.out, "2026-11-08_10-00-00", {
            "": [("20G", "/u"), ("15G", "/u/lib"), ("3G", "/u/dev")],
            "lib": [("15G", "/u/lib"), ("5G", "/u/lib/caches"), ("9G", "/u/lib/clones")],
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_compute_delta_rules(self):
        self.assertEqual(snapshot_diff.compute_delta("/a", 5, {"/a": 2}, True), 3)
        self.assertEqual(snapshot_diff.compute_delta("/b", 5, {}, True), 5)
        self.assertIsNone(snapshot_diff.compute_delta("/b", 5, {}, False))

    def test_read_children(self):
        snap = os.path.join(self.out, "2026-11-01_10-00-00")
        sizes, scanned = snapshot_diff.read_children(snap, "/u/lib")
        self.assertTrue(scanned)
        self.assertEqual(sizes["/u/lib/caches"], 5 * 1024**3)
        self.assertEqual(snapshot_diff.read_children(snap, "/u/dev"), ({}, False))
        self.assertEqual(snapshot_diff.read_children(snap, "/elsewhere"), ({}, False))

    def test_top_changes_points_at_the_folder_that_grew(self):
        result = snapshot_diff.top_changes(self.out, days=7, min_bytes=1024**3)
        self.assertEqual(result["baseline"][0], "2026-11-01_10-00-00")
        paths = [r[1] for r in result["rows"]]
        # /u/lib/clones explains /u/lib's growth, which explains /u's
        self.assertEqual(paths, ["/u/lib/clones"])
        delta, _path, size, is_new = result["rows"][0]
        self.assertEqual((delta, size, is_new), (9 * 1024**3, 9 * 1024**3, True))

    def test_needs_two_snapshots(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertIsNone(snapshot_diff.top_changes(empty))


if __name__ == "__main__":
    unittest.main()
