#!/bin/bash

#
# This script installs the prerequisites for the project
#

# Update package lists
sudo apt update && sudo apt upgrade -y

# install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
# install just
sudo apt install just -y
# install bun
curl -fsSL https://bun.com/install | bash

#
# Optional
#
# install tmux
sudo apt install tmux -y
# install opencode
curl -fsSL https://opencode.ai/install | bash
# install claude
curl -fsSL https://claude.ai/install.sh | bash


#
# Docker
#

# Add Docker's official GPG key:
sudo apt install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
# Install Docker Engine, CLI, and Containerd
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin -y