FROM debian:bookworm-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 libpython3.11 python3-venv python3-tk binutils dpkg-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/freezer && /opt/freezer/bin/pip install \
    PyInstaller==6.20.0 pyinstaller-hooks-contrib==2026.10
ENV PATH="/opt/freezer/bin:${PATH}"
WORKDIR /src

FROM debian:bookworm-slim AS acceptance
RUN apt-get update && apt-get install -y --no-install-recommends \
    libc6 libx11-6 libxext6 libxft2 libxrender1 libfontconfig1 libfreetype6 \
    libexpat1 zlib1g xdg-utils fonts-noto-cjk xvfb xauth openbox xdotool \
    scrot libgtk-3-bin firefox-esr python3 ca-certificates dbus-x11 dbus-daemon \
    desktop-file-utils procps \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 student
WORKDIR /tmp
