# Mini Program One-Click Publish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the WeChat Mini Program page into an editor-focused workflow where operators enter facts, generate a publishable draft, and copy only the title/lead/body with one click.

**Architecture:** Keep the existing single-page mini program and existing backend APIs. Refactor `miniprogram/pages/index/` so JavaScript owns derived state for settings summary and publish draft, WXML separates input/result/auxiliary/history areas, and WXSS provides the updated editor-workbench visual hierarchy.

**Tech Stack:** WeChat Mini Program WXML/WXSS/JavaScript, existing `wx.request`, existing `/api/toutiao-packages` and `/api/generations` APIs, `node -c` syntax validation.

---

## File Structure

- Modify `miniprogram/pages/index/index.js`
  - Add UI state for advanced settings and publish draft.
  - Add setting summary derivation.
  - Replace broad article copy with safe publish-draft copy.
  - Add body-only copy.
  - Scroll to result after generation.
  - Keep existing API payloads, health check, image polling, and history behavior.

- Modify `miniprogram/pages/index/index.wxml`
  - Reorder the page into top status, input card, result card, auxiliary result blocks, and history.
  - Move angle, audience, type, length, cover style, and image switch into an advanced settings panel.
  - Add the “复制发布稿” primary result action.

- Modify `miniprogram/pages/index/index.wxss`
  - Update layout, chips, advanced settings, publish preview, result actions, auxiliary cards, and history styling.
  - Preserve the current light tool style and teal primary color.

No backend files are modified.

---

### Task 1: Refactor Mini Program Page State and Copy Logic

**Files:**
- Modify: `miniprogram/pages/index/index.js`

- [ ] **Step 1: Replace `index.js` with the refactored page logic**

Replace the full contents of `miniprogram/pages/index/index.js` with:

