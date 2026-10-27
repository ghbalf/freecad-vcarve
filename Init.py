# SPDX-License-Identifier: LGPL-2.1-or-later
# Authors: alf and Claude (Anthropic)
"""App-side hook, run headless too. FreeCAD 26.3 blocks restoring Python objects from a module it
cannot trace to an addon (a symlinked install resolves outside Mod); a package that is already
imported is accepted, so import the (empty) package here."""
import vcarve_flat  # noqa: F401
