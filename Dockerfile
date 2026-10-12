# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Pawel Mikolajczuk
# Toolchain for the SD stage images (Debian bookworm, arm-linux-gnueabi-gcc 12.2).
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc-arm-linux-gnueabi binutils-arm-linux-gnueabi \
    bison flex libssl-dev libgnutls28-dev python3 python3-dev python3-setuptools \
    python3-pyelftools swig device-tree-compiler bc ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /work