```javascript
const app = getApp();

const ARTICLE_STYLES = [
  { label: "资讯快讯", value: "news" },
  { label: "深度解读", value: "analysis" },
  { label: "本地民生", value: "local" },
  { label: "科技数码", value: "technology" },
  { label: "消费服务", value: "consumer" },
  { label: "故事叙述", value: "story" }
];

const LENGTHS = [
  { label: "短图文", value: "short" },
  { label: "标准", value: "standard" },
  { label: "长解读", value: "long" }
];

const COVER_STYLES = [
  { label: "新闻编辑", value: "editorial" },
  { label: "真实摄影", value: "realistic" },
  { label: "科技产品", value: "tech" },
  { label: "本地生活", value: "local" },
  { label: "数据图解", value: "data" }
];

const JOB_STATUS = {
  pending: "排队中",
  running: "生成中",
  succeeded: "已完成",
  failed: "失败"
};

Page({
  data: {
    healthText: "连接中",
    healthOk: false,
    topic: "",
    facts: "",
    angle: "",
    audience: "今日头条普通读者",
    articleStyles: ARTICLE_STYLES.map((item) => item.label),
    articleStyleIndex: 0,
    articleStyleLabel: ARTICLE_STYLES[0].label,
    lengths: LENGTHS.map((item) => item.label),
    lengthIndex: 1,
    lengthLabel: LENGTHS[1].label,
    coverStyles: COVER_STYLES.map((item) => item.label),
    coverStyleIndex: 0,
    coverStyleLabel: COVER_STYLES[0].label,
    includeImage: true,
    advancedOpen: false,
    settingSummary: buildSettingSummary(0, 1, true),
    creating: false,
    error: "",
    result: null,
    bodyParagraphs: [],
    publishDraft: "",
    imageJob: null,
    imageUrl: "",
    jobStatusText: "",
    recentJobs: []
  },

  onLoad() {
    this.loadHealth();
    this.loadHistory();
  },

  onUnload() {
    this.stopPolling();
  },

  loadHealth() {
    this.request("/api/health")
      .then((health) => {
        this.setData({
          healthText: health.provider && health.provider.has_api_key ? "服务器已连接" : "服务器待配置",
          healthOk: Boolean(health.provider && health.provider.has_api_key)
        });
      })
      .catch(() => {
        this.setData({ healthText: "服务器连接失败", healthOk: false });
      });
  },

  bindInput(event) {
    this.setData({ [event.currentTarget.dataset.field]: event.detail.value });
  },

  toggleAdvanced() {
    this.setData({ advancedOpen: !this.data.advancedOpen });
  },

  changeArticleStyle(event) {
    const articleStyleIndex = Number(event.detail.value || 0);
    this.setData({
      articleStyleIndex,
      articleStyleLabel: ARTICLE_STYLES[articleStyleIndex].label,
      settingSummary: buildSettingSummary(articleStyleIndex, this.data.lengthIndex, this.data.includeImage)
    });
  },

  changeLength(event) {
    const lengthIndex = Number(event.detail.value || 0);
    this.setData({
      lengthIndex,
      lengthLabel: LENGTHS[lengthIndex].label,
      settingSummary: buildSettingSummary(this.data.articleStyleIndex, lengthIndex, this.data.includeImage)
    });
  },

  changeCoverStyle(event) {
    const coverStyleIndex = Number(event.detail.value || 0);
    this.setData({ coverStyleIndex, coverStyleLabel: COVER_STYLES[coverStyleIndex].label });
  },

  toggleImage(event) {
    const includeImage = event.detail.value;
    this.setData({
      includeImage,
      settingSummary: buildSettingSummary(this.data.articleStyleIndex, this.data.lengthIndex, includeImage)
    });
  },

  useDemo() {
    this.setData({
      topic: "新能源车充电体验升级",
      facts: "某城市近期新增一批公共快充站，覆盖商圈、社区和高速服务区。车主反馈排队时间有所缩短，但部分老旧小区夜间充电仍不方便。官方称后续会继续优化站点布局。",
      angle: "从普通车主的充电便利性切入，说明新设施带来的变化和仍需解决的问题。",
      audience: "关注出行和新能源汽车的头条读者"
    });
  },

  createPackage() {
    const topic = this.data.topic.trim();
    const facts = this.data.facts.trim();
    if (topic.length < 2) {
      this.setData({ error: "请先填写选题，至少 2 个字。" });
      return;
    }
    if (facts.length < 10) {
      this.setData({ error: "请填写可核验事实，至少 10 个字。" });
      return;
    }

    this.stopPolling();
    this.setData({
      creating: true,
      error: "",
      result: null,
      bodyParagraphs: [],
      publishDraft: "",
      imageJob: null,
      imageUrl: "",
      jobStatusText: ""
    });

    this.request("/api/toutiao-packages", {
      method: "POST",
      data: {
        topic,
        facts,
        angle: this.data.angle.trim(),
        audience: this.data.audience.trim() || "今日头条普通读者",
        article_style: ARTICLE_STYLES[this.data.articleStyleIndex].value,
        length: LENGTHS[this.data.lengthIndex].value,
        cover_style: COVER_STYLES[this.data.coverStyleIndex].value,
        include_image: this.data.includeImage,
        client_user_id: app.globalData.clientUserId
      }
    })
      .then((payload) => {
        const result = payload.package;
        const imageJob = payload.image_job || null;
        this.setData({
          result,
          bodyParagraphs: splitParagraphs(result.body),
          publishDraft: formatPublishDraft(result),
          imageJob,
          jobStatusText: imageJob ? JOB_STATUS[imageJob.status] || imageJob.status : "",
          imageUrl: imageFromJob(imageJob)
        });
        this.scrollToResult();
        if (imageJob && ["pending", "running"].includes(imageJob.status)) {
          this.startPolling(imageJob.id);
        }
        this.loadHistory();
      })
      .catch((error) => {
        this.setData({ error: `生成失败：${error.message || error.errMsg || "请稍后再试"}` });
      })
      .finally(() => {
        this.setData({ creating: false });
      });
  },

  scrollToResult() {
    wx.nextTick(() => {
      wx.pageScrollTo({ selector: "#result-card", duration: 260 });
    });
  },

  startPolling(jobId) {
    this.stopPolling();
    this.pollTimer = setInterval(() => {
      this.request(`/api/generations/${jobId}`)
        .then((job) => {
          this.setData({
            imageJob: job,
            jobStatusText: JOB_STATUS[job.status] || job.status,
            imageUrl: imageFromJob(job)
          });
          if (["succeeded", "failed"].includes(job.status)) {
            this.stopPolling();
            this.loadHistory();
          }
        })
        .catch(() => {
          this.stopPolling();
        });
    }, 1800);
  },

  stopPolling() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  },

  loadHistory() {
    this.request("/api/generations?limit=8")
      .then((jobs) => {
        this.setData({
          recentJobs: (jobs || []).map((job) => ({
            ...job,
            statusText: JOB_STATUS[job.status] || job.status,
            imageUrl: imageFromJob(job),
            createdAt: formatTime(job.created_at)
          }))
        });
      })
      .catch(() => {});
  },

  copyPublishDraft() {
    if (!this.data.publishDraft) return;
    wx.setClipboardData({ data: this.data.publishDraft });
  },

  copyTitle() {
    if (!this.data.result) return;
    wx.setClipboardData({ data: this.data.result.best_title });
  },

  copyBody() {
    if (!this.data.result) return;
    wx.setClipboardData({ data: this.data.result.body });
  },

  request(path, options = {}) {
    return new Promise((resolve, reject) => {
      wx.request({
        url: `${app.globalData.apiBaseUrl}${path}`,
        method: options.method || "GET",
        data: options.data,
        header: { "Content-Type": "application/json" },
        success: (response) => {
          if (response.statusCode >= 200 && response.statusCode < 300) {
            resolve(response.data);
            return;
          }
          const detail = response.data && (response.data.detail || response.data.message);
          reject(new Error(detail || `HTTP ${response.statusCode}`));
        },
        fail: reject
      });
    });
  }
});

function buildSettingSummary(articleStyleIndex, lengthIndex, includeImage) {
  return [
    ARTICLE_STYLES[articleStyleIndex].label,
    LENGTHS[lengthIndex].label,
    includeImage ? "生成封面" : "仅文案"
  ];
}

function formatPublishDraft(result) {
  return [result.best_title, result.lead, result.body]
    .map((item) => String(item || "").trim())
    .filter(Boolean)
    .join("\n\n");
}

function splitParagraphs(body) {
  return String(body || "")
    .split(/\n+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function imageFromJob(job) {
  if (!job || !job.images || !job.images.length) return "";
  const url = job.images[0].url || "";
  if (url.startsWith("http")) return url;
  return `${app.globalData.apiBaseUrl}${url}`;
}

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}
```

