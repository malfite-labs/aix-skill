# AIX Skill 强制公开发布规则

生效：2026-10-16。适用于此后每一次 Skill 版本升级，包括补丁版本。本文件是发布流程的强制门禁；历史预检或单项工具成功不能豁免。本轮只更新规范，不执行部署、Tag/Release 创建或公开包发布。

## 五处同步，缺一不可

1. **aix-protocol Skill 源码**：冻结版本及完整构建输入提交，保留必要兼容性验证。
2. **公开 malfite-labs/aix-skill 仓库**：同步真实源码及完整包文件映射，提供可匿名读取的不可变提交。
3. **GitHub Tag 与正式 Release**：版本 Tag 必须指向已核验的公开源码提交；正式 Release 必须附上冻结 ZIP、SHA256 和对应溯源记录。
4. **skill.aixprotocol.org 下载包及版本清单**：官网使用同一冻结 ZIP，首页、安装入口、manifest 和下载 URL 指向同一发行版本。
5. **README、CHANGELOG、安装文档**：中英文当前版本、Build ID、下载地址、源码链接、更新步骤和兼容说明同步；不能仍将历史版本称为当前版本。缺失 CHANGELOG 时补齐对应版本记录。

## 强制检查项与证据

| 检查项 | 必须保留的实际证据 |
| --- | --- |
| 公开源码与发行包逐文件一致 | 完整 ZIP 文件清单、每个成员 SHA256、固定公开 Git 提交的真实 blob/匿名源码归档对照结果；包括生成的元数据与校验文件，不能只检查源码子集 |
| GitHub Tag 对应正确源码提交 | 从 GitHub 实际读取的 Tag 指向；注解 Tag 核对解引用后的完整 commit SHA；该提交所有包文件与冻结 ZIP 相同 |
| Release ZIP 与官网 ZIP SHA256 一致 | 两个入口实际下载的 ZIP、各自 URL、HTTP 结果和 SHA256；两者还必须等于批准的冻结哈希，不能只互相相等 |
| Build ID、版本号、源码提交对应关系一致 | manifest、包内 VERSION、发行记录、Tag/Release、README/安装入口的核对记录；原始构建提交与公开镜像提交可不同，但必须明确区分，并有完整字节映射证明，不能声称为同一提交 |
| 无敏感凭据或内部文件泄露 | 包与待公开 Git 差异的安全扫描、精确文件白名单及人工检查；排除私钥、Token、Agent 凭据、数据库、真实交易资料、内部部署配置和缓存二进制；测试不得使用真实身份状态 |
| 真实 ZIP 干净安装 | 在临时隔离目录/新进程安装实际发行 ZIP，验证版本、依赖闭包、导入与必要行为；不得新建真实身份、修改原凭据或删除用户既有文件 |

## 失败关闭规则

- 每项结果仅可为 PASS、FAIL 或 NOT_RUN；证据缺失、不可访问、超时或无法判断均不得算作 PASS。
- 任意一项不是 PASS：`RELEASE_BLOCKED=YES`，不得开放新版本下载、切换官网当前版本、宣称发布完成或继续后续公开发布阶段。
- 只有全部强制检查通过且本轮有明确发布授权，才可继续发布。技术就绪与发布授权分别记录；源码合并不等于发行完成。
- 不得仅修改 README/manifest 制造溯源声明；不得重新打包不同 ZIP 冒充冻结包；不得移动已发布 Tag 或覆盖不可变版本文件以隐藏错误。

## 最小执行顺序

1. 更新并冻结协议仓库 Skill 源码、版本说明与 README/CHANGELOG/安装文档；生成并批准唯一候选 ZIP，记录 Build ID 和冻结 SHA256。
2. 同步公开仓库，在不可变提交上逐文件比对；执行安全扫描、干净安装和独立 Review。公开源码提交必须真实可读。
3. 在明确发行授权下，准备正确源码指向的版本 Tag 和尚未公开的 Release/分发暂存资产；对 GitHub 待发行资产与官网待切换资产实际下载验哈希，检查全部元数据和文档。任何预检失败则停止，不开放新版本。
4. 全部预检 PASS 后，才发布正式 GitHub Release 并切换官网同一冻结包。两处非原子操作必须记录进度；失败时停止后续阶段，保留原可用官网入口，不得伪报发布完成。
5. 发布后再次从真实公开 GitHub Release 和官网入口分别下载、验哈希、干净安装，并复核源码/Tag。任一失败立即置 `RELEASE_BLOCKED=YES`，停止推广和后续发布，保留故障证据并按兼容回滚方案处理。
6. 更新最终发布记录、codex.md 与交接文档。不得通过恢复旧账本覆盖后续交易；Skill 发布不得暗含 Production 或 Genesis 修改权限。

## 每版发布记录模板

```text
SKILL_VERSION =
BUILD_ID =
PROTOCOL_SOURCE_COMMIT =
PUBLIC_SOURCE_COMMIT =
SOURCE_FILE_COUNT =
SOURCE_FILES_MATCH = NOT_RUN
GITHUB_TAG =
TAG_TARGET_COMMIT =
TAG_SOURCE_MATCH = NOT_RUN
GITHUB_RELEASE_URL =
GITHUB_RELEASE_ZIP_SHA256 =
WEBSITE_ZIP_URL =
WEBSITE_ZIP_SHA256 =
FROZEN_ZIP_SHA256 =
RELEASE_WEBSITE_HASH_MATCH = NOT_RUN
METADATA_MATCH = NOT_RUN
README_CHANGELOG_INSTALL_DOCS = NOT_RUN
SECURITY_SCAN = NOT_RUN
CLEAN_INSTALL = NOT_RUN
INDEPENDENT_REVIEW = NOT_RUN
PUBLIC_DOWNLOAD_VERIFICATION = NOT_RUN
RELEASE_AUTHORIZED = NO
RELEASE_BLOCKED = YES
EVIDENCE_LOCATION =
```

模板未填写的默认值不是本轮现场检查结论；不得把本次规范更新当作一次发行验收。发布人员应分开记录预检和公开复验结果。

## Rule / Checklist / Anti-pattern

Rule：每个版本必须完成五处同步，冻结字节、真实公开源码和实际下载证据共同构成发布依据。
Checklist：源码、Tag、正式 Release、官网包/清单、README/CHANGELOG/安装文档、全部成员哈希、敏感扫描、干净安装和公开复验。
Anti-pattern：官网先升级而公开仓库/Release 缺失、仅看本地包或 manifest、将无结果算 PASS、不同构建复用版本身份、改冻结包或盲目重试不确定的发布操作。
