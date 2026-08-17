# Dify Plugin Offline Packager

面向 Dify Enterprise Docker Compose 3.12.0 的 Python 插件离线打包工具。它不会依赖宿主机 Python 的 ABI，也不会用单一 `pip --platform` 猜测 Linux wheel 标签。

## 它解决什么问题

Dify 3.12.0 的 plugin daemon 在插件同时包含 `pyproject.toml` 和 `uv.lock` 时会执行：

```text
uv sync --no-dev --frozen
```

因此，只往包里加入 `wheels/` 并在 `pyproject.toml` 写 `no-index` 并不充分：原锁文件仍可能含远端 URL，`--frozen` 也不会重写它。

实现依据为 Dify 3.12.0 对应的 plugin daemon 源码：Python 运行时固定为 3.12（[local.dockerfile](https://github.com/langgenius/dify-plugin-daemon/blob/eff6e1eef304cbeb43de2df82ee575bde0a957e6/docker/local.dockerfile#L25-L50)），依赖文件选择和 `uv sync` / `uv pip install` 参数位于 [setup_python_environment.go](https://github.com/langgenius/dify-plugin-daemon/blob/eff6e1eef304cbeb43de2df82ee575bde0a957e6/internal/core/local_runtime/setup_python_environment.go#L73-L195)。上游曾加入全局 `uv sync --offline`，随后因破坏正常 Marketplace 安装而回退，见 [PR #651](https://github.com/langgenius/dify-plugin-daemon/pull/651)。

本工具采用另一条经过 3.12.0 daemon 支持的路径：

1. 在与目标环境相同的 plugin daemon 镜像和 CPU 架构中原生构建全部 wheels；
2. 生成只引用 `./wheels` 的完全固定版本 `requirements.txt`；
3. 从输出包中移除 `pyproject.toml` 和 `uv.lock`，使 daemon 明确选择 `uv pip install -r requirements.txt`；
4. 用同一镜像、`--network none` 再安装一次，断网验证通过后才输出包；
5. 生成包含镜像 ID、依赖清单和 SHA-256 的审计报告。

当前范围：Dify Enterprise Docker Compose 3.12.0、Python 3.12 插件、`linux/amd64` 与 `linux/arm64`。本仓库的工单验收样例已覆盖 `linux/amd64`；发布 arm64 包时仍应在对应架构上独立执行完整命令并保留报告。

## 前置条件

- Docker；
- 已能访问依赖源的打包机；
- 目标部署使用的 `langgenius/dify-ee-plugin-daemon-local:3.12.0` 镜像。若镜像使用私有仓库地址，通过 `--image` 传入实际地址。

打包机可以是 Apple Silicon。`--platform linux/amd64` 会让依赖在目标 Linux x86_64 容器中解析和构建。

## 快速使用

先生成本组织自己的插件签名密钥：

```bash
./dify-offline-packager keygen \
  --platform linux/amd64 \
  --output-dir ./keys
```

私钥只保留在受控的打包环境，不能复制到 Dify 服务器。服务器只需要公钥。

打包 Marketplace 下载的插件：

```bash
./dify-offline-packager pack ./openai_api_compatible_0.0.59.difypkg \
  --platform linux/amd64 \
  --index-url https://mirrors.cloud.tencent.com/pypi/simple \
  --private-key ./keys/offline-packager.private.pem \
  --public-key ./keys/offline-packager.public.pem
```

如果部署镜像来自私有镜像仓库：

```bash
./dify-offline-packager pack ./plugin.difypkg \
  --platform linux/amd64 \
  --image registry.example.com/dify-ee-plugin-daemon-local:3.12.0 \
  --private-key ./keys/offline-packager.private.pem \
  --public-key ./keys/offline-packager.public.pem
```

成功后产生：

- `*-offline-linux-amd64.difypkg`：离线插件包；
- `*.difypkg.report.json`：输入/输出 SHA-256、精确镜像身份、固定依赖清单、断网验证结果。

命令只有在 `--network none` 的二次安装成功后才返回成功。

## 在 Dify 3.12.0 中信任组织公钥

推荐保留 `FORCE_VERIFYING_SIGNATURE=true`，为 plugin daemon 挂载公钥并开启第三方签名校验。仓库提供了 [deploy/docker-compose.third-party-signatures.yaml](deploy/docker-compose.third-party-signatures.yaml) 示例：

```bash
mkdir -p ./keys
cp /安全传输路径/offline-packager.public.pem ./keys/
docker compose \
  -f docker-compose.yaml \
  -f /path/to/docker-compose.third-party-signatures.yaml \
  up -d plugin_daemon
```

请先用 `docker compose ... config` 检查合并结果。不要把私钥挂载到服务器或提交到 Git。

若不传 `--private-key`，工具仍可生成并断网验证 unsigned 包，但 Dify 3.12.0 默认会拒绝它。将 `FORCE_VERIFYING_SIGNATURE=false` 会扩大所有插件的信任面，仅适合已有隔离控制的临时环境，不作为推荐方案。

## 独立验证

重复断网安装测试：

```bash
./dify-offline-packager verify ./plugin-offline-linux-amd64.difypkg \
  --platform linux/amd64
```

验证第三方签名：

```bash
./dify-offline-packager verify-signature ./plugin-offline-linux-amd64.difypkg \
  --platform linux/amd64 \
  --public-key ./keys/offline-packager.public.pem
```

## 安全边界

- 重打包会改变原 Marketplace 包，原官方签名不再有效；输出包必须按本组织供应链重新签名。
- 构建 Python sdist 时，第三方构建脚本会在受限 Docker 容器中执行。容器不挂载 Docker socket、用户主目录、签名密钥或其他项目目录，但构建阶段需要网络访问依赖源。
- 私钥仅挂载到 `--network none` 的独立签名容器；签名完成后会立即使用所给公钥验签。
- 离线验证证明依赖安装不访问网络，不等于插件业务功能验证或依赖安全审计。
- 默认包大小上限为 50 MB，与 3.12.0 Compose 默认 `PLUGIN_MAX_PACKAGE_SIZE` 一致。调整 `--max-size-mb` 时必须同步评估服务器限制。

## 测试

```bash
python3 -m unittest discover -s tests -v
```
