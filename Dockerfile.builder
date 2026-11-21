# syntax=docker/dockerfile:1

# LeanCLR Godot Linux publication image.
#
# The image contains the official Godot .NET editor (project import and C#
# glue), the private headless exporter, the LeanCLR Linux release template and
# the generic publication GodotSharp/calli assets. A mounted Godot project is
# exported against the baked LeanCLR template.
#
#   docker build -t godot-leanclr:v4.7.2-linux .
#   docker run --rm -v "$PWD":/src -v leanclr-cache:/cache godot-leanclr:v4.7.2-linux
#   docker run --rm godot-leanclr:v4.7.2-linux --ready

FROM ubuntu:24.04 AS toolchain

ARG GODOT_VERSION="4.7.2"

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    DOTNET_ROOT=/usr/lib/dotnet \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1 \
    NUGET_PACKAGES=/cache/nuget \
    HOME=/root \
    GODOT_VERSION=${GODOT_VERSION} \
    EMSDK=/opt/emsdk \
    PATH=/opt/emsdk:/opt/emsdk/upstream/emscripten:/opt/leanclr:/usr/lib/dotnet:/opt/godot:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# A single failed index download makes apt exit 100, so retry the whole
# update+install pair instead of failing the layer on the first attempt.
RUN set -eux; \
 apt_install() { \
  apt-get -o Acquire::ForceIPv4=true -o Acquire::Retries=5 \
   -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 "$@"; \
 }; \
 attempt=0; \
 while :; do \
  attempt=$((attempt + 1)); \
  if apt_install update && apt_install install -y --no-install-recommends \
   build-essential \
   bzip2 \
   ca-certificates \
   cmake \
   curl \
   dotnet-runtime-8.0 \
   dotnet-sdk-10.0 \
   dotnet-targeting-pack-8.0 \
   file \
   git \
   ninja-build \
   pkg-config \
   python-is-python3 \
   python3 \
   python3-pip \
   unzip \
   xz-utils \
   zip \
   libx11-dev \
   libxcursor-dev \
   libxinerama-dev \
   libxi-dev \
   libxkbcommon-dev \
   libxkbcommon-x11-0 \
   libxrandr-dev \
   libgl1-mesa-dev \
   libglu1-mesa-dev \
   libasound2-dev \
   libpulse-dev \
   libudev-dev \
   libwayland-dev \
   wayland-protocols \
   libfontconfig1-dev \
   libdbus-1-dev \
   libspeechd-dev; then \
   break; \
  fi; \
  if [ "$attempt" -ge 5 ]; then \
   echo "apt failed after $attempt attempts"; \
   exit 1; \
  fi; \
  echo "apt attempt $attempt failed, retrying in $((attempt * 5))s"; \
  sleep $((attempt * 5)); \
 done; \
 rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb; \
 dotnet --info >/dev/null

RUN set -eux; \
 python3 -m pip install --no-cache-dir --break-system-packages \
  --disable-pip-version-check --retries 5 --timeout 60 'scons==4.8.1'; \
 scons --version >/dev/null

# The publication BCL is pinned to 10.0.8. The win-x64 runtime pack matches
# dependencies.json corelib.native_sha256 and is the portable 64-bit BCL used
# by the LeanCLR Linux template.
RUN set -eux; \
 mkdir -p /opt/dotnet/packs/win-x64; \
 curl -4 -fsSL --retry 10 --retry-all-errors --retry-delay 2 --connect-timeout 20 \
  -o /tmp/win-x64.nupkg \
  https://api.nuget.org/v3-flatcontainer/microsoft.netcore.app.runtime.win-x64/10.0.8/microsoft.netcore.app.runtime.win-x64.10.0.8.nupkg; \
 unzip -q /tmp/win-x64.nupkg -d /opt/dotnet/packs/win-x64; \
 rm /tmp/win-x64.nupkg; \
 test -f /opt/dotnet/packs/win-x64/runtimes/win-x64/lib/net10.0/System.Private.CoreLib.dll

# The Web publication BCL is the 32-bit managed runtime pack.
RUN set -eux; \
 mkdir -p /opt/dotnet/packs/win-x86; \
 curl -4 -fsSL --retry 10 --retry-all-errors --retry-delay 2 --connect-timeout 20 \
  -o /tmp/win-x86.nupkg \
  https://api.nuget.org/v3-flatcontainer/microsoft.netcore.app.runtime.win-x86/10.0.8/microsoft.netcore.app.runtime.win-x86.10.0.8.nupkg; \
 unzip -q /tmp/win-x86.nupkg -d /opt/dotnet/packs/win-x86; \
 rm /tmp/win-x86.nupkg; \
 test -f /opt/dotnet/packs/win-x86/runtimes/win-x86/lib/net10.0/System.Private.CoreLib.dll

