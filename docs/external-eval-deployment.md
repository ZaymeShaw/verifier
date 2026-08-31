# 远程评测接入（外网 verifier + 本机 API）

评测机：`154.9.252.35`。verifier 跑在这台机器上；你的业务 API 跑在本机。
使用者本机**零安装**，只要系统自带的 `ssh` 和浏览器。

- **要评测**：看第一章，三步。
- **想知道为什么、或负责部署**：看第二章。

---

# 第一章 远程用户接入指南

本章「你」= 要测自己 API 的远程用户。评测机上的账号、sshd、公钥名单都不是你改的。

你日常只做三件事：建隧道、在页面上配 API（可顺带传资料）、评测。
部署、judge、服务器密钥、往机器上加公钥，都不是你的事。

本章整条流程**专指 `llm_probe` 项目**（远程评测的主路径）。`llm_probe` 适用于**任意单轮 HTTP JSON API 评测**：不管接口做什么业务，给出请求体和能力描述就能当黑盒评。默认非流式；接口是**伪流式**（SSE 但最后一帧是全量内容）时，在 capability 预设的响应模式里选「SSE 取最后一帧」即可。不支持多轮对话，也不支持帧是增量、要逐帧累加的真流式。
页面里其他项目（client_search、QA 等）是内置业务项目，各有自己的字段合同，不适用本章的填法。

## 开通一次（每人一次，不是每次评测）

新用户**不能自己**把公钥写进服务器。分两边：

| 谁 | 做什么 | 做几次 |
|---|---|---|
| 远程用户 | 把本机 **公钥**（一行文本）发给评测机管理员；告诉管理员本机 API 端口 | 每人一次 |
| 评测机管理员 | 把这行公钥追加到服务器 `eval-tunnel` 的 `authorized_keys`，并告诉用户分到的隧道口（15001 / 15002 / …） | 每来一个新人做一次 |

用户侧没有公钥时，本机生成再发出去（只发 `.pub`，**不要发没有 `.pub` 后缀的私钥**）：

```bash
# 没有密钥才跑这一行
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

管理员开通完成后，用户才有第一章后面的 ssh 命令可用。日常评测不再碰公钥。

前置检查：本机 API 已经能在本机端口访问；管理员已经开通你的公钥，并告诉你隧道口。

## 1. 建隧道

本机开一个终端，保持开着：

```bash
ssh -N -o ServerAliveInterval=30 \
    -R 15001:127.0.0.1:8000 \
    -L 18080:127.0.0.1:8022 \
    eval-tunnel@154.9.252.35
```

| 你可能要改的 | 含义 |
|---|---|
| 右边 `8000` | 本机 API 端口。不是 8000 就改成实际端口 |
| 左边 `15001` | 评测机上分给你的隧道口。多人共用时每人一个：15001 / 15002 / 15003 |
| 左边 `18080` | 本机浏览器端口，被占用就换一个空闲端口 |

这条命令同时做两件事：把本机 API 搬到评测机 `127.0.0.1:15001`，把评测页面搬回本机 `localhost:18080`。

浏览器打开：

- 首页：http://localhost:18080/frontend/index.html
- 资料管理：http://localhost:18080/frontend/materials.html
- Live（单条）：http://localhost:18080/frontend/live.html
- 归因总结（批量）：http://localhost:18080/frontend/summary.html

默认项目是 `llm_probe`。评测期间不要关隧道终端；断了重跑同一条命令即可。

## 2. 配置 API（上传资料）

打开「资料管理」，确认项目是 `llm_probe`。

### 2.1 建 capability 预设（必做）

「capability 预设」→ 新建，填：

1. **预设名**：小写，如 `my-api`。之后 case 用 `capability_ref` 引用它。
2. **探测端点 service.url**：**必须写评测机视角**  
   `http://127.0.0.1:15001/你的接口路径`  
   （`15001` 换成你的隧道口；**不要**写成你本机的 `8000`。）  
   method 一般 `POST`，超时按接口耗时留足（例如 60～120 秒）。  
   响应模式默认「非流式 JSON」；接口回 SSE 但**最后一帧是全量内容**（伪流式）时选「SSE 取最后一帧」。帧是增量、要逐帧累加的真流式不支持。
3. **能力描述**（judge 轴1）：用用户视角写这个接口办成什么事、交付物被谁怎么用、什么算办成。几行即可，不要写「输出某种 JSON 结构」。
4. **能力边界**（选填，轴2）：能做什么 / 不能做什么，陈述句。不填则轴2会「说不清」。
5. **mock_body**（选填）：造 case 时的请求体模板，用 `{query}` 占位。

保存后即存即用，数据在评测机上，不会被下次代码部署覆盖。

