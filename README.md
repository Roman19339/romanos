# RomanOS 1.1 "parrilla"

Sistema operativo para la **Rotisería & Carnicería Román**, construido sobre la base
de Ubuntu 24.04 LTS, con escritorio, identidad, instalador y herramientas propias, y
**Claude integrado en el sistema**.

```
┌───────────────────────── Panel Román ─────────────────────────┐
│ 🔥 Román      │                                    │ ✦ Claude  │
│ 🏠 Inicio      │   App elegida (sesión siempre      │ "¿Qué     │
│ 🥩 Caja (POS)  │   iniciada, imprime directo)       │ facturas  │
│ 📦 Inventario  │                                    │ vencen…?" │
│ 🍗 Recetario   │   Inicio = resumen del día:        │           │
│ 🧾 Facturas    │   facturas por pagar, stock en     │ [⏰ 🧾]   │
│ 💵 Liquidación │   cero, estado del equipo          │ Respuesta │
│ 🎧 Música      │                                    │ con datos │
└───────────────┴────────────────────────────────────┴───────────┘
```

## Qué lo hace distinto de Ubuntu

| | Ubuntu | RomanOS |
|---|---|---|
| Escritorio | GNOME | XFCE liviano con capa propia: dock inferior, tema brasa/carbón, Panel Román como pantalla principal |
| Identidad | Ubuntu | `os-release`, inicio de sesión, arranque, instalador y fondos RomanOS |
| Snaps | Sí | No (bloqueados) — más rápido en equipos de caja modestos |
| Idioma / zona | Inglés / UTC | Español de Chile, `America/Santiago`, teclado latinoamericano |
| Instalador | Subiquity | Calamares con marca RomanOS, crea usuarios en el grupo `caja` |
| Negocio | — | Tus apps integradas, impresoras térmicas ESC/POS listas, respaldo diario 23:30 |
| Navegador | Firefox (snap) | **Brave** con **Brave Search** como buscador predeterminado |
| IA | — | **Claude nativo** (ver abajo) |

## Claude integrado

| Dónde | Cómo |
|---|---|
| **Barra lateral del Panel** | Siempre visible; `Ctrl+Espacio` la muestra/oculta |
| **Atajo global** | `Super+Espacio` desde cualquier ventana |
| **Terminal** | `roman "¿cuánto compramos de pollo este mes?"` o `roman` para conversar; también acepta tuberías: `cat pedido.txt \| roman "ordénalo por proveedor"` |
| **Archivos** | Clic derecho → *Preguntar a Claude* (lee PDFs de facturas, Excel, documentos) |
| **Claude Code** | `Super+T` o Panel → *Terminal Claude*: el agente oficial de Anthropic, abierto en `~/Negocio` con el contexto del negocio y las herramientas de RomanOS conectadas por MCP, más el MCP de Supabase para administrar tus bases |
| **Inicio** | La pantalla de inicio pregunta directo a Claude |

Detrás está **`romanos-ai`**, un servicio del sistema (solo escucha en `127.0.0.1`,
con token por sesión) que le da a Claude estas herramientas:

| Herramienta | Fuente |
|---|---|
| `inventario_productos`, `inventario_registros`, `inventario_compras`, `inventario_ajustes` | Supabase **Inventario-Calama** |
| `facturas`, `facturas_por_vencer`, `personal` | Supabase **Control de Facturas** (recib, emit, nc, pers, remu) |
| `recetas` | Supabase **Recetario-Román** (sesión por RPC) |
| `estado_equipo`, `imprimir`, `guardar_reporte`, `leer_archivo`, `abrir_modulo`, `respaldar_ahora` | El propio computador |

Claude entra a cada app **con tu mismo usuario**, así que respeta las reglas de
acceso (RLS) que ya tienen tus bases. Las herramientas de negocio solo leen; las únicas
acciones son imprimir, guardar reportes en `~/Documentos/Reportes` y respaldar.

## Tus proyectos integrados

| Módulo | Origen |
|---|---|
| Caja (POS) | Artefacto *POS Carnicería · Rotisería · Minimarket* |
| Inventario | `inventario-calama.netlify.app` + Supabase Inventario-Calama |
| Recetario | `recetario-roman.netlify.app` + Supabase Recetario-Román |
| Facturas | `facturas-roman.netlify.app` + Supabase de facturas |
| Liquidación | Artefacto *Liquidación Roti Calama* |
| Música local / DJ Local | Artefactos *DJ Auto · Mezcla y anuncios* y *DJ Local* |
| Convertir MP3 | Artefacto *Convertidor a MP3* |

La lista está en `/etc/romanos/modulos.json`: agregar una app es agregar una línea.
Los módulos marcados con ↗ (artefactos de claude.ai) se abren en una ventana de Brave,
porque claude.ai no funciona en el motor WebKit del Panel (`"motor": "brave"`). Piden
iniciar sesión en Claude la primera vez y Brave recuerda la sesión.

