# AGENTS.md

## 上游同步流程

本仓库是 `rosemarycox5334-debug/PA_Agent` 的 fork，长期维护分支为 `feat/mt5-macos-support`。

### 远程配置

- `origin` → `CaiJingLong/PA_Agent`（本 fork）
- `upstream` → `rosemarycox5334-debug/PA_Agent`（上游）

### 同步上游更新

```bash
git fetch upstream
git checkout feat/mt5-macos-support
git merge upstream/main
# 解决冲突后
git push origin feat/mt5-macos-support
```

### 查看上游新增提交

```bash
git fetch upstream
git log --oneline upstream/main ^feat/mt5-macos-support
```
