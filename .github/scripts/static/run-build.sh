#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu

if [ -f /etc/alpine-release ]; then
    apk add --no-cache build-base meson ninja pkgconf curl xz \
        xorgproto pixman-dev pixman-static libx11-dev libx11-static \
        libxcb-static libxau-dev libxdmcp-dev libxfont2-dev libxkbfile-dev \
        libxcvt-dev libpciaccess-dev libdrm-dev libbsd-dev libbsd-static \
        libmd-dev zlib-static freetype-static bzip2-static brotli-static \
        libpng-static expat-static xkbcomp xkeyboard-config xdpyinfo mesa-dev
else
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential meson ninja-build pkg-config curl xz-utils \
        xserver-xorg-dev libpixman-1-dev libxfont-dev libxkbfile-dev \
        libxcvt-dev libpciaccess-dev libdrm-dev libmd-dev libbsd-dev \
        xkb-data x11-xkb-utils x11-utils mesa-common-dev
fi

sh .github/scripts/static/build-deps.sh

meson setup _build-static --prefix=/usr \
    -Dstatic=true -Dxorg=true -Dxvfb=true -Dxfbdev=true -Dxfake=true \
    -Dxnest=false -Dglx=false -Dglamor=false -Dgbm=false \
    -Dudev=false -Dudev_kms=false -Dseatd_libseat=false \
    -Dsystemd_logind=false -Dsystemd_notify=false -Dxselinux=false \
    -Ddocs=false -Ddevel-docs=false
meson compile -C _build-static -j2
meson test -C _build-static --print-errorlogs 'static module loader' 'static DRI loader' unit

for server in hw/xfree86/Xorg hw/vfb/Xvfb hw/kdrive/fake/Xfake hw/kdrive/fbdev/Xfbdev; do
    binary="_build-static/$server"
    test -x "$binary"
    if readelf -l "$binary" | grep -q INTERP || readelf -d "$binary" | grep -q NEEDED; then
        echo "$binary has a dynamic runtime dependency" >&2
        exit 1
    fi
done

# Confirm that the static server accepts an actual X client connection.
_build-static/test/simple-xinit xdpyinfo -- \
    "$(pwd)/_build-static/hw/vfb/Xvfb" -screen scrn 1280x1024x24