- [ ] **Step 2: Run JavaScript syntax validation**

Run:

```bash
node -c miniprogram/pages/index/index.js
```

Expected: command exits with no output.

- [ ] **Step 3: Commit the state and logic refactor**

Run:

```bash
git add miniprogram/pages/index/index.js
git commit -m "Refactor mini program publish draft logic"
```

Expected: commit succeeds and includes only `miniprogram/pages/index/index.js`.

---

### Task 2: Rebuild the Page Markup Around Input, Result, Auxiliary, and History Areas

**Files:**
- Modify: `miniprogram/pages/index/index.wxml`

- [ ] **Step 1: Replace `index.wxml` with the new page structure**

Replace the full contents of `miniprogram/pages/index/index.wxml` with:

```xml
<view class="screen">
  <view class="hero compact">
    <view>
      <text class="eyebrow">Toutiao Creator</text>
      <text class="title">头条图文创作台</text>
      <text class="subtitle">输入事实材料，一键生成可复制的发布稿</text>
    </view>
    <view class="health {{healthOk ? 'ok' : 'warn'}}">{{healthText}}</view>
  </view>

  <view class="panel input-panel">
    <view class="panel-head">
      <view>
        <text class="eyebrow">Step 1</text>
        <text class="panel-title">写素材</text>
      </view>
      <button class="text-action" bindtap="useDemo">填入示例</button>
    </view>

    <view class="field">
      <text>选题</text>
      <input value="{{topic}}" data-field="topic" placeholder="例如：新能源车充电体验升级" bindinput="bindInput" />
    </view>

    <view class="field fact-field">
      <text>事实材料</text>
      <textarea value="{{facts}}" data-field="facts" maxlength="4000" placeholder="粘贴已确认的时间、地点、人物、数据、来源和背景。材料越具体，发布稿越稳。" bindinput="bindInput"></textarea>
    </view>

    <view class="settings-summary">
      <view class="summary-label">生成设置</view>
      <view class="chip-row">
        <view wx:for="{{settingSummary}}" wx:key="*this" class="chip">{{item}}</view>
      </view>
      <button class="link-button" bindtap="toggleAdvanced">{{advancedOpen ? '收起高级设置' : '展开高级设置'}}</button>
    </view>

    <view wx:if="{{advancedOpen}}" class="advanced-panel">
      <view class="field">
        <text>报道角度</text>
        <input value="{{angle}}" data-field="angle" placeholder="可选：从用户影响、政策变化、消费建议等角度切入" bindinput="bindInput" />
      </view>

      <view class="field">
        <text>目标读者</text>
        <input value="{{audience}}" data-field="audience" placeholder="例如：关注本地生活的普通读者" bindinput="bindInput" />
      </view>

      <view class="picker-grid">
        <picker mode="selector" range="{{articleStyles}}" value="{{articleStyleIndex}}" bindchange="changeArticleStyle">
          <view class="select"><text>类型</text><view>{{articleStyleLabel}}</view></view>
        </picker>
        <picker mode="selector" range="{{lengths}}" value="{{lengthIndex}}" bindchange="changeLength">
          <view class="select"><text>篇幅</text><view>{{lengthLabel}}</view></view>
        </picker>
        <picker mode="selector" range="{{coverStyles}}" value="{{coverStyleIndex}}" bindchange="changeCoverStyle">
          <view class="select"><text>封面</text><view>{{coverStyleLabel}}</view></view>
        </picker>
      </view>

      <view class="switch-row">
        <view>
          <text>同时生成封面图</text>
          <view>文案先返回，封面图会继续异步生成</view>
        </view>
        <switch checked="{{includeImage}}" bindchange="toggleImage" color="#0f766e" />
      </view>
    </view>

    <button class="primary" loading="{{creating}}" disabled="{{creating}}" bindtap="createPackage">
      {{creating ? '生成中' : '生成发布稿'}}
    </button>
    <view wx:if="{{error}}" class="error">{{error}}</view>
  </view>

  <view wx:if="{{result}}" id="result-card" class="result publish-result">
    <view class="result-head">
      <view>
        <text class="eyebrow">Step 2</text>
        <text class="panel-title">发布稿已生成</text>
        <text class="result-hint">默认复制内容只包含标题、导语和正文。</text>
      </view>
    </view>

    <view class="copy-actions">
      <button class="copy-primary" bindtap="copyPublishDraft">复制发布稿</button>
      <button bindtap="copyTitle">复制标题</button>
      <button bindtap="copyBody">复制正文</button>
    </view>

    <view class="publish-preview">
      <text class="preview-title">{{result.best_title}}</text>
      <view class="preview-lead">{{result.lead}}</view>
      <view class="preview-body">
        <view wx:for="{{bodyParagraphs}}" wx:key="*this" class="paragraph">{{item}}</view>
      </view>
    </view>
  </view>

  <view wx:if="{{result}}" class="auxiliary">
    <view class="block card-block">
      <text class="block-title">备选标题</text>
      <view wx:for="{{result.title_options}}" wx:key="*this" class="option-title">{{item}}</view>
    </view>

    <view class="block card-block">
      <text class="block-title">要点摘要</text>
      <view wx:for="{{result.summary_bullets}}" wx:key="*this" class="bullet">{{item}}</view>
    </view>

    <view class="block card-block">
      <text class="block-title">封面策划</text>
      <view class="cover-brief">{{result.cover_brief}}</view>
      <view class="prompt-text">{{result.image_prompt}}</view>
      <view wx:if="{{result.image_negative_prompt}}" class="negative">避免：{{result.image_negative_prompt}}</view>
    </view>

    <view wx:if="{{imageJob}}" class="block card-block image-block">
      <view class="image-status">
        <text class="block-title">封面图</text>
        <text>{{jobStatusText}}</text>
      </view>
      <image wx:if="{{imageUrl}}" class="preview" mode="aspectFit" src="{{imageUrl}}"></image>
      <view wx:elif="{{imageJob.status === 'failed'}}" class="error inline-error">{{imageJob.error || '图片生成失败'}}</view>
      <view wx:else class="empty compact-empty">图片正在生成，请稍等...</view>
    </view>

    <view class="block card-block review-block">
      <text class="block-title">合规与复核</text>
      <view wx:for="{{result.compliance_notes}}" wx:key="*this" class="check-note">OK {{item}}</view>
      <view wx:for="{{result.fact_check_notes}}" wx:key="*this" class="fact-note">待核 {{item}}</view>
    </view>
  </view>

  <view class="history-section">
    <view class="section-row">
      <text class="section-title">最近封面任务</text>
      <button class="text-action" bindtap="loadHistory">刷新</button>
    </view>
    <view wx:if="{{recentJobs.length === 0}}" class="empty">暂无图片任务</view>
    <view wx:for="{{recentJobs}}" wx:key="id" class="job-card">
      <view>
        <text>{{item.prompt}}</text>
        <view>{{item.createdAt}} · {{item.statusText}}</view>
      </view>
      <image wx:if="{{item.imageUrl}}" src="{{item.imageUrl}}" mode="aspectFill"></image>
    </view>
  </view>
</view>
```

