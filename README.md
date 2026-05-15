# 微博搜索爬虫 GUI

基于 [dataabc/weibo-search](https://github.com/dataabc/weibo-search) 二次开发，为其添加了图形界面，让不熟悉代码的用户也能轻松使用。

## 功能

- 图形界面操作，无需编辑代码或使用命令行
- 支持 Windows（.exe）和 macOS（.app）双平台，双击即用
- 连续获取一个或多个**微博关键词搜索**结果
- 支持指定搜索时间范围、微博类型、内容类型、地区筛选
- 多种输出格式：CSV、MySQL、MongoDB、SQLite
- 支持下载微博中的图片和视频
- 自定义保存路径
- 配置自动保存，下次打开自动恢复

## 下载使用

从 [Releases](../../releases) 页面下载对应系统的版本：

| 系统 | 文件 | 说明 |
|------|------|------|
| Windows | `微博搜索爬虫.exe` | 双击运行，无需安装 |
| macOS | `微博搜索爬虫.app` | 双击运行，首次需右键→打开 |

### 获取 Cookie

1. 用浏览器登录 [weibo.com](https://weibo.com)
2. 按 `F12` 打开开发者工具
3. 切换到「网络」(Network) 标签
4. 刷新页面，点击任意一个请求
5. 在请求头 (Request Headers) 中找到 `Cookie`，整行复制
6. 粘贴到程序的 Cookie 输入框中

### 操作步骤

1. 粘贴 Cookie
2. 填写关键词（每行一个）
3. 选择日期范围、微博类型等筛选条件
4. 选择输出格式和保存路径
5. 点击「保存配置」确认参数无误
6. 点击「开始爬取」

结果文件默认保存在程序所在目录的 `结果文件/` 文件夹下。

## 从源码运行

```bash
# 克隆项目
git clone https://github.com/你的用户名/weibo-search-gui.git
cd weibo-search-gui

# 安装依赖
pip install -r requirements.txt

# 启动 GUI
python gui.py
```

### 依赖

- Python 3.8+
- scrapy
- PyQt5
- Pillow

## 打包为可执行文件

```bash
# Windows
python build_exe.py

# macOS
python3 build_mac.py
```

打包完成后，可执行文件在 `dist/` 目录下。

## 输出字段

| 字段 | 说明 |
|------|------|
| 微博id | 微博的数字id |
| 微博bid | 微博的bid |
| 用户昵称 | 发布者昵称 |
| 微博正文 | 微博内容 |
| 头条文章url | 头条文章链接 |
| 发布位置 | 位置信息 |
| 艾特用户 | @的用户 |
| 话题 | #话题# |
| 转发数 / 评论数 / 点赞数 | 互动数据 |
| 发布时间 | 发布时间 |
| 发布工具 | 如iPhone客户端等 |
| 微博图片url | 图片链接 |
| 微博视频url | 视频链接 |
| retweet_id | 转发微博的原微博id |
| ip | 发布ip |
| user_authentication | 用户类型：蓝v/黄v/红v/金v/普通用户 |
| 会员类型 / 会员等级 | 微博会员信息 |

## 致谢

本项目基于 [dataabc/weibo-search](https://github.com/dataabc/weibo-search) 开发，感谢原作者的贡献。
