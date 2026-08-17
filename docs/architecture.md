# 设计与信任边界

## 版本模型

`config/runtime-profiles.json` 是运行时兼容性的唯一声明入口。每个 profile 同时固定：

- Dify 版本与部署形态；
- plugin daemon 镜像及已验证 manifest digest；
- Python 主次版本与可执行文件；
- uv 可执行文件；
- Dify 打包/签名 CLI 路径；
- 各 CPU 架构的验证状态和已观察 CLI SHA-256。

`doctor` 会在无网络容器中读取真实镜像 digest、Python、uv、CPU 架构和 CLI 哈希。内置 profile 与观察值不一致时默认失败，避免仅凭镜像 tag 继续构建。

## 为什么仓库不提交四个 CLI 二进制

`darwin-amd64`、`darwin-arm64`、`linux-amd64`、`linux-arm64` 描述的是运行打包命令的宿主机，而不是插件将要运行的 Dify 版本。仅提交这四个二进制不能回答以下问题：

- 二进制由哪个 Dify daemon 源码 tag 构建；
- 构建参数和依赖是否可复现；
- CLI 是否与目标 daemon 的包校验和签名格式一致；
- 插件依赖 wheel 是否匹配目标 Linux/Python ABI。

本项目直接在目标 daemon 容器内运行该版本随镜像发布的 CLI，并把镜像 ID、digest 和 CLI SHA-256 写入报告。宿主机只需要 Docker，不执行无法由本仓库复现构建的预编译 Dify CLI。

## 构建数据流

1. 输入 `.difypkg` 被安全解压，拒绝绝对路径、目录穿越、符号链接和异常解压体积；
2. 在目标 daemon 镜像与目标 CPU 架构中解析依赖并原生构建 wheels；
3. 输出改为只包含固定版本 `requirements.txt` 与本地 `wheels/`；
4. 删除 `pyproject.toml` 和 `uv.lock`，确保 daemon 选择 requirements 安装路径；
5. 使用目标镜像内置 Dify CLI 重新打包；
6. 如需签名，在不联网且只挂载私钥的独立容器中签名，随后立即使用公钥验签；
7. 在 `--network none` 容器中重新创建虚拟环境并安装，成功后才发布输出。

## 证明范围

断网安装成功证明输出包的 Python 依赖不需要访问包索引。它不证明：

- 插件连接的外部 API 可用；
- 依赖没有已知漏洞或恶意代码；
- 客户 Dify 的第三方公钥配置正确；
- 未验证的 CPU 架构或自定义镜像与内置 profile 等价。
