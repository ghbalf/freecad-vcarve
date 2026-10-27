# SPDX-License-Identifier: LGPL-2.1-or-later
"""FreeCAD's progress indicator with Cancel, for long computations on the GUI thread.

Inside doc.recompute() FreeCAD's own sequencer runs and ignores a nested ProgressIndicator entirely
(no events, no Cancel), so in the GUI step() also processes events itself and watches for Esc."""
import time
from contextlib import contextmanager

import FreeCAD as App
import Path

_PERIOD = 0.1  # s between processing GUI events
_indicator = None  # the outermost task's
_gui = None  # (poll, remove) in the GUI
_depth = 0
_cancelled = False


class Cancelled(Exception):
    """The user cancelled the computation."""


def _watch_gui():
    """(poll, remove): poll(beat) beats the indicator and processes pending events at most every _PERIOD, and
    at most a quarter of the time when that is slow (offscreen, FreeCAD 1.1 takes 0.35 s); an application event filter,
    installed after FreeCAD's sequencer's (which swallows Esc), turns Esc into Cancel."""
    from PySide import QtCore, QtGui

    class Esc(QtCore.QObject):
        def eventFilter(self, obj, event):
            global _cancelled
            if event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Escape:
                _cancelled = True
            return False  # FreeCAD's sequencer sees it too: in a recompute it then offers to abort the rest

    app, esc, due = QtGui.QApplication.instance(), Esc(), [time.monotonic() + _PERIOD]
    app.installEventFilter(esc)

    def poll(beat):
        start = time.monotonic()
        if start >= due[0]:
            beat()
            app.processEvents()
            end = time.monotonic()
            due[0] = end + max(_PERIOD, 3 * (end - start))
    return poll, lambda: app.removeEventFilter(esc)


@contextmanager
def task(text):
    """Shows the progress indicator with text; nested tasks share the outermost one."""
    global _indicator, _gui, _depth, _cancelled
    if not _depth:
        _indicator = App.Base.ProgressIndicator()
        _indicator.start(text, 0)
        _gui = _watch_gui() if App.GuiUp else None
    _depth += 1
    try:
        yield
    finally:
        _depth -= 1
        if not _depth:
            if _gui:
                _gui[1]()
            indicator, _indicator, _gui, _cancelled = _indicator, None, None, False
            indicator.stop()


def _beat():
    global _cancelled
    try:
        _indicator.next(True)
    except RuntimeError:  # FreeCAD's "abort progress indicator"
        _cancelled = True


def step():
    """Lets the GUI breathe; raises Cancelled once the user cancelled, until the outermost task exits."""
    if _indicator is None:
        return
    if not _cancelled and _gui:
        _gui[0](_beat)
    elif not _cancelled:
        _beat()
    if _cancelled:
        raise Cancelled("cancelled")


def cancelled() -> bool:
    """Whether the user cancelled; for callers after a doc.recompute(), which swallows Cancelled per object."""
    return _cancelled


@contextmanager
def op_task(proxy, obj):
    """task(obj.Label) around an op's computation; on Cancel the op keeps no path and Cancelled propagates,
    so FreeCAD marks the op as failed."""
    with task(obj.Label):
        try:
            yield
        except Cancelled:
            proxy.commandlist = []
            obj.Path = Path.Path()
            Path.Log.notice(f"{obj.Label}: cancelled")
            raise
