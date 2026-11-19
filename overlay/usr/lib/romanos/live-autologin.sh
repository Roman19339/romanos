#!/bin/sh
# Solo en la sesión en vivo: entra directo con el usuario de prueba, sin contraseña.
U="$(. /etc/casper.conf 2>/dev/null; echo "${USERNAME:-roman}")"
id "$U" >/dev/null 2>&1 || U="$(getent passwd 999 | cut -d: -f1)"
[ -n "$U" ] || exit 0
groupadd -f autologin
groupadd -f nopasswdlogin
usermod -aG autologin,nopasswdlogin,caja "$U" 2>/dev/null || true
passwd -d "$U" >/dev/null 2>&1 || true
mkdir -p /etc/lightdm/lightdm.conf.d
cat > /etc/lightdm/lightdm.conf.d/90-romanos-live.conf <<EOF
[Seat:*]
autologin-user=$U
autologin-user-timeout=0
autologin-session=xfce
EOF