---

## 1. Construir la ISO

### Opción A — en la nube con GitHub (no instalas nada) ⭐
1. Crea una cuenta gratis en <https://github.com> y luego **New repository** → nombre `romanos`,
   visibilidad **Public** (los repositorios privados gratis solo guardan 500 MB y la ISO pesa ~2,5 GB;
   el kit no contiene contraseñas: las claves de Supabase incluidas son las públicas).
2. En el repositorio: **Add file → Upload files** → arrastra el **contenido** de la carpeta `romanos`
   (README.md, build, overlay) → **Commit changes**.
3. **Add file → Create new file** → nombre: `.github/workflows/construir-iso.yml` →
   pega el contenido de `build/construir-iso.yml` → **Commit changes**.
   (Este paso es necesario porque la subida por navegador omite carpetas que empiezan con punto.)
4. Pestaña **Actions** → *Construir ISO RomanOS* → **Run workflow**. Tarda 30–50 minutos.
5. Al terminar (✓ verde), abre la ejecución y descarga **RomanOS-ISO** al final de la página
   (es un .zip con la ISO adentro). Queda disponible 7 días.

### Opción B — en Ubuntu 24.04 (PC con Ubuntu, live USB o WSL2)
```bash
sudo apt install debootstrap squashfs-tools xorriso grub-pc-bin grub-efi-amd64-bin mtools dosfstools
sudo ./build/build-iso.sh
```

### Opción C — Docker Desktop
```powershell
docker build -t romanos-builder -f build/Dockerfile .
docker run --rm --privileged -v "${PWD}:/romanos" romanos-builder
```

Resultado: `RomanOS-1.1-amd64.iso` (+ `.sha256`). Si algún paquete no existe en
los repositorios, el script lo informa como “omitido” y continúa.

## 2. Probar

En VirtualBox (ya lo tienes instalado): nueva VM *Linux / Ubuntu 64-bit*, 4 GB RAM,
30 GB disco, **habilitar EFI** opcional, montar la ISO → *Probar RomanOS*.

## 3. Instalar en el computador del local

Graba la ISO en un USB con **balenaEtcher** o **Rufus (modo DD)** → arranca desde
el USB → *Instalar RomanOS*. El instalador borra o comparte el disco según elijas.

## 4. Primer inicio

Se abre **Ajustes de Claude**:
1. **Clave de API de Anthropic** — créala en <https://console.anthropic.com> (se paga por uso;
   es distinta de la suscripción de claude.ai). Modelo recomendado: *Claude Sonnet 5.5*.
2. **Cuentas** — el correo y clave con que entras a Inventario y Facturas, y tu usuario del Recetario.
3. *Probar conexiones* → los tres deben decir **conectado**.

Claude Code (`Super+T`) también puede usar tu plan Pro/Max con `/login`, sin clave de API.

## 5. Impresora térmica y cajón

Conecta la impresora USB y agrégala en *Configuración → Impresoras* (CUPS). Los
usuarios del grupo `caja` tienen acceso directo a impresoras ESC/POS por USB. El POS
imprime con el diálogo normal; Claude puede imprimir listas y pedidos con `imprimir`.

## Personalizar

| Quiero… | Edito |
|---|---|
| Cambiar lo que Claude sabe del negocio | `/etc/romanos/contexto.md` (todos) o `~/.config/romanos/negocio.md` (solo mi usuario) |
| Agregar/quitar apps del Panel | `/etc/romanos/modulos.json` |
| Cambiar el modelo de Claude | Ajustes de Claude |
| Agregar paquetes a la ISO | `build/packages.list` |
| Cambiar fondo / logo | `overlay/usr/share/romanos/branding/` |

## Estructura

```
build/
  build-iso.sh        debootstrap → chroot → squashfs → ISO híbrida BIOS+UEFI
  customize.sh        identidad, escritorio, servicios, Claude Code (dentro del chroot)
  packages.list       paquetes del sistema
  construir-iso.yml   para construir en la nube con GitHub Actions
  Dockerfile          para construir con Docker
overlay/              se copia tal cual sobre el sistema
  etc/romanos/        servicios.json · modulos.json · contexto.md
  etc/calamares/      instalador con marca RomanOS
  usr/lib/romanos/ai/ romanos-ai (server.py), MCP (mcp_romanos.py), interfaz web
  usr/lib/romanos/panel/panel.py   Panel Román (GTK3 + WebKit)
  usr/bin/            roman · roman-panel · roman-setup · roman-respaldo · roman-claude-*
  usr/share/romanos/  marca, configuración XFCE, espacio ~/Negocio para Claude Code
```

## Comandos útiles

```bash
systemctl --user status romanos-ai       # estado del servicio de Claude
journalctl --user -u romanos-ai -f       # registro en vivo
roman-respaldo                           # respaldo manual
roman-panel --caja                       # POS en pantalla completa (Ctrl+Alt+C)
```
