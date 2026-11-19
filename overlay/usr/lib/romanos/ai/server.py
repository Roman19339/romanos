#!/usr/bin/env python3
"""
RomanOS · servicio Claude nativo (romanos-ai)

Servicio de usuario que corre en 127.0.0.1:7777 y conecta a Claude con:
  * los datos del negocio (Inventario, Facturas, Recetario en Supabase)
  * el propio equipo (disco, red, impresoras, respaldos, archivos)

Lo usan el Panel Román (barra lateral de Claude), el comando `roman` en la
terminal, el menú contextual de archivos y el atajo Super+Espacio.

Solo usa la biblioteca estándar de Python: no requiere pip.
"""
from __future__ import annotations

import datetime as dt
import http.server
import json
import os
import secrets
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HOST, PORT = "127.0.0.1", int(os.environ.get("ROMANOS_AI_PORT", "7777"))
ETC = Path(os.environ.get("ROMANOS_ETC", "/etc/romanos"))
WEB = Path(__file__).resolve().parent / "web"
CFG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "romanos"
CFG_FILE = CFG_DIR / "config.json"
TOKEN_FILE = CFG_DIR / ".token"
HIST_DIR = CFG_DIR / "conversaciones"
DOCS = Path.home() / "Documentos"
API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_TURNS = 12


# --------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------
def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def servicios() -> dict:
    return load_json(ETC / "servicios.json", {})


def config() -> dict:
    c = load_json(CFG_FILE, {})
    c.setdefault("modelo", DEFAULT_MODEL)
    c.setdefault("cuentas", {})
    return c


def save_config(c: dict) -> None:
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CFG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(CFG_FILE)


def api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY") or config().get("anthropic_api_key")


def system_prompt() -> str:
    parts = []
    for p in (ETC / "contexto.md", CFG_DIR / "negocio.md"):
        if p.exists():
            parts.append(p.read_text(encoding="utf-8"))
    now = dt.datetime.now().strftime("%A %d-%m-%Y %H:%M")
    parts.append(f"Fecha y hora actual del equipo: {now}. Usuario del sistema: {os.environ.get('USER','')}.")
    return "\n\n".join(parts)


# --------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------
def http_json(method: str, url: str, headers: dict | None = None, body=None, timeout=40):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode() or "null"
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")[:500]
        raise RuntimeError(f"HTTP {e.code}: {msg}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Sin conexión ({e.reason}). Revisa internet.") from None


# --------------------------------------------------------------------------
# Conexión a los proyectos Supabase
# --------------------------------------------------------------------------
class Supa:
    _tokens: dict[str, tuple[str, float]] = {}
    _lock = threading.Lock()

    def __init__(self, nombre: str):
        s = servicios().get(nombre)
        if not s:
            raise RuntimeError(f"Servicio '{nombre}' no definido en /etc/romanos/servicios.json")
        self.nombre, self.url, self.anon, self.auth = nombre, s["url"].rstrip("/"), s["anon"], s.get("auth", "supabase")
        self.cuenta = config()["cuentas"].get(nombre, {})

    def _login(self) -> str:
        if not self.cuenta.get("usuario") or not self.cuenta.get("clave"):
            raise RuntimeError(f"Falta la cuenta de '{self.nombre}'. Configúrala con roman-setup.")
        if self.auth == "supabase":
            r = http_json("POST", f"{self.url}/auth/v1/token?grant_type=password", {"apikey": self.anon},
                          {"email": self.cuenta["usuario"], "password": self.cuenta["clave"]})
            return r["access_token"], time.time() + int(r.get("expires_in", 3600)) - 120
        # Recetario: sesión propia por RPC
        r = http_json("POST", f"{self.url}/rest/v1/rpc/iniciar_sesion", self._h(None),
                      {"p_usuario": self.cuenta["usuario"], "p_clave": self.cuenta["clave"]})
        tok = r.get("token") if isinstance(r, dict) else r
        if not tok:
            raise RuntimeError("El recetario no devolvió sesión: revisa usuario y clave.")
        return tok, time.time() + 6 * 3600

    def token(self) -> str:
        with self._lock:
            t = self._tokens.get(self.nombre)
            if not t or t[1] < time.time():
                t = self._login()
                self._tokens[self.nombre] = t
            return t[0]

    def _h(self, bearer):
        return {"apikey": self.anon, "Authorization": f"Bearer {bearer or self.anon}"}

    def select(self, tabla: str, params: dict) -> list:
        q = urllib.parse.urlencode(params, safe="*,.():")
        return http_json("GET", f"{self.url}/rest/v1/{tabla}?{q}", self._h(self.token()))

    def rpc(self, fn: str, args: dict):
        args = {"p_token": self.token(), **args}
        return http_json("POST", f"{self.url}/rest/v1/rpc/{fn}", self._h(None), args)