- [ ] **Step 2: Run JavaScript syntax validation**

Run:

```bash
node -c miniprogram/pages/index/index.js
```

Expected: command exits with no output. This confirms the renamed handlers used by WXML exist in JavaScript from Task 1.

- [ ] **Step 3: Commit the markup refactor**

Run:

```bash
git add miniprogram/pages/index/index.wxml
git commit -m "Rebuild mini program publish workflow markup"
```

Expected: commit succeeds and includes only `miniprogram/pages/index/index.wxml`.

---

### Task 3: Restyle the Editor Workflow UI

**Files:**
- Modify: `miniprogram/pages/index/index.wxss`

- [ ] **Step 1: Replace `index.wxss` with the new visual styles**

Replace the full contents of `miniprogram/pages/index/index.wxss` with:

```css
.screen {
  min-height: 100vh;
  padding: 28rpx;
}

.hero,
.panel,
.result,
.card-block,
.job-card {
  border: 1rpx solid #dce1e8;
  border-radius: 18rpx;
  background: #ffffff;
  box-shadow: 0 14rpx 36rpx rgba(29, 38, 61, 0.08);
}

.hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18rpx;
  padding: 26rpx 28rpx;
}

.hero.compact {
  padding-bottom: 24rpx;
}

.eyebrow {
  display: block;
  margin-bottom: 8rpx;
  color: #69707d;
  font-size: 22rpx;
  font-weight: 900;
  letter-spacing: 0;
  text-transform: uppercase;
}

.title {
  display: block;
  color: #1c1d1f;
  font-size: 38rpx;
  font-weight: 900;
  line-height: 1.15;
}

.subtitle,
.result-hint {
  display: block;
  margin-top: 10rpx;
  color: #69707d;
  font-size: 24rpx;
  line-height: 1.45;
}

.health {
  flex: 0 0 auto;
  min-width: 140rpx;
  padding: 12rpx 16rpx;
  border: 1rpx solid #f1c58f;
  border-radius: 999rpx;
  color: #9a4f0a;
  background: #fff7ed;
  text-align: center;
  font-size: 22rpx;
  font-weight: 900;
}

.health.ok {
  border-color: #b8ded5;
  color: #0f5e3f;
  background: #e6f4f1;
}

.panel,
.result,
.auxiliary,
.history-section {
  margin-top: 22rpx;
}

.panel,
.result {
  padding: 24rpx;
}

.panel-head,
.result-head,
.section-row,
.image-status,
.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18rpx;
}

.result-head {
  align-items: flex-start;
}

.panel-title,
.section-title,
.block-title {
  display: block;
  color: #1c1d1f;
  font-size: 30rpx;
  font-weight: 900;
  line-height: 1.2;
}

.text-action,
.link-button,
.copy-actions button {
  min-width: 120rpx;
  height: 60rpx;
  border: 1rpx solid #dce1e8;
  border-radius: 999rpx;
  color: #0f766e;
  background: #ffffff;
  text-align: center;
  font-size: 23rpx;
  font-weight: 900;
  line-height: 60rpx;
}

.link-button {
  width: 210rpx;
  margin-top: 14rpx;
  border-color: transparent;
  background: transparent;
  text-align: left;
}

.field {
  margin-top: 22rpx;
}

.field > text,
.switch-row text,
.summary-label {
  display: block;
  margin-bottom: 10rpx;
  color: #69707d;
  font-size: 24rpx;
  font-weight: 900;
}

input,
textarea {
  width: 100%;
  border: 1rpx solid #dce1e8;
  border-radius: 14rpx;
  color: #1c1d1f;
  background: #ffffff;
  font-size: 26rpx;
}

input {
  height: 78rpx;
  padding: 0 18rpx;
}

textarea {
  min-height: 260rpx;
  padding: 18rpx;
  line-height: 1.55;
}

.fact-field textarea {
  min-height: 300rpx;
}

.settings-summary,
.advanced-panel {
  margin-top: 22rpx;
  padding: 18rpx;
  border: 1rpx solid #e8edf3;
  border-radius: 14rpx;
  background: #f8fafc;
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10rpx;
}

.chip {
  padding: 10rpx 16rpx;
  border-radius: 999rpx;
  color: #0f5e3f;
  background: #e6f4f1;
  font-size: 23rpx;
  font-weight: 900;
}

.advanced-panel {
  background: #ffffff;
}

.picker-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12rpx;
  margin-top: 22rpx;
}

.select {
  min-height: 88rpx;
  border: 1rpx solid #dce1e8;
  border-radius: 12rpx;
  padding: 12rpx;
  background: #f8fafc;
}

.select text {
  display: block;
  color: #69707d;
  font-size: 20rpx;
  font-weight: 900;
}

.select view {
  margin-top: 6rpx;
  color: #1c1d1f;
  font-size: 24rpx;
  font-weight: 900;
}

.switch-row {
  margin-top: 22rpx;
  padding: 18rpx;
  border-radius: 12rpx;
  background: #f8fafc;
}

.switch-row view view {
  color: #69707d;
  font-size: 22rpx;
}

.primary {
  height: 92rpx;
  margin-top: 24rpx;
  border-radius: 14rpx;
  color: #ffffff;
  background: #0f766e;
  font-size: 29rpx;
  font-weight: 900;
  line-height: 92rpx;
}

.primary[disabled] {
  opacity: 0.66;
}

.error,
.empty {
  margin-top: 18rpx;
  padding: 24rpx;
  border: 1rpx solid #f0c8c8;
  border-radius: 12rpx;
  color: #b64040;
  background: #fff0f2;
  font-size: 24rpx;
  line-height: 1.5;
}

.empty {
  border-style: dashed;
  border-color: #dce1e8;
  color: #69707d;
  background: rgba(255, 255, 255, 0.66);
  text-align: center;
}

.compact-empty,
.inline-error {
  margin-top: 14rpx;
}

.copy-actions {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr;
  gap: 12rpx;
  margin-top: 22rpx;
}

.copy-actions button {
  width: 100%;
  min-width: 0;
  border-radius: 14rpx;
}

.copy-actions .copy-primary {
  border-color: #0f766e;
  color: #ffffff;
  background: #0f766e;
}

.publish-preview {
  margin-top: 22rpx;
  padding: 26rpx;
  border-radius: 16rpx;
  background: #f8fafc;
}

.preview-title {
  display: block;
  color: #1c1d1f;
  font-size: 36rpx;
  font-weight: 900;
  line-height: 1.35;
}

.preview-lead {
  margin-top: 16rpx;
  color: #39404a;
  font-size: 27rpx;
  font-weight: 700;
  line-height: 1.6;
}

.preview-body {
  margin-top: 18rpx;
  padding-top: 18rpx;
  border-top: 1rpx solid #e4e9f0;
}

.block {
  margin-top: 18rpx;
}

.card-block {
  padding: 22rpx;
}

.option-title,
.paragraph,
.bullet,
.cover-brief,
.prompt-text,
.negative,
.check-note,
.fact-note {
  margin-top: 12rpx;
  color: #1c1d1f;
  font-size: 26rpx;
  line-height: 1.6;
}

.option-title,
.bullet,
.check-note,
.fact-note {
  padding: 14rpx 16rpx;
  border-radius: 10rpx;
  background: #f8fafc;
}

.prompt-text {
  padding: 16rpx;
  border-left: 6rpx solid #0f766e;
  border-radius: 8rpx;
  background: #f8fafc;
}

.negative,
.fact-note {
  color: #9a4f0a;
}

.check-note {
  color: #0f5e3f;
}

.preview {
  width: 100%;
  height: 430rpx;
  margin-top: 16rpx;
  border-radius: 12rpx;
  background: #eef2f7;
}

.section-row {
  margin: 30rpx 0 16rpx;
}

.history-section {
  opacity: 0.88;
}

.job-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 150rpx;
  gap: 16rpx;
  align-items: center;
  margin-bottom: 14rpx;
  padding: 18rpx;
}

.job-card text {
  display: block;
  color: #1c1d1f;
  font-size: 24rpx;
  font-weight: 800;
  line-height: 1.45;
}

.job-card view view {
  margin-top: 8rpx;
  color: #69707d;
  font-size: 22rpx;
}

.job-card image {
  width: 150rpx;
  height: 100rpx;
  border-radius: 10rpx;
  background: #eef2f7;
}
```

