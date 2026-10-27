# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
"""Touches the ops of a clearance chain when a clearance op is deleted or the Job's ops are reordered:
neither change reaches all of the chain's ops through their onChanged."""
import FreeCAD as App

from . import op_vcarve


def _touch_stale(link, gone=None):
    """Touch link and its clearance ops whose stored RestChain no longer matches the chain (without gone)."""
    cops = [c for c in op_vcarve.clearance_ops(link) if c != gone]
    if link.RestChain != op_vcarve.chain_key(cops):
        link.touch()
    for j, c in enumerate(cops):
        if c.RestChain != op_vcarve.chain_key(cops[:j]):
            c.touch()


def _deleted(obj):
    link = getattr(obj, "VCarveOp", None)
    if hasattr(obj, "RestChain") and hasattr(link, "RestChain"):
        _touch_stale(link, obj)


def _regrouped(group):
    for op in group.Group:
        if hasattr(op, "RestChain") and not hasattr(op, "VCarveOp"):  # a V-carve or plug op
            _touch_stale(op)


def _quietly(fn, obj):
    # Slots also fire while a document closes, restores or undoes, on objects half torn down.
    try:
        if not obj.Document.Restoring:
            fn(obj)
    except Exception:
        pass


class _Observer:
    def slotDeletedObject(self, obj):
        _quietly(_deleted, obj)

    def slotChangedObject(self, obj, prop):
        if prop == "Group":
            _quietly(_regrouped, obj)


def install():
    """Add the observer, replacing one added by an earlier import of this module."""
    old = getattr(App, "_vcarve_observer", None)
    if old is not None:
        App.removeDocumentObserver(old)
    App._vcarve_observer = _Observer()
    App.addDocumentObserver(App._vcarve_observer)