# --------------------------------------------------------------------------
# Herramientas de negocio
# --------------------------------------------------------------------------
def _ilike(v: str) -> str:
    return "ilike.*" + v.replace("*", "").replace(",", " ") + "*"


def t_inventario_productos(busqueda: str = "", categoria: str = "", solo_activos: bool = True, limite: int = 60):
    p = {"select": "id,code,name,cat,precio,kg_caja,activo,precio_fecha", "order": "cat,orden", "limit": str(min(limite, 300))}
    if busqueda:
        p["name"] = _ilike(busqueda)
    if categoria:
        p["cat"] = _ilike(categoria)
    if solo_activos:
        p["activo"] = "not.is.false"
    return Supa("inventario").select("productos", p)


def t_inventario_registros(tipo: str = "semanal", cantidad: int = 2):
    s = Supa("inventario")
    regs = s.select("inventarios", {"select": "id,fecha,tipo,sin_stock,items,nota,usuario_email",
                                    "tipo": f"eq.{tipo}", "order": "fecha.desc", "limit": str(min(cantidad, 10))})
    nombres = {p["id"]: p["name"] for p in s.select("productos", {"select": "id,name", "limit": "1000"})}
    for r in regs:
        items = r.get("items") or {}
        r["items"] = {nombres.get(k, k): v for k, v in items.items()} if isinstance(items, dict) else items
    return regs


def t_inventario_compras(desde: str, hasta: str = "", proveedor: str = "", producto: str = ""):
    p = {"select": "fecha,local,proveedor,folio,tipo_doc,nombre,cantidad,unidad,neto,producto_id",
         "ignorado": "is.false", "order": "fecha.desc", "limit": "500", "fecha": f"gte.{desde}"}
    if hasta:
        p["and"] = f"(fecha.lte.{hasta})"
    if proveedor:
        p["proveedor"] = _ilike(proveedor)
    if producto:
        p["nombre"] = _ilike(producto)
    rows = Supa("inventario").select("ingresos", p)
    total = sum(float(r.get("neto") or 0) for r in rows)
    return {"lineas": rows[:200], "n_lineas": len(rows), "neto_total": round(total)}


def t_inventario_ajustes():
    return Supa("inventario").select("ajustes", {"select": "*"})


def _locales(s: Supa) -> dict:
    return {l["id"]: l["nombre"] for l in s.select("locales", {"select": "id,nombre"})}


def _num(v) -> float:
    s = str(v if v is not None else "0").replace("$", "").replace(" ", "").strip() or "0"
    if "," in s:                       # formato chileno 12.345,5
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _neto(d: dict) -> float:
    return sum(_num(it.get("neto")) for it in (d.get("items") or []) if isinstance(it, dict))


