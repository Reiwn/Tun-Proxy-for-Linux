# Tun-Proxy-for-Linux

Installation
sudo install -m 755 netns.py /usr/local/bin/scripts/
sudo install -m 644 netns.service /usr/local/lib/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now netns.service
