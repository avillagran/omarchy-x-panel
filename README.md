# X Panel

Opera-GX style always-on **X (x.com, Twitter) side panel** for [Omarchy](https://github.com/Omarchy/omarchy) (Quickshell / Hyprland).

The panel uses your **system default browser** and its native profile. An existing X window in that browser is reused; otherwise a new window is opened. Chromium browsers use a dedicated native popup with client-only fullscreen: browser controls are hidden while X keeps its unread count in the window title. Links to other sites open in a normal browser window. The compositor keeps the panel floating at the configured size. The popup is opened automatically through a short-lived, loopback-only launcher; no extension or browser debugging port is used. Floorp uses its native Web App mode. X Panel reuses or creates the X app registration and automatically disables **Show Toolbar** through Floorp’s native settings control before launching it. No manual installation or navigation inside the app is required. The toolbar setting applies to Floorp Web App windows; regular browser windows keep their controls. The adapter requires Python GObject introspection and the desktop AT-SPI accessibility service. It does not restart Floorp or rewrite a running `prefs.js`. It is pinned (visible on every workspace) and floating at a configurable position and size, toggled from the bar icon or `SUPER+SHIFT+X` without ever closing the window, so the session and scroll position are preserved.

## Screenshot

![X Panel](preview.png)

## Features

- One persistent, always-on X window (your real session, not a separate login).
- Toggle show / hide from the bar icon or `SUPER+SHIFT+X` — hiding keeps the session alive.
- Pinned + floating on all workspaces.
- Rectangular unread badge to the right of `𝕏`: reads X's native window-title count every 12 seconds and expands to show the full number, including totals such as `100` or `1000`.
- Preferences panel (right-click the bar icon) anchored under the icon, with live apply:
  - **Side**: Left / Center / Right
  - **Vertical**: Top / Middle / Bottom
  - **Width**: 320 / 420 / 520 / 620 / 1080 px
  - **Height**: 25% / 50% / 75% / 100% of the safe area
  - **Auto-refresh**: Off / 30 min / 1 h / 3 h — reloads X when you show the panel after it has been hidden that long (long-lived X tabs slow down or crash over time), plus a **Reload now** button
  - **Reload if X breaks** (on by default): if the window title shows the page failed to load (a bare URL or a stuck `X` splash instead of `… / X`) for three checks a minute apart, X is reloaded the next time you show or focus the panel. Never while you are using it, and at most once every 10 minutes.
  - **Hide on focus loss** (off by default): hides the panel when another window takes focus. With Hyprland's focus-follows-mouse, moving the pointer onto another window counts.
- Resize grips on the panel's free corners: drag them to resize, and the size is remembered per monitor (by EDID description, or connector name for a laptop panel).
- Multi-monitor aware: the panel opens on the focused monitor, below *that* monitor's bar, with that monitor's size.
- Multi-language UI — 19 languages (en, es, pt, fr, de, it, nl, pl, ru, ja, ko, zh, ar, tr, sv, da, no, fi, cs), auto-detected from the OS locale (`localectl`).
- UI matching the Omarchy Control Panel style (header, sections, separators).

## Installation

```bash
omarchy plugin add https://github.com/avillagran/omarchy-x-panel --enable
```

That is all. The plugin (including its helper script under `bin/`) is resolved relative to its own location, so it works on any machine with no extra steps. Reload the shell if it does not pick up the new widget immediately:

```bash
omarchy-restart-shell
```

### Keyboard shortcut

The plugin can bind `SUPER+SHIFT+X` to toggle the panel, replacing Omarchy's
default X webapp bind (which relaunches a fresh window every time). This is
**opt-in**: the plugin never touches your Hyprland config on install or load.
Open the preferences panel (right-click the bar icon) and switch on *Keyboard
shortcut* — only then does the plugin write `~/.config/hypr/x-panel-bindings.lua`
and append a single `require("hypr.x-panel-bindings")` line to
`~/.config/hypr/hyprland.lua` (idempotent, atomic writes). Switching it off
removes both and restores Omarchy's default bind.

## Usage

- **Left-click** the `𝕏` bar icon (or `SUPER+SHIFT+X`): toggle the X window.
- **Right-click** the `𝕏` bar icon: open the preferences panel (position / size), applied live.
- The preferences panel **stays open and on top** while you pick options, so you can preview each change live (the X window sits behind it) — close it with the `✕` in the top-right corner.

## How it works

- Identity is tracked as `address|pid` in `$XDG_RUNTIME_DIR/x-panel.state`.
- Layout is computed against the **safe area** (the monitor minus the Quickshell bar strip), so the panel never covers the bar.
- Preferences are persisted at `${XDG_CONFIG_HOME:-~/.config}/omarchy-x-panel/prefs.json` (survives reboots; outside the plugin directory, so writing them never triggers a plugin reload; a pre-1.1 file in `$XDG_RUNTIME_DIR` is migrated automatically) and applied live via the bundled helper script. All state writes use exclusive `mktemp` + atomic `mv`, and every external read is opened once with `O_NOFOLLOW | O_NONBLOCK`, verified via `fstat`, and capped at 256 KiB.
- The default browser is resolved through `xdg-settings` (with an HTTPS MIME fallback) and its desktop entry, preserving launch arguments and the native profile. Floorp launches the registered X app with its native `--start-ssb` command and app window class; Floorp builds without the experimental app-specific Linux window class are supported by tracking the newly launched window and its PID instead of adopting an arbitrary browser window. The panel bypasses `X.desktop` and the stock webapp launcher, which substitutes Chromium for unsupported browsers. Changing the default browser leaves the old window intact and opens or reuses X in the newly selected browser. There is no silent Chromium fallback.

## Uninstall

```bash
omarchy plugin remove io.github.avillagran.omarchy-x-panel
```

If you turned the keybind on, turn it off first in the preferences panel; that
removes both generated changes. If the plugin is already gone, delete them by hand
to restore Omarchy's default X bind:

```bash
sed -i '/require("hypr.x-panel-bindings")/d' ~/.config/hypr/hyprland.lua
rm -f ~/.config/hypr/x-panel-bindings.lua
```

Preferences are kept outside the plugin directory, so removal leaves them. To
delete them too:

```bash
rm -rf ~/.config/omarchy-x-panel
```

## License

MIT — see [LICENSE](LICENSE).
