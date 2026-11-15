#!/bin/sh
# SPDX-License-Identifier: MIT
# Build archives omitted by distribution development packages.
set -eu

deps_dir=$(mktemp -d "${TMPDIR:-/tmp}/xserver-static-deps.XXXXXX")
trap 'rm -rf "$deps_dir"' EXIT HUP INT TERM
cd "$deps_dir"
libdir=$(pkg-config --variable=libdir xau)

fetch_xorg()
{
    curl --fail --location --retry 3 \
        "https://www.x.org/releases/individual/$1/$2.tar.xz" -o "$2.tar.xz"
    tar -xf "$2.tar.xz"
}

build_autotools()
{
    fetch_xorg lib "$1"
    (
        cd "$1"
        ./configure --prefix=/usr --libdir="$libdir" --disable-shared --enable-static
        make -j2
        make install
    )
}

build_autotools libXau-1.0.12
build_autotools libfontenc-1.1.8
build_autotools libXfont2-2.0.7
build_autotools libxshmfence-1.3.3

fetch_xorg proto xorgproto-2024.1
meson setup proto-build xorgproto-2024.1 --prefix=/usr
meson install -C proto-build

fetch_xorg lib libpciaccess-0.18.1
meson setup pciaccess-build libpciaccess-0.18.1 \
    --prefix=/usr --libdir="$libdir" -Ddefault_library=static
meson install -C pciaccess-build

curl --fail --location --retry 3 \
    https://dri.freedesktop.org/libdrm/libdrm-2.4.124.tar.xz -o libdrm.tar.xz
tar -xf libdrm.tar.xz
meson setup drm-build libdrm-2.4.124 --prefix=/usr --libdir="$libdir" \
    -Ddefault_library=static -Dtests=false -Dintel=disabled \
    -Dradeon=disabled -Damdgpu=disabled -Dnouveau=disabled \
    -Dvmwgfx=disabled -Dfreedreno=disabled
meson install -C drm-build

fetch_xorg lib libxcvt-0.1.3
# libxcvt 0.1.3 hardcodes shared_library; let default_library select an archive.
sed -i 's/shared_library(/library(/' libxcvt-0.1.3/lib/meson.build
meson setup xcvt-build libxcvt-0.1.3 --prefix=/usr --libdir="$libdir" \
    -Ddefault_library=static
meson install -C xcvt-build
