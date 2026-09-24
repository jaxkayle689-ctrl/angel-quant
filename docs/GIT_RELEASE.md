# Git 源码发布指南

## 包含内容

源码包保留 `src/`（含构建后的前端）、`frontend/` 源码及 npm 锁文件、`tests/`、`scripts/`、`docs/`、`chanlun/`、`packaging/`、实验脚本和实验说明。实验配置转换为清空凭据、关闭 API 服务的 `config.example.json` 和 `martingale_config.example.json`。运行实验前自行复制为对应的 `config.json` / `martingale_config.json`；真实配置已被 Git 忽略。

不包含 `.env`、`api/`、个人工具记录、虚拟环境、node_modules、缓存、历史构建、安装包、回测 CSV/ZIP 和实验结果目录。原始实验数据需要在本机保留或另外存储。`output/` 是本地交付目录，不提交 Git。

公开行情无需密钥。账户、模型或推送所需的密钥由使用者自行设置；不要将真实密钥放入 `.env.example`。应用运行数据位于 macOS Application Support，不在源码包内。

## 本地验证

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e . -r requirements-dev.txt
python -m unittest discover -s tests -p 'test_pipeline*.py'
cd frontend
npm ci
npm run build
cd ..
```

完整后端测试可用 `python -m unittest discover -s tests`，部分原有功能需要额外外部引擎或网络。Freqtrade 安装入口是 `scripts/install_freqtrade_engine.sh`。

## 上传空仓库

先解压源码包，进入 `angel-quant/`。在 GitHub、Gitee 或其他托管平台建立一个空仓库，再执行以下命令。将 `<仓库地址>` 替换为自己的实际地址。

```bash
git init -b main
git add .
git status --short
git commit -m "Initial import: Angel Quant desktop and pipeline"
git remote add origin <仓库地址>
git push -u origin main
```

不要直接把 ZIP 文件作为仓库唯一内容上传；应提交解压后的源码。仓库可见性由你在托管平台选择。此步骤尚未由打包过程执行。

## 再次打包

```bash
python3 scripts/package_source.py
```

脚本生成带时间戳的 ZIP、SHA-256 校验文件和打包清单，并对入包文本执行常见密钥模式检查。该检查不能替代人工审查。项目包含第三方策略参考资源、视频转写和图片，公开发布前需自行确认再分发权限；本次未擅自为整个项目添加开源许可证。
