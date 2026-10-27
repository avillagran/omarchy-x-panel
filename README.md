# X Panel

Opera-GX style always-on **X (x.com, Twitter) side panel** for [Omarchy](https://github.com/Omarchy/omarchy) (Quickshell / Hyprland).

The panel uses your **system default browser** and its native profile. The plugin reuses its tracked panel; otherwise it opens a dedicated window. Chromium browsers use a dedicated native popup with client-only fullscreen: browser controls are hidden while X keeps its unread count in the window title. Links to other sites open in a normal browser window. The compositor keeps the panel floating at the configured size. The popup is opened automatically through a short-lived, private local HTML launcher; no extension or browser debugging port is used. Floorp uses its native Web App mode. X Panel reuses or creates the X app registration and automatically disables **Show Toolbar** through Floorp’s native settings control before launching it. No manual installation or navigation inside the app is required. The toolbar setting applies to Floorp Web App windows; regular browser windows keep their controls. The adapter requires Python GObject introspection and the desktop AT-SPI accessibility service. It does not restart Floorp or rewrite a running `prefs.js`. It is pinned (visible on every workspace) and floating at a configurable position and size, toggled from the bar icon or `SUPER+SHIFT+X`. By default hiding never closes the window, so the session and scroll position are preserved; low-memory mode closes it instead to free memory.

## Version 1.3.0

- **Low-memory mode** (Alt+click the `𝕏` icon, which turns lime): hiding closes X instead of keeping it in memory, and the next show opens a fresh window. If a post is still being written, the page's own leave-site prompt keeps it open and a notification asks you to save a draft.
- **Opens as the panel from the first frame**: in low-memory mode Chromium uses a lighter app window, and Hyprland places it floating, pinned and sized before it is drawn.
- **Choose the panel browser** in the preferences: the system default or any installed browser. Firefox runs X in a private panel profile without tabs or toolbar; closing it ends that Firefox process.
- A second click while X is still opening hides it instead of opening another window.

## Version 1.2.0

Uses the real default browser, restores Chromium unread counts while sending external links to normal browser windows, and adds a full-width count badge matching the desktop style. Includes the legacy keyboard-shortcut migration fix.

## Screenshot

![X Panel](preview.png)

## Features

- One persistent, always-on X window (your real session, not a separate login).
- Toggle show / hide from the bar icon or `SUPER+SHIFT+X` — hiding keeps the session alive (or frees it, in low-memory mode).
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
  - **Low-memory mode** (off by default): hiding closes the X window instead of parking it, so the browser frees the X tab's memory, and showing opens a fresh one. The close is a normal window close: if a post is still being written, X's own "leave site?" guard keeps the window open. The panel then stays on screen and a notification reminds you to save the post as a draft. The window is never force-closed. Turning the mode on also closes a panel that is currently hidden. Toggle it here or with **Alt+click** on the `𝕏` bar icon; the icon turns lime green while the mode is on. While the window is closed, the unread badge is not shown. In this mode Chromium browsers open X as a lighter app window (`--app=https://x.com/home`) instead of the popup, since the unread count is not needed. Its class is unique to the panel, so a Hyprland rule opens it floating, pinned, sized and in place from its first frame.
  - **Panel browser**: the system default or any installed browser (desktop entries in the `WebBrowser` category). Firefox-family browsers run X in a profile of their own (`~/.local/share/omarchy-x-panel/firefox`), separate from your normal Firefox: sign in to X there once. The panel process has its own window class, so it opens as the panel from its first frame; the profile's `userChrome.css` hides tabs and toolbar while X is the only tab (a link that opens a second tab brings them back so it can be closed), and first-run pages are disabled in its `user.js`. Closing the last panel window ends that Firefox process, which makes it a good fit for low-memory mode. Changing the browser closes the current panel first, with the same unsent-post check; if a post is being written, the change is not applied.
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
removes both and restores Omarchy's default bind. Enabling also migrates the
exact legacy `require("x-panel-bindings")` line to the namespaced spelling,
without duplicating it. Disabling removes both generated spellings. Other
configuration bytes and the file mode are preserved; a private
`.x-panel-backup-*` copy is kept beside `hyprland.lua` before each rewrite.
If the main config cannot be read completely or replaced, the module is
retained and the operation reports failure; fix the config access and retry.

## Usage

- **Left-click** the `𝕏` bar icon (or `SUPER+SHIFT+X`): toggle the X window.
- **Right-click** the `𝕏` bar icon: open the preferences panel (position / size), applied live.
- **Alt+click** the `𝕏` bar icon: turn low-memory mode on or off (lime icon = on).
- Clicking again while X is still opening hides it instead of opening a second window.
- The preferences panel **stays open and on top** while you pick options, so you can preview each change live (the X window sits behind it) — close it with the `✕` in the top-right corner.

## How it works

- Identity is tracked as `address|pid` in `$XDG_RUNTIME_DIR/x-panel.state`.
- Layout is computed against the **safe area** (the monitor minus the Quickshell bar strip), so the panel never covers the bar.
- Preferences are persisted at `${XDG_CONFIG_HOME:-~/.config}/omarchy-x-panel/prefs.json` (survives reboots; outside the plugin directory, so writing them never triggers a plugin reload; a pre-1.1 file in `$XDG_RUNTIME_DIR` is migrated automatically) and applied live via the bundled helper script. State files are private and replaced atomically. File reads use `O_NOFOLLOW | O_NONBLOCK`, a regular-file check and a 256 KiB cap; compositor output is limited to 256 KiB with a five-second total deadline before collection.
- The default browser is resolved through `xdg-settings` (with an HTTPS MIME fallback) and its desktop entry, preserving launch arguments and the native profile. Floorp launches the registered X app with its native `--start-ssb` command and app window class; Floorp builds without the experimental app-specific Linux window class are supported by tracking the newly launched window and its PID instead of adopting an arbitrary browser window. The panel bypasses `X.desktop` and the stock webapp launcher, which substitutes Chromium for unsupported browsers. Changing the default browser leaves the old window intact and opens or reuses X in the newly selected browser. There is no silent Chromium fallback.

## Uninstall

```bash
omarchy plugin remove io.github.avillagran.omarchy-x-panel
```

If you turned the keybind on, turn it off first in the preferences panel; that
removes both generated changes. If the plugin is already gone, open
`~/.config/hypr/hyprland.lua` in your editor and remove only the exact standalone
lines `require("x-panel-bindings")` and `require("hypr.x-panel-bindings")`.
Save successfully **before** deleting `~/.config/hypr/x-panel-bindings.lua`;
retain the module if you cannot read or save the main config. Private
`.x-panel-backup-*` copies beside the config can be removed once you have checked
the result.

Preferences are kept outside the plugin directory, so removal leaves them. To
delete them too:

```bash
rm -rf ~/.config/omarchy-x-panel ~/.local/share/omarchy-x-panel
```

## Dependencies and side effects

Requires Omarchy with the Hyprland Lua dispatcher API, Python 3, jq, xdg-utils, uwsm-app and a supported system browser. No sudo or pkexec is required, and the plugin downloads no executable code. Floorp additionally requires Python GObject introspection and AT-SPI.

Chromium creates a private, static HTML file in a random 0700 directory under `$XDG_RUNTIME_DIR`, opens it through the browser, activates its own button once and removes the launcher after opening X. No network listener is created. The launcher and panel are identified by nonce, address and PID; unrelated browser windows are preserved. Popup behavior has been verified with Google Chrome; other Chromium derivatives still need live testing.

Runtime state uses `$XDG_RUNTIME_DIR/x-panel.*`; it contains window identity, timestamps, watchdog state and a toggle lock. A named Hyprland window rule (`omarchy-x-panel`) matching only the panel's own window class (the Firefox panel profile, or the `*-x.com__home-*` Chromium app used in low-memory mode) is registered at runtime with `hyprctl eval`; it is replaced on each launch and disappears when Hyprland reloads. Choosing a Firefox-family browser creates the private panel profile; delete `~/.local/share/omarchy-x-panel` to remove it and its X login. On logout it disappears. Floorp may initialize its default profile, registers X in that profile’s `ssb/ssb.json`, and disables the shared Web App toolbar setting through its native UI, temporarily enabling desktop accessibility and restoring its previous value. To reverse that optional browser change, re-enable **Show Toolbar** in Floorp Hub → Web Apps and remove X from Floorp’s own Web App list. Existing registrations are reused. Close the persistent browser panel manually if you no longer want it after removing the plugin.

## License

MIT — see [LICENSE](LICENSE).