- [ ] **Step 2: Run JavaScript syntax validation**

Run:

```bash
node -c miniprogram/pages/index/index.js
```

Expected: command exits with no output.

- [ ] **Step 3: Commit the visual restyle**

Run:

```bash
git add miniprogram/pages/index/index.wxss
git commit -m "Restyle mini program publish workflow"
```

Expected: commit succeeds and includes only `miniprogram/pages/index/index.wxss`.

---

### Task 4: Verify the Full Mini Program Workflow Locally

**Files:**
- Verify: `miniprogram/pages/index/index.js`
- Verify: `miniprogram/pages/index/index.wxml`
- Verify: `miniprogram/pages/index/index.wxss`

- [ ] **Step 1: Run syntax validation**

Run:

```bash
node -c miniprogram/pages/index/index.js
```

Expected: command exits with no output.

- [ ] **Step 2: Inspect the final diff**

Run:

```bash
git diff -- miniprogram/pages/index/index.js miniprogram/pages/index/index.wxml miniprogram/pages/index/index.wxss
```

Expected: no unstaged diff if Tasks 1-3 were committed. If there is diff, review it and either commit intentional changes or revert accidental edits before continuing.

- [ ] **Step 3: Launch the Mini Program in WeChat Developer Tools**

Open `/Volumes/MacData/projects/text_image_demo` in WeChat Developer Tools.

