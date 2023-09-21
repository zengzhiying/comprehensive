#!/bin/bash
base_dir=$(cd "$(dirname "$0")"; pwd)
cd ${base_dir}

service_file=my-program.service
target_service=/usr/lib/systemd/system/$service_file

if [[ ! -f $service_file ]]; then
    echo "service 文件不存在!"
    exit
fi

is_exists=0

if [[ -f $target_service ]]; then
    read -r -p "文件: "$target_service" 已存在, 是否覆盖? [Y/n]" input
    case $input in
        [yY][eE][sS]|[yY])
        echo "执行覆盖."
        is_exists=1
        ;;
        [nN][oO]|[nN])
        echo "取消操作."
        exit
        ;;
        *)
        echo "Invalid input."
        exit
        ;;
    esac
fi

cp $service_file .$service_file

sed -i 's/{{ MY_PROGRAM_HOME }}/'${base_dir//\//\\\/}'/g' .$service_file
\mv .$service_file ${target_service}

if [[ $is_exists -eq 1 ]]; then
    systemctl daemon-reload
fi
