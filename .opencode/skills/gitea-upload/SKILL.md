---
name: gitea-upload
description: Use when user says "上传到gitea", "push to gitea", "upload to gitea", or wants to sync project to self-hosted Gitea at 192.168.3.20:3080.
---

# Gitea Upload

自托管 Gitea（NUC, `192.168.3.20:3080`），SSH 端口 3022。

## 环境变量

从 `~/.bashrc` source 获取：

```
source ~/.bashrc  # 加载 GITEA_TOKEN, GITEA_HOST, GITEA_SSH_PORT
```

- `GITEA_HOST` = `192.168.3.20:3080`
- `GITEA_TOKEN` = Gitea API token
- `GITEA_SSH_PORT` = `3022`

SSH key 名: `mac-mini-hermes`（已部署到 Gitea）

## 流程

### 1. 创建仓库

```bash
source ~/.bashrc
curl -s -X POST \
  -H "Authorization: token $GITEA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"仓库名","description":"描述","auto_init":false,"private":false,"default_branch":"main"}' \
  "http://192.168.3.20:3080/api/v1/user/repos"
```

### 2. 添加 remote 并推送

```bash
git remote add gitea ssh://git@192.168.3.20:3022/lvyun/仓库名.git
GIT_SSH_COMMAND="ssh -p 3022" git push gitea main
```

要保留两个 remote 共存可以保留 `origin`（GitHub）和 `gitea`。

### 3. 验证

```bash
source ~/.bashrc
curl -s -H "Authorization: token $GITEA_TOKEN" "http://192.168.3.20:3080/api/v1/users/lvyun/repos" | python3 -m json.tool
```

## 已知问题

- Gitea API PATH 是 `/api/v1/`（不是 GitHub 的 `/api/v3/`）
- 容器内 SSH 端口是 2222，外部映射到 3022
- 必须用 `GIT_SSH_COMMAND="ssh -p 3022"` 或 `git config core.sshCommand "ssh -p 3022"`
