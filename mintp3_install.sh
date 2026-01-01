#!/bin/bash

# MintP3 Installation Script
# This script sets up the environment for the Raspberry Pi based digital audio player.

set -e

echo "--- Starting MintP3 Installation ---"

# 1. Update system and install native dependencies
echo "Updating system and installing system dependencies..."
sudo apt-get update
sudo apt-get install -y \
	vlc \
	libvlc-dev \
	python3-pip \
	python3-vlc \
	python3-pil \
	python3-evdev \
	python3-psutil \
	i2c-tools \
	python3-dev \
	libfreetype6-dev \
	libjpeg-dev \
	libopenjp2-7-dev \
	libtiff5-dev \
	network-manager \
	bluetooth \
	bluez \
	bluez-tools

# 2. Create directory structure
echo "Creating project directory structure..."
mkdir -p assets
mkdir -p music
mkdir -p templates

# 3. Install Python libraries
echo "Installing required Python packages..."
# Using --break-system-packages if on newer Debian/PiOS, or standard pip
PIP_CMD="pip3 install --upgrade"
if python3 -m pip --version | grep -q "externally-managed"; then
	PIP_CMD="pip3 install --upgrade --break-system-packages"
fi

$PIP_CMD \
	luma.lcd \
	mutagen \
	flask \
	evdev \
	psutil

# 4. Set up GPIO and SPI permissions
echo "Configuring hardware interfaces..."
sudo usermod -a -G gpio,spi,i2c,audio,input $USER

# 5. Create default config file if it doesn't exist
if [ ! -f assets/config.json ]; then
	echo "Creating default configuration..."
	cat <<EOF > assets/config.json
{
	"wifi_ssid": "MintP3-Recovery",
	"wifi_pass": "recovery123",
	"music_dir": "music/"
}
EOF
fi

echo "--- Installation Complete ---"
echo "Please reboot your Pi to apply group permission changes."
echo "Usage: python3 main.py"