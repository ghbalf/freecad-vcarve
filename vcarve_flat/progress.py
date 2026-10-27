# SPDX-License-Identifier: LGPL-2.1-or-later
"""FreeCAD's progress indicator with Cancel, for long computations on the GUI thread.

Inside doc.recompute() FreeCAD's own sequencer runs and ignores a nested ProgressIndicator entirely
(no events, no Cancel), so in the GUI step() also processes events itself and watches for Esc. Headless a task
shows nothing and cannot be cancelled."""
import time
from contextlib import contextmanager

import FreeCAD as App
import Path

_PERIOD = 0.1  # s between processing GUI events
_SHOW = 2.5  # s after which FreeCAD's bar is up (it shows a sequencer 2 s after its start)
_indicator = None  # the outermost task's
_gui = None  # (poll, remove) in the GUI
_depth = 0
_cancelled = False


class Cancelled(Exception):
    """The user cancelled the computation."""


def _watch_gui(restart):
    """(poll, remove): poll(beat) beats the indicator and processes pending events at most every _PERIOD, and
    at most a quarter of the time when that is slow (offscreen, FreeCAD 1.1 takes 0.35 s); an application event filter,
    installed after FreeCAD's sequencer's, turns Esc into Cancel. FreeCAD 26's Part booleans stop the running
    sequencer (their Part::ProgressIndicator does), which hides the bar for the rest of the task: once it should be
    up, poll calls restart and shows the bar again whenever it is hidden outside a recompute."""
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui

    class Esc(QtCore.QObject):
        def eventFilter(self, obj, event):
            global _cancelled
            if event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Escape:
                _cancelled = True
                return True  # FreeCAD's sequencer would ask whether to abort the rest of a recompute
            return False

    app, esc, due = QtGui.QApplication.instance(), Esc(), [time.monotonic() + _PERIOD]
    app.installEventFilter(esc)
    bar = next(iter(Gui.getMainWindow().statusBar().findChildren(QtGui.QProgressBar)), None)
    up = time.monotonic() + _SHOW

    def poll(beat):
        start = time.monotonic()
        if start >= due[0]:
            beat()
            app.processEvents()
            if bar is not None and start >= up and not bar.isVisible() and not _recomputing():
                restart()
                app.processEvents()  # the stop's queued hide
                bar.show()
            end = time.monotonic()
            due[0] = end + max(_PERIOD, min(3 * (end - start), 1.0))
    return poll, lambda: app.removeEventFilter(esc)


def _recomputing() -> bool:
    return any(doc.Recomputing for doc in App.listDocuments().values())


def _later(fn):
    from PySide import QtCore
    QtCore.QTimer.singleShot(100, fn)


def _release():
    """Ends a Cancel held for a recompute once the event loop runs with no document recomputing (FreeCAD's
    sequencer processes events between objects). A Python document observer would be exact, but with one
    FreeCAD 1.1.1's GUI check crashed now and then."""
    global _cancelled
    if _depth:
        return  # the running task's exit decides again
    if _recomputing():
        _later(_release)
    else:
        _cancelled = False


@contextmanager
def task(text):
    """Shows the progress indicator with text in the GUI; nested tasks share the outermost one. A Cancel inside
    a recompute holds until it ends, so the recompute's later objects cancel too."""
    global _indicator, _gui, _depth, _cancelled
    if not _depth:
        _cancelled = _cancelled and _recomputing()
        if App.GuiUp:
            indicator = App.Base.ProgressIndicator()
            try:
                indicator.start(text, 0)
                _gui = _watch_gui(lambda: (indicator.stop(), indicator.start(text, 0)))
            except BaseException:
                indicator.stop()
                raise
            _indicator = indicator
    _depth += 1
    try:
        yield
    finally:
        _depth -= 1
        if not _depth:
            if _gui:
                _gui[1]()
            indicator, _indicator, _gui = _indicator, None, None
            _cancelled = _cancelled and _recomputing()
            if _cancelled:
                _later(_release)
            if indicator:
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
