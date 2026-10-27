// Sidepanel X — Opera-GX style always-on X (Twitter) side panel for Omarchy.
// Left click: toggle the X window (show/hide without closing — session kept).
// Right click: open the preferences popup (PopupWindow anchored under the icon).
// While the panel is shown, grips on its free corners resize it; the size is
// saved per monitor.
//
// The PopupWindow is declared inline (not via Loader) because a PopupWindow is
// a top-level window and cannot be a Loader item child of a BarWidget — that
// left panelLoader.item null and the panel never opened.
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import Quickshell.Wayland
import QtQuick.Controls
import qs.Ui
import qs.Commons

BarWidget {
  id: root
  moduleName: "io.github.avillagran.omarchy-x-panel"

  // Absolute path to the helper script, resolved relative to this plugin
  // (so it works after `omarchy plugin add` without copying to PATH).
  readonly property string binPath: Qt.resolvedUrl("bin/omarchy-x-panel").toString().replace("file://", "")

  readonly property bool opened: geom.visible === true
  // Panel window geometry from the helper's `geom` (monitor-relative).
  property var geom: ({ visible: false })
  property bool geomPending: false
  property bool panelFocused: false
  // A fullscreen app on the active workspace hides the grips.
  property bool fullscreenActive: false
  readonly property string panelAddr: geom.address ? String(geom.address).replace(/^0x/, "") : ""
  // Every monitor's bar mounts its own instance of this widget. Only one may
  // drive the grips and hide-on-blur (the one on the panel's monitor), and
  // only one may run the watchdog (the first screen's), or work is doubled.
  readonly property string hostScreen: QsWindow.window && QsWindow.window.screen ? QsWindow.window.screen.name : ""
  readonly property bool primaryBar: hostScreen === "" || Quickshell.screens.length === 0 || hostScreen === Quickshell.screens[0].name
  readonly property bool ownsPanel: hostScreen === "" || (root.geom.monitor ? hostScreen === root.geom.monitor : primaryBar)
  readonly property var panelScreen: {
    var ss = Quickshell.screens
    for (var i = 0; i < ss.length; i++)
      if (ss[i].name === root.geom.monitor) return ss[i]
    return null
  }
  property int unreadCount: 0
  readonly property string unreadLabel: String(unreadCount)

  function refresh() {
    if (geomProc.running) root.geomPending = true
    else geomProc.running = true
  }
  function applyGeom(data) {
    try {
      var g = JSON.parse(data || "{}")
      root.geom = g
      root.panelFocused = g.focused === true
      if (!gripLayer.dragging) gripLayer.syncFromGeom()
    } catch (e) {}
  }
  function refreshUnread() { unreadProc.running = true }

  Process {
    id: unreadProc
    command: [root.binPath, "unread-count"]
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var parsed = Number(text.trim())
        root.unreadCount = isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 0
      }
    }
  }

  // Chromium updates the X webapp title when notifications arrive. A modest
  // polling interval keeps the bar current without touching the browser.
  Timer {
    interval: 12000
    repeat: true
    running: true
    onTriggered: root.refreshUnread()
  }

  Process {
    id: geomProc
    command: [root.binPath, "geom"]
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyGeom(text)
    }
    onExited: if (root.geomPending) { root.geomPending = false; running = true }
  }

  Timer {
    id: pollTimer
    interval: 300
    repeat: false
    onTriggered: root.refresh()
  }
  // Helper actions take a moment (move, resize, focus), so read the geometry
  // once they have settled.
  Timer {
    id: settleTimer
    interval: 900
    repeat: false
    onTriggered: root.refresh()
  }

  // Hyprland events keep the grips and the focus state current. activewindowv2
  // also drives hide-on-blur: only a focus change AWAY from the panel counts.
  Connections {
    target: Hyprland
    function onRawEvent(event) {
      if (!event) return
      var name = String(event.name || "")
      if (name === "activewindowv2") {
        var addr = String(event.data || "").replace(/^0x/, "")
        var wasFocused = root.panelFocused
        root.panelFocused = addr !== "" && addr === root.panelAddr
        if (root.panelFocused) {
          pollTimer.restart()
          if (!wasFocused && root.ownsPanel && root.curWatchdog)
            Quickshell.execDetached([root.binPath, "focused"])
        }
        else if (wasFocused && addr !== "" && root.ownsPanel && root.curAutohide && !popup.popupOpen && !gripLayer.dragging)
          Quickshell.execDetached([root.binPath, "hide-if-blurred", addr])
      } else if (name === "fullscreen") {
        root.fullscreenActive = String(event.data || "") === "1"
      } else if (name === "movewindowv2" || name === "openwindow" || name === "closewindow"
                 || name === "changefloatingmode" || name === "pin"
                 || name === "monitoradded" || name === "monitorremoved") {
        pollTimer.restart()
      }
    }
  }

  // Watchdog: the helper flags a reload if X's title says the page is broken
  // for several checks in a row; it runs when the panel next gets focus.
  Process { id: watchdogProc; command: [root.binPath, "watchdog"]; running: false }
  Timer {
    interval: 60000
    repeat: true
    running: root.curWatchdog && root.primaryBar
    onTriggered: watchdogProc.running = true
  }

  Component.onCompleted: {
    root.refresh()
    root.refreshUnread()
    // Load prefs + i18n via Process+StdioCollector (same robust pattern as the
    // Omarchy Control Panel) instead of FileView, which does not auto-load
    // without running:true in this Quickshell build.
    prefsLoader.running = true
    i18nLoader.running = true
    localeProc.running = true
  }

  function toggle() {
    Quickshell.execDetached([root.binPath, "toggle"])
    Qt.callLater(function () { pollTimer.restart() })
  }

  // --- i18n ----------------------------------------------------------------
  property var i18n: ({})
  // Detect the OS locale (localectl) because Quickshell's env is LANG=C, so
  // Qt.locale().name falls back to en_US. Mirrors the Omarchy Control Panel.
  property string sysLocale: ""
  readonly property string lang: {
    var l = (root.sysLocale && root.sysLocale !== ""
      ? root.sysLocale
      : (Qt.locale().name || "en_US"))
    return l.toLowerCase().split(/[_.]/)[0]
  }
  function loadI18n(data) { try { root.i18n = JSON.parse(data || "{}") } catch (e) {} }
  function tr(k) {
    if (root.i18n[root.lang] && root.i18n[root.lang][k] !== undefined) return root.i18n[root.lang][k]
    if (root.i18n["en"] && root.i18n["en"][k] !== undefined) return root.i18n["en"][k]
    return k
  }

  property string curSide: "right"
  property string curValign: "top"
  property var curWidth: 420
  property var curHeight: "75%"
  property int curRefresh: 60
  property bool curWatchdog: true
  property bool curAutohide: false
  property string curMonitor: ""

  function applyPrefs(data) {
    try {
      var d = JSON.parse(data || "{}")
      if (d.side) root.curSide = d.side
      if (d.valign) root.curValign = d.valign
      if (d.width !== undefined) root.curWidth = d.width
      if (d.height !== undefined) root.curHeight = d.height
      if (d.refresh !== undefined) root.curRefresh = d.refresh
      if (d.watchdog !== undefined) root.curWatchdog = d.watchdog
      if (d.autohide !== undefined) root.curAutohide = d.autohide
      if (d.monitor !== undefined) root.curMonitor = d.monitor
    } catch (e) {}
  }

  // --- loaders (Process + StdioCollector, mirroring Omarchy Control Panel) --
  // Prefs go through the helper's get-prefs, which reads via the single-open
  // O_NOFOLLOW+fstat-capped reader — never an unbounded cat into QML.
  Process {
    id: prefsLoader
    running: false
    command: [root.binPath, "get-prefs"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyPrefs(text)
    }
  }
  Process {
    id: i18nLoader
    running: false
    command: ["bash", "-lc", "head -c 262144 '" + Qt.resolvedUrl("i18n.json").toString().replace("file://", "") + "'"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.loadI18n(text)
    }
  }
  property bool bindOn: false

  // Keybind on/off state (reads `bind-status` from the helper).
  Process {
    id: bindStatusProc
    running: false
    command: [root.binPath, "bind-status"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.bindOn = (text.trim() === "enabled")
    }
  }
  // bind-toggle takes ~1s (writes + hyprctl reload), so re-check AFTER it
  // finishes — an immediate re-read would fetch the OLD state and the switch
  // would not move.
  Timer {
    id: bindRecheck
    interval: 1500
    onTriggered: bindStatusProc.running = true
  }

  // OS locale detection (Quickshell env is LANG=C, so Qt.locale() is wrong).
  Process {
    id: localeProc
    running: false
    command: ["bash", "-lc", "localectl status 2>/dev/null | grep -i 'LANG=' | head -1"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var m = text.match(/LANG=([A-Za-z]+)/)
        if (m) root.sysLocale = m[1]
      }
    }
  }

  function refreshLabel(m) { return m >= 60 ? (m / 60) + " h" : m + " min" }

  function setPref(key, value) {
    Quickshell.execDetached([root.binPath, "set-pref", key, String(value)])
    settleTimer.restart()
  }

  // In-panel keyboard shortcut helpers: % cycles height, + cycles width.
  function cycleWidth() {
    var ws = [320, 420, 520, 620, 1080]
    var i = ws.indexOf(root.curWidth)
    var n = ws[(i + 1) % ws.length]
    setPref("width", n); root.curWidth = n
  }
  function cycleHeight() {
    var hs = ["25%", "50%", "75%", "100%"]
    var i = hs.indexOf(root.curHeight)
    var n = hs[(i + 1) % hs.length]
    setPref("height", '"' + n + '"'); root.curHeight = n
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "𝕏"
    labelVisible: false
    fixedWidth: Math.ceil(buttonContent.implicitWidth + button.scaledHorizontalMargin * 2)
    fixedHeight: button.vertical ? Math.max(button.barSize, buttonContent.implicitHeight + button.scaledVerticalPadding * 2) : -1
    tooltipText: "Toggle X side panel (SUPER+SHIFT+X) · right-click for preferences"
    onPressed: function (b) {
      if (b === Qt.LeftButton) root.toggle()
      else if (b === Qt.RightButton) popup.togglePanel()
    }

    // El ancho del botón incluye el badge completo, sin superponerlo a la X.
    Row {
      id: buttonContent
      anchors.centerIn: parent
      spacing: Style.spaceReal(4)

      Text {
        textFormat: Text.PlainText
        anchors.verticalCenter: parent.verticalCenter
        text: button.text
        color: button.foreground
        font.family: button.fontFamily
        font.pixelSize: Math.round(button.fontSize * 1.15)
        renderType: Text.NativeRendering
      }

      Rectangle {
        visible: root.unreadCount > 0
        anchors.verticalCenter: parent.verticalCenter
        // Mismas medidas y tipografía que T3StatusBadges; sin limitar el número.
        width: Math.max(Style.space(14), unreadText.implicitWidth + Style.space(6))
        height: Style.space(10)
        radius: Style.space(2.5)
        color: button.activeColor

        Text {
          id: unreadText
          textFormat: Text.PlainText
          anchors.centerIn: parent
          text: root.unreadLabel
          color: Color.popups.background
          font.pixelSize: Style.space(8)
          font.bold: true
        }
      }
    }
  }

  // --- resize grips --------------------------------------------------------
  // A transparent overlay on the panel's monitor whose input region is only
  // the grips. The panel is anchored by side/valign, so the anchored edges stay
  // put: a grip resizes along each axis whose edge is free (both edges when
  // centered). The window follows live; the size is saved on release.
  component Grip: Item {
    id: grip
    required property int hdir   // -1 left edge, +1 right edge
    required property int vdir   // -1 top edge, +1 bottom edge
    // Inline components cannot see this file's ids, so the overlay is passed in.
    required property var host
    readonly property bool freeH: grip.host.freeH(hdir)
    readonly property bool freeV: grip.host.freeV(vdir)
    readonly property int size: Style.space(14)

    // Same discreet corner mark as Omarchy's pinned panels: a faint ◢ turned
    // to face its corner, brighter on hover. Inside the panel's corner: with
    // focus-follows-mouse, reaching a grip must not cross another window.
    width: (freeH || freeV) ? size : 0
    height: width
    x: hdir < 0 ? grip.host.liveX : grip.host.liveX + grip.host.liveW - size
    y: vdir < 0 ? grip.host.liveY : grip.host.liveY + grip.host.liveH - size

    Text {
      textFormat: Text.PlainText
      anchors.centerIn: parent
      text: "◢"
      rotation: grip.hdir < 0 ? (grip.vdir < 0 ? 180 : 90) : (grip.vdir < 0 ? 270 : 0)
      color: Color.popups.text
      opacity: gripArea.containsMouse || gripArea.pressed ? 0.6 : 0.16
      font.pixelSize: Style.space(10)
    }

    MouseArea {
      id: gripArea
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: grip.freeH && grip.freeV
        ? (grip.hdir * grip.vdir > 0 ? Qt.SizeFDiagCursor : Qt.SizeBDiagCursor)
        : (grip.freeH ? Qt.SizeHorCursor : Qt.SizeVerCursor)
      property real startX: 0
      property real startY: 0
      // Scene coordinates: the grip itself moves while it is dragged.
      onPressed: function (m) {
        var p = mapToItem(null, m.x, m.y)
        startX = p.x; startY = p.y
        grip.host.beginDrag()
      }
      onPositionChanged: function (m) {
        if (!pressed || !grip.host.dragging) return
        var p = mapToItem(null, m.x, m.y)
        grip.host.dragTo(grip.hdir, grip.vdir, p.x - startX, p.y - startY)
      }
      onReleased: grip.host.endDrag()
      onCanceled: grip.host.endDrag()
    }
  }

  PanelWindow {
    id: gripLayer
    screen: root.panelScreen
    visible: root.ownsPanel && root.panelScreen !== null && root.geom.visible === true && (!root.fullscreenActive || dragging)
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "omarchy-x-panel-grips"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    anchors { top: true; bottom: true; left: true; right: true }
    mask: Region {
      Region { item: gripTL }
      Region { item: gripTR }
      Region { item: gripBL }
      Region { item: gripBR }
    }

    property bool dragging: false
    property int liveX: 0
    property int liveY: 0
    property int liveW: 0
    property int liveH: 0
    property int x0: 0
    property int y0: 0
    property int w0: 0
    property int h0: 0
    readonly property string side: root.geom.side || "right"
    readonly property string valign: root.geom.valign || "top"

    function freeH(h) { return side === "center" || (h < 0 ? side !== "left" : side !== "right") }
    function freeV(v) { return valign === "center" || (v < 0 ? valign !== "top" : valign !== "bottom") }
    function syncFromGeom() {
      liveX = root.geom.x || 0; liveY = root.geom.y || 0
      liveW = root.geom.w || 0; liveH = root.geom.h || 0
    }
    function beginDrag() {
      dragging = true
      x0 = liveX; y0 = liveY; w0 = liveW; h0 = liveH
    }
    function dragTo(h, v, dx, dy) {
      var nw = w0, nh = h0
      if (freeH(h)) nw = Math.round(Math.max(280, Math.min(width - 40, w0 + h * dx * (side === "center" ? 2 : 1))))
      if (freeV(v)) nh = Math.round(Math.max(200, Math.min(height - 16, h0 + v * dy * (valign === "center" ? 2 : 1))))
      liveW = nw; liveH = nh
      liveX = side === "left" ? x0 : side === "center" ? Math.round(x0 + (w0 - nw) / 2) : x0 + w0 - nw
      liveY = valign === "top" ? y0 : valign === "center" ? Math.round(y0 + (h0 - nh) / 2) : y0 + h0 - nh
      if (!liveTimer.running) liveTimer.start()
    }
    function pushLive() {
      var w = "window = \"address:0x" + root.panelAddr + "\""
      Hyprland.dispatch("hl.dsp.window.resize({ " + w + ", x = " + liveW + ", y = " + liveH + " })")
      Hyprland.dispatch("hl.dsp.window.move({ " + w + ", x = " + (liveX + (root.geom.mx || 0)) + ", y = " + (liveY + (root.geom.my || 0)) + " })")
    }
    function endDrag() {
      if (!dragging) return
      liveTimer.stop()
      pushLive()
      dragging = false
      root.curWidth = liveW; root.curHeight = liveH
      Quickshell.execDetached([root.binPath, "set-size", String(liveW), String(liveH)])
      settleTimer.restart()
    }

    // Throttle live resizes: Chromium re-lays out X on every one.
    Timer { id: liveTimer; interval: 50; onTriggered: gripLayer.pushLive() }

    Grip { id: gripTL; host: gripLayer; hdir: -1; vdir: -1 }
    Grip { id: gripTR; host: gripLayer; hdir: 1; vdir: -1 }
    Grip { id: gripBL; host: gripLayer; hdir: -1; vdir: 1 }
    Grip { id: gripBR; host: gripLayer; hdir: 1; vdir: 1 }
  }

  // --- preferences panel (KeyboardPanel) ---------------------------------
  // xdg-popups (PopupWindow) never receive keyboard focus on Hyprland —
  // keys go to the parent surface. Keyboard-driven panels must be
  // layer-shell windows (KeyboardPanel, layer Overlay, keyboardFocus OnDemand).
  QtObject { id: popupOwner; function close() { popup.popupOpen = false } }

  KeyboardPanel {
    id: popup
    anchorItem: button
    bar: root.bar
    owner: popupOwner
    open: popupOpen
    focusTarget: keyCatcher
    contentWidth: 475
    contentHeight: popup.fittedContentHeight(column.implicitHeight, Style.space(700))

    property bool popupOpen: false
    readonly property color fg: bar ? bar.foreground : "#fff"

    function openPanel()   { prefsLoader.running = true; i18nLoader.running = true; localeProc.running = true; bindStatusProc.running = true; popup.popupOpen = true; Quickshell.execDetached([root.binPath, "prefs-open"]) }
    function closePanel()  { popup.popupOpen = false; Quickshell.execDetached([root.binPath, "prefs-close"]) }
    function togglePanel() { if (popup.popupOpen) popup.closePanel(); else popup.openPanel() }

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent

      onCloseRequested: popup.closePanel()

      // Arrows (and vim hjkl) set position: <-/-> side, up/down vertical.
      onMoveRequested: function (dx, dy) {
        if (dx < 0)      { setPref("side", "\"left\"");   root.curSide = "left" }
        else if (dx > 0) { setPref("side", "\"right\"");  root.curSide = "right" }
        if (dy < 0)      { setPref("valign", "\"top\"");    root.curValign = "top" }
        else if (dy > 0) { setPref("valign", "\"bottom\""); root.curValign = "bottom" }
      }

      // | = center side, - = center vertical, % = cycle height, + = cycle width.
      onTextKey: function (t) {
        if (t === "|")      { setPref("side", "\"center\"");   root.curSide = "center" }
        else if (t === "-") { setPref("valign", "\"center\""); root.curValign = "center" }
        else if (t === "%") { cycleHeight() }
        else if (t === "+") { cycleWidth() }
      }

      Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true

        Column {
          id: column
          width: parent.width
          spacing: Style.space(12)

          // Header (estilo Omarchy Control Panel) con boton de cierre
          Row {
            width: parent.width
            spacing: Style.space(8)
            Text {
              textFormat: Text.PlainText
              text: "𝕏"
              color: Color.accent
              font.family: popup.bar ? popup.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.title
              anchors.verticalCenter: parent.verticalCenter
            }
            Text {
              textFormat: Text.PlainText
              text: tr("title")
              color: popup.fg
              font.family: popup.bar ? popup.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.subtitle
              font.bold: true
              anchors.verticalCenter: parent.verticalCenter
            }
            Item { width: parent.width - x - 30; height: 1 }
            Button {
              iconText: "✕"
              bordered: false
              anchors.verticalCenter: parent.verticalCenter
              onClicked: popup.closePanel()
            }
          }

          PanelSeparator { foreground: popup.fg }

          // Seccion Posicion
          Column {
            width: parent.width
            spacing: Style.space(8)
            Text {
              textFormat: Text.PlainText
              width: parent.width
              text: tr("side") + ": " + tr(root.curSide) + "    " + tr("vertical") + ": " + tr(root.curValign)
              color: popup.fg
              opacity: 0.7
              font.family: popup.bar ? popup.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.caption
            }
            Row {
              spacing: Style.space(6)
              Button { iconText: "◀"; text: tr("left");   bordered: true; selected: root.curSide === "left";   onClicked: function () { setPref("side", "\"left\"");   root.curSide = "left" } }
              Button { iconText: "▮"; text: tr("center"); bordered: true; selected: root.curSide === "center"; onClicked: function () { setPref("side", "\"center\""); root.curSide = "center" } }
              Button { iconText: "▶"; text: tr("right");  bordered: true; selected: root.curSide === "right";  onClicked: function () { setPref("side", "\"right\"");  root.curSide = "right" } }
            }
            Row {
              spacing: Style.space(6)
              Button { iconText: "▲"; text: tr("top");    bordered: true; selected: root.curValign === "top";    onClicked: function () { setPref("valign", "\"top\"");    root.curValign = "top" } }
              Button { iconText: "▬"; text: tr("middle"); bordered: true; selected: root.curValign === "center"; onClicked: function () { setPref("valign", "\"center\""); root.curValign = "center" } }
              Button { iconText: "▼"; text: tr("bottom"); bordered: true; selected: root.curValign === "bottom"; onClicked: function () { setPref("valign", "\"bottom\""); root.curValign = "bottom" } }
            }
          }

          // Seccion Tamano
          Column {
            width: parent.width
            spacing: Style.space(8)
            Text {
              textFormat: Text.PlainText
              width: parent.width
              text: tr("width") + ": " + root.curWidth + "    " + tr("height") + ": " + root.curHeight
                + (root.curMonitor !== "" ? "    (" + root.curMonitor + ")" : "")
              color: popup.fg
              opacity: 0.7
              font.family: popup.bar ? popup.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.caption
            }
            Flow {
              width: parent.width
              spacing: Style.space(4)
              Button { iconText: "█"; text: "320"; bordered: true; selected: root.curWidth === 320; onClicked: function () { setPref("width", 320); root.curWidth = 320 } }
              Button { iconText: "██"; text: "420"; bordered: true; selected: root.curWidth === 420; onClicked: function () { setPref("width", 420); root.curWidth = 420 } }
              Button { iconText: "███"; text: "520"; bordered: true; selected: root.curWidth === 520; onClicked: function () { setPref("width", 520); root.curWidth = 520 } }
              Button { iconText: "████"; text: "620"; bordered: true; selected: root.curWidth === 620; onClicked: function () { setPref("width", 620); root.curWidth = 620 } }
              Button { iconText: "█████"; text: "1080"; bordered: true; selected: root.curWidth === 1080; onClicked: function () { setPref("width", 1080); root.curWidth = 1080 } }
            }
            Flow {
              width: parent.width
              spacing: Style.space(4)
              Button { iconText: "▁"; text: "25%"; bordered: true; selected: root.curHeight === "25%"; onClicked: function () { setPref("height", '"25%"'); root.curHeight = "25%" } }
              Button { iconText: "▃"; text: "50%"; bordered: true; selected: root.curHeight === "50%"; onClicked: function () { setPref("height", '"50%"'); root.curHeight = "50%" } }
              Button { iconText: "▅"; text: "75%"; bordered: true; selected: root.curHeight === "75%"; onClicked: function () { setPref("height", '"75%"'); root.curHeight = "75%" } }
              Button { iconText: "█"; text: "100%"; bordered: true; selected: root.curHeight === "100%"; onClicked: function () { setPref("height", '"100%"'); root.curHeight = "100%" } }
            }
            Text {
              textFormat: Text.PlainText
              width: parent.width
              text: tr("dragHint")
              color: popup.fg
              opacity: 0.55
              wrapMode: Text.WordWrap
              font.family: popup.bar ? popup.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.caption
            }
          }

          PanelSeparator { foreground: popup.fg }

          // Seccion Auto-refresco: reload X on show after N minutes hidden
          // (long-lived X tabs degrade over time). 0 = off.
          Column {
            width: parent.width
            spacing: Style.space(8)
            Text {
              textFormat: Text.PlainText
              width: parent.width
              text: tr("autoRefresh") + ": " + (root.curRefresh > 0 ? tr("afterHidden").replace("%1", refreshLabel(root.curRefresh)) : tr("off"))
              color: popup.fg
              opacity: 0.7
              wrapMode: Text.WordWrap
              font.family: popup.bar ? popup.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.caption
            }
            Flow {
              width: parent.width
              spacing: Style.space(4)
              Repeater {
                model: [0, 30, 60, 180]
                Button {
                  required property int modelData
                  text: modelData > 0 ? refreshLabel(modelData) : tr("off")
                  bordered: true
                  selected: root.curRefresh === modelData
                  onClicked: function () { setPref("refresh", modelData); root.curRefresh = modelData }
                }
              }
              Button {
                iconText: "⟳"
                text: tr("reloadNow")
                bordered: true
                onClicked: function () { Quickshell.execDetached([root.binPath, "reload"]) }
              }
            }
          }

          PanelSeparator { foreground: popup.fg }

          Toggle {
            width: parent.width
            label: tr("watchdog")
            description: tr("watchdogDesc")
            checked: root.curWatchdog
            foreground: popup.fg
            onClicked: function () { root.curWatchdog = !root.curWatchdog; setPref("watchdog", root.curWatchdog) }
          }
          Toggle {
            width: parent.width
            label: tr("autohide")
            description: tr("autohideDesc")
            checked: root.curAutohide
            foreground: popup.fg
            onClicked: function () { root.curAutohide = !root.curAutohide; setPref("autohide", root.curAutohide) }
          }

          PanelSeparator { foreground: popup.fg }

          // Keyboard shortcut toggle (opt-in SUPER+SHIFT+X bind) — one line.
          Toggle {
            width: parent.width
            label: tr("keybind") + ": SUPER+SHIFT+X"
            checked: root.bindOn
            foreground: popup.fg
            onClicked: function () {
              root.bindOn = !root.bindOn   // optimistic: the switch moves now
              Quickshell.execDetached([root.binPath, "bind-toggle"])
              bindRecheck.restart()        // confirm from disk once it finishes
            }
          }

          // Marquee with the in-panel shortcuts (animates only when it overflows).
          Item {
            id: marqueeBox
            width: parent.width
            height: marq.implicitHeight
            clip: true
            Text {
              textFormat: Text.PlainText
              id: marq
              text: "← " + tr("left") + " → " + tr("right") + " ↑ " + tr("top") + " ↓ " + tr("bottom") + "  ·  | " + tr("center") + " − " + tr("middle") + "  ·  % " + tr("height") + "  ·  + " + tr("width")
              color: popup.fg
              opacity: 0.55
              font.family: popup.bar ? popup.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.caption
              SequentialAnimation on x {
                loops: Animation.Infinite
                running: popup.popupOpen && marq.implicitWidth > marqueeBox.width
                PauseAnimation { duration: 1600 }
                NumberAnimation { to: -(marq.implicitWidth - marqueeBox.width); duration: Math.max(2500, (marq.implicitWidth - marqueeBox.width) * 28); easing.type: Easing.InOutSine }
                PauseAnimation { duration: 1600 }
                NumberAnimation { to: 0; duration: 900; easing.type: Easing.InOutSine }
              }
            }
          }
        }
      }
    }
  }
}
