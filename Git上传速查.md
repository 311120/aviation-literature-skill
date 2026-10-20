# Git 上传速查表

> 把本地项目传到 GitHub，永远是同一套动作。这份表贴在旁边，照着做就不会错。

## 一、心智模型：四个阶段

```
工作区（你的文件） --git add--> 暂存区（待提交清单） --git commit--> 本地仓库（快照） --git push--> GitHub
```

关键理解：**`git commit` 只存到本地，不联网**。只有 `git push` 才真正上传到 GitHub。
所以断网也能 commit，攒几次再一起 push，完全正常。

## 二、日常循环（改完东西就这三条）

```bash
git status              # 1. 先看改了什么（养成习惯，别跳过）
git add .               # 2. 全部加入暂存区
git commit -m "说明"    # 3. 存一个快照
git push                # 4. 推到 GitHub（首次之后不用写 origin main）
```

想只提交某个文件：`git add 文件名` 而不是 `git add .`

## 三、全新项目从零上传（六步）

```bash
cd 项目目录
git init -b main                          # 1. 初始化，分支名定为 main
# 2. 手动创建 .gitignore（见下方第四节）
git add .                                 # 3. 暂存
git commit -m "chore: 初始化仓库"          # 4. 首次提交
git remote add origin https://github.com/用户名/仓库名.git   # 5. 接远程
git push -u origin main                   # 6. 推送并绑定（-u 只需首次）
```

配套动作：先去 `https://github.com/new` 建一个**空仓库**——README、.gitignore、license **三个勾都别勾**。
理由：本地已有这些文件时，GitHub 再生成一份会产生两条互不相关的初始提交，push 会被拒。

## 四、.gitignore 必须写的几类

| 类别 | 例子 | 为什么 |
|---|---|---|
| 密钥凭据 | `*.env`、`*api_key*`、`*.pem` | **最严重**，泄露等于送人 |
| 依赖目录 | `node_modules/`、`.venv/`、`venv/` | 体积巨大且可重建 |
| 缓存产物 | `__pycache__/`、`*.pyc`、`.pytest_cache/` | 每次运行都变，污染提交历史 |
| 打包产物 | `dist/`、`build/`、`*.zip` | 正式发布请用 GitHub Releases |
| 备份/临时 | `_backup_*/`、`*.bak`、`*.log` | 历史快照没必要进版本库 |
| 系统垃圾 | `.DS_Store`、`Thumbs.db`、`.idea/` | 和项目无关 |

**规则**：`*` 通配任意字符，`/` 结尾表示目录，`!` 开头表示例外（不忽略）。
写完务必验证：`git check-ignore -v 目录名`

## 五、提交信息怎么写

格式：`类型: 简短说明`，类型用这几个就够：

| 类型 | 用在 |
|---|---|
| `feat` | 新增功能 |
| `fix` | 修 bug |
| `docs` | 只改文档 |
| `refactor` | 重构，行为不变 |
| `chore` | 杂活：初始化、改配置、清缓存 |
| `test` | 只改测试 |

好例子：`fix: 修正作者姓名解析把姓名写反的问题`
坏例子：`update`、`改了一下`、`asdf`

## 六、常见报错对照

| 报错 | 原因 | 解法 |
|---|---|---|
| `rejected — fetch first` | 远端有你本地没有的提交（常见于建仓库时勾了 README） | `git pull --rebase origin main` 再 push |
| `refusing to merge unrelated histories` | 两边历史完全无关 | `git pull origin main --allow-unrelated-histories` |
| `Permission denied (publickey)` | 用了 SSH 地址但没配密钥 | 改用 https 地址，或配 SSH key |
| `Authentication failed` | 凭据过期 | 删掉旧凭据：Windows「凭据管理器」→ 删 github 条目，再 push 会重新弹窗登录 |
| `fatal: not a git repository` | 当前目录没有 .git | `cd` 到正确目录，或先 `git init` |
| `large files detected` / push 很慢 | 传了超大文件 | 先 `git rm --cached 大文件`，加进 .gitignore 重新提交 |
| `src refspec main does not match any` | 还没有任何提交 | 先 `git add` + `git commit` |

## 七、后悔药

| 想干什么 | 命令 | 危险度 |
|---|---|---|
| 看改了什么 | `git diff` | 安全 |
| 撤销某个文件的未提交修改 | `git checkout -- 文件名` | 会丢修改 |
| 撤销最近一次 commit（保留改动） | `git reset --soft HEAD~1` | 较安全 |
| 撤销最近一次 commit（丢弃改动） | `git reset --hard HEAD~1` | **危险** |
| 改最后一次提交的说明 | `git commit --amend -m "新说明"` | 已推送的别用 |
| 看历史 | `git log --oneline --graph` | 安全 |

**一条铁律**：`--hard` 之前先 `git stash` 或确认真的不要了。已经 push 出去的历史不要改写（别对已推送的提交用 `--amend` 或 `reset`）。

## 八、这个仓库专属提醒

- **绝不要提交** `文献库/`、`对话记录/`——里面有 `.zotero_api_key`。已在 `.gitignore` 中挡住。
- 发新版本时，`dist/` 的 zip 不进仓库，改用 GitHub 的 **Releases** 功能上传附件。
- 当前仓库：https://github.com/311120/aviation-literature-skill