Expected visual checks:
- The first screen shows the compact header and input card.
- The visible input fields are only “选题” and “事实材料”.
- The settings summary shows three chips: article type, length, and image mode.
- The primary button says “生成发布稿”.

- [ ] **Step 4: Verify advanced settings**

In WeChat Developer Tools:
1. Click “展开高级设置”.
2. Change article type, length, cover style, and image switch.
3. Confirm the chips update when article type, length, or image switch changes.
4. Click “收起高级设置”.

Expected: advanced fields hide and the selected settings remain active.

- [ ] **Step 5: Verify generation and copy behavior**

In WeChat Developer Tools:
1. Click “填入示例”.
2. Click “生成发布稿”.
3. Wait for result.
4. Confirm the page scrolls to “发布稿已生成”.
5. Click “复制发布稿”.
6. Paste into a temporary text field outside the app.

Expected copied format:

```text
新能源车充电体验升级...

...

...
```

Expected content rule: copied text includes only the selected title, lead, and body. It must not include “封面图提示词”, “OK”, “待核”, compliance notes, fact-check notes, or image prompt text.

- [ ] **Step 6: Verify auxiliary sections and history**

In WeChat Developer Tools after generation:
1. Confirm “备选标题” appears below the publish preview.
2. Confirm “要点摘要” appears below the publish preview.
3. Confirm “封面策划” appears below the publish preview.
4. If image generation is enabled, confirm “封面图” shows one of: 排队中, 生成中, 已完成, 失败.
5. Confirm “合规与复核” appears below the cover section.
6. Click “刷新” in “最近封面任务”.

