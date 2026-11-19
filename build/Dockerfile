# Construye la ISO de RomanOS desde Windows/macOS con Docker Desktop.
#
#   docker build -t romanos-builder -f build/Dockerfile .
#   docker run --rm --privileged -v "%cd%:/romanos" romanos-builder        (Windows CMD)
#   docker run --rm --privileged -v "${PWD}:/romanos" romanos-builder      (PowerShell / Linux)
#
# La ISO queda en ./out/
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      debootstrap squashfs-tools xorriso grub-pc-bin grub-efi-amd64-bin \
      grub-common mtools dosfstools ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /romanos
# WORK fuera del volumen montado: en Windows, NTFS no admite dispositivos/enlaces del chroot
ENV WORK=/tmp/romanos-work
CMD ["bash", "./build/build-iso.sh"]
