#!/usr/bin/env bash
# Se ejecuta DENTRO del chroot. Convierte el Ubuntu base en RomanOS.
set -euo pipefail
VERSION="$1"; CODENAME="$2"
export DEBIAN_FRONTEND=noninteractive

echo ">> Identidad del sistema"
rm -f /etc/os-release
cat > /usr/lib/os-release <<EOF
PRETTY_NAME="RomanOS $VERSION ($CODENAME)"
NAME="RomanOS"
VERSION_ID="$VERSION"
VERSION="$VERSION ($CODENAME)"
VERSION_CODENAME=noble
ID=romanos
ID_LIKE="ubuntu debian"
HOME_URL="https://rotiseria-roman.local"
SUPPORT_URL="https://rotiseria-roman.local/soporte"
UBUNTU_CODENAME=noble
LOGO=romanos
EOF
ln -sf ../usr/lib/os-release /etc/os-release
cat > /etc/lsb-release <<EOF
DISTRIB_ID=RomanOS
DISTRIB_RELEASE=$VERSION
DISTRIB_CODENAME=$CODENAME
DISTRIB_DESCRIPTION="RomanOS $VERSION"
EOF
echo "RomanOS $VERSION · Rotisería & Carnicería Román \n \l" > /etc/issue
echo "RomanOS $VERSION" > /etc/issue.net
rm -f /etc/update-motd.d/10-help-text /etc/update-motd.d/50-motd-news 2>/dev/null || true
cat > /etc/update-motd.d/05-romanos <<'EOF'
#!/bin/sh
echo ""
echo "  RomanOS · administración de Rotisería & Carnicería Román"
echo "  Escribe  'roman \"tu pregunta\"'  para consultar a Claude desde la terminal."
echo ""
EOF
chmod +x /etc/update-motd.d/05-romanos

echo ">> Sesión en vivo"
cat > /etc/casper.conf <<'EOF'
export USERNAME="roman"
export USERFULLNAME="Román (sesión en vivo)"
export HOST="romanos"
export BUILD_SYSTEM="Ubuntu"
export FLAVOUR="RomanOS"
EOF

echo ">> Pantalla de inicio de sesión"
mkdir -p /etc/lightdm/lightdm.conf.d
cat > /etc/lightdm/lightdm.conf.d/50-romanos.conf <<'EOF'
[Seat:*]
greeter-session=lightdm-gtk-greeter
user-session=xfce
greeter-hide-users=false
EOF
cat > /etc/lightdm/lightdm-gtk-greeter.conf <<'EOF'
[greeter]
background=/usr/share/romanos/branding/wallpaper.png
theme-name=Arc-Dark
icon-theme-name=Papirus-Dark
font-name=Inter 11
default-user-image=/usr/share/romanos/branding/logo.svg
indicators=~host;~spacer;~clock;~spacer;~session;~a11y;~power
clock-format=%A %d de %B · %H:%M
position=50%,center 55%,center
EOF

echo ">> Escritorio por defecto (XFCE con capa RomanOS)"
mkdir -p /etc/xdg/xfce4/xfconf/xfce-perchannel-xml /etc/xdg/xfce4/panel
cp /usr/share/romanos/xfce/xsettings.xml /usr/share/romanos/xfce/xfwm4.xml /etc/xdg/xfce4/xfconf/xfce-perchannel-xml/
cp /usr/share/romanos/xfce/panel-default.xml /etc/xdg/xfce4/panel/default.xml

echo ">> Menú contextual de Archivos (Preguntar a Claude)"
mkdir -p /etc/skel/.config/Thunar
cp /usr/share/romanos/thunar-uca.xml /etc/skel/.config/Thunar/uca.xml

echo ">> Plymouth"
if [ -d /usr/share/plymouth/themes/spinner ]; then
  cp /usr/share/romanos/branding/logo.png /usr/share/plymouth/themes/spinner/watermark.png 2>/dev/null || true
  update-alternatives --set default.plymouth /usr/share/plymouth/themes/spinner/spinner.plymouth 2>/dev/null || true
fi

echo ">> Claude Code (agente de terminal oficial de Anthropic)"
npm install -g @anthropic-ai/claude-code || echo "!! No se pudo instalar Claude Code ahora; 'roman-setup' lo reintenta en el primer inicio."