def t_facturas(tipo: str = "recibidas", estado: str = "", desde: str = "", hasta: str = "", proveedor: str = "", local: str = "", detalle: bool = False):
    tabla = {"recibidas": "recib", "emitidas": "emit", "notas_credito": "nc"}.get(tipo)
    if not tabla:
        raise RuntimeError("tipo debe ser recibidas, emitidas o notas_credito")
    s = Supa("facturas")
    locs = _locales(s)
    out = []
    for r in s.select(tabla, {"select": "id,local_id,data", "limit": "2000"}):
        d = r.get("data") or {}
        fecha = d.get("emi") or d.get("fecha") or ""
        if estado and str(d.get("estado", "")).upper() != estado.upper():
            continue
        if desde and fecha and fecha < desde:
            continue
        if hasta and fecha and fecha > hasta:
            continue
        if proveedor and proveedor.lower() not in str(d.get("prov", "") + d.get("cliente", "")).lower():
            continue
        loc = locs.get(r.get("local_id"), "")
        if local and local.lower() not in loc.lower():
            continue
        fila = {k: v for k, v in d.items() if k != "items"}
        fila["local"] = loc
        fila["neto_items"] = round(_neto(d))
        if detalle:
            fila["items"] = d.get("items")
        out.append(fila)
    out.sort(key=lambda x: x.get("emi") or x.get("fecha") or "", reverse=True)
    return {"n": len(out), "neto_total": sum(f["neto_items"] for f in out), "facturas": out[:150]}


def t_facturas_por_vencer(dias: int = 7):
    hoy = dt.date.today()
    lim = (hoy + dt.timedelta(days=dias)).isoformat()
    res = t_facturas("recibidas")["facturas"]
    pend = [f for f in res if str(f.get("estado", "")).upper() != "PAGADO" and f.get("venc")]
    vencidas = [f for f in pend if f["venc"] < hoy.isoformat()]
    proximas = [f for f in pend if hoy.isoformat() <= f["venc"] <= lim]
    pick = lambda L: [{k: f.get(k) for k in ("local", "prov", "folio", "emi", "venc", "neto_items", "estado")} for f in sorted(L, key=lambda x: x["venc"])]
    return {"hoy": hoy.isoformat(), "vencidas": pick(vencidas), "por_vencer": pick(proximas),
            "monto_vencido": sum(f["neto_items"] for f in vencidas), "monto_por_vencer": sum(f["neto_items"] for f in proximas)}


def t_personal(local: str = "", incluir_remuneraciones: bool = False):
    s = Supa("facturas")
    locs = _locales(s)
    def rows(t):
        out = []
        for r in s.select(t, {"select": "id,local_id,data", "limit": "1000"}):
            l = locs.get(r["local_id"], "")
            if not local or local.lower() in l.lower():
                out.append({"local": l, **(r.get("data") or {})})
        return out
    res = {"personal": rows("pers")}
    if incluir_remuneraciones:
        res["remuneraciones"] = rows("remu")
    return res


def t_recetas(busqueda: str = ""):
    r = Supa("recetario").rpc("recetas_listar", {})
    lista = r if isinstance(r, list) else (r or {}).get("recetas", r)
    if busqueda and isinstance(lista, list):
        b = busqueda.lower()
        lista = [x for x in lista if b in json.dumps(x, ensure_ascii=False).lower()]
    return lista


# --------------------------------------------------------------------------
# Herramientas del equipo
# --------------------------------------------------------------------------
def sh(cmd: list[str], timeout=15) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception as e:
        return f"(no disponible: {e})"


def t_estado_equipo():
    du = shutil.disk_usage("/")
    mem = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            mem[k] = int(v.split()[0])
    except Exception:
        pass
    respaldos = sorted((DOCS / "Respaldos").glob("*"), reverse=True)[:3] if (DOCS / "Respaldos").exists() else []
    return {
        "disco": f"{du.used/1e9:.1f} GB usados de {du.total/1e9:.1f} GB ({du.used*100//du.total}%)",
        "memoria": f"{(mem.get('MemTotal',0)-mem.get('MemAvailable',0))/1e6:.1f} GB de {mem.get('MemTotal',0)/1e6:.1f} GB" if mem else "?",
        "encendido": sh(["uptime", "-p"]),
        "red": sh(["nmcli", "-t", "-f", "STATE,CONNECTIVITY", "general"]),
        "impresoras": sh(["lpstat", "-p", "-d"]) or "sin impresoras configuradas",
        "trabajos_impresion": sh(["lpstat", "-o"]) or "ninguno",
        "ultimos_respaldos": [p.name for p in respaldos],
        "actualizaciones_pendientes": sh(["bash", "-c", "apt list --upgradable 2>/dev/null | tail -n +2 | wc -l"]),
    }


