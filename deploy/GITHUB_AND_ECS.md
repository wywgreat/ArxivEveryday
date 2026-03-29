# GitHub 和 ECS 上线指南

这份文档把本项目从本地推到 GitHub，再部署到阿里云 ECS 的最短路径整理好了。

## 1. 本地绑定 GitHub 远程仓库

先在 GitHub 网页上新建一个空仓库，例如：

- `https://github.com/<你的 GitHub 用户名>/ArxivEveryday.git`

然后在本地项目根目录执行：

```bash
git add .
git commit -m "feat: initial arxiv everyday app"
git branch -M main
git remote add origin https://github.com/<你的 GitHub 用户名>/ArxivEveryday.git
git push -u origin main
```

如果之后你已经配置过 `origin`，改成：

```bash
git remote set-url origin https://github.com/<你的 GitHub 用户名>/ArxivEveryday.git
git push -u origin main
```

如果你想偷懒，也可以直接用脚本：

```bash
bash deploy/github-publish.sh.example https://github.com/<你的 GitHub 用户名>/ArxivEveryday.git
```

## 2. ECS 首次部署

先登录你的阿里云 ECS：

```bash
ssh root@<你的 ECS 公网 IP>
```

然后执行：

```bash
sudo yum makecache
sudo yum install -y python3.11 git nginx
sudo mkdir -p /opt
cd /opt
sudo git clone https://github.com/<你的 GitHub 用户名>/ArxivEveryday.git ArxivEveryday
cd /opt/ArxivEveryday
sudo python3.11 -m venv .venv
sudo cp deploy/arxiv-everyday.env.example deploy/arxiv-everyday.env
sudo cp deploy/arxiv-everyday.service.example /etc/systemd/system/arxiv-everyday.service
sudo systemctl daemon-reload
sudo systemctl enable arxiv-everyday.service
sudo systemctl restart arxiv-everyday.service
sudo cp deploy/nginx.arxiv-everyday.conf /etc/nginx/sites-available/arxiv-everyday
sudo ln -sf /etc/nginx/sites-available/arxiv-everyday /etc/nginx/sites-enabled/arxiv-everyday
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl restart nginx
```

快速检查服务：

```bash
curl http://127.0.0.1:8000/health
systemctl status arxiv-everyday.service --no-pager
```

## 3. ECS 一键脚本版

如果你希望少敲命令，可以直接在 ECS 上执行：

```bash
bash deploy/ecs-first-deploy.sh.example https://github.com/<你的 GitHub 用户名>/ArxivEveryday.git <你的域名或公网IP>
```

比如：

```bash
bash deploy/ecs-first-deploy.sh.example https://github.com/demo-user/ArxivEveryday.git 47.96.10.10
```

## 4. 后续更新代码

你本地改完并推送到 GitHub 后，在 ECS 上执行：

```bash
cd /opt/ArxivEveryday
git pull --ff-only origin main
sudo systemctl restart arxiv-everyday.service
curl http://127.0.0.1:8000/health
```

或者直接：

```bash
bash deploy/ecs-update.sh.example
```

## 5. 公网前建议

- Alibaba Cloud Linux 3.2104 默认 `python3` 是 `Python 3.6`，而本项目部署时应使用 `Python 3.11`。
- 编辑 `/opt/ArxivEveryday/deploy/arxiv-everyday.env`，把 `ADMIN_PASSWORD` 改成强密码。
- 在阿里云安全组中放行 `80` 端口；如果后续上 HTTPS，再放行 `443`。
- 如果你有域名，建议后续补一个 HTTPS 证书。

## 6. 当前部署文件

- [`deploy/arxiv-everyday.service.example`](/Users/wangyuwei/Desktop/CodexProj/ArxivEveryday/deploy/arxiv-everyday.service.example)
- [`deploy/arxiv-everyday.env.example`](/Users/wangyuwei/Desktop/CodexProj/ArxivEveryday/deploy/arxiv-everyday.env.example)
- [`deploy/nginx.arxiv-everyday.conf`](/Users/wangyuwei/Desktop/CodexProj/ArxivEveryday/deploy/nginx.arxiv-everyday.conf)
- [`deploy/github-publish.sh.example`](/Users/wangyuwei/Desktop/CodexProj/ArxivEveryday/deploy/github-publish.sh.example)
- [`deploy/ecs-first-deploy.sh.example`](/Users/wangyuwei/Desktop/CodexProj/ArxivEveryday/deploy/ecs-first-deploy.sh.example)
- [`deploy/ecs-update.sh.example`](/Users/wangyuwei/Desktop/CodexProj/ArxivEveryday/deploy/ecs-update.sh.example)
