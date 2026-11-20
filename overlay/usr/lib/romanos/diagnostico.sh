#!/bin/sh
# Prueba automática de arranque (solo con el parámetro de kernel 'romanos-diag').
# Espera a que el escritorio abra y escribe el resultado en la consola serie.
sleep 150
{
echo "=====ROMANOS-DIAG-INICIO====="
echo "--- usuarios"; getent passwd | awk -F: '$3>=999 && $3<65000{print $1, $3, $6}'
echo "--- sesiones"; loginctl list-sessions --no-pager 2>&1
echo "--- procesos gráficos"; ps -eo user,pid,comm | grep -E 'Xorg|lightdm|xfce4-session|xfwm4|xfce4-panel|xfdesktop|panel.py|server.py' | grep -v grep
echo "--- lightdm.log"; tail -n 40 /var/log/lightdm/lightdm.log 2>&1
echo "--- seat0-greeter"; tail -n 15 /var/log/lightdm/seat0-greeter.log 2>&1
for h in /home/*; do echo "--- $h/.xsession-errors"; tail -n 60 "$h/.xsession-errors" 2>&1; done
echo "--- conf lightdm"; cat /etc/lightdm/lightdm.conf.d/*.conf 2>&1
echo "--- servicios fallidos"; systemctl --failed --no-pager 2>&1
echo "--- live-autologin"; journalctl -b -u romanos-live-autologin --no-pager 2>&1 | tail -n 15
echo "--- red"; nmcli -t dev 2>&1; ls -l /etc/resolv.conf; cat /etc/resolv.conf 2>&1 | grep -v '^#'
echo "--- navegador"; brave-browser --version 2>&1 | head -1; ls -l /etc/alternatives/x-www-browser; xdg-mime query default x-scheme-handler/https 2>&1
echo "--- DNS claude.ai"; getent hosts claude.ai 2>&1 || echo "SIN DNS"
if ps -eo comm | grep -q '^xfce4-session$'; then echo "RESULTADO: ESCRITORIO_OK"; else echo "RESULTADO: ESCRITORIO_FALLA"; fi
if getent hosts claude.ai >/dev/null 2>&1; then echo "RESULTADO: RED_OK"; else echo "RESULTADO: RED_FALLA"; fi
echo "=====ROMANOS-DIAG-FIN====="
} > /dev/ttyS0 2>&1
sleep 2
systemctl poweroff