def t_imprimir(texto: str, impresora: str = "", copias: int = 1):
    cmd = ["lp", "-n", str(max(1, min(copias, 5)))]
    if impresora:
        cmd += ["-d", impresora]
    p = subprocess.run(cmd, input=texto, capture_output=True, text=True, timeout=20)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or "No se pudo imprimir")
    return p.stdout.strip() or "Enviado a imprimir"


def _seguro(nombre: str) -> str:
    return "".join(c for c in nombre if c.isalnum() or c in "-_ .")[:80].strip() or "reporte"


def t_guardar_reporte(nombre: str, contenido: str, formato: str = "md"):
    formato = formato if formato in ("md", "csv", "txt", "html") else "md"
    carpeta = DOCS / "Reportes"
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{dt.date.today().isoformat()} {_seguro(nombre)}.{formato}"
    ruta.write_text(contenido, encoding="utf-8")
    return {"guardado_en": str(ruta)}


def t_leer_archivo(ruta: str):
    p = Path(ruta).expanduser().resolve()
    home = Path.home().resolve()
    if home not in p.parents and p != home and not str(p).startswith("/media/"):
        raise RuntimeError("Solo puedo leer archivos dentro de tu carpeta personal o de un USB.")
    if not p.is_file():
        raise RuntimeError("El archivo no existe")
    suf = p.suffix.lower()
    if suf == ".pdf" and shutil.which("pdftotext"):
        txt = sh(["pdftotext", "-layout", str(p), "-"], timeout=30)
    elif suf in (".xlsx", ".xls", ".ods", ".docx", ".odt") and shutil.which("soffice"):
        tmp = Path("/tmp") / f"romanos-{secrets.token_hex(4)}"
        tmp.mkdir()
        fmt = "csv" if suf in (".xlsx", ".xls", ".ods") else "txt:Text"
        sh(["soffice", "--headless", "--convert-to", fmt, "--outdir", str(tmp), str(p)], timeout=60)
        out = next(tmp.glob("*"), None)
        txt = out.read_text(errors="replace") if out else "(no se pudo convertir)"
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        txt = p.read_text(errors="replace")
    return {"archivo": str(p), "contenido": txt[:60000], "recortado": len(txt) > 60000}


def t_abrir_modulo(modulo: str):
    subprocess.Popen(["roman-panel", "--abrir", modulo], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"Abriendo {modulo} en el Panel Román"


def t_respaldar_ahora():
    p = subprocess.run(["roman-respaldo"], capture_output=True, text=True, timeout=300)
    return (p.stdout + p.stderr).strip()[-2000:]


def _obj(props: dict, req: list[str] | None = None):
    return {"type": "object", "properties": props, "required": req or []}


S, I, B = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}
TOOLS = {
    "inventario_productos": (t_inventario_productos, "Busca productos del inventario (nombre, categoría, precio de compra, kg por caja).",
        _obj({"busqueda": S, "categoria": S, "solo_activos": B, "limite": I})),
    "inventario_registros": (t_inventario_registros, "Últimos conteos de inventario. tipo='semanal' (conteo de stock) o 'kg' (cierre mensual en kg). items = producto → cantidad.",
        _obj({"tipo": {"type": "string", "enum": ["semanal", "kg"]}, "cantidad": I})),
    "inventario_compras": (t_inventario_compras, "Líneas de mercadería ingresada desde facturas de proveedores en un rango de fechas (YYYY-MM-DD). Sirve para costos y compras por producto.",
        _obj({"desde": S, "hasta": S, "proveedor": S, "producto": S}, ["desde"])),
    "inventario_ajustes": (t_inventario_ajustes, "Parámetros del pedido sugerido (cobertura, stock de seguridad, semanas de historial, límites).", _obj({})),
    "facturas": (t_facturas, "Facturas del sistema de control por local. tipo: recibidas | emitidas | notas_credito. Filtros opcionales por estado (PENDIENTE/PAGADO), fechas de emisión, proveedor y local.",
        _obj({"tipo": {"type": "string", "enum": ["recibidas", "emitidas", "notas_credito"]}, "estado": S, "desde": S, "hasta": S, "proveedor": S, "local": S, "detalle": B})),
    "facturas_por_vencer": (t_facturas_por_vencer, "Facturas recibidas impagas: vencidas y las que vencen en los próximos N días.", _obj({"dias": I})),
    "personal": (t_personal, "Personal por local y, si se pide, remuneraciones. Información confidencial.", _obj({"local": S, "incluir_remuneraciones": B})),
    "recetas": (t_recetas, "Recetas de la rotisería con ingredientes y costos. Para escalar a otro peso de carne, calcula proporcionalmente.", _obj({"busqueda": S})),
    "estado_equipo": (t_estado_equipo, "Estado del computador: disco, memoria, red, impresoras, respaldos y actualizaciones.", _obj({})),
    "imprimir": (t_imprimir, "Imprime texto en la impresora (boleta interna, lista de pedido, etiqueta). Confirma con el usuario antes.",
        _obj({"texto": S, "impresora": S, "copias": I}, ["texto"])),
    "guardar_reporte": (t_guardar_reporte, "Guarda un reporte en ~/Documentos/Reportes (md, csv, txt o html).",
        _obj({"nombre": S, "contenido": S, "formato": S}, ["nombre", "contenido"])),
    "leer_archivo": (t_leer_archivo, "Lee un archivo del usuario (PDF de factura, planilla Excel/CSV, documento) para analizarlo.", _obj({"ruta": S}, ["ruta"])),
    "abrir_modulo": (t_abrir_modulo, "Abre un módulo en el Panel Román: inicio, pos, inventario, recetario, facturas, liquidacion, dj, djlocal, mp3.", _obj({"modulo": S}, ["modulo"])),
    "respaldar_ahora": (t_respaldar_ahora, "Descarga ahora un respaldo de todos los datos del negocio a ~/Documentos/Respaldos.", _obj({})),
}


