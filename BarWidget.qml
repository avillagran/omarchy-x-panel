// Sidepanel X — Opera-GX style always-on X (Twitter) side panel for Omarchy.
// Left click: toggle the X window (show/hide without closing — session kept).
// Right click: open the preferences popup (PopupWindow anchored under the icon).
//
// The PopupWindow is declared inline (not via Loader) because a PopupWindow is
// a top-level window and cannot be a Loader item child of a BarWidget — that
// left panelLoader.item null and the panel never opened.
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import QtQuick.Controls
import qs.Ui
import qs.Commons

BarWidget {
  id: root
  moduleName: "io.github.avillagran.omarchy-x-panel"

  // Absolute path to the helper script, resolved relative to this plugin
  // (so it works after `omarchy plugin add` without copying to PATH).
  readonly property string binPath: Qt.resolvedUrl("bin/omarchy-x-panel").toString().replace("file://", "")

  readonly property bool opened: panelState.visible
  property var panelState: ({ visible: false })

  function refresh() { visProc.running = true }

  Process {
    id: visProc
    command: [root.binPath, "is-visible"]
    running: false
    onExited: function (exitCode) {
      panelState.visible = (exitCode === 0)
    }
  }

  Timer {
    id: pollTimer
    interval: 300
    repeat: false
    onTriggered: root.refresh()
  }

  Component.onCompleted: {
    root.refresh()
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

  function applyPrefs(data) {
    try {
      var d = JSON.parse(data || "{}")
      if (d.side) root.curSide = d.side
      if (d.valign) root.curValign = d.valign
      if (d.width !== undefined) root.curWidth = d.width
      if (d.height !== undefined) root.curHeight = d.height
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

  function setPref(key, value) {
    Quickshell.execDetached([root.binPath, "set-pref", key, String(value)])
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
    tooltipText: "Toggle X side panel (SUPER+SHIFT+X) · right-click for preferences"
    onPressed: function (b) {
      if (b === Qt.LeftButton) root.toggle()
      else if (b === Qt.RightButton) popup.togglePanel()
    }
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
              text: "𝕏"
              color: Color.accent
              font.family: popup.bar ? popup.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.title
              anchors.verticalCenter: parent.verticalCenter
            }
            Text {
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
              width: parent.width
              text: tr("width") + ": " + root.curWidth + "    " + tr("height") + ": " + root.curHeight
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
