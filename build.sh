#!/usr/bin/env bash

# Atualiza os pacotes do sistema
apt-get update

# Instala o FFmpeg
apt-get install -y ffmpeg

# Instala as dependências do Python
pip install -r requirements.txt
