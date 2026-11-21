# syntax=docker/dockerfile:1

# Slim runtime image for the LeanCLR Linux release bundle.
#
# The bundle is produced by Dockerfile.builder (or downloaded from a GitHub
# Release) and extracted to ./bundle/leanclr before this image is built:
#
#   mkdir -p bundle
#   tar -xzf leanclr-linux-bundle-v4.7.2.tar.gz -C bundle
#   docker build -t godot-leanclr:v4.7.2 .
#   docker run --rm -v "$PWD":/src -v leanclr-cache:/cache godot-leanclr:v4.7.2

FROM ubuntu:24.04

ARG IMAGE_SOURCE=""
ARG GODOT_VERSION="4.7.2"

LABEL org.opencontainers.image.title="godot-leanclr" \
      org.opencontainers.image.description="Godot ${GODOT_VERSION} LeanCLR publication runtime" \
      org.opencontainers.image.source="${IMAGE_SOURCE}" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.base.name="ubuntu:24.04"

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    DOTNET_ROOT=/usr/lib/dotnet \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1 \
    NUGET_PACKAGES=/cache/nuget \
    HOME=/root \
    PATH=/opt/leanclr:/usr/lib/dotnet:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

RUN set -eux; \
 apt-get -o Acquire::ForceIPv4=true -o Acquire::Retries=5 \
  -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update; \
 apt-get -o Acquire::ForceIPv4=true -o Acquire::Retries=5 \
  -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 install -y --no-install-recommends \
  ca-certificates \
  dotnet-runtime-8.0 \
  dotnet-sdk-10.0 \
  dotnet-targeting-pack-8.0 \
  findutils \
  python-is-python3 \
  python3 \
  unzip \
  zip \
  libx11-6 \
  libxext6 \
  libxfixes3 \
  libxdamage1 \
  libxcomposite1 \
  libxrender1 \
  libxss1 \
  libxtst6 \
  libxcursor1 \
  libxinerama1 \
  libxi6 \
  libxkbcommon0 \
  libxkbcommon-x11-0 \
  libxrandr2 \
  libgl1 \
  libegl1 \
  libgbm1 \
  libglu1-mesa \
  libwayland-egl1 \
  libasound2t64 \
  libpulse0 \
  libudev1 \
  libwayland-client0 \
  libwayland-cursor0 \
  libfontconfig1 \
  libdbus-1-3 \
  libspeechd2; \
 rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb; \
 dotnet --info >/dev/null

RUN mkdir -p /cache/nuget /src

COPY bundle/leanclr /opt/leanclr

RUN set -eux; \
 bash -n /opt/leanclr/publish; \
 test -x /opt/leanclr/publish; \
 test -f /opt/leanclr/templates/linux/linux_release.x86_64; \
 test -n "$(find /opt/leanclr/exporter -maxdepth 1 -type f -name '*leanclr_m0*' -print -quit)"; \
 test -f /opt/leanclr/managed/GodotSharp.dll; \
 test -f /opt/leanclr/managed/analyzers/Godot.SourceGenerators.dll; \
 test -f /opt/leanclr/managed/ManagedInfo.dll; \
 test -f /opt/leanclr/managed/Bootstrap.cs; \
 test -f /opt/leanclr/bcl/win-x64/System.Private.CoreLib.dll; \
 /opt/leanclr/publish --ready

WORKDIR /src

ENTRYPOINT ["/opt/leanclr/publish"]
