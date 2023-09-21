# Systemd service 的标准用法示例



## 1.程序目录和 service 设置

将 service 文件、安装脚本 `install-service.sh` 放到和发布的程序同一级目录下，假设程序命令为 my-program，前台启动命令假设如下：

```shell
./my-program --conf ./config.yaml
```

我们当前的服务名为：`my-program.service`，需要根据实际的名称修改。

然后编辑 service 文件，重点修改下面几个位置：

```service
[Unit]
Description=my-program
# ...

[Service]
# ...
Type=simple
ExecStart={{ MY_PROGRAM_HOME }}/my-program --conf {{ MY_PROGRAM_HOME }}/config.yaml
# ...

```

首先是 `Description` 根据实际的修改即可。然后如果程序是前台运行，则保持 `Type=simple` 不变，如果程序是以守护进程方式后台运行的话，那么可以修改 `Type=forking` 这样即可正常追踪程序的状态。最后就是 `ExecStart` 指定程序的启动命令，一定要使用绝对路径启动，在这里使用变量 {{ MY_PROGRAM_HOME }} 替代当前的目录，这个变量保持不变即可，只替换具体的可执行文件和配置文件的相对路径即可。最后修改完成后保存。

## 2.服务安装脚本修改

我们只需要修改 `install-service.sh` 中的 `service_file` 变量的值即可：

```shell
service_file=my-program.service
```

需要和我们的服务文件保持一致。



## 3.安装服务

为安装脚本添加可执行权限：

```shell
chmod 755 install-service.sh
```

安装服务：

```shell
./install-service.sh
```

脚本可以执行多次，会提示是否覆盖原有的，当我们的服务文件修改后或者是程序目录变化后都可以重新执行覆盖之前的服务。

安装无误即可尝试启动服务：

```shell
systemctl start my-program.service
# 查看服务状态
systemctl status my-program.service
```

设置开机自动启动：

```shell
systemctl enable my-program.service
```

