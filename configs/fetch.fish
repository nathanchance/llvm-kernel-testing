#!/usr/bin/env fish

set configs_folder (realpath (status dirname))

if test (count $argv) -gt 0
    set distros $argv
else
    set distros \
        alpine \
        archlinux \
        debian \
        fedora \
        opensuse
end

for distro in $distros
    set dest $configs_folder/$distro
    mkdir -p $dest

    switch $distro
        case alpine
            for arch in aarch64 armv7 riscv64 x86_64
                echo "Fetching $distro $arch configuration..."
                crl -o $dest/$arch.config https://git.alpinelinux.org/aports/plain/community/linux-edge/config-edge.$arch; or return
            end

        case archlinux
            for arch in armv7 aarch64 x86_64
                if test "$arch" = x86_64
                    set url https://github.com/archlinux/svntogit-packages/raw/packages/linux/trunk/config
                else
                    set url https://github.com/archlinuxarm/PKGBUILDs/raw/master/core/linux-$arch/config
                end
                echo "Fetching $distro $arch configuration..."
                crl -o $dest/$arch.config $url; or return
            end

        case debian
            set tmp_dir (mktemp -d -p $dest)

            for arch in amd64 arm64 armmp i386 powerpc64le s390x
                set package_version_signed 6.1.0-6
                set kernel_version_signed 6.1.15-1
                set package_version_unsigned $package_version_signed
                set kernel_version_unsigned $kernel_version_signed

                set deb_arch_config $arch
                set deb_arch_final $arch
                set work_dir $tmp_dir/$arch

                switch $arch
                    case amd64 arm64 i386
                        switch $arch
                            case i386
                                set deb_arch_config 686
                        end

                        set url_suffix linux-signed-$arch/linux-image-"$package_version_signed"-"$deb_arch_config"_"$kernel_version_signed"_"$deb_arch_final".deb

                    case armmp powerpc64le s390x
                        switch $arch
                            case armmp
                                set deb_arch_final armhf
                            case powerpc64le
                                set deb_arch_final ppc64el
                        end

                        set url_suffix linux/linux-image-"$package_version_unsigned"-"$deb_arch_config"_"$kernel_version_unsigned"_"$deb_arch_final".deb
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
                    rm -fr $tmp_dir
                    print_error "Issue processing Debian configuration for $arch!"
                    return 1
                end
            end
            rm -fr $tmp_dir

        case fedora
            for arch in aarch64 armv7hl ppc64le s390x x86_64
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