Expected: auxiliary sections render without blocking publish draft copy, and recent jobs still load.

- [ ] **Step 7: Commit any verification fixes**

If Tasks 4-6 revealed necessary code fixes, run:

```bash
git add miniprogram/pages/index/index.js miniprogram/pages/index/index.wxml miniprogram/pages/index/index.wxss
git commit -m "Fix mini program publish workflow verification issues"
```

Expected: commit only occurs if verification produced fixes. If no files changed, do not create an empty commit.

---

## Self-Review Notes

- Spec coverage: Task 1 implements advanced state, settings summary, safe publish draft formatting, split copy actions, existing API payloads, scroll-to-result, image polling, and history retention. Task 2 implements the five-region information architecture and moves advanced inputs into a collapsed panel. Task 3 implements the visual hierarchy, chips, primary/secondary buttons, publish preview, auxiliary cards, and low-weight history. Task 4 verifies syntax, UI behavior, copy safety, image status, and history.
- Placeholder scan: no TBD/TODO/fill-in placeholders are included.
- Type consistency: WXML handlers match Task 1 method names: `useDemo`, `bindInput`, `toggleAdvanced`, `changeArticleStyle`, `changeLength`, `changeCoverStyle`, `toggleImage`, `createPackage`, `copyPublishDraft`, `copyTitle`, `copyBody`, and `loadHistory`.
