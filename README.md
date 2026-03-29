# Arxiv Everyday

一个本地即可运行的 arXiv 论文看板，支持：

- 登录页拦截
- 按时间窗口抓取相关主题论文
- 论文标题与摘要的中英文展示
- 收藏 / 取消收藏
- SQLite 持久化收藏与翻译缓存
- 外网受限时自动回退缓存或演示数据，方便本地联调

## 本地启动

```bash
python3 server.py
```

启动后访问：

- [http://127.0.0.1:8000/login](http://127.0.0.1:8000/login)

默认账号密码：

- 账号：`admin123`
- 密码：`admin123`

## 可选环境变量

- `HOST`
- `PORT`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `ARXIV_MAX_MATCHED`
- `ARXIV_PAGE_SIZE`
- `ARXIV_FETCH_CAP`

## ECS 上的 Python 版本提醒

如果你部署到 `Alibaba Cloud Linux 3.2104 LTS 64位`，建议使用 `Python 3.11` 而不是系统默认的 `python3`。原因是系统默认 `python3` 通常仍是 `Python 3.6`，而本项目代码使用了 `Python 3.9+` 的 `str.removeprefix()`，可参考 [server.py:810](/Users/wangyuwei/Desktop/CodexProj/ArxivEveryday/server.py#L810) 和 [server.py:830](/Users/wangyuwei/Desktop/CodexProj/ArxivEveryday/server.py#L830)。

示例：

```bash
HOST=0.0.0.0 PORT=8000 ADMIN_USERNAME=admin123 ADMIN_PASSWORD=admin123 python3 server.py
```

## 目录说明

- [`server.py`](/Users/wangyuwei/Desktop/CodexProj/ArxivEveryday/server.py)：后端服务、登录、arXiv 拉取、翻译、收藏存储
- [`static/index.html`](/Users/wangyuwei/Desktop/CodexProj/ArxivEveryday/static/index.html)：主页面
- [`static/login.html`](/Users/wangyuwei/Desktop/CodexProj/ArxivEveryday/static/login.html)：登录页
- [`static/app.js`](/Users/wangyuwei/Desktop/CodexProj/ArxivEveryday/static/app.js)：主页交互逻辑
- [`static/login.js`](/Users/wangyuwei/Desktop/CodexProj/ArxivEveryday/static/login.js)：登录逻辑
- [`static/styles.css`](/Users/wangyuwei/Desktop/CodexProj/ArxivEveryday/static/styles.css)：整体样式

## GitHub 与 ECS

GitHub 远程绑定、首次部署、后续更新命令都整理到了：

- [`deploy/GITHUB_AND_ECS.md`](/Users/wangyuwei/Desktop/CodexProj/ArxivEveryday/deploy/GITHUB_AND_ECS.md)

也提供了可直接复用的脚本和模板：

- [`deploy/github-publish.sh.example`](/Users/wangyuwei/Desktop/CodexProj/ArxivEveryday/deploy/github-publish.sh.example)
- [`deploy/ecs-first-deploy.sh.example`](/Users/wangyuwei/Desktop/CodexProj/ArxivEveryday/deploy/ecs-first-deploy.sh.example)
- [`deploy/ecs-update.sh.example`](/Users/wangyuwei/Desktop/CodexProj/ArxivEveryday/deploy/ecs-update.sh.example)
- [`deploy/arxiv-everyday.service.example`](/Users/wangyuwei/Desktop/CodexProj/ArxivEveryday/deploy/arxiv-everyday.service.example)
- [`deploy/arxiv-everyday.env.example`](/Users/wangyuwei/Desktop/CodexProj/ArxivEveryday/deploy/arxiv-everyday.env.example)
- [`deploy/nginx.arxiv-everyday.conf`](/Users/wangyuwei/Desktop/CodexProj/ArxivEveryday/deploy/nginx.arxiv-everyday.conf)

## 生产环境提示

- 你要求的 `admin123 / admin123` 已按需求内置，但公网部署前建议至少改成环境变量里的强密码。
- 当前翻译逻辑优先尝试公开在线服务。如果你的 ECS 在中国大陆，个别翻译源可能不稳定，后续可以切换成阿里云翻译或其他国内可用服务。
- 当前是单用户演示版。如果你希望未来给更多人公开体验，建议下一步再加：
  - 用户表与密码哈希
  - 分用户收藏
  - 抓取任务缓存
  - 访问限流
  - HTTPS 和域名接入
