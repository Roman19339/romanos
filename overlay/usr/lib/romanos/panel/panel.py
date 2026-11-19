#!/usr/bin/env python3
"""
Panel Román — el escritorio de trabajo de RomanOS.

Una sola ventana con:
  • barra izquierda: tus apps del negocio (POS, Inventario, Recetario, Facturas…)
  • centro: la app elegida (cada una mantiene su sesión iniciada)
  • derecha: Claude, siempre a mano (Ctrl+Espacio o Super+Espacio)

Uso:
  roman-panel                       abre / trae al frente
  roman-panel --abrir inventario    abre un módulo
  roman-panel --preguntar "texto"   envía una pregunta a Claude
  roman-panel --claude              muestra/oculta la barra de Claude
  roman-panel --caja                modo caja: pantalla completa en el POS
"""
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, Gio, GLib, Gtk, WebKit2  # noqa: E402

APP_ID = "cl.roman.Panel"
AI = "http://127.0.0.1:7777"
ETC = Path("/etc/romanos")
CFG = Path(GLib.get_user_config_dir()) / "romanos"
DATA = Path(GLib.get_user_data_dir()) / "romanos" / "web"
CSS = b"""
window, .rp-side { background: #141110; }
.rp-side { border-right: 1px solid #3a302b; padding: 10px 8px; }
.rp-side button { background: transparent; border: 0; box-shadow: none; color: #f3ece6;
                  padding: 9px 10px; border-radius: 10px; font-size: 14px; }
.rp-side button:hover { background: #26201d; }
.rp-side button.activo { background: #d9452b; color: #fff; }
.rp-logo { color: #f3ece6; font-weight: 800; font-size: 17px; padding: 6px 10px 14px; }
.rp-logo-sub { color: #b5a79d; font-size: 11px; padding: 0 10px 12px; }
headerbar { background: #1d1917; color: #f3ece6; border-bottom: 1px solid #3a302b; }
headerbar button { color: #f3ece6; }
.rp-claude { border-left: 1px solid #3a302b; }
"""


def leer_modulos():
    try:
        return json.loads((ETC / "modulos.json").read_text(encoding="utf-8"))["modulos"]
    except Exception:
        return [{"id": "inicio", "nombre": "Inicio", "icono": "🏠", "url": "local:inicio"}]


def token_ai(espera=20):
    """Lee el token del servicio romanos-ai (lo arranca si no corre)."""
    f = CFG / ".token"
    t0 = time.time()
    intentado = False
    while time.time() - t0 < espera:
        try:
            urllib.request.urlopen(AI + "/api/salud", timeout=1)
            if f.exists():
                return f.read_text().strip()
        except Exception:
            if not intentado:
                subprocess.Popen(["systemctl", "--user", "start", "romanos-ai.service"])
                intentado = True
        time.sleep(0.4)
    return ""


