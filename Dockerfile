# ExCoder: Python environment, Java 8 + Maven 3.8 (to build the subject
# projects) and llama.cpp (to serve the local models).
#
# Build with GPU support:
#   docker build --build-arg BASE_IMAGE=nvidia/cuda:12.4.0-devel-ubuntu22.04 --build-arg USE_CUDA=true -t excoder-cuda .
#   docker run --gpus all -it excoder-cuda /bin/bash
#
# Build CPU-only version:
#   docker build -t excoder .
#   docker run -it excoder /bin/bash

ARG BASE_IMAGE=ubuntu:22.04
FROM ${BASE_IMAGE}

ARG USE_CUDA=false
# Cap the llama.cpp build's parallelism on small machines: --build-arg BUILD_JOBS=4
ARG BUILD_JOBS=
ARG DEBIAN_FRONTEND=noninteractive

# Install essential build tools and dependencies
RUN rm /bin/sh && ln -s /bin/bash /bin/sh
RUN apt-get update && \
    apt-get install -y software-properties-common gnupg && \
    apt-get -qq -y install \
    apt-utils \
    curl \
    wget \
    unzip \
    zip \
    gcc \
    g++ \
    cmake \
    mono-mcs \
    sudo \
    less \
    git \
    build-essential \
    pkg-config \
    libicu-dev \
    libcurl4-openssl-dev \
    libgomp1

# Install Java 8 (Eclipse Temurin) and Maven 3.8 as root
RUN wget -qO - https://packages.adoptium.net/artifactory/api/gpg/key/public | gpg --dearmor > /etc/apt/trusted.gpg.d/adoptium.gpg && \
    echo "deb https://packages.adoptium.net/artifactory/deb $(. /etc/os-release && echo $VERSION_CODENAME) main" > /etc/apt/sources.list.d/adoptium.list && \
    apt-get update && \
    apt-get install -y temurin-8-jdk && \
    wget -qO /tmp/maven.tar.gz https://archive.apache.org/dist/maven/maven-3/3.8.3/binaries/apache-maven-3.8.3-bin.tar.gz && \
    tar -xzf /tmp/maven.tar.gz -C /opt && \
    ln -s /opt/apache-maven-3.8.3/bin/mvn /usr/local/bin/mvn && \
    rm /tmp/maven.tar.gz

# Build llama.cpp with optional CUDA support.  It goes under /opt rather than
# /root because the image runs as the unprivileged `etest` user, and /root is
# mode 700 -- llama-server would be unreachable from there.
WORKDIR /opt/llama.cpp
RUN git clone https://github.com/ggml-org/llama.cpp.git . && \
    if [ "$USE_CUDA" = "true" ]; then \
        cmake -B build \
            -DGGML_NATIVE=OFF \
            -DGGML_CUDA=ON \
            -DGGML_BACKEND_DL=ON \
            -DGGML_CPU_ALL_VARIANTS=ON \
            -DLLAMA_BUILD_TESTS=OFF \
            -DCMAKE_EXE_LINKER_FLAGS=-Wl,--allow-shlib-undefined .; \
    else \
        cmake -B build \
            -DGGML_NATIVE=OFF \
            -DLLAMA_BUILD_TESTS=OFF .; \
    fi && \
    cmake --build build --config Release -j"${BUILD_JOBS:-$(nproc)}" && \
    chmod -R a+rX /opt/llama.cpp

# Install Rust and Cargo (as root)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Add new user
RUN useradd -ms /bin/bash -c "Etest User" etest && \
    echo "etest:etest" | chpasswd && \
    adduser etest sudo

USER etest
WORKDIR /home/etest/

# Set environment variables
ENV HOME=/home/etest
ENV USER=etest
ENV PATH="$HOME/.local/bin:$HOME/.cargo/bin:${PATH}"

# Set up working environment.  gguf_models is pre-created so that the named
# volume docker-compose mounts there inherits etest's ownership.
RUN mkdir $HOME/excoder $HOME/gguf_models
ENV GGUF_DIR="$HOME/gguf_models"
COPY --chown=etest:etest ./pyproject.toml $HOME/excoder
COPY --chown=etest:etest ./uv.lock $HOME/excoder
COPY --chown=etest:etest ./.python-version $HOME/excoder

# Install the Python dependencies with uv.  Only the lockfile is copied in, so
# this is --no-install-project: ExCoder's own packages are not baked into the
# image, they come from the bind-mounted checkout via the PYTHONPATH that
# scripts/helper/env.sh exports.  (Without the flag, setuptools looks for the
# `python/` package directory and README.md, which are not in this layer.)
RUN cd $HOME/excoder && \
    curl -LsSf https://astral.sh/uv/install.sh | sh && \
    uv venv && \
    uv sync --no-install-project

# Activate the virtualenv through the environment rather than through .bashrc,
# so that `docker compose run excoder ./scripts/...` gets it too and not only an
# interactive shell.  scripts/helper/env.sh honours a VIRTUAL_ENV that is
# already set, so the repository's own .venv (if the host has one) is ignored.
ENV VIRTUAL_ENV="$HOME/excoder/.venv"
ENV PATH="$VIRTUAL_ENV/bin:${PATH}:/opt/llama.cpp/build/bin"

RUN echo 'export PATH="$HOME/.local/bin:$PATH"' >> $HOME/.bashrc

# The repository is bind-mounted here by docker-compose.
WORKDIR /workspace

ENTRYPOINT ["/bin/bash"]