def run_tool(name: str, args: dict) -> tuple[str, bool]:
    fn = TOOLS.get(name, (None,))[0]
    if not fn:
        return f"Herramienta desconocida: {name}", True
    try:
        res = fn(**(args or {}))
        txt = res if isinstance(res, str) else json.dumps(res, ensure_ascii=False, default=str)
        return txt[:80000], False
    except TypeError as e:
        return f"Parámetros inválidos: {e}", True
    except Exception as e:
        return str(e), True


# --------------------------------------------------------------------------
# Bucle del agente
# --------------------------------------------------------------------------
def chat(messages: list[dict], on_event=None) -> dict:
    key = api_key()
    if not key:
        return {"error": "Falta la clave de Claude. Abre roman-setup (Ajustes → Claude) y pégala."}
    cfg = config()
    tools = [{"name": n, "description": d, "input_schema": s} for n, (_, d, s) in TOOLS.items()]
    trace = []
    msgs = list(messages)
    for _ in range(MAX_TURNS):
        resp = http_json("POST", API_URL, {"x-api-key": key, "anthropic-version": "2023-06-01"}, {
            "model": cfg["modelo"], "max_tokens": 4096, "system": system_prompt(), "tools": tools, "messages": msgs,
        }, timeout=180)
        msgs.append({"role": "assistant", "content": resp["content"]})
        uses = [b for b in resp["content"] if b.get("type") == "tool_use"]
        if resp.get("stop_reason") != "tool_use" or not uses:
            text = "".join(b.get("text", "") for b in resp["content"] if b.get("type") == "text")
            return {"respuesta": text, "herramientas": trace, "messages": msgs}
        results = []
        for u in uses:
            if on_event:
                on_event(u["name"])
            out, err = run_tool(u["name"], u.get("input") or {})
            trace.append({"herramienta": u["name"], "entrada": u.get("input"), "error": err})
            results.append({"type": "tool_result", "tool_use_id": u["id"], "content": out, "is_error": err})
        msgs.append({"role": "user", "content": results})
    return {"respuesta": "Detuve la tarea: necesitó demasiados pasos. Intenta una pregunta más acotada.", "herramientas": trace, "messages": msgs}