### 2.2 上传资料（选做，评测更准）

接口有字段表、规则、说明时：

1. 「自由资料」→ 新建，粘贴或上传 `.md` / `.txt` / `.yaml` / `.json`；
2. 复制 `{material://llm_probe/<资料id>}`；
3. 在能力描述或能力边界里插入这条引用。

大表（几十万字）可以整份上传后只在**能力边界**里引用。

## 3. 评测

### 单条：Live

打开 Live 页，项目 `llm_probe`。信封最小形状：

```json
{
  "capability_ref": "my-api",
  "body": { "user_text": "你的测试问句" }
}
```

`body` 按你接口真实字段填（有 `mock_body` 的按模板改）。点「请求业务服务」再「请求 Judge」，或直接「统一全链路」。

### 批量：归因总结

评你自己的 API 要**上传自己的数据集**：一个 `.json` 文件（或直接粘贴同样内容的文本），
内容是一个 **case 数组**——你想测的每个问句/请求占一条。通过「上传/导入用例 JSON」
选文件或粘贴 →「导入候选区」→ 勾选 →「批量运行」。
（「加载 Mock 数据集」加载的是仓库内置的示例用例，打的是内置业务服务，不是你的 API；只用来看样例。）

数据集长这样（两条 case 的例子）。**以下填法是 `llm_probe` 专属的**：

```json
[
  {
    "id": "my-api-case-1",
    "project_id": "llm_probe",
    "scenario": "my-api",
    "intent": null,
    "live_request": {
      "capability_ref": "my-api",
      "body": { "user_text": "测试问句1" }
    },
    "output": null,
    "reference": null
  },
  {
    "id": "my-api-case-2",
    "project_id": "llm_probe",
    "scenario": "my-api",
    "intent": null,
    "live_request": {
      "capability_ref": "my-api",
      "body": { "user_text": "测试问句2" }
    },
    "output": null,
    "reference": null
  }
]
```

- **`live_request` 就是这条 case 实际要发给你 API 的那次 HTTP 调用**：`body` 是你接口的请求体（字段照你接口的真实入参写，不是 verifier 的格式）；`capability_ref` 指向你建的预设，端点和能力口径都从预设来。也可以不建预设，直接在 `live_request` 里写 `url` / `method` / `capability`。
- 在 `llm_probe` 下，其余字段是信封样板：`id` 每条唯一；`project_id` 固定 `llm_probe`；`scenario` 建议填预设名（只影响页面按场景筛选）；`intent` / `output` / `reference` 固定 `null`。
- 七个字段都要在，少一个导入会报「不是 VNext MockCase」。

准备数据集时通常就是：把上面模板复制 N 份，每份换 `id` 和 `body` 里的问句。

> 这份七字段信封是所有项目通用的 case 协议，但**各字段怎么填因项目而异**。
> 上面的 null 样板只适用于 `llm_probe`；用其他项目（如 QA 要给 `reference` 金标、
> 多轮项目要给 `intent`）时按该项目的合同填，不要照抄这份模板。

跑完一批可在「用例池库」起个名字保存，下次直接加载，不用重新导。

看结果时：

- 轴1：办成了没有（fulfilled / not_fulfilled）；
- 轴2：没办成时是「做错了 / 做不了 / 说不清」。

### 常见卡点

| 现象 | 先查 |
|---|---|
| 浏览器打不开 18080 | 隧道终端是否还在；本机端口是否被占用 |
| 业务请求失败 / 连不上 | 本机 API 是否在听；`-R` 右边端口是否真是 API 端口；capability 的 url 是否写成了 `15001` 而不是本机 `8000` |
| 轴2 全是「说不清」 | 能力边界没填 |
| 业务自己返回失败码（如「解析失败」） | 是被测服务的问题，不是隧道或 verifier 信封 |

---

# 第二章 原理与部署记录

给要看机制的人，以及部署/更新代码时用。使用者评测不必往下读。

## 拓扑

```
使用者本机                                评测机 154.9.252.35
┌──────────────────────┐                ┌──────────────────────────────┐
│ 业务系统 127.0.0.1:8000 │                │ verifier  127.0.0.1:8022      │
│ 浏览器 → localhost:18080│ ←── ssh ────→ │ 隧道口    127.0.0.1:15001     │
└──────────────────────┘   一条长连接    │ sshd     0.0.0.0:22          │
                                        └──────────────────────────────┘
```

一条 ssh 同时两个方向：

- `-R`：业务系统被搬到服务器 `127.0.0.1:15001`，verifier 像调本机一样调它；
- `-L`：verifier 前端被搬到使用者 `localhost:18080`。

