#!/usr/bin/env bash
# =============================================================================
#  RomanOS · constructor de ISO
#  Base: Ubuntu 24.04 LTS (noble) · Escritorio propio sobre XFCE · Claude nativo
#
#  Uso (en Ubuntu 24.04, o dentro del contenedor Docker de build/Dockerfile):
#     sudo ./build/build-iso.sh            # ISO completa
#     sudo ./build/build-iso.sh --clean    # borra la carpeta de trabajo antes
#
#  Resultado:  out/RomanOS-<version>-amd64.iso  (arranca en BIOS y UEFI,
#              modo "probar" + instalador Calamares)
# =============================================================================
set -euo pipefail

VERSION="1.0"
CODENAME="parrilla"
UBUNTU_SUITE="noble"
ARCH="amd64"
MIRROR="${MIRROR:-http://archive.ubuntu.com/ubuntu}"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${WORK:-$ROOT_DIR/work}"
CHROOT="$WORK/chroot"
IMAGE="$WORK/image"
OUT="${OUT:-$ROOT_DIR/out}"
ISO="$OUT/RomanOS-${VERSION}-${ARCH}.iso"

log() { printf '\n\033[1;31m[RomanOS]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Ejecuta con sudo."
for b in debootstrap mksquashfs xorriso grub-mkstandalone mformat; do
  command -v "$b" >/dev/null || die "Falta '$b'. Instala: sudo apt install debootstrap squashfs-tools xorriso grub-pc-bin grub-efi-amd64-bin mtools dosfstools"
done

if [[ "${1:-}" == "--clean" ]]; then
  log "Limpiando $WORK"
  umount -lf "$CHROOT"/{dev/pts,dev,proc,sys,run} 2>/dev/null || true
  rm -rf "$WORK"
fi
mkdir -p "$CHROOT" "$IMAGE"/{casper,boot/grub,EFI/BOOT,isolinux} "$OUT"

# ---------------------------------------------------------------------------
# 1. Sistema base
# ---------------------------------------------------------------------------
if [[ ! -x "$CHROOT/bin/bash" ]]; then
  log "1/7 debootstrap $UBUNTU_SUITE ($ARCH)"
  debootstrap --arch="$ARCH" --variant=minbase "$UBUNTU_SUITE" "$CHROOT" "$MIRROR"
fi

mount_chroot() {
  for d in dev dev/pts proc sys run; do
    mountpoint -q "$CHROOT/$d" || mount --bind "/$d" "$CHROOT/$d"
  done
}
umount_chroot() {
  for d in run sys proc dev/pts dev; do umount -lf "$CHROOT/$d" 2>/dev/null || true; done
}
trap umount_chroot EXIT
mount_chroot

cat > "$CHROOT/etc/apt/sources.list" <<EOF
deb $MIRROR $UBUNTU_SUITE main restricted universe multiverse
deb $MIRROR $UBUNTU_SUITE-updates main restricted universe multiverse
deb $MIRROR $UBUNTU_SUITE-security main restricted universe multiverse
EOF
cp /etc/resolv.conf "$CHROOT/etc/resolv.conf"

# ---------------------------------------------------------------------------
# 2. Paquetes (lista en build/packages.list)
# ---------------------------------------------------------------------------
log "2/7 Instalando paquetes"
cp "$ROOT_DIR/build/packages.list" "$CHROOT/tmp/packages.list"
chroot "$CHROOT" /bin/bash -euo pipefail <<'EOS'
export DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
echo "RomanOS" > /etc/hostname
apt-get update
apt-get install -y --no-install-recommends systemd-sysv dbus locales tzdata
# Sin snaps: Firefox/Chromium no se usan; el Panel trae su propio motor WebKit.
cat > /etc/apt/preferences.d/no-snap <<P
Package: snapd
Pin: release a=*
Pin-Priority: -10
P
PKGS=$(grep -vE '^\s*(#|$)' /tmp/packages.list | tr '\n' ' ')
if ! apt-get install -y --no-install-recommends $PKGS; then
  echo ">> Instalación en bloque falló; instalando uno a uno para aislar paquetes faltantes"
  for p in $PKGS; do apt-get install -y --no-install-recommends "$p" || echo "!! omitido: $p" >> /tmp/omitidos.txt; done
  [ -f /tmp/omitidos.txt ] && cat /tmp/omitidos.txt
fi
locale-gen es_CL.UTF-8 en_US.UTF-8
update-locale LANG=es_CL.UTF-8 LANGUAGE=es_CL:es
ln -sf /usr/share/zoneinfo/America/Santiago /etc/localtime
echo "America/Santiago" > /etc/timezone
EOS

# ---------------------------------------------------------------------------
# 3. Capa RomanOS (overlay) + personalización
# ---------------------------------------------------------------------------
log "3/7 Copiando capa RomanOS"
cp -a "$ROOT_DIR/overlay/." "$CHROOT/"
cp "$ROOT_DIR/build/customize.sh" "$CHROOT/tmp/customize.sh"
chroot "$CHROOT" /bin/bash /tmp/customize.sh "$VERSION" "$CODENAME"

# ---------------------------------------------------------------------------
# 4. Limpieza
# ---------------------------------------------------------------------------
log "Verificando la imagen"
chroot "$CHROOT" dpkg -s casper user-setup lightdm xfce4 calamares network-manager systemd-resolved >/dev/null || die "Faltan paquetes esenciales"
chroot "$CHROOT" test -e /etc/systemd/system/multi-user.target.wants/romanos-live-autologin.service || die "No quedó activo el inicio automático de la sesión en vivo"
chroot "$CHROOT" test -x /usr/lib/romanos/live-autologin.sh || die "Falta live-autologin.sh"
chroot "$CHROOT" test -e /etc/systemd/user/default.target.wants/romanos-ai.service || die "No quedó activo el servicio romanos-ai"
ls "$CHROOT"/boot/vmlinuz-* >/dev/null || die "No hay kernel en /boot"
echo "OK: paquetes esenciales, servicios y kernel presentes"

log "4/7 Limpiando chroot"
chroot "$CHROOT" /bin/bash -c 'apt-get clean; rm -rf /tmp/* /var/lib/apt/lists/* /var/log/*.log; truncate -s0 /etc/machine-id'
rm -f "$CHROOT/etc/resolv.conf"
ln -sf ../run/systemd/resolve/stub-resolv.conf "$CHROOT/etc/resolv.conf"
umount_chroot

# ---------------------------------------------------------------------------
# 5. Kernel + squashfs
# ---------------------------------------------------------------------------
log "5/7 Generando filesystem.squashfs (tarda varios minutos)"
cp "$CHROOT"/boot/vmlinuz-*  "$IMAGE/casper/vmlinuz"
cp "$CHROOT"/boot/initrd.img-* "$IMAGE/casper/initrd"
rm -f "$IMAGE/casper/filesystem.squashfs"
mksquashfs "$CHROOT" "$IMAGE/casper/filesystem.squashfs" -comp zstd -Xcompression-level 15 -noappend
du -sx --block-size=1 "$CHROOT" | cut -f1 > "$IMAGE/casper/filesystem.size"
chroot "$CHROOT" dpkg-query -W --showformat='${Package} ${Version}\n' > "$IMAGE/casper/filesystem.manifest" 2>/dev/null || true

mkdir -p "$IMAGE/.disk"
echo "RomanOS $VERSION \"$CODENAME\" - Release $ARCH ($(date +%Y%m%d))" > "$IMAGE/.disk/info"
touch "$IMAGE/ubuntu"   # marcador que usa grub para encontrar el medio

# ---------------------------------------------------------------------------
# 6. GRUB (BIOS + UEFI)
# ---------------------------------------------------------------------------
log "6/7 Configurando arranque"
cat > "$IMAGE/boot/grub/grub.cfg" <<'EOF'
search --set=root --file /ubuntu
insmod all_video
set default="0"
set timeout=5
set color_normal=white/black
set color_highlight=black/light-red

menuentry "Probar RomanOS (sin instalar)" {
  linux /casper/vmlinuz boot=casper quiet splash locale=es_CL.UTF-8 keyboard-configuration/layoutcode=latam ---
  initrd /casper/initrd
}
menuentry "Instalar RomanOS" {
  linux /casper/vmlinuz boot=casper quiet splash locale=es_CL.UTF-8 keyboard-configuration/layoutcode=latam romanos-instalar ---
  initrd /casper/initrd
}
menuentry "RomanOS - modo seguro (gráficos básicos)" {
  linux /casper/vmlinuz boot=casper nomodeset locale=es_CL.UTF-8 ---
  initrd /casper/initrd
}
EOF

grub-mkstandalone --format=x86_64-efi --output="$IMAGE/EFI/BOOT/BOOTx64.EFI" \
  --locales="" --fonts="" "boot/grub/grub.cfg=$IMAGE/boot/grub/grub.cfg"
( cd "$IMAGE/EFI/BOOT" && rm -f efiboot.img && dd if=/dev/zero of=efiboot.img bs=1M count=10 status=none \
  && mkfs.vfat efiboot.img >/dev/null && mmd -i efiboot.img efi efi/boot \
  && mcopy -i efiboot.img ./BOOTx64.EFI ::efi/boot/ )

grub-mkstandalone --format=i386-pc --output="$WORK/core.img" \
  --install-modules="linux16 linux normal iso9660 biosdisk memdisk search tar ls" \
  --modules="linux16 linux normal iso9660 biosdisk search" --locales="" --fonts="" \
  "boot/grub/grub.cfg=$IMAGE/boot/grub/grub.cfg"
cat /usr/lib/grub/i386-pc/cdboot.img "$WORK/core.img" > "$IMAGE/isolinux/bios.img"

( cd "$IMAGE" && find . -type f -print0 | xargs -0 md5sum | grep -v -e 'md5sum.txt' -e 'bios.img' -e 'efiboot.img' > md5sum.txt )

# ---------------------------------------------------------------------------
# 7. ISO híbrida
# ---------------------------------------------------------------------------
log "7/7 Escribiendo $ISO"
xorriso -as mkisofs -iso-level 3 -full-iso9660-filenames \
  -volid "ROMANOS_${VERSION//./_}" \
  -eltorito-boot isolinux/bios.img -no-emul-boot -boot-load-size 4 -boot-info-table --eltorito-catalog boot/grub/boot.cat \
  --grub2-boot-info --grub2-mbr /usr/lib/grub/i386-pc/boot_hybrid.img \
  -eltorito-alt-boot -e EFI/BOOT/efiboot.img -no-emul-boot -append_partition 2 0xef "$IMAGE/EFI/BOOT/efiboot.img" \
  -output "$ISO" -graft-points "$IMAGE" /boot/grub/bios.img="$IMAGE/isolinux/bios.img" /EFI/efiboot.img="$IMAGE/EFI/BOOT/efiboot.img"

sha256sum "$ISO" > "$ISO.sha256"
log "Listo: $ISO ($(du -h "$ISO" | cut -f1))"
log "Graba en USB con balenaEtcher / Rufus (modo DD) o pruébala en VirtualBox."
