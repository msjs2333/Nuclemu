# Linux amd64 离线包

本包面向 Debian 12（glibc 2.36）及兼容的 x86_64 桌面系统。携带 Python、Tk、SQLite、内置课程及浏览器资源，不需要安装 Python、Node 或联网下载 Python 包。运行工作台仍需已有可用的浏览器。图形环境须提供 X11（Wayland 会话可用 XWayland）、字体及系统库；本包不携带 glibc。

系统依赖：`libc6 >= 2.36`、`libx11-6`、`libxext6`、`libxft2`、`libxrender1`、`libfontconfig1`、`libfreetype6`、`libexpat1`、`zlib1g`。建议已有 `xdg-utils` 和中文字体。课机断网安装前应由管理员准备这些系统组件；`.deb` 的依赖声明会检查必需库。

## 安装与使用

```sh
sudo dpkg -i nuclemu_0.0.1-1_amd64.deb
nuclemu list
nuclemu serve --no-gui
```

应用菜单中的 **Nuclemu** 或终端的 `nuclemu-desktop` 打开桌面启动器。桌面菜单入口不创建终端。`nuclemu serve --gui` 使用相同的设置与实例归属；`serve --no-gui` 在终端打印实际地址，不需要显示设备，不读取桌面设置，也不自动打开浏览器。Ctrl+C 停止终端服务，不代为保存实验。

偏好保存在当前用户的 `~/.nuclemu/launcher.json`。升级使用 `sudo dpkg -i 新包.deb`，卸载使用 `sudo dpkg -r nuclemu`。卸载只移除程序，不修改用户偏好和自行另存的 `.nuclemu` 文件。卸载前关闭本包启动器及前台服务。

便携包无需 root：解压整个 `tar.gz` 到用户可写目录，在其中运行 `./nuclemu-desktop` 或 `./nuclemu serve --no-gui`。保留 `_internal` 与两个入口同级。移动目录后从新路径运行即可；同一用户的桌面偏好与实例仍共享。

## 构建与隔离验收

在仓库根目录构建专用 Debian 12 镜像并冻结应用。仓库已含生产前端；前端变更后须先重建资源。

```sh
docker build --target builder -t nuclemu-linux-builder -f packaging/linux/Dockerfile packaging/linux
docker run --rm -v "$PWD:/src" -e NUCLEMU_SOURCE_SHA="$(git rev-parse HEAD)" nuclemu-linux-builder python packaging/linux/build.py
```

产物位于 `dist/release/`，每个文件附 SHA256。`BUILD-INFO.json` 记录源码、版本和运行时基线。`--revision 0` 可制作较早候选供隔离升级验收，正式默认候选为 `0.0.1-1`。构建过程需下载工具与系统包；完成后的目标机运行不联网。实际验收范围见随本次交付的记录，尚未实测的平台不列为已支持。
