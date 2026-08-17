# 兼容性与验证矩阵

本项目只把完成了明确验证门槛的 Dify 版本列为 `supported`。Dify 应用版本、plugin daemon 镜像、Python ABI、CPU 架构和 daemon 内置 CLI 是一组不可拆开的运行时身份，不能只凭版本号相近推断兼容。

## 状态定义

- `integration-tested`：使用该版本声明的目标镜像，在对应架构完成运行时自检、依赖构建、Dify CLI 打包、断网安装；`linux/amd64` 还完成了第三方签名及验签。
- `not-tested`：配置和镜像声明存在，但尚未在该架构完成端到端验收，不能作为已支持能力对外承诺。
- `custom-runtime-not-validated`：通过 `--runtime-image` 或高级参数覆盖了内置 profile。工具仍会做实时能力检查，但内置 profile 的验收结论不再适用。

## 当前矩阵

| Dify 部署 | Profile | 目标 daemon 镜像 | linux/amd64 | linux/arm64 |
| --- | --- | --- | --- | --- |
| Enterprise Compose 3.9.2 | `enterprise-3.9.2` | `langgenius/dify-ee-plugin-daemon-local:3.9.2` | `integration-tested` | `not-tested` |
| Enterprise Compose 3.12.0 | `enterprise-3.12.0` | `langgenius/dify-ee-plugin-daemon-local:3.12.0` | `integration-tested` | `not-tested` |

验收 fixture 为 `langgenius/openai_api_compatible:0.0.59`。验证结论只覆盖插件依赖的打包、签名、验签和离线安装，不等价于插件业务 API 的功能验收。

本次 `linux/amd64` 的镜像 digest、CLI 哈希和输出证据见 [2026-08-17 验证记录](validation/2026-08-17-linux-amd64.md)。

## 为什么没有把所有 Dify 版本都写成支持

Dify Enterprise Compose 3.5.2 使用 `langgenius/dify-plugin-daemon:0.2.0-local`。对应上游 `0.2.0` 的 [`docker/local.dockerfile`](https://github.com/langgenius/dify-plugin-daemon/blob/0.2.0/docker/local.dockerfile) 构建 `/app/main`，但没有把 `cmd/commandline` 构建为 `/app/commandline` 放进运行时镜像。当前工具的打包和组织签名流程要求使用目标版本提供的 Dify CLI，因此 3.5.2 暂不列入可选 profile。

这项边界是有意保留的：复用其他 Dify 版本的 CLI 可能引入包格式或签名语义偏差；把无法由本仓库复现构建的预编译 CLI 直接提交到仓库也不满足可审计要求。后续若要支持旧版本，应从对应上游 tag 可复现地构建 CLI，并完成目标 daemon 的上传安装验收。

## 新增版本的准入门槛

新增 profile 至少需要：

1. 从该 Dify 发布的 Compose 或 Helm 配置确认精确 daemon 镜像；
2. `doctor` 确认目标架构、Python、uv 和 Dify CLI，并记录 CLI SHA-256；
3. 使用包含二进制依赖的 Python 插件完成原生 wheel 构建；
4. 在 `--network none` 容器中从输出包安装全部依赖；
5. 生成组织测试密钥，完成签名和公钥验签；
6. 在实际 Dify 测试环境完成上传、安装与一次业务调用；
7. 更新 `config/runtime-profiles.json` 和本页，不覆盖尚未验证的架构状态。

仓库中的 `integration-tested` 目前覆盖第 1 至第 5 项；真实 Dify UI 上传与业务调用仍属于部署方验收范围。
