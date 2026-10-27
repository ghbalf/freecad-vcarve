# SPDX-License-Identifier: LGPL-2.1-or-later
import unittest
from unittest import mock

import FreeCAD as App
import Path

from helpers import make_job, make_sketch
from test_op_vcarve import RECT
from vcarve_flat import op_clearance, progress

ABORT = RuntimeError("abort progress indicator")  # what FreeCAD's ProgressIndicator.next raises on Cancel


def indicator(abort_at=None):
    """Patches App.Base.ProgressIndicator; its next() aborts on call abort_at (1-based)."""
    calls = []

    def next_(can_abort):
        calls.append(can_abort)
        if len(calls) == abort_at:
            raise ABORT

    patch = mock.patch.object(App.Base, "ProgressIndicator")
    pi = patch.start()
    pi.return_value.next.side_effect = next_
    return patch, pi


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(mock.patch.stopall)

    def test_step_without_task(self):
        _, pi = indicator(abort_at=1)
        progress.step()
        pi.assert_not_called()
        self.assertFalse(progress.cancelled())

    def test_nested_tasks_share_one_indicator(self):
        _, pi = indicator()
        with progress.task("Outer"):
            with progress.task("Inner"):
                progress.step()
            progress.step()
            pi.return_value.stop.assert_not_called()
        pi.assert_called_once_with()
        pi.return_value.start.assert_called_once_with("Outer", 0)
        self.assertEqual(pi.return_value.next.call_args_list, [mock.call(True)] * 2)
        pi.return_value.stop.assert_called_once_with()

    def test_abort_sticks_until_outer_task_exits(self):
        _, pi = indicator(abort_at=2)
        with progress.task("Outer"):
            with progress.task("Inner"):
                progress.step()
                with self.assertRaises(progress.Cancelled):
                    progress.step()
            self.assertTrue(progress.cancelled())
            with self.assertRaises(progress.Cancelled):
                progress.step()
            self.assertEqual(pi.return_value.next.call_count, 2)
        self.assertFalse(progress.cancelled())
        pi.return_value.stop.assert_called_once_with()
        with progress.task("Again"):
            progress.step()

    def test_error_in_task_stops(self):
        _, pi = indicator()
        with self.assertRaises(ZeroDivisionError):
            with progress.task("Outer"):
                1 / 0
        pi.return_value.stop.assert_called_once_with()
        progress.step()
        self.assertEqual(pi.return_value.next.call_count, 0)


class OpCancelTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("cancel")
        for fn in ("warning", "error"):
            mock.patch.object(Path.Log, fn).start()
        self.notice = mock.patch.object(Path.Log, "notice").start()
        self.addCleanup(mock.patch.stopall)
        sk = make_sketch(self.doc, "S", [RECT])
        self.job, _ = make_job(self.doc, [sk])
        self.clr, self.vc = op_clearance.create_pair(self.job)
        self.vc.BaseShapes = list(self.job.Model.Group)
        self.vc.FlatDepth = 1.0
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_op_cancel(self):
        for op, abort_at in ((self.vc, 2), (self.clr, 1)):  # the clearance op steps once per level
            normal = op.Path.toGCode()
            self.assertIn("G1", normal)
            patch, _ = indicator(abort_at)
            op.touch()
            self.doc.recompute()
            patch.stop()
            self.assertEqual(op.Path.Commands, [], op.Label)
            self.assertTrue({"Invalid", "Error"} & set(op.State), (op.Label, op.State))
            self.assertIn(mock.call(f"{op.Label}: cancelled"), self.notice.call_args_list)
            self.assertFalse(progress.cancelled())
            op.touch()
            self.doc.recompute()
            self.assertEqual(op.Path.toGCode(), normal, op.Label)


if __name__ == "__main__":
    unittest.main()
