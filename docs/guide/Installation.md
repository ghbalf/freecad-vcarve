# Installation

V-Carve Flat is a pure-Python addon for FreeCAD's CAM workbench. It needs nothing beyond FreeCAD itself
(numpy, which it uses, ships with FreeCAD).

## Requirements

| | |
|---|---|
| FreeCAD | 1.0.0 or newer. Tested with 1.0.2, 1.1.1, 1.1.4 and 26.3rc2 |
| Workbench | CAM (built into FreeCAD; called Path before 1.0) |
| Operating system | Tested on Linux. Windows and macOS should work, as the addon is pure Python, but are untested so far: please [report](https://github.com/ghbalf/freecad-vcarve/issues) how it goes |

## Option 1: Addon Manager (recommended)

V-Carve Flat is not in FreeCAD's addon catalogue yet, so add its repository to the Addon Manager once:

1. **Edit → Preferences → Addon Manager**.
2. Under **Custom repositories**, add a row: repository `https://github.com/ghbalf/freecad-vcarve`, branch `main`.
3. Press **OK**, then open **Tools → Addon manager**.
4. Find **V-Carve Flat**, select it and press **Install**.
5. Restart FreeCAD.

The Addon Manager also shows when an update is available, and uninstalls the addon.

## Option 2: Download a release

1. Download the **Source code (zip)** of the latest release from the
   [Releases page](https://github.com/ghbalf/freecad-vcarve/releases).
2. Find your FreeCAD user data folder: open **View → Panels → Python console** and enter
   ```python
   App.getUserAppDataDir()
   ```
   It is for example `~/.local/share/FreeCAD/` (Linux, FreeCAD 1.0), `~/.local/share/FreeCAD/v1-1/`
   (Linux, 1.1), `%APPDATA%\FreeCAD\` (Windows) or `~/Library/Application Support/FreeCAD/` (macOS).
3. Extract the zip into the `Mod` folder inside it (create `Mod` if it does not exist) and rename the
   extracted folder to `freecad-vcarve`, so that you get `<user data>/Mod/freecad-vcarve/package.xml`.
4. Restart FreeCAD.

To update, replace the folder with a newer release; to uninstall, delete it.

## Option 3: Git checkout (to follow development)

```sh
git clone https://github.com/ghbalf/freecad-vcarve.git
ln -s "$PWD/freecad-vcarve" "<user data>/Mod/freecad-vcarve"
```

`git pull` and a FreeCAD restart then update it. On Windows, clone straight into the `Mod` folder
instead of linking.

## Check the installation

Switch to the **CAM** workbench. The addon adds seven commands to the **New Operations** toolbar, just
before the Engrave dropdown:

![The V-Carve Flat toolbar buttons](images/install-toolbar.png)

From left to right: **V-Carve Flat**, **V-Carve Clearance**, **V-Carve Pair**, **V-Carve Plug**,
**V-Carve Inlay**, **Check Inlay Fit** and **V-Carve Photo**. The same commands are in the **CAM** menu, after Vcarve.
They are greyed out until the document has a CAM Job.

Nothing there? Open **View → Panels → Report view** and restart FreeCAD: an addon that fails to load
says why there. Check that the folder is named `freecad-vcarve` and sits directly in `Mod` (not
`Mod/freecad-vcarve/freecad-vcarve`).

Next: [Getting started](Getting-Started.md).
