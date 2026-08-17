# Dify Plugin Offline Packager

[![CI](https://github.com/ZhouhaoJiang/dify-plugin-offline-packager/actions/workflows/ci.yml/badge.svg)](https://github.com/ZhouhaoJiang/dify-plugin-offline-packager/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

面向隔离网络部署的 Dify Python 插件重打包工具。它按 Dify 版本选择目标 plugin daemon 镜像，在目标 Linux/Python/CPU 运行时中构建依赖，完成断网安装验证，并生成可审计报告。

这是独立社区项目，不是 Dify 官方发行物。重打包会改变原 Marketplace 包，部署方需要对新的依赖供应链和组织签名负责。

## 支持范围

| Profile | Dify 部署 | linux/amd64 | linux/arm64 |
| --- | --- | --- | --- |
| `enterprise-3.9.2` | Enterprise Compose 3.9.2 | 已完成集成验证 | 未验证 |
| `enterprise-3.12.0` | Enterprise Compose 3.12.0 | 已完成集成验证 | 未验证 |

完整证据边界、旧版本差异和新增版本准入规则见 [兼容性与验证矩阵](docs/compatibility.md)。未列出的版本不应按“应该兼容”处理。

## 为什么按 Dify 版本管理

离线包是否可用取决于一整组运行时身份：

- Dify/plugin daemon 版本；
- Python ABI；
- Linux CPU 架构；
- uv 与 daemon 的依赖安装分支；
- Dify 打包和签名 CLI。

因此，本项目不提交 `darwin-amd64`、`darwin-arm64`、`linux-amd64`、`linux-arm64` 四个宿主机预编译二进制。它直接使用目标 daemon 镜像中随版本交付的 `/app/commandline`，并在执行前核对 Python、uv、CPU 架构和 CLI SHA-256。详细设计见 [设计与信任边界](docs/architecture.md)。

## 工作原理

当插件同时包含 `pyproject.toml` 与 `uv.lock` 时，部分 daemon 版本会选择 `uv sync --frozen`。原锁文件仍可能含远端 URL，所以仅加入 `wheels/` 或在 `pyproject.toml` 中声明 `no-index` 不能构成离线保证。

本工具会：

1. 在目标 daemon 镜像和 CPU 架构中原生构建所有 wheels；
2. 生成只引用 `./wheels` 的固定版本 `requirements.txt`；
3. 从输出包移除 `pyproject.toml` 和 `uv.lock`，明确选择 requirements 安装路径；
4. 使用目标版本内置 Dify CLI 打包和可选签名；
5. 在 `--network none` 容器中重新安装依赖，成功后才发布产物；
6. 记录输入输出 SHA-256、镜像 ID/digest、CLI 哈希、Python、uv 和依赖清单。

## 前置条件

- Docker Engine 或 Docker Desktop；
- 打包阶段可以访问所选 Python 包索引；
- 能拉取目标 Dify plugin daemon 镜像；
- 输入为 Python 插件 `.difypkg`。

宿主机可以是 macOS。`--platform linux/amd64` 或 `linux/arm64` 决定真正构建 wheel 的目标容器架构。

## 快速开始

先查看仓库声明的版本，而不是默认猜测：

```bash
./dify-offline-packager profiles
```

所有会运行容器的命令都要求显式传入 `--profile`；工具不会静默选择某个 Dify 版本。

检查目标镜像的实际能力：

```bash
./dify-offline-packager doctor \
  --profile enterprise-3.12.0 \
  --platform linux/amd64
```

生成本组织自己的测试/生产签名密钥：

```bash
./dify-offline-packager keygen \
  --profile enterprise-3.12.0 \
  --platform linux/amd64 \
  --output-dir ./keys
```

私钥只保留在受控打包环境。Dify 服务器只需要公钥。

打包并完成断网验证：

```bash
./dify-offline-packager pack ./plugin.difypkg \
  --profile enterprise-3.12.0 \
  --platform linux/amd64 \
  --index-url https://pypi.org/simple \
  --private-key ./keys/offline-packager.private.pem \
  --public-key ./keys/offline-packager.public.pem
```

成功后产生：

- `*-offline-linux-amd64.difypkg`：输出插件包；
- `*.difypkg.report.json`：运行时身份、依赖、签名状态和断网验证结果。

命令只有在无网络二次安装成功后才返回成功。

## 私有镜像仓库

如果客户镜像来自内部仓库，仍需选择语义匹配的 profile，再覆盖镜像地址：

```bash
./dify-offline-packager doctor \
  --profile enterprise-3.9.2 \
  --platform linux/amd64 \
  --runtime-image registry.example.com/dify-ee-plugin-daemon-local:3.9.2
```

覆盖后报告会把 profile 标记为 `custom-runtime-not-validated`。实时自检通过只说明基础组件匹配，不继承内置镜像的集成验证结论。

## 独立复核

重复断网安装：

```bash
./dify-offline-packager verify ./plugin-offline-linux-amd64.difypkg \
  --profile enterprise-3.12.0 \
  --platform linux/amd64
```

复核第三方签名：

```bash
./dify-offline-packager verify-signature ./plugin-offline-linux-amd64.difypkg \
  --profile enterprise-3.12.0 \
  --platform linux/amd64 \
  --public-key ./keys/offline-packager.public.pem
```

仓库中的 [Compose override 示例](deploy/docker-compose.third-party-signatures.yaml) 展示了公钥挂载方式。应用前必须与目标 Dify 版本的环境变量逐项核对，并先运行 `docker compose ... config` 检查合并结果。不要把私钥挂载到 Dify 服务器。

## 安全边界

- 构建 Python sdist 会执行第三方构建代码；请使用专用 worker，且不要挂载 Docker socket、宿主机主目录或无关凭据。
- 私钥只挂载到 `--network none` 的独立签名容器，随后立即公钥验签。
- 断网安装不等于插件业务验证，也不等于依赖漏洞扫描。
- 默认解压后大小上限为 50 MB。修改 `--max-size-mb` 前需确认目标 Dify 的包大小限制。
- 不传签名密钥可生成 unsigned 包，但开启强制签名校验的 Dify 会拒绝它。不要为了安装一个包而全局关闭签名校验。

安全问题请按 [Security Policy](SECURITY.md) 私密报告。

## 开发

```bash
python3 -m unittest discover -s tests -v
ruff check src tests
ruff format --check src tests
```

版本配置位于 [`config/runtime-profiles.json`](config/runtime-profiles.json)。新增版本必须遵循 [兼容性准入门槛](docs/compatibility.md#新增版本的准入门槛)，不能只复制一个镜像 tag。

## License

Apache License 2.0。Dify 名称及相关商标归其权利人所有。
