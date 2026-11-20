#!/bin/sh
# Solo en la sesión en vivo (USB): asegura el usuario de prueba y entra directo sin contraseña.
U="$(. /etc/casper.conf 2>/dev/null; echo "${USERNAME:-roman}")"
[ -n "$U" ] || U=roman
if ! id "$U" >/dev/null 2>&1; then
  useradd -m -s /bin/bash -c "Román (sesión en vivo)" "$U"
fi
for g in sudo adm cdrom audio video plugdev netdev lpadmin caja autologin nopasswdlogin; do
  getent group "$g" >/dev/null || groupadd "$g"
  usermod -aG "$g" "$U" 2>/dev/null || true
done
passwd -d "$U" >/dev/null 2>&1 || true
echo "$U ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/90-romanos-live
chmod 440 /etc/sudoers.d/90-romanos-live
mkdir -p /etc/lightdm/lightdm.conf.d
cat > /etc/lightdm/lightdm.conf.d/90-romanos-live.conf <<EOF
[Seat:*]
autologin-user=$U
autologin-user-timeout=0
autologin-session=xfce
EOF
