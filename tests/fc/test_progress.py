# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
import types
import unittest
from unittest import mock

import FreeCAD as App
import Path

from helpers import make_job, make_sketch
from test_op_vcarve import RECT
from vcarve_flat import op_clearance, progress

ABORT = RuntimeError("abort progress indicator")  # what FreeCAD's ProgressIndicator.next raises on Cancel


def indicator(abort_at=None, gui=True):
    """Patches App.Base.ProgressIndicator; its next() aborts on call abort_at (1-based). With gui, progress
    sees a GUI (whose event watching is left out)."""
    calls = []

    def next_(can_abort):
        calls.append(can_abort)
        if len(calls) == abort_at:
            raise ABORT

    patch = mock.patch.object(App.Base, "ProgressIndicator")
    pi = patch.start()
    pi.return_value.next.side_effect = next_
    if gui:
        mock.patch.object(progress, "App", types.SimpleNamespace(
            GuiUp=True, Base=App.Base, listDocuments=App.listDocuments)).start()
        mock.patch.object(progress, "_watch_gui", return_value=None).start()
    return patch, pi


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(mock.patch.stopall)

    def test_step_without_task(self):
        _, pi = indicator(abort_at=1)
        progress.step()
        pi.assert_not_called()
        self.assertFalse(progress.cancelled())

    def test_headless_shows_nothing(self):
        _, pi = indicator(abort_at=1, gui=False)
        with progress.task("Outer"):
            progress.step()
        pi.assert_not_called()
        self.assertFalse(progress.cancelled())

    def test_failed_setup_leaves_no_task(self):
        _, pi = indicator()
        progress._watch_gui.side_effect = RuntimeError("no Qt")
        with self.assertRaises(RuntimeError):
            with progress.task("Outer"):
                pass
        pi.return_value.stop.assert_called_once_with()
        self.assertEqual((progress._indicator, progress._gui, progress._depth), (None, None, 0))
        progress._watch_gui.side_effect = None
        with progress.task("Again"):
            progress.step()
        self.assertEqual(pi.return_value.next.call_count, 1)

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
        self.later = mock.patch.object(progress, "_later").start()  # the GUI's event loop: idle()
        self.addCleanup(mock.patch.stopall)
        sk = make_sketch(self.doc, "S", [RECT])
        self.job, _ = make_job(self.doc, [sk])
        self.clr, self.vc = op_clearance.create_pair(self.job)
        self.vc.BaseShapes = list(self.job.Model.Group)
        self.vc.FlatDepth = 1.0
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def idle(self):
        while self.later.call_args_list:
            self.later.call_args_list.pop(0).args[0]()

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
            self.idle()
            self.assertFalse(progress.cancelled())
            op.touch()
            self.doc.recompute()
            self.assertEqual(op.Path.toGCode(), normal, op.Label)

    def test_cancel_holds_for_the_recompute(self):
        """A Cancel cancels the recompute's later ops too, and not the next recompute."""
        _, vc2 = op_clearance.create_pair(self.job)
        vc2.BaseShapes, vc2.FlatDepth = self.vc.BaseShapes, 0.5
        self.doc.recompute()
        ops = (self.vc, vc2)
        normal = [op.Path.toGCode() for op in ops]
        patch, pi = indicator(abort_at=1)
        for op in ops:
            op.touch()
        self.doc.recompute()
        self.assertEqual([op.Path.Commands for op in ops], [[], []])
        self.assertEqual(pi.return_value.next.call_count, 1)
        self.assertTrue(progress.cancelled())
        self.idle()
        self.assertFalse(progress.cancelled())
        patch.stop()
        for op in ops:
            op.touch()
        self.doc.recompute()
        self.assertEqual([op.Path.toGCode() for op in ops], normal)

if __name__ == "__main__":
    unittest.main()