# Emscripten 4.0.20 for the Web export template.
RUN set -eux; \
 curl -4 -fsSL --retry 10 --retry-all-errors --retry-delay 2 --connect-timeout 20 \
  -o /tmp/emsdk.tar.gz \
  https://codeload.github.com/emscripten-core/emsdk/tar.gz/e4fe26ef59168ff44f4c23c466e497bf60b3411e; \
 mkdir -p /opt/emsdk; \
 tar -xzf /tmp/emsdk.tar.gz -C /opt/emsdk --strip-components=1; \
 rm /tmp/emsdk.tar.gz; \
 /opt/emsdk/emsdk install releases-c387d7a7e9537d0041d2c3ae71b7538cc978104e-64bit; \
 /opt/emsdk/emsdk activate releases-c387d7a7e9537d0041d2c3ae71b7538cc978104e-64bit

# The official .NET editor is used headless to import projects and generate C#
# glue. It is never the shipped runtime.
RUN set -eux; \
 curl -4 -fsSL --retry 10 --retry-all-errors --retry-delay 2 --connect-timeout 20 \
  -o /tmp/godot.zip \
  https://github.com/godotengine/godot-builds/releases/download/${GODOT_VERSION}-stable/Godot_v${GODOT_VERSION}-stable_mono_linux_x86_64.zip; \
 mkdir -p /tmp/godot /opt/godot; \
 unzip -q /tmp/godot.zip -d /tmp/godot; \
 editor="$(find /tmp/godot -type f -name 'Godot_v*-stable_mono_linux.x86_64' -print -quit)"; \
 test -n "$editor"; \
 mv "$(dirname "$editor")"/* /opt/godot/; \
 chmod +x "/opt/godot/Godot_v${GODOT_VERSION}-stable_mono_linux.x86_64"; \
 ln -s "/opt/godot/Godot_v${GODOT_VERSION}-stable_mono_linux.x86_64" /usr/local/bin/godot; \
 rm -rf /tmp/godot /tmp/godot.zip

RUN mkdir -p /cache/nuget /src

# ---------------------------------------------------------------------------
# LeanCLR Linux export assets
# ---------------------------------------------------------------------------
FROM toolchain AS leanclr-linux

# Keep the generic project-package assets out of this stage: changes to
# publish/ or managed/m1/Bootstrap.cs only need the final small layer.
COPY dependencies.json /build/repo/dependencies.json
COPY extern/leanclr /build/repo/extern/leanclr
COPY godot_patches /build/repo/godot_patches
COPY tools /build/repo/tools

# Expensive, project-independent work: Godot source, private exporter, generic
# publication GodotSharp/calli and the backend patch.
RUN python3 /build/repo/tools/build_linux_image.py --step prepare

COPY native /build/repo/native

# LeanCLR native runtime, Linux template and artifact assembly.
RUN python3 /build/repo/tools/build_linux_image.py --step web --out /opt/leanclr

# ---------------------------------------------------------------------------
# Final image
# ---------------------------------------------------------------------------
FROM toolchain AS final

ARG IMAGE_SOURCE=""
ARG GODOT_VERSION="4.7.2"

LABEL org.opencontainers.image.title="godot-leanclr" \
      org.opencontainers.image.description="Godot ${GODOT_VERSION} LeanCLR Linux publication image" \
      org.opencontainers.image.source="${IMAGE_SOURCE}" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.base.name="ubuntu:24.04"

COPY --from=leanclr-linux /opt/leanclr /opt/leanclr
COPY --chmod=755 publish /opt/leanclr/publish
COPY tools /opt/leanclr/tools
COPY dependencies.json /opt/leanclr/dependencies.json
COPY managed/m1/Bootstrap.cs /opt/leanclr/managed/Bootstrap.cs

RUN set -eux; \
 bash -n /opt/leanclr/publish; \
 test -f /opt/leanclr/templates/web/web_nothreads_release.zip; \
 test -n "$(find /opt/leanclr/exporter -maxdepth 1 -type f -name '*leanclr_m0*' -print -quit)"; \
 test -f /opt/leanclr/managed/GodotSharp.dll; \
 test -f /opt/leanclr/managed/analyzers/Godot.SourceGenerators.dll; \
 test -f /opt/leanclr/managed/ManagedInfo.dll; \
 test -f /opt/dotnet/packs/win-x86/runtimes/win-x86/lib/net10.0/System.Private.CoreLib.dll; \
 /opt/leanclr/publish --ready

WORKDIR /src

ENTRYPOINT ["/opt/leanclr/publish"]

# Export the prebuilt Linux assets for GitHub Release packaging.
FROM scratch AS bundle
COPY --from=leanclr-linux /opt/leanclr /leanclr
