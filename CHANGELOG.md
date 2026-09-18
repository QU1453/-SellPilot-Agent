# 变更记录（CHANGELOG）

> 约定：**只维护这一个应用，不另开版本副本**。每次改动在这里追加一段，
> 并写明「回滚到哪个提交、执行什么命令」，以便随时退回上一形态。

---

## 2026-09-18 · 桌面版 + 浅色高雅重设计

**本轮起点（回滚目标）**：`bb01e0e` —— 深色「港口仪表盘」界面 + 完整设置面板（密钥/地址/模型/温度/权限/预算）

**本轮落地提交**：`af561d4`（已推送至 origin/main）

### 一、新增：桌面应用形态

| 文件 | 作用 |
| --- | --- |
| `main.py` | 桌面入口。启动内嵌 FastAPI 服务 → 开原生窗口（pywebview）；无 GUI 后端或未装 pywebview 时自动回落默认浏览器 |
| `SellPilot.spec` | PyInstaller 打包配置，产出**单文件**可执行程序 |
| `build.py` | 一键打包脚本，构建后打印产物路径与体积 |

打包命令与产物（PyInstaller **不支持交叉编译**，需在目标平台上构建）：

```bash
python -m pip install -r requirements.txt pyinstaller
python build.py          # Windows → dist/SellPilot.exe
                         # macOS   → dist/SellPilot
                         # Linux   → dist/SellPilot
```

- 仍是**同一个应用**：`python server.py`（纯 Web）与 `python main.py`（桌面窗口）共用同一套后端与前端，没有第二份代码。
- 打包后 `config.RESOURCE_DIR` 指向解包临时目录（读 `ui/`），`config.BASE_DIR` 指向可执行文件所在目录
  —— 设置面板写入的 `.env`、运行日志 `sellpilot.log` 都落在**程序旁边**，不会随临时目录被清掉。

### 二、改动：界面改为浅色高雅风格（白瓷与细金 / Porcelain Atelier）

| 文件 | 改动 |
| --- | --- |
| `ui/style.css` | **整体重写**。暖白瓷底 `#f6f4f0` + 墨色字 + 碧玉/黄铜双信号色；发丝线与衬线标题承担层次；动效统一为「长尾减速」缓动（入场错峰、悬停位移、按钮掠光、弹窗缩放淡入），并尊重 `prefers-reduced-motion` |
| `ui/index.html` | 字体换成 Newsreader（标题衬线）/ Jost（正文）/ Noto Sans SC（中文）/ IBM Plex Mono（数据）；补 `color-scheme: light`。**所有 id / class 契约未变** |
| `ui/app.js` | 仅两处：中/日文案里的「作战台」→「工作台」；模块条目按序号错峰入场（`animation-delay`）。功能逻辑零改动 |

功能完整保留：两个板块（选品 / Listing）、11 个细分模块、模块表单 → 结构化提问 → 8 类结果卡片、
中/日双语、双板块独立会话、状态胶囊四态、设置面板六项（含 API Key 校验与连接测试）。

### 三、改动：打包相关适配

| 文件 | 改动 |
| --- | --- |
| `config.py` | 新增 `_app_dir()` / `_resource_dir()`，拆出 `BASE_DIR`（可写）与 `RESOURCE_DIR`（只读资源） |
| `server.py` | 静态资源改从 `config.RESOURCE_DIR` 挂载；`persist_env()` 写 `config.BASE_DIR/.env`（打包后写到 exe 旁） |
| `requirements.txt` | 启用 `pywebview`（桌面外壳）、新增 `pyinstaller`（打包） |

### 四、回滚方式

按粒度从大到小，任选其一：

```bash
# 1) 只退回界面外观（保留桌面版与打包能力）
git checkout bb01e0e -- ui/

# 2) 退回本轮全部已跟踪文件的改动（保留新增的 main.py / build.py / SellPilot.spec）
git checkout bb01e0e -- config.py server.py requirements.txt ui/

# 3) 连新增文件一起退回本轮起点
git checkout bb01e0e -- .
rm -f main.py build.py SellPilot.spec
```

回滚后如需重新打包，先删掉旧产物与构建缓存：

```bash
rm -rf build dist && python build.py
```

---

## 历史节点

| 提交 | 说明 |
| --- | --- |
| `bb01e0e` | 深色「港口仪表盘」界面 + 完整运行时设置面板（本轮回滚目标） |
| `ed57e4c` | 智能体项目配置与 Git 安全 |
| `9c14866` | 品牌重塑 ECCS → SellPilot（仓库更名 SellPilot_Agent） |
