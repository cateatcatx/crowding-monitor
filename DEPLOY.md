# 免费发布到互联网 (GitHub Pages + Actions)

网站会被托管在 GitHub 的服务器上, **不依赖你的电脑开机**。每日北京时间约09:17、13:47检查更新，工作日19:30加跑。免费, 无需买域名。

最终网址形如: `https://<你的GitHub用户名>.github.io/<仓库名>/`

## 原理

- `build_static.py` 在 GitHub 的服务器上跑数据管线(拉新浪/Naver/CBOE → 算分 → 生成 `dashboard.json`), 连同网页一起发布到 GitHub Pages。
- `.github/workflows/deploy.yml` 定时触发(北京时间约 09:17 / 13:47 / 工作日19:30), 也可在Actions网页上手动触发。晚间更新安排在NXT收盘后, 并用ALL/KRX/NXT逐市场新鲜度校验确认数据已落地。
- Forward P/E先独立抓图、OCR校准并反推曲线，每张图最多重试3次；数据与状态提交至main的 `data/FORWARD_PE.json`，不依赖易淘汰的Actions缓存。工作流需要 `contents: write`，只写该公开数据文件。失败时保留旧数据、发布告警并将Actions标为失败；下次调度继续重试。
- 页面前端优先读构建好的 `dashboard.json`(静态); 在你本机用 `server.py` 打开时仍走实时接口, 两种模式同一份 `index.html`。

## 一次性设置(约 5 分钟)

### 1. 建一个 GitHub 仓库
在 https://github.com/new 新建仓库(**Public 公开**, 免费版 Pages 要求公开; 名字随意, 例如 `crowding-monitor`)。不要勾选任何初始化文件。

### 2. 把本目录推上去
在本目录 `d:\investment\crowding_monitor` 打开终端(PowerShell), 依次执行(把 URL 换成你的仓库):

```powershell
git init
git add .
git commit -m "AI硬件拥挤度看板"
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

> 注意: 只推这个 `crowding_monitor` 目录, **不要**把整个 `d:\investment` 传上去(里面有几百 MB 的数据库和无关文件)。本目录已带 `.gitignore`。

### 3. 打开 Pages 的 Actions 部署方式
仓库页面 → **Settings** → 左侧 **Pages** → "Build and deployment" 的 **Source** 选 **GitHub Actions**(不是 Deploy from a branch)。

### 4. 触发首次构建
- 推送后工作流会自动跑一次; 或到 **Actions** 标签页 → 选 "build-and-deploy" → **Run workflow**。
- 跑完(约 2-4 分钟)后, 访问 `https://<用户名>.github.io/<仓库名>/` 即可。手机浏览器加书签就能随时看。

## 日常

- 每日约09:17、13:47(北京)自动重建，工作日19:30加跑。GitHub定时调度可能延迟，休市或数据源未发布时保留实际源日期。
- 想立即更新: Actions 页面点 "Run workflow"; 或本机运行 `python build_static.py` 后 `git commit`/`push`(会触发重建)。
- 网页上的"刷新页面"按钮只是重新加载当前已发布的数据。

## 说明与局限

- 数据源(新浪美股 / Naver 韩股 / CBOE 期权)在 GitHub 美国服务器上抓取。SK海力士外资历史会通过 Actions 缓存保留最近一次成功结果; 若缓存不可用, 再回退到仓库种子数据。页面顶部会显示抓取提示, 不会中断主看板发布。
- 因此建议保留 `data/*.csv`、`out/*.csv`、`out/options_snapshot.json` 作为种子数据(已在 git 跟踪中)。
- 免费版 Pages 要求仓库公开; 本项目不含任何密钥或账号信息。
- 本地预览静态版: `python build_static.py --no-fetch` 后, `cd site && python -m http.server 8080`, 浏览器开 http://127.0.0.1:8080/ 。
