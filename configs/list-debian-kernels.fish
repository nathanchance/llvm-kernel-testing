#!/usr/bin/env fish

crl http://ftp.us.debian.org/debian/pool/main/l/linux/ | string match -r 'linux-image-6\.[a-z0-9_\-.~+]+\.deb' | sort | uniq | bat