echo ">> Permisos y servicios"
chmod 755 /usr/bin/roman /usr/bin/roman-panel /usr/bin/roman-setup /usr/bin/roman-respaldo /usr/bin/roman-claude-archivo /usr/bin/roman-claude-terminal /usr/bin/romanos-primer-inicio
chmod 755 /usr/lib/romanos/ai/server.py /usr/lib/romanos/ai/mcp_romanos.py /usr/lib/romanos/panel/panel.py
systemctl --global enable romanos-ai.service 2>/dev/null || \
  { mkdir -p /etc/systemd/user/default.target.wants && ln -sf /usr/lib/systemd/user/romanos-ai.service /etc/systemd/user/default.target.wants/romanos-ai.service; }
systemctl --global enable romanos-respaldo.timer 2>/dev/null || \
  { mkdir -p /etc/systemd/user/timers.target.wants && ln -sf /usr/lib/systemd/user/romanos-respaldo.timer /etc/systemd/user/timers.target.wants/romanos-respaldo.timer; }
systemctl enable cups NetworkManager lightdm 2>/dev/null || true
chmod 755 /usr/lib/romanos/live-autologin.sh /usr/lib/romanos/diagnostico.sh
systemctl enable romanos-diag.service 2>/dev/null || ln -sf /usr/lib/systemd/system/romanos-diag.service /etc/systemd/system/multi-user.target.wants/romanos-diag.service
systemctl enable romanos-live-autologin.service 2>/dev/null || ln -sf /usr/lib/systemd/system/romanos-live-autologin.service /etc/systemd/system/multi-user.target.wants/romanos-live-autologin.service
# Cajeros: grupo con acceso a impresoras térmicas USB y cajón
groupadd -f caja
cat > /etc/udev/rules.d/60-romanos-impresoras.rules <<'EOF'
# Impresoras térmicas ESC/POS (Epson, Xprinter, genéricas) accesibles para el grupo 'caja'
SUBSYSTEM=="usb", ATTR{bInterfaceClass}=="07", MODE="0664", GROUP="caja"
SUBSYSTEM=="usb", ATTRS{idVendor}=="04b8", MODE="0664", GROUP="caja"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0416", MODE="0664", GROUP="caja"
SUBSYSTEM=="usb", ATTRS{idVendor}=="1fc9", MODE="0664", GROUP="caja"
EOF
sed -i 's/^#\?EXTRA_GROUPS=.*/EXTRA_GROUPS="caja lpadmin audio video plugdev netdev"/; s/^#\?ADD_EXTRA_GROUPS=.*/ADD_EXTRA_GROUPS=1/' /etc/adduser.conf

echo ">> Red: NetworkManager administra cable, wifi y móvil"
mkdir -p /etc/NetworkManager/conf.d /etc/netplan
# Ubuntu deja las conexiones por cable sin administrar si no hay netplan; esto las activa
touch /etc/NetworkManager/conf.d/10-globally-managed-devices.conf
cat > /etc/NetworkManager/conf.d/20-romanos.conf <<'EOF'
[main]
dns=systemd-resolved

[ifupdown]
managed=true
EOF
cat > /etc/netplan/01-network-manager-all.yaml <<'EOF'
network:
  version: 2
  renderer: NetworkManager
EOF
chmod 600 /etc/netplan/01-network-manager-all.yaml
systemctl enable systemd-resolved NetworkManager 2>/dev/null || true

echo ">> Actualizaciones de seguridad automáticas"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

echo ">> Instalador en la sesión en vivo"
cp /usr/share/applications/romanos-instalar.desktop /etc/skel/Escritorio/ 2>/dev/null || {
  mkdir -p /etc/skel/Escritorio && cp /usr/share/applications/romanos-instalar.desktop /etc/skel/Escritorio/; }
chmod +x /etc/skel/Escritorio/romanos-instalar.desktop
# Tras instalar, Calamares quita el acceso directo (ver modules/shellprocess.conf)

update-desktop-database /usr/share/applications 2>/dev/null || true
gtk-update-icon-cache -f /usr/share/icons/hicolor 2>/dev/null || true
echo ">> RomanOS personalizado."