class Panel(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Panel Román")
        self.set_default_size(1440, 900)
        self.set_icon_name("romanos")
        self.token = token_ai()
        self.vistas = {}
        self.botones = {}
        self.modulos = leer_modulos()

        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # Sesiones persistentes (cookies / logins de cada app)
        DATA.mkdir(parents=True, exist_ok=True)
        self.dm = WebKit2.WebsiteDataManager(base_data_directory=str(DATA), base_cache_directory=str(DATA / "cache"))
        self.ctx = WebKit2.WebContext.new_with_website_data_manager(self.dm)
        self.ctx.get_cookie_manager().set_persistent_storage(str(DATA / "cookies.sqlite"), WebKit2.CookiePersistentStorage.SQLITE)
        self.ctx.connect("download-started", self._descarga)

        # Barra superior
        hb = Gtk.HeaderBar(show_close_button=True)
        hb.set_title("RomanOS")
        self.subtitulo = hb
        self.reloj = Gtk.Label()
        hb.pack_end(self._boton_icono("✦ Claude", "Mostrar u ocultar a Claude (Ctrl+Espacio)", lambda *_: self.alternar_claude()))
        hb.pack_end(self.reloj)
        hb.pack_start(self._boton_icono("⟳", "Recargar", lambda *_: self.vista_actual() and self.vista_actual().reload()))
        hb.pack_start(self._boton_icono("←", "Atrás", lambda *_: self.vista_actual() and self.vista_actual().go_back()))
        self.set_titlebar(hb)
        GLib.timeout_add_seconds(15, self._tick)
        self._tick()

        # Barra lateral
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        side.get_style_context().add_class("rp-side")
        side.set_size_request(200, -1)
        logo = Gtk.Label(label="🔥 Román", xalign=0)
        logo.get_style_context().add_class("rp-logo")
        sub = Gtk.Label(label="Rotisería · Carnicería", xalign=0)
        sub.get_style_context().add_class("rp-logo-sub")
        side.pack_start(logo, False, False, 0)
        side.pack_start(sub, False, False, 0)
        for m in self.modulos:
            b = Gtk.Button(label=f"{m.get('icono','•')}   {m['nombre']}")
            b.get_child().set_xalign(0)
            b.set_tooltip_text(m.get("desc", m["nombre"]))
            b.connect("clicked", lambda _b, mid=m["id"]: self.abrir(mid))
            self.botones[m["id"]] = b
            side.pack_start(b, False, False, 0)
        side.pack_start(Gtk.Box(), True, True, 0)
        for txt, fn in (("⌨   Terminal Claude", self.terminal_claude), ("📁   Archivos", lambda: Gio.AppInfo.launch_default_for_uri("file://" + str(Path.home()), None)),
                        ("⚙   Ajustes Claude", lambda: self.abrir_url_claude("/ajustes"))):
            b = Gtk.Button(label=txt)
            b.get_child().set_xalign(0)
            b.connect("clicked", lambda _b, f=fn: f())
            side.pack_end(b, False, False, 0)

        # Centro + Claude
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120)
        self.claude = self._webview()
        self.claude.get_style_context().add_class("rp-claude")
        self.claude_box = Gtk.Box()
        self.claude_box.pack_start(self.claude, True, True, 0)
        self.claude_box.set_size_request(400, -1)
        self.abrir_url_claude("/chat")

        pan = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        pan.pack1(self.stack, True, False)
        pan.pack2(self.claude_box, False, False)
        pan.set_position(1000)
        root = Gtk.Box()
        root.pack_start(side, False, False, 0)
        root.pack_start(pan, True, True, 0)
        self.add(root)

        acc = Gtk.AccelGroup()
        acc.connect(Gdk.keyval_from_name("space"), Gdk.ModifierType.CONTROL_MASK, 0, lambda *_: self.alternar_claude() or True)
        acc.connect(Gdk.keyval_from_name("F11"), 0, 0, lambda *_: self._pantalla_completa() or True)
        self.add_accel_group(acc)
        self.completa = False
        self.show_all()
        self.abrir("inicio")

    # ---- utilidades
    def _boton_icono(self, txt, tip, cb):
        b = Gtk.Button(label=txt)
        b.set_tooltip_text(tip)
        b.connect("clicked", cb)
        return b

    def _tick(self):
        self.reloj.set_text(time.strftime("%H:%M"))
        return True

    def _pantalla_completa(self):
        self.completa = not self.completa
        (self.fullscreen if self.completa else self.unfullscreen)()

    def _webview(self):
        v = WebKit2.WebView.new_with_context(self.ctx)
        s = v.get_settings()
        s.set_enable_developer_extras(True)
        s.set_javascript_can_access_clipboard(True)
        s.set_enable_media_stream(True)  # escáner por cámara, micrófono para DJ/anuncios
        s.set_media_playback_requires_user_gesture(False)
        s.set_user_agent_with_application_details("RomanOS", "1.0")
        v.connect("decide-policy", self._politica)
        v.connect("create", self._emergente)  # ventanas emergentes (target=_blank) se abren en la misma vista
        v.connect("permission-request", lambda _v, req: req.allow() or True)
        return v

    def _emergente(self, view, accion):
        view.load_request(accion.get_request())
        return None

    def _politica(self, view, decision, tipo):
        if tipo != WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            return False
        uri = decision.get_navigation_action().get_request().get_uri()
        if uri.startswith("roman://"):
            u = urllib.parse.urlparse(uri)
            q = urllib.parse.parse_qs(u.query)
            if u.netloc == "preguntar":
                self.preguntar(q.get("q", [""])[0])
            elif u.netloc == "abrir":
                self.abrir(q.get("m", ["inicio"])[0])
            decision.ignore()
            return True
        return False

    def _descarga(self, _ctx, dl):
        destino = Path(GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD) or Path.home() / "Descargas")

        def nombre(d, sugerido):
            d.set_destination("file://" + str(destino / sugerido))
            return True
        dl.connect("decide-destination", nombre)
        dl.connect("finished", lambda d: subprocess.Popen(["notify-send", "-i", "document-save", "Descarga lista",
                                                          Path(urllib.parse.unquote(d.get_destination() or "")).name]))

    # ---- acciones
    def vista_actual(self):
        return self.stack.get_visible_child()

    def abrir(self, mid):
        m = next((x for x in self.modulos if x["id"] == mid), None)
        if not m:
            return
        if mid not in self.vistas:
            v = self._webview()
            url = m["url"]
            if url.startswith("local:"):
                url = f"{AI}/{url[6:]}?t={urllib.parse.quote(self.token)}"
            v.load_uri(url)
            self.stack.add_named(v, mid)
            v.show()
            self.vistas[mid] = v
        self.stack.set_visible_child_name(mid)
        for k, b in self.botones.items():
            ctx = b.get_style_context()
            (ctx.add_class if k == mid else ctx.remove_class)("activo")
        self.get_titlebar().set_subtitle(m["nombre"])
        self.present()

    def abrir_url_claude(self, ruta, extra=""):
        if not self.token:
            self.token = token_ai(5)
        self.claude.load_uri(f"{AI}{ruta}?t={urllib.parse.quote(self.token)}{extra}")

    def alternar_claude(self, mostrar=None):
        vis = not self.claude_box.get_visible() if mostrar is None else mostrar
        self.claude_box.set_visible(vis)
        if vis:
            self.claude.grab_focus()

    def preguntar(self, texto):
        self.alternar_claude(True)
        self.abrir_url_claude("/chat", "&q=" + urllib.parse.quote(texto))
        self.present()

    def terminal_claude(self):
        Gio.Subprocess.new(["xfce4-terminal", "--title=Claude", "--working-directory=" + str(Path.home()), "-x", "bash", "-lc", "roman-claude-terminal"], Gio.SubprocessFlags.NONE)


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = None

    def do_command_line(self, cl):
        args = cl.get_arguments()[1:]
        if not self.win:
            self.win = Panel(self)
        i = 0
        while i < len(args):
            a = args[i]
            nxt = args[i + 1] if i + 1 < len(args) else ""
            if a == "--abrir":
                self.win.abrir(nxt); i += 1
            elif a == "--preguntar":
                self.win.preguntar(nxt); i += 1
            elif a == "--claude":
                self.win.alternar_claude()
            elif a == "--caja":
                self.win.abrir("pos"); self.win.alternar_claude(False); self.win.fullscreen()
            i += 1
        self.win.present()
        return 0


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
