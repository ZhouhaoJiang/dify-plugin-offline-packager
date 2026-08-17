# Dify Plugin Offline Packager

[简体中文](README.md) | [English](README_EN.md)

[![CI](https://github.com/ZhouhaoJiang/dify-plugin-offline-packager/actions/workflows/ci.yml/badge.svg)](https://github.com/ZhouhaoJiang/dify-plugin-offline-packager/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

面向隔离网络部署的 Dify Python 插件重打包工具。它按 Dify 版本选择目标 plugin daemon 镜像，在目标 Linux、Python 和 CPU 运行时中构建依赖，完成断网安装验证，并生成可审计报告。

本项目由社区独立维护，不属于 Dify 官方发行物。重打包会改变原 Marketplace 包，使用方需要审查新的依赖供应链，并管理自己的签名密钥。

## 支持范围

| Profile | Dify 部署 | `linux/amd64` | `linux/arm64` |
| --- | --- | --- | --- |
| `dify-compose-3.9.2` | Docker Compose 3.9.2 | 已完成集成验证 | 未验证 |
| `dify-compose-3.12.0` | Docker Compose 3.12.0 | 已完成集成验证 | 未验证 |

完整证据边界、旧版本差异和新增版本准入规则见[兼容性与验证矩阵](docs/compatibility.md)。未列出的版本不应按“应该兼容”处理。

## 为什么按 Dify 版本管理

离线包是否可用取决于一整组运行时身份：

- Dify 与 plugin daemon 版本；
- Python ABI；
- Linux CPU 架构；
- uv 与 daemon 的依赖安装分支；
- Dify 打包和签名 CLI。

因此，本项目不提交 `darwin-amd64`、`darwin-arm64`、`linux-amd64`、`linux-arm64` 四个宿主机预编译二进制。它直接使用目标 daemon 镜像中随版本交付的 `/app/commandline`，并在执行前核对 Python、uv、CPU 架构和 CLI SHA-256。详细设计见[设计与信任边界](docs/architecture.md)。

## 工作原理

当插件同时包含 `pyproject.toml` 与 `uv.lock` 时，部分 daemon 版本会选择 `uv sync --frozen`。原锁文件仍可能包含远端 URL，因此仅加入 `wheels/` 或在 `pyproject.toml` 中声明 `no-index` 不能构成离线保证。

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
- 可以拉取目标 Dify plugin daemon 镜像；
- 输入为 Python 插件 `.difypkg`。

宿主机可以是 macOS。`--platform linux/amd64` 或 `linux/arm64` 决定真正构建 wheel 的目标容器架构。

## Fork 后在 GitHub Actions 中打包

Fork 用户可以只通过 GitHub 网页完成下载、目标运行时检查、打包、签名和断网复验，无需在本机安装 Docker。

### 1. Fork 并启用工作流

1. Fork 本仓库；
2. 打开 fork 的 **Actions** 页面并启用工作流；
3. 选择 **Build offline package**，点击 **Run workflow**。

Fork 不会继承上游仓库的 Actions Secrets。构建只使用当前 fork 所有者自行配置的密钥和下载地址。

### 2. 准备源包地址和哈希

`workflow_dispatch` 不能直接上传本地文件，因此源 `.difypkg` 必须通过 GitHub-hosted runner 可访问的 HTTPS 地址下载。先在本地计算输入包 SHA-256：

```bash
# macOS
shasum -a 256 plugin.difypkg

# Linux
sha256sum plugin.difypkg
```

公开下载地址可以直接填入 `package_url`。私有或临时签名地址不要填写在可见的 workflow input 中，应保存为 fork 的 Repository Secret：

```bash
printf '%s' 'https://storage.example.com/private/plugin.difypkg?...' \
  | gh secret set DIFY_PLUGIN_PACKAGE_URL
```

如果源包只能在隔离网络内访问，请使用本地命令行或经过审查的自托管 runner，不要把客户包提交到公开 fork。

### 3. 填写 Run workflow 参数

| 参数 | 填写方式 |
| --- | --- |
| `package_url` | 公开 HTTPS 地址；使用 `DIFY_PLUGIN_PACKAGE_URL` Secret 时留空 |
| `package_filename` | 仅用于产物命名，例如 `langgenius-openai_api_compatible_0.0.59.difypkg`；它不会上传本地文件 |
| `package_sha256` | 输入源包的完整 64 位 SHA-256，下载后不一致会立即失败 |
| `profile` | 必须与目标 Dify 部署版本一致 |
| `architecture` | plugin daemon 的 Linux CPU 架构，不是浏览器或本机架构 |
| `signing_mode` | 首次体验选 `ephemeral`；长期使用组织密钥选 `repository-secrets` |
| `index_url` | 公开 Python 包索引；私有索引使用 `DIFY_PYPI_INDEX_URL` Secret |

`ephemeral` 每次运行生成新的临时私钥，私钥在上传产物前删除；下载包中只包含对应公钥。每次都需要让目标 Dify 信任这次生成的公钥。

长期为多个插件使用同一组织密钥时，先在受控环境生成密钥，并把目录放在仓库 checkout 之外：

```bash
mkdir -p ../dify-offline-packager-keys

./dify-offline-packager keygen \
  --profile dify-compose-3.12.0 \
  --platform linux/amd64 \
  --output-dir ../dify-offline-packager-keys

base64 < ../dify-offline-packager-keys/offline-packager.private.pem \
  | tr -d '\n' | gh secret set DIFY_PLUGIN_PRIVATE_KEY_B64

base64 < ../dify-offline-packager-keys/offline-packager.public.pem \
  | tr -d '\n' | gh secret set DIFY_PLUGIN_PUBLIC_KEY_B64
```

随后选择 `repository-secrets`。Action 不会上传私钥；公钥会随每次产物提供，便于部署方核对。

### 4. 下载和部署产物

成功后，从该次 run 的 **Artifacts** 下载 `dify-offline-*`。压缩包包含：

- `*-offline-linux-*.difypkg`：应上传到 Dify 的离线插件包；
- `*.difypkg.report.json`：运行时身份、依赖、签名和断网复验证据；
- `offline-packager.public.pem`：目标 Dify 需要信任的公钥；
- `SHA256SUMS` 与 `NEXT_STEPS.md`：完整性校验和后续步骤。

Artifact 默认保留 7 天。先按 [Compose override 示例](deploy/docker-compose.third-party-signatures.yaml)配置并核对公钥，再上传 `*-offline-linux-*.difypkg`，不要再次上传原始源包。

Action 可执行 `linux/arm64` 构建不代表该架构自动获得集成验证结论；支持状态仍以[兼容性与验证矩阵](docs/compatibility.md)为准。

## 本地命令行快速开始

先查看仓库声明的版本：

```bash
./dify-offline-packager profiles
```

所有会运行容器的命令都要求显式传入 `--profile`，工具不会静默选择 Dify 版本。

检查目标镜像的实际能力：

```bash
./dify-offline-packager doctor \
  --profile dify-compose-3.12.0 \
  --platform linux/amd64
```

生成本组织自己的签名密钥：

```bash
mkdir -p ../dify-offline-packager-keys

./dify-offline-packager keygen \
  --profile dify-compose-3.12.0 \
  --platform linux/amd64 \
  --output-dir ../dify-offline-packager-keys
```

私钥只保留在受控打包环境，Dify 服务器只需要公钥。

打包并完成断网验证：

```bash
./dify-offline-packager pack ./plugin.difypkg \
  --profile dify-compose-3.12.0 \
  --platform linux/amd64 \
  --index-url https://pypi.org/simple \
  --private-key ../dify-offline-packager-keys/offline-packager.private.pem \
  --public-key ../dify-offline-packager-keys/offline-packager.public.pem
```

成功后产生：

- `*-offline-linux-amd64.difypkg`：输出插件包；
- `*.difypkg.report.json`：运行时身份、依赖、签名状态和断网验证结果。

命令只有在无网络二次安装成功后才返回成功。

## 私有镜像仓库

如果目标镜像来自内部仓库，仍需选择语义匹配的 profile，再覆盖镜像地址：

```bash
./dify-offline-packager doctor \
  --profile dify-compose-3.9.2 \
  --platform linux/amd64 \
  --runtime-image registry.example.com/dify-plugin-daemon:3.9.2
```

覆盖后报告会把 profile 标记为 `custom-runtime-not-validated`。实时自检通过只说明基础组件匹配，不继承内置镜像的集成验证结论。

## 独立复核

重复断网安装：

```bash
./dify-offline-packager verify ./plugin-offline-linux-amd64.difypkg \
  --profile dify-compose-3.12.0 \
  --platform linux/amd64
```

复核第三方签名：

```bash
./dify-offline-packager verify-signature ./plugin-offline-linux-amd64.difypkg \
  --profile dify-compose-3.12.0 \
  --platform linux/amd64 \
  --public-key ../dify-offline-packager-keys/offline-packager.public.pem
```

仓库中的 [Compose override 示例](deploy/docker-compose.third-party-signatures.yaml)展示了公钥挂载方式。应用前必须与目标 Dify 版本的环境变量逐项核对，并先运行 `docker compose ... config` 检查合并结果。不要把私钥挂载到 Dify 服务器。

## 安全边界

- 构建 Python sdist 会执行第三方构建代码；请使用专用 worker，且不要挂载 Docker socket、宿主机主目录或无关凭据。
- Action 使用私有 Python 索引时，构建代码可以读取该索引 URL；只能使用最小权限、只读且可撤销的下载凭据。
- 不要把私有包 URL 填入可见的 workflow input，也不要把源包、私钥或凭据提交到公开 fork。
- 私钥只挂载到 `--network none` 的独立签名容器，随后立即使用公钥验签。
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

版本配置位于 [`config/runtime-profiles.json`](config/runtime-profiles.json)。新增版本必须遵循[兼容性准入门槛](docs/compatibility.md#新增版本的准入门槛)，不能只复制一个镜像 tag。

## License

Apache License 2.0。Dify 名称及相关商标归其权利人所有。
