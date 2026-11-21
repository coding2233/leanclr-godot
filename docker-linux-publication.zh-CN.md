# Linux 镜像多平台打包方案

> 当前实现范围已调整为 Linux 专用自包含镜像 `godot-leanclr:v4.7.2-linux`：镜像内预编译 LeanCLR Linux 导出模板和私有导出器，挂载项目后直接导出 Linux 包。Windows、WebGL、Android 仍按本文后续阶段拆分镜像实现。

日期：2026-11-19。项目：[focus-creative-games/leanclr-godot](https://github.com/focus-creative-games/leanclr-godot)。

现有仓库只作为版本和能力的参考。打包宿主机是一张 Linux 镜像；Linux 版本一次构建产出 LeanCLR Linux 发布包。Windows、WebGL 和 Android 按平台拆分成独立镜像，避免单镜像过大。

## 结论

基础镜像是 `ubuntu:24.04`，工具链在构建镜像时装好。Godot 源码、编译缓存和发布结果放在挂载卷上，不写进镜像层。

四个目标共用同一次托管编译、同一份 Godot 源码，以及同一套 LeanCLR 后端，差别只在工具链和 CoreLib 的指针宽度。

| 目标 | 容器内的编译方式 | 默认产物 |
| --- | --- | --- |
| Linux x64 | 发行版 GCC，官方 `platform=linuxbsd target=template_release` | 可执行文件和 PCK |
| Windows x64 | 发行版 `mingw-w64`，`x86_64-w64-mingw32-gcc`，POSIX 线程模型 | `exe` 和 PCK |
| WebGL | Emscripten 4.0.20，Godot `platform=web`，`arch=wasm32` | 可部署的 Web 导出目录 |
| Android | NDK r29 的 Linux 包，默认 ABI `arm64-v8a` | APK |

四个目标顺序执行；它们会改同一棵 Godot 源码树，并行 SCons 会互相踩目录。

```text
源码与场景
    │
    ├─ dotnet 编译发布用托管程序集（一次）
    ├─ 静态链入 LeanCLR 的发布后端（四个模板共用）
    │
    ├─ Linux：GCC + SCons platform=linuxbsd template_release → 导出
    ├─ Windows：MinGW-w64 + SCons platform=windows → 导出 exe
    ├─ WebGL：emcmake + Ninja → wasm32 模板 → 导出
    └─ Android：NDK toolchain + Ninja → arm64 模板 → 打 APK
```

## 后端替换

发布模板仍走 Godot `modules/mono` 的 `CSharpScript` 路径，玩家进程里的运行时换成 LeanCLR。官方 .NET 只留在 `/opt/godot` 的 headless 编辑器里，用来生成胶水和调用导出。导出器本身不加载 LeanCLR。

模板不是编辑器构建时，编译定义 `LEANCLR_GODOT`。`GDMono::initialize` 调用 `leanclr_godot::initialize()`，失败即停止启动。LeanCLR 和 calli 桥以静态库链进模板。

玩家进程的启动检查拒绝 CoreCLR、hostfxr 和 Mono 运行时库。编辑器里的 Play 和 C# 断点仍使用官方 .NET，不在这张镜像里。

## 从参考仓库留下的版本

| 组件 | 版本 |
| --- | --- |
| Godot 源码 | 4.7.2，`ed1daf0bf001b61586d9930840f2f1394092c079` |
| LeanCLR | `coreclr-minimal`，`7d98994f7954ed637d7a47e9c851170239643353` |
| .NET | SDK 10；托管 BCL 固定 10.0.8，不跟 SDK 自带的更新补丁走 |
| Windows 交叉编译 | Ubuntu 包 `mingw-w64`，编译器 `x86_64-w64-mingw32-gcc`，线程模型 posix |
| Emscripten | 4.0.20 |
| Android | NDK `29.0.14206865`，编译平台 `android-36`，build-tools `36.1.0`，最低 API 24 |
| SCons | 4.8.1 |
| Python | 3.12 |
| JDK | 17 |

10.0.8 的程序集按目标下载 NuGet 运行时包，放到 `/opt/dotnet/packs/`。Linux、Windows 和 Android 的 64 位目标使用 `win-x64` 运行时包中的托管 BCL；WebGL 是 wasm32，使用 `win-x86` 托管包。镜像实现时用 SHA-256 钉住实际选中的包。

## 镜像里有什么

镜像只放工具和预编译的通用产物，不放项目构建结果。

- 构建工具：`build-essential`、GCC、clang、lld、cmake、ninja、git、pkg-config、Python 3.12、SCons 4.8.1、`mingw-w64`
- Linux 模板依赖：官方 Ubuntu 列表中的 X11、Xcursor、Xinerama、Xi、XRandR、Mesa、GLU、ALSA、PulseAudio、udev、Wayland 开发包
- .NET SDK 10、.NET Runtime 8（官方 Godot 编辑器的 GodotTools 使用 net8.0）、以及 10.0.8 运行时包
- OpenJDK 17
- Emscripten 4.0.20，激活后 `emcc` 和 `emcmake` 在默认 `PATH` 中
- Android cmdline-tools、platform-tools、`platforms;android-36`、`build-tools;36.1.0`、`ndk;29.0.14206865`
- 官方 Godot 4.7.2 Linux x64 .NET 编辑器，解压到 `/opt/godot`，只用它的 headless 模式生成胶水和调用导出器
- 私有 headless 导出器、LeanCLR Linux 模板、通用 GodotSharp/calli 资产

Android 包使用 Google 的 Linux 归档，通过 `sdkmanager` 安装。镜像构建时接受许可证；运行容器时不再依赖宿主机上的 Android SDK。

Godot 的私有导出策略仍然需要：官方导出器不会接受 LeanCLR 载荷。实现时把参考仓库 `godot_patches/m0` 里的策略补丁接到 Linux 导出器上，并在 Linux 上从源码编出一个 headless 导出器。

```dockerfile
# syntax=docker/dockerfile:1

FROM ubuntu:24.04 AS toolchain

# 安装 clang、cmake、ninja、Python 3.12、SCons 4.8.1、.NET SDK 10、
# .NET Runtime 8、OpenJDK 17、mingw-w64，以及 X11/Wayland/ALSA 开发包。

# 把 x86_64-w64-mingw32-gcc 和 g++ 切到 posix 变体。
# 安装并激活 Emscripten 4.0.20 到 /opt/emsdk。
# 用 sdkmanager 安装 Android 平台 36、build-tools 36.1.0、NDK 29.0.14206865。
# 把官方 Linux .NET 编辑器解压到 /opt/godot。
# 把 10.0.8 的 linux-x64、win-x64、win-x86 运行时包放到 /opt/dotnet/packs。

FROM toolchain AS leanclr-linux
# 下载/校验 Godot 和 LeanCLR，应用 m0/m1 补丁，构建导出器和 Linux 模板。

FROM toolchain AS final
# 复制预编译产物，设置入口。

ENTRYPOINT ["/opt/leanclr/publish"]
```

## 为什么要 Godot 源码

官方 `export_templates.tpz` 里的 Linux、Windows、Web、Android 模板仍带着 Godot 自己的 .NET 宿主。这里要的是从锁定的 4.7.2 源码编出的 `template_release`：定义 `LEANCLR_GODOT`，把 LeanCLR 静态库链进模板。`/opt/godot` 里的官方 Linux 编辑器只生成胶水和调用导出，不作为玩家进程。

## Linux 导出模板

Godot 4.7 的说明在 [Compiling for Linux, \*BSD](https://docs.godotengine.org/en/stable/engine_details/development/compiling/compiling_for_linuxbsd.html) 的 “Building export templates”。64 位发布模板是：

```bash
scons platform=linuxbsd target=template_release arch=x86_64
```

文档建议正式产物用 GCC。镜像里的 Linux 模板和它要链接的 LeanCLR 静态库都用这套 GCC，不另开 `use_llvm=yes`。

编译这行之前，源码树里已经接上 `godot_patches/m1` 的后端，并且 `LEANCLR_GODOT_RUNTIME` 指向刚编好的静态库目录。`modules/mono/SCsub` 在非编辑器构建且该变量存在时定义 `LEANCLR_GODOT`。Linux 走 `.a` 分支，链入 `libleanclr-godot-calli.a` 和 `libleanclr.a`。因此这份 `godot.linuxbsd.template_release.x86_64` 里的 `GDMono::initialize` 调用 `leanclr_godot::initialize()`。

改过的引擎按同一页的说明当作自定义导出模板：导出预设指向源码 `bin/` 里的这个文件，不复制成 `linux_release.x86_64` 去替换编辑器自带模板。

## Windows 交叉编译

Godot 4.7 的说明在 [Compiling for Windows](https://docs.godotengine.org/en/stable/engine_details/development/compiling/compiling_for_windows.html) 的 “Cross-compiling for Windows from other operating systems”。Ubuntu 上安装发行版包：

```bash
apt install mingw-w64
```

SCons 在 `PATH` 中查找 `x86_64-w64-mingw32-gcc`。MinGW-w64 必须使用 POSIX 线程模型。Ubuntu 的该包默认可能是 win32 模型，镜像构建时切到 posix 变体：

```bash
update-alternatives --set x86_64-w64-mingw32-gcc /usr/bin/x86_64-w64-mingw32-gcc-posix
update-alternatives --set x86_64-w64-mingw32-g++ /usr/bin/x86_64-w64-mingw32-g++-posix
```

导出模板：

```bash
scons platform=windows target=template_release arch=x86_64 use_mingw=yes d3d12=no
```

`use_mingw=yes` 是文档要求的 MinGW-w64 编译参数。`d3d12=no` 使用文档给出的跳过 Direct3D 12 SDK 的选项；第一版桌面模板保留 OpenGL。MinGW-w64 只覆盖 `x86_64` 和 `x86_32`，这里只编 `x86_64`。

LeanCLR 静态库用同一套编译器：`x86_64-w64-mingw32-gcc` 与 `x86_64-w64-mingw32-g++`。

## 一次打包怎么走

`/opt/leanclr/publish` 接收 `--targets linux,windows,web,android`。默认按镜像支持的平台打包。

共享步骤只做一次：

1. 若缓存卷里没有对应提交的 Godot 源码，下载 `ed1daf0` 并校验归档 SHA-256 `e607e9985e1c201bc9cdc1aec8a120f0c3f53b9603f1f828e2b748534a2471ef`。
2. 应用导出策略补丁，编 Linux headless 导出器。
3. 用 `/opt/godot` 里的官方 Linux 编辑器生成 C# 胶水。
4. `dotnet build` 发布用的托管程序集。开发工程可以继续是 `net8.0`；发布程序集单独编。
5. 生成 calli 桥，并把 LeanCLR 后端补丁接到 `modules/mono`。这一步与目标平台无关。

然后按目标各编一次 LeanCLR 静态库和对应的 Godot 模板：

| 步骤 | Linux x64 | Windows x64 | WebGL | Android arm64 |
| --- | --- | --- | --- | --- |
| LeanCLR 运行时 | `cmake -G Ninja`，GCC | `cmake -G Ninja`，`x86_64-w64-mingw32-gcc` | `emcmake cmake -G Ninja` | `cmake -G Ninja`，`android.toolchain.cmake`，`ANDROID_ABI=arm64-v8a`，`ANDROID_PLATFORM=android-24` |
| Godot 模板 | `platform=linuxbsd` `target=template_release` `arch=x86_64`，链入 LeanCLR `.a` | `platform=windows` `target=template_release` `arch=x86_64` `use_mingw=yes` `d3d12=no` | `platform=web` `arch=wasm32` `threads=no` | `platform=android` `arch=arm64v8` |
| 导出 | 可执行文件和 PCK | `exe` 和 PCK | Web 目录 | 只含 `arm64-v8a` 的 APK |

模板目标都是 `template_release`。WebGL 关闭线程，因为 LeanCLR 发布宿主是单线程的，VM 调用留在启动线程。

模块裁剪沿用参考模板的范围：默认关闭可选模块，打开 mono、gdscript、freetype、svg、text_server_fb 和 2D 物理。Windows、Web 与 Android 使用 OpenGL，不把 Vulkan 编进第一版模板。

## 目录和运行

```text
/src                         游戏仓库，绑定挂载
/cache/godot                 Godot 源码、导出器和四套模板
/cache/nuget                 NuGet 全局包
/src/out/linux
/src/out/windows
/src/out/web
/src/out/android
```

```bash
docker build -t godot-leanclr:v4.7.2-linux .

docker run --rm \
  -v "$PWD":/src \
  -v leanclr-cache:/cache \
  -e NUGET_PACKAGES=/cache/nuget \
  godot-leanclr:v4.7.2-linux \
  --targets linux \
  --output /src/out
```

只打其中一个目标时把 `--targets` 改成 `linux`、`windows`、`web` 或 `android`。输出目录由入口创建；同一路径已有结果时拒绝覆盖，调用方换一个新的 `--output`。

给 `/cache` 预留不少于 50 GB。导出器和四套模板的对象文件都在这个卷里。第一次下载源码并编译以小时计。工具链本身已经在镜像里，后续打包不再下载 NDK、Emscripten 和 MinGW-w64。

## GitHub Actions 缓存

镜像构建和项目导出都利用缓存：

- 模板/镜像构建使用 GHCR registry cache：`type=registry,ref=<image>:buildcache-linux,mode=max`。
- 镜像按内容哈希打标签 `v4.7.2-linux-<hash>`；标签已存在时跳过重建，只做冒烟测试。
- Dockerfile 拆成 `toolchain`、`leanclr-linux`（`prepare`/`linux`）和 `final` 层，修改 `publish` 或 `Bootstrap.cs` 只重建最终小层；修改 `native` 只重建 Linux 模板层。
- 项目导出时 `/cache/nuget` 可挂载持久化，避免重复还原 NuGet 包。

## 验收

四个目录都产出之后：

- Linux：在容器内运行打出的可执行文件，headless，退出码为 0。日志含 `LEANCLR_GODOT_READY backend=LeanCLR`。
- Windows：确认产物是 PE32+ 可执行文件，导入表里没有 `coreclr.dll`、`hostfxr.dll`、`hostpolicy.dll`。镜像不运行这个 exe。
- WebGL：导出目录包含 wasm、js 和 html，并用镜像内的 headless Chromium 打开本地 HTTP 服务后的页面，页面完成启动。
- Android：`aapt` 确认包内原生库只有 `lib/arm64-v8a` 下的游戏库和 `libc++_shared.so`，没有桌面 CoreCLR、hostfxr 或 Mono 运行时库。

参考样例 `samples/dotnet` 的玩法契约是 `NODE2D_SMOKE_OK instances=1 frames=4 x=8 speed=120`。Linux 和 WebGL 可以把这个输出当作第一版冒烟。Windows exe 的同一条冒烟在 Windows 机器上跑。

## 不搬进这张镜像的东西

- Windows 容器、Visual Studio、MSVC 生成器 `Visual Studio 17 2022`、`msvcrt` 文件锁。Windows 目标按 Godot 文档用发行版 MinGW-w64 交叉编译。
- MinGW-LLVM 和 `use_llvm=yes`。文档里那条路用于 Windows arm64；x86_64 使用 MinGW-w64 GCC。
- 仓库父目录下的 `Godot_v4.7.2-stable_mono_win64`，以及 `C:\Program Files\dotnet\shared\Microsoft.NETCore.App\10.0.8` 这种路径。
- `tools/build-m1.ps1`、`tools/build-web-runtime.ps1`、`tools/build-android-runtime.ps1`、`tools/publish.py`。新的 Linux 入口使用 Ninja，但不调用这些脚本。
- 参考仓库把 Windows 链接硬编码成 MSVC `*.lib` 的那段 `SCsub`。
- 官方 `export_templates.tpz`。模板都从锁定的 Godot 源码编译。
- 参考仓库的 Windows 版 Android SDK 压缩包和它从 `LOCALAPPDATA` 复制许可证的做法。
- 混合 AOT。解释执行的四目标打通之后再加；AOT 仍然是同一镜像里的一个开关，不另做镜像。
- 日常 Play 和 C# 断点调试。那继续留在开发机的官方编辑器里。

公开分发镜像时要单独处理 Android SDK、.NET 和 Godot 编辑器的许可。第一版按本机和 CI 使用。
