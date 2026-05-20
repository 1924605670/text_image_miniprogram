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
    creating: false,
    error: "",
    result: null,
    bodyParagraphs: [],
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

  changeArticleStyle(event) {
    const articleStyleIndex = Number(event.detail.value || 0);
    this.setData({ articleStyleIndex, articleStyleLabel: ARTICLE_STYLES[articleStyleIndex].label });
  },

  changeLength(event) {
    const lengthIndex = Number(event.detail.value || 0);
    this.setData({ lengthIndex, lengthLabel: LENGTHS[lengthIndex].label });
  },

  changeCoverStyle(event) {
    const coverStyleIndex = Number(event.detail.value || 0);
    this.setData({ coverStyleIndex, coverStyleLabel: COVER_STYLES[coverStyleIndex].label });
  },

  toggleImage(event) {
    this.setData({ includeImage: event.detail.value });
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
          imageJob,
          jobStatusText: imageJob ? JOB_STATUS[imageJob.status] || imageJob.status : "",
          imageUrl: imageFromJob(imageJob)
        });
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

  copyTitle() {
    if (!this.data.result) return;
    wx.setClipboardData({ data: this.data.result.best_title });
  },

  copyArticle() {
    if (!this.data.result) return;
    const result = this.data.result;
    const content = [
      result.best_title,
      "",
      result.lead,
      "",
      result.body,
      "",
      "封面图提示词：",
      result.image_prompt
    ].join("\n");
    wx.setClipboardData({ data: content });
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
