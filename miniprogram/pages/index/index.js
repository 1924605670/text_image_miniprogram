const app = getApp();

const STYLE_PRESETS = [
  { label: "原始", value: "none" },
  { label: "写实", value: "photorealistic" },
  { label: "电影感", value: "cinematic" },
  { label: "产品", value: "product" },
  { label: "插画", value: "illustration" },
  { label: "国风", value: "chinese_illustration" },
  { label: "动漫", value: "anime" },
  { label: "海报", value: "poster" },
  { label: "建筑", value: "architecture" }
];

const SIZES = [
  { label: "方图 1:1", value: "1024x1024" },
  { label: "竖图 2:3", value: "1024x1536" },
  { label: "横图 16:9", value: "2048x1152" },
  { label: "高清方图", value: "2048x2048" }
];

const QUALITIES = [
  { label: "自动", value: "auto" },
  { label: "高清", value: "high" },
  { label: "标准", value: "medium" }
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
    prompt: "",
    negativePrompt: "",
    optimizedPrompt: "",
    stylePresets: STYLE_PRESETS.map((item) => item.label),
    stylePresetIndex: 0,
    stylePresetLabel: STYLE_PRESETS[0].label,
    sizes: SIZES.map((item) => item.label),
    sizeIndex: 0,
    sizeLabel: SIZES[0].label,
    qualities: QUALITIES.map((item) => item.label),
    qualityIndex: 0,
    qualityLabel: QUALITIES[0].label,
    advancedOpen: false,
    optimizing: false,
    creating: false,
    error: "",
    imageJob: null,
    imageUrl: "",
    jobStatusText: "",
    resultImageUrl: "",
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

  changeStylePreset(event) {
    const stylePresetIndex = Number(event.detail.value || 0);
    this.setData({
      stylePresetIndex,
      stylePresetLabel: STYLE_PRESETS[stylePresetIndex].label
    });
  },

  changeSize(event) {
    const sizeIndex = Number(event.detail.value || 0);
    this.setData({ sizeIndex, sizeLabel: SIZES[sizeIndex].label });
  },

  changeQuality(event) {
    const qualityIndex = Number(event.detail.value || 0);
    this.setData({ qualityIndex, qualityLabel: QUALITIES[qualityIndex].label });
  },

  useDemo() {
    this.setData({
      prompt: "雨后傍晚的城市天台，一位年轻设计师站在护栏边看远处霓虹灯，湿润地面有柔和倒影，电影感构图，真实摄影质感，安静但有故事感",
      negativePrompt: "低清晰度、畸形手指、错乱文字、水印、logo、过曝、杂乱背景",
      optimizedPrompt: ""
    });
  },

  optimizePrompt() {
    const prompt = this.data.prompt.trim();
    if (prompt.length < 3) {
      this.setData({ error: "请先输入至少 3 个字的提示词。" });
      return;
    }

    this.setData({ optimizing: true, error: "" });
    this.request("/api/prompt-optimize", {
      method: "POST",
      data: {
        prompt,
        style_preset: STYLE_PRESETS[this.data.stylePresetIndex].value,
        size: SIZES[this.data.sizeIndex].value,
        quality: QUALITIES[this.data.qualityIndex].value,
        output_format: "png"
      }
    })
      .then((payload) => {
        this.setData({ optimizedPrompt: payload.optimized_prompt || "" });
      })
      .catch((error) => {
        this.setData({ error: `优化失败：${error.message || error.errMsg || "请稍后再试"}` });
      })
      .finally(() => {
        this.setData({ optimizing: false });
      });
  },

  useOptimizedPrompt() {
    if (!this.data.optimizedPrompt) return;
    this.setData({ prompt: this.data.optimizedPrompt, optimizedPrompt: "" });
  },

  copyPrompt() {
    const prompt = (this.data.optimizedPrompt || this.data.prompt).trim();
    if (!prompt) return;
    wx.setClipboardData({ data: prompt });
  },

  copyImageUrl() {
    if (!this.data.resultImageUrl) return;
    wx.setClipboardData({ data: this.data.resultImageUrl });
  },

  copyResultPrompt() {
    if (!this.data.imageJob) return;
    wx.setClipboardData({
      data: this.data.imageJob.final_prompt || this.data.imageJob.prompt || ""
    });
  },

  previewImage() {
    if (!this.data.resultImageUrl) return;
    wx.previewImage({
      urls: [this.data.resultImageUrl],
      current: this.data.resultImageUrl
    });
  },

  createImage() {
    const prompt = (this.data.optimizedPrompt || this.data.prompt).trim();
    if (prompt.length < 3) {
      this.setData({ error: "请先输入至少 3 个字的提示词。" });
      return;
    }

    this.stopPolling();
    this.setData({
      creating: true,
      error: "",
      imageJob: null,
      imageUrl: "",
      jobStatusText: "",
      resultImageUrl: ""
    });

    this.request("/api/generations", {
      method: "POST",
      data: {
        prompt,
        negative_prompt: this.data.negativePrompt.trim(),
        style_preset: STYLE_PRESETS[this.data.stylePresetIndex].value,
        size: SIZES[this.data.sizeIndex].value,
        quality: QUALITIES[this.data.qualityIndex].value,
        output_format: "png",
        n: 1,
        client_user_id: app.globalData.clientUserId
      }
    })
      .then((payload) => {
        const imageJob = payload.job;
        this.setData({
          imageJob,
          jobStatusText: JOB_STATUS[imageJob.status] || imageJob.status,
          imageUrl: imageFromJob(imageJob),
          resultImageUrl: imageFromJob(imageJob)
        });
        this.scrollToResult();
        if (["pending", "running"].includes(imageJob.status)) {
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
            imageUrl: imageFromJob(job),
            resultImageUrl: imageFromJob(job)
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
            styleLabel: styleLabelFromJob(job),
            sizeLabel: sizeLabelFromJob(job),
            createdAt: formatTime(job.created_at)
          }))
        });
      })
      .catch(() => {});
  },

  reuseJob(event) {
    const jobId = event.currentTarget.dataset.id;
    const job = this.data.recentJobs.find((item) => item.id === jobId);
    if (!job) return;
    const request = job.request || {};
    const stylePresetIndex = indexByValue(STYLE_PRESETS, request.style_preset, this.data.stylePresetIndex);
    const sizeIndex = indexByValue(SIZES, request.size, this.data.sizeIndex);
    const qualityIndex = indexByValue(QUALITIES, request.quality, this.data.qualityIndex);
    this.setData({
      prompt: request.prompt || job.prompt || "",
      negativePrompt: request.negative_prompt || "",
      optimizedPrompt: "",
      stylePresetIndex,
      stylePresetLabel: STYLE_PRESETS[stylePresetIndex].label,
      sizeIndex,
      sizeLabel: SIZES[sizeIndex].label,
      qualityIndex,
      qualityLabel: QUALITIES[qualityIndex].label,
      error: ""
    });
    wx.pageScrollTo({ scrollTop: 0, duration: 220 });
  },

  openHistoryImage(event) {
    const url = event.currentTarget.dataset.url;
    if (!url) return;
    wx.previewImage({ urls: [url], current: url });
  },

  retryJob(event) {
    const jobId = event.currentTarget.dataset.id;
    if (!jobId || this.data.creating || this.data.optimizing) return;
    this.stopPolling();
    this.setData({
      creating: true,
      error: "",
      imageJob: null,
      imageUrl: "",
      jobStatusText: "",
      resultImageUrl: ""
    });
    this.request(`/api/generations/${jobId}/retry`, { method: "POST" })
      .then((payload) => {
        const imageJob = payload.job;
        this.setData({
          imageJob,
          jobStatusText: JOB_STATUS[imageJob.status] || imageJob.status,
          imageUrl: imageFromJob(imageJob),
          resultImageUrl: imageFromJob(imageJob)
        });
        this.scrollToResult();
        if (["pending", "running"].includes(imageJob.status)) {
          this.startPolling(imageJob.id);
        }
        this.loadHistory();
      })
      .catch((error) => {
        this.setData({ error: `重试失败：${error.message || error.errMsg || "请稍后再试"}` });
      })
      .finally(() => {
        this.setData({ creating: false });
      });
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

function imageFromJob(job) {
  if (!job || !job.images || !job.images.length) return "";
  const url = job.images[0].url || "";
  if (url.startsWith("http")) return url;
  return `${app.globalData.apiBaseUrl}${url}`;
}

function styleLabelFromJob(job) {
  const value = job && job.request && job.request.style_preset;
  const item = STYLE_PRESETS.find((preset) => preset.value === value);
  return item ? item.label : "默认";
}

function sizeLabelFromJob(job) {
  const value = job && job.request && job.request.size;
  const item = SIZES.find((size) => size.value === value);
  return item ? item.label : value || "";
}

function indexByValue(list, value, fallback) {
  const index = list.findIndex((item) => item.value === value);
  return index >= 0 ? index : fallback;
}

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}