def resumen_inicio() -> dict:
    """Datos para la pantalla de Inicio del panel (sin usar Claude)."""
    out = {"fecha": dt.date.today().isoformat()}
    for k, fn in (("vencimientos", lambda: t_facturas_por_vencer(7)), ("equipo", t_estado_equipo),
                  ("inventario", lambda: t_inventario_registros("semanal", 1))):
        try:
            out[k] = fn()
        except Exception as e:
            out[k] = {"error": str(e)}
    return out


# --------------------------------------------------------------------------
# Servidor HTTP local
# --------------------------------------------------------------------------
SESSION_TOKEN = secrets.token_urlsafe(24)


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "romanos-ai/1.0"

    def log_message(self, fmt, *a):
        sys.stderr.write("[romanos-ai] " + (fmt % a) + "\n")

    def _send(self, code: int, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else (json.dumps(body, ensure_ascii=False, default=str).encode() if not isinstance(body, str) else body.encode())
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)

    def _host_ok(self) -> bool:  # defensa contra DNS rebinding
        return self.headers.get("Host", "").split(":")[0] in ("127.0.0.1", "localhost")

    def _auth(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-Roman-Token", ""), SESSION_TOKEN)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n < 5_000_000 else {}

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "host"})
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/chat"):
            return self._send(200, (WEB / "chat.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/inicio":
            return self._send(200, (WEB / "inicio.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/ajustes":
            return self._send(200, (WEB / "ajustes.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/estilo.css":
            return self._send(200, (WEB / "estilo.css").read_bytes(), "text/css")
        if path == "/api/salud":
            return self._send(200, {"ok": True, "claude": bool(api_key())})
        if not self._auth():
            return self._send(401, {"error": "token"})
        if path == "/api/resumen":
            return self._send(200, resumen_inicio())
        if path == "/api/ajustes":
            c = config()
            cuentas = {k: {"usuario": v.get("usuario", ""), "tiene_clave": bool(v.get("clave"))} for k, v in c["cuentas"].items()}
            return self._send(200, {"modelo": c["modelo"], "tiene_api_key": bool(c.get("anthropic_api_key")),
                                    "cuentas": cuentas, "servicios": {k: v["nombre"] for k, v in servicios().items() if isinstance(v, dict)}})
        if path == "/api/modulos":
            return self._send(200, load_json(ETC / "modulos.json", {"modulos": []}))
        self._send(404, {"error": "no encontrado"})

    def do_POST(self):
        if not self._host_ok() or not self._auth():
            return self._send(401, {"error": "token"})
        path = urllib.parse.urlparse(self.path).path
        try:
            b = self._body()
            if path == "/api/chat":
                return self._send(200, chat(b.get("messages") or []))
            if path == "/api/ajustes":
                c = config()
                if b.get("anthropic_api_key"):
                    c["anthropic_api_key"] = b["anthropic_api_key"].strip()
                if b.get("modelo"):
                    c["modelo"] = b["modelo"].strip()
                for k, v in (b.get("cuentas") or {}).items():
                    cur = c["cuentas"].setdefault(k, {})
                    if v.get("usuario") is not None:
                        cur["usuario"] = v["usuario"].strip()
                    if v.get("clave"):
                        cur["clave"] = v["clave"]
                    Supa._tokens.pop(k, None)
                save_config(c)
                return self._send(200, {"ok": True})
            if path == "/api/probar":
                res = {}
                for k in servicios():
                    if k.startswith("_"):
                        continue
                    try:
                        Supa(k).token()
                        res[k] = "ok"
                    except Exception as e:
                        res[k] = str(e)
                return self._send(200, res)
            if path == "/api/herramienta":  # usado por scripts locales
                out, err = run_tool(b.get("nombre", ""), b.get("args") or {})
                return self._send(200, {"resultado": out, "error": err})
        except Exception as e:
            return self._send(500, {"error": str(e)})
        self._send(404, {"error": "no encontrado"})


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CFG_DIR, 0o700)
    TOKEN_FILE.write_text(SESSION_TOKEN)
    os.chmod(TOKEN_FILE, 0o600)
    srv = Server((HOST, PORT), Handler)
    print(f"romanos-ai escuchando en http://{HOST}:{PORT}", flush=True)
    try:
        srv.serve_forever()
    finally:
        TOKEN_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