verifier 与隧道口都只绑 loopback，**服务器没有对公网暴露的 HTTP 端口**，因此现阶段不给 verifier 加页面鉴权。

评测主路径是 **`llm_probe`**：任意单轮 HTTP JSON 接口（非流式，或声明了 last-frame 的伪流式 SSE），按 capability 描述 + 可选资料做 judge。前端默认项目已是 `llm_probe`。内置业务项目若也要从本机打到评测机，端口习惯是：

| 本机服务 | 本机端口 | 评测机隧道口 |
|---|---|---|
| 一般自有 API / client_search | 8000 | 15001 |
| policy_search | 8050 | 15002 |
| 营销意图 | 9006 | 15003 |

capability 里的 service URL 永远是评测机视角：`http://127.0.0.1:1500X/...`。

## 为什么评测代码不用为隧道改

- 真实请求唯一出口是 `impl/core/live_transport.py` 的 `LiveTransport`。llm_probe 的 `resolve_http` 只校验 http/https；信封接受任意 URL，填 `http://127.0.0.1:15001/...` 即走隧道。
- 前端全部同源相对路径，挂在 `/frontend`，经 `-L` 访问没有写死公网地址。
- `impl/config.yaml` 的 server 默认绑 `127.0.0.1:8022`，远程实例保持这个绑定，不要改成 `0.0.0.0`。
- judge / attribute 走 OpenAI 兼容端点（服务器 `.env` 的 `LLM_BASE_URL`），与隧道无关。
- 资料和 capability 预设落在服务器 `impl/data/<project>/`，经页面 API 读写；远程用户不能（也不该）ssh 进机器改文件。

## llm_probe 在评什么（和页面字段的关系）

- **轴1（能力描述）**：系统定位三问——用户拿它办什么事（用户视角，不要写实现视角）；交付物被谁怎么消费；什么算办成。judge 按消费方语义推演，不是做输出形状比对。
- **轴2（能力边界）**：能做 / 不能做。未达成时归位「做错了 / 做不了 / 说不清」。空边界 → 说不清。大资料用 `{material://llm_probe/<id>}`，超预算走检索工具，引用带行号。
- **show_schema**：可选，是 live 信封上的 judge 焦点，**不是 mock 场景字段**。不要往 mock 数据里塞。
- **scenario**：mock 按被探测能力分桶，与 `capability_ref` 同名。

## 当前部署实例（2026-08-31）

- 服务器：`154.9.252.35`（Debian 11，与其它服务共存）
- 代码：`/opt/verifier`，Python 3.11 venv 于 `/opt/verifier/venv`
- 服务：`systemctl {status,restart} verifier`（开机自启，绑 `127.0.0.1:8022`）
- 隧道账号：`eval-tunnel`（密钥登录，不能开 shell）
- 使用者入口：第一章的 ssh 命令；浏览器 `http://localhost:18080`

## 服务器侧一次性准备

### 部署 verifier

```bash
python3.11 -m venv ~/verifier-venv && source ~/verifier-venv/bin/activate
pip install -r requirements.txt
```

`.env` 最小配置（对照 `impl/config.yaml` 的 environment 节）：

```
DEEPSEEK_API_KEY=...            # 或所用网关的 key
LLM_BASE_URL=...                # judge 用的 OpenAI 兼容端点，须从该服务器可达
LLM_MODEL=...
EMBEDDING_ENABLED=false         # 或配 BAILIAN_API_KEY
```

部署时必须验证：当前 `.env` 的 LLM 网关从这台服务器可达。不可达就换公网可达端点。

```bash
bash run.sh config-check
curl -s $LLM_BASE_URL/models -H "Authorization: Bearer $KEY" | head
```

启动（保持 127.0.0.1，不要 0.0.0.0）：

```bash
bash run.sh server
```

生产实例用 systemd，不要用临时前台进程冒充。

### 隧道账号与 sshd

```bash
sudo useradd -m -s /usr/sbin/nologin eval-tunnel
sudo passwd eval-tunnel        # 或只配 authorized_keys，推荐密钥
```

`/etc/ssh/sshd_config` 追加后 `sudo systemctl reload sshd`：

```
Match User eval-tunnel
    AllowTcpForwarding yes
    PermitListen 15001 15002 15003
    PermitOpen 127.0.0.1:8022
    PermitTTY no
    X11Forwarding no
    AllowAgentForwarding no
    ForceCommand /bin/false
```

要点：该账号不能开 shell；`PermitListen` 限死反向隧道端口；`PermitOpen` 限死正向转发只能到 verifier；sshd 默认 `GatewayPorts no`，`-R` 只绑 loopback。若出站 22 被拦，sshd 可追加听 443。

