#!/usr/bin/env fish

set configs_folder (realpath (status dirname))

set distros \
    alpine \
    archlinux \
    fedora \
    opensuse

if test (count $argv) -gt 0
    # allow opting out of downloading Debian configurations with '-debian' as the only argument
    if not contains -- -debian $argv
        set distros $argv
    end
else
    set -a distros debian
end

for distro in $distros
    set dest $configs_folder/$distro
    mkdir -p $dest

    switch $distro
        case alpine
            for arch in aarch64 armv7 loongarch64 ppc64le riscv64 s390x x86 x86_64
                echo "Fetching $distro $arch configuration..."
                crl -o $dest/$arch.config https://github.com/alpinelinux/aports/raw/refs/heads/master/community/linux-stable/stable.$arch.config; or return
            end

            if test (string match -r '^CONFIG_CRYPTO_CRC32C=' <$dest/ppc64le.config | count) -gt 1
                python3 -c "from pathlib import Path

cfg_txt = (cfg := Path('$dest/ppc64le.config')).read_text(encoding='utf-8')
(cfg_parts := cfg_txt.split('CONFIG_CRYPTO_CRC32C=y\n')).insert(1, 'CONFIG_CRYPTO_CRC32C=y\n')
cfg.write_text(''.join(cfg_parts), encoding='utf-8')"
            else
                print_warning "alpine ppc64le CONFIG_CRYPTO_CRC32C workaround can be removed"
            end

        case archlinux
            for arch in armv7 aarch64 x86_64
                if test "$arch" = x86_64
                    set url https://gitlab.archlinux.org/archlinux/packaging/packages/linux/-/raw/main/config
                else
                    set url https://github.com/archlinuxarm/PKGBUILDs/raw/master/core/linux-$arch/config
                end
                echo "Fetching $distro $arch configuration..."
                crl -o $dest/$arch.config $url; or return
            end

        case debian
            set tmp_dir (mktemp -d -p $dest)
            set deb_arches \
                amd64 \
                arm64 \
                armmp \
                powerpc64le \
                riscv64 \
                s390x

            for arch in $deb_arches
                set package_version_signed 6.17.5
                if string match -qr -- -rc $package_version_signed; or test "$package_version_signed" = 6.17.5
                    set kernel_version_signed (string replace - '~' $package_version_signed)-1~exp1
                else
                    set kernel_version_signed $package_version_signed-1
                    set package_version_signed $package_version_signed+deb14
                end
                set package_version_unsigned $package_version_signed
                set kernel_version_unsigned $kernel_version_signed

                set deb_arch_config $arch
                set deb_arch_final $arch
                set work_dir $tmp_dir/$arch

                switch $arch
                    case amd64 arm64
                        set url_suffix linux-signed-$arch/linux-image-"$package_version_signed"-"$deb_arch_config"_"$kernel_version_signed"_"$deb_arch_final".deb

                    case armmp i386 powerpc64le riscv64 s390x
                        switch $arch
                            case armmp
                                set deb_arch_final armhf
                            case i386
                                set deb_arch_config 686
                            case powerpc64le
                                set deb_arch_final ppc64el
                        end

                        set url_suffix linux/linux-image-"$package_version_unsigned"-"$deb_arch_config"_"$kernel_version_unsigned"_"$deb_arch_final".deb

                    case '*'
                        __print_error "Unhandled architecture: $arch"
                        return 1
                end

                set -l deb $work_dir/(basename $url_suffix)
                begin
                    echo "Fetching $distro $arch configuration..."
                    and mkdir $work_dir
                    and crl -o $deb http://ftp.us.debian.org/debian/pool/main/l/$url_suffix
                    and ar x --output $work_dir $deb
                    and tar -C $work_dir -xJf $work_dir/data.tar.xz
                    and cp -v $work_dir/boot/config-*-$deb_arch_config $dest/$arch.config
                end
                or begin
                    __print_error "Issue processing Debian configuration for $arch!"
                end
            end
            rm -fr $tmp_dir

        case fedora
            for arch in aarch64 ppc64le riscv64 s390x x86_64
                echo "Fetching $distro $arch configuration..."
                crl -o $dest/$arch.config https://src.fedoraproject.org/rpms/kernel/raw/rawhide/f/kernel-$arch-fedora.config; or return
            end

        case opensuse
            for arch in arm64 armv7hl i386 ppc64le riscv64 s390x x86_64
                echo "Fetching $distro $arch configuration..."
                crl -o $dest/$arch.config https://github.com/openSUSE/kernel-source/raw/master/config/$arch/default; or return
            end
    end
end
