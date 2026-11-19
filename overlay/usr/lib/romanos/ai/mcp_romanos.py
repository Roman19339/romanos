#!/usr/bin/env python3
"""
Servidor MCP (stdio) de RomanOS.

Expone a Claude Code las mismas herramientas de negocio y del equipo que usa
el asistente del Panel (inventario, facturas, recetas, impresión, respaldos…).
Se registra automáticamente en ~/Negocio/.mcp.json.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402

PROTO = "2025-06-18"


def send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(msg):
    mid, method = msg.get("id"), msg.get("method")
    if method == "initialize":
        return {"protocolVersion": msg.get("params", {}).get("protocolVersion", PROTO),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "romanos", "version": "1.0"},
                "instructions": (server.ETC / "contexto.md").read_text(encoding="utf-8") if (server.ETC / "contexto.md").exists() else ""}
    if method == "tools/list":
        return {"tools": [{"name": n, "description": d, "inputSchema": s} for n, (_, d, s) in server.TOOLS.items()]}
    if method == "tools/call":
        p = msg.get("params", {})
        out, err = server.run_tool(p.get("name", ""), p.get("arguments") or {})
        return {"content": [{"type": "text", "text": out}], "isError": err}
    if method == "ping":
        return {}
    if mid is not None:
        raise LookupError(method)
    return None


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" not in msg:          # notificación (p. ej. notifications/initialized)
            continue
        try:
            send({"jsonrpc": "2.0", "id": msg["id"], "result": handle(msg)})
        except LookupError as e:
            send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": f"Método no soportado: {e}"}})
        except Exception as e:
            send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": str(e)}})


if __name__ == "__main__":
    main()