### 开通一个新远程用户（评测机管理员做）

这是**评测机负责人**的开通动作，不是远程用户自己做的，也不是每次评测都做。`eval-tunnel` 账号和 sshd 规则只建一次；之后每来一个人只做下面几步。

1. 向对方要一行公钥（`cat ~/.ssh/id_ed25519.pub` 或 `id_rsa.pub` 的输出），以及本机 API 端口。
2. 在评测机上追加（把引号里换成对方那一行）：

```bash
sudo mkdir -p ~eval-tunnel/.ssh
echo 'ssh-ed25519 AAAA... comment' | sudo tee -a ~eval-tunnel/.ssh/authorized_keys
sudo chown -R eval-tunnel:eval-tunnel ~eval-tunnel/.ssh
sudo chmod 700 ~eval-tunnel/.ssh
sudo chmod 600 ~eval-tunnel/.ssh/authorized_keys
```

3. 从 `PermitListen` 里分一个空闲口（15001 / 15002 / 15003），把口告诉对方，让对方改第一章 ssh 命令里的 `-R 1500X`。口不够就先改 `PermitListen` 再 `sudo systemctl reload sshd`。
4. 不要把 root 或 `eval-tunnel` 的密码发给远程用户；他们只用自己的私钥连 `eval-tunnel@154.9.252.35`。

## 更新代码

`impl/data/` 里的资料（capability 预设、自由资料、mock、case 池）大约数 MB，**随代码一起部署**。评测机上的探测 URL（`1500X`）部署脚本会写回，不会被本机的 `8000` 盖掉。仍排除：`.env`、本地评测痕迹 `context_store` / `context_runtime`。槽位声明在 `impl/projects/<id>/materials.yaml`，随代码走。rsync 不用 `--delete`，评测机上多出来的文件会留着。

```bash
scripts/deploy_verifier.sh root@154.9.252.35            # 部署到 /opt/verifier 并重启
scripts/deploy_verifier.sh root@154.9.252.35 /opt/verifier --dry-run
scripts/deploy_verifier.sh root@154.9.252.35 --no-restart
```

脚本排除 `.env`、本地评测痕迹 `impl/data/context_store` / `context_runtime`、报告与笔记、调查循环历史（`.state`）、`.DS_Store` / `__pycache__` 等。
`impl/data` 里的资料、以及 `.agents` / `.claude` / `.codex` / `.github`、`search-test-case` / `demand` / `hooks` / `agents` / 仓库根 `data/` **会同步**。
`--dry-run` 按 checksum 比较，不因 git checkout 的 mtime 列出整包。
排除项已锚定仓库根：不锚定的 `--exclude experiments` 会误伤调查包里的 `experiments/`。

## 同步资料（部署者 / AI，不是远程用户日常操作）

远程用户日常用页面上传即可。下面是本机物化后推到评测机的通道：

```bash
scripts/sync_materials.sh --host root@154.9.252.35 --project client_search --ids field_glossary

bash run.sh cli materialize --project client_search --role judge --apply \
    | scripts/sync_materials.sh --host root@154.9.252.35 --project client_search --from-materialize-json -

scripts/sync_materials.sh --host root@154.9.252.35 --project client_search --all-free

bash run.sh cli materialize --project client_search --role judge --apply --push root@154.9.252.35:/opt/verifier
```

物化必须在**有业务仓库的机器**上执行。远程评测机不承诺源码级调查。
不要把调查快照写入 `field_glossary` 或 `roles: [judge]` 槽位——会撑爆 binding 预算。

Windows 上跑部署/同步脚本请用 WSL（依赖 bash/rsync/ssh）。

## 多人共用

每人固定一个隧道口（15001/15002/15003，须在 `PermitListen` 里）。capability / case 各写各的端口。
当前是单实例共用一个 verifier，case pool 不隔离，适合小团队。要隔离再考虑每人一实例。

## 谁做什么

| 阶段 | 远程用户 | 评测机管理员 |
|---|---|---|
| 日常评测 | 起本机 API；隧道；资料页配 capability；Live / 总结页跑 | 无（不碰公钥） |
| 首次开通 | 生成本机密钥（若无）；把 `.pub` 发给管理员；说本机 API 端口 | 追加 `authorized_keys`；分配 1500X；把隧道口告诉用户 |
| 更新评测代码 | 无 | `scripts/deploy_verifier.sh`（含 impl/data 资料；排除 .env 和 context 痕迹） |
| 业务源码更新后刷新调查资料 | 说一声即可 | baseline → drift → increment → materialize → sync |

备份：改版前原文在 `docs/bak/2026-08-31-external-eval-deployment.md`。
