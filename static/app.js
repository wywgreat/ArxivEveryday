const TRACKED_TOPICS = [
  "大语言模型",
  "智能体",
  "推理",
  "世界模型",
  "具身智能",
  "多模态",
  "代码生成",
  "训练优化",
  "推理优化",
  "AI安全",
  "扩展与泛化",
];

const state = {
  activeTab: "all",
  papers: [],
  favorites: [],
  source: "",
  loading: false,
  windowLabel: "最近 7 天",
};

const refs = {
  windowForm: document.querySelector("#windowForm"),
  windowSelect: document.querySelector("#windowSelect"),
  startDateField: document.querySelector("#startDateField"),
  endDateField: document.querySelector("#endDateField"),
  startDate: document.querySelector("#startDate"),
  endDate: document.querySelector("#endDate"),
  refreshButton: document.querySelector("#refreshButton"),
  allTab: document.querySelector("#allTab"),
  favoriteTab: document.querySelector("#favoriteTab"),
  paperGrid: document.querySelector("#paperGrid"),
  emptyState: document.querySelector("#emptyState"),
  loadingState: document.querySelector("#loadingState"),
  topicCloud: document.querySelector("#topicCloud"),
  banner: document.querySelector("#banner"),
  paperCount: document.querySelector("#paperCount"),
  favoriteCount: document.querySelector("#favoriteCount"),
  sourceLabel: document.querySelector("#sourceLabel"),
  windowLabel: document.querySelector("#windowLabel"),
  listHint: document.querySelector("#listHint"),
  userBadge: document.querySelector("#userBadge"),
  logoutButton: document.querySelector("#logoutButton"),
};

function escapeHtml(value = "") {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatDate(value) {
  try {
    return new Intl.DateTimeFormat("zh-CN", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(value));
  } catch {
    return value || "-";
  }
}

function setDefaultCustomDates() {
  const today = new Date();
  const end = today.toISOString().slice(0, 10);
  const start = new Date(today.getTime() - 6 * 24 * 60 * 60 * 1000)
    .toISOString()
    .slice(0, 10);
  refs.startDate.value = refs.startDate.value || start;
  refs.endDate.value = refs.endDate.value || end;
}

function toggleCustomFields() {
  const isCustom = refs.windowSelect.value === "custom";
  refs.startDateField.classList.toggle("hidden", !isCustom);
  refs.endDateField.classList.toggle("hidden", !isCustom);
  if (isCustom) {
    setDefaultCustomDates();
  }
}

function renderTopicCloud() {
  refs.topicCloud.innerHTML = TRACKED_TOPICS.map(
    (topic) => `<span class="topic-pill">${escapeHtml(topic)}</span>`
  ).join("");
}

function setBanner(message, tone = "info") {
  if (!message) {
    refs.banner.className = "banner hidden";
    refs.banner.textContent = "";
    return;
  }
  refs.banner.className = `banner ${tone}`;
  refs.banner.textContent = message;
}

function setLoading(loading) {
  state.loading = loading;
  refs.refreshButton.disabled = loading;
  refs.refreshButton.textContent = loading ? "更新中..." : "立即更新";
  refs.loadingState.classList.toggle("hidden", !loading);
}

function syncFavoriteFlags() {
  const favoriteIds = new Set(state.favorites.map((paper) => paper.id));
  state.papers = state.papers.map((paper) => ({
    ...paper,
    isFavorite: favoriteIds.has(paper.id),
  }));
}

function updateStats() {
  refs.paperCount.textContent = String(state.papers.length);
  refs.favoriteCount.textContent = String(state.favorites.length);
  refs.sourceLabel.textContent =
    state.source === "live"
      ? "实时 arXiv"
      : state.source === "cache"
        ? "本地缓存"
        : state.source === "demo"
          ? "演示数据"
          : "未加载";
  refs.windowLabel.textContent = state.windowLabel;
}

function currentList() {
  return state.activeTab === "favorites" ? state.favorites : state.papers;
}

function buildPaperCard(paper, index) {
  const favoriteLabel = paper.isFavorite ? "已收藏" : "收藏";
  const favoriteClass = paper.isFavorite ? "favorite active" : "favorite";
  const topics = (paper.matchedTopics || [])
    .map((topic) => `<span class="mini-pill">${escapeHtml(topic)}</span>`)
    .join("");
  const keywords = (paper.matchedKeywords || [])
    .slice(0, 4)
    .map((keyword) => `<span class="keyword-pill">${escapeHtml(keyword)}</span>`)
    .join("");
  const authors = (paper.authors || []).length
    ? escapeHtml(paper.authors.join(", "))
    : "未知作者";

  return `
    <article class="paper-card" style="animation-delay: ${index * 55}ms">
      <div class="paper-card-top">
        <div class="pill-row">${topics || '<span class="mini-pill">主题匹配中</span>'}</div>
        <button class="${favoriteClass}" type="button" data-action="favorite" data-id="${encodeURIComponent(paper.id)}">${favoriteLabel}</button>
      </div>

      <div class="paper-meta">
        <span>${escapeHtml(paper.primaryCategory || "未分类")}</span>
        <span>${escapeHtml(formatDate(paper.published))}</span>
      </div>

      <div class="keyword-row">${keywords}</div>

      <section class="copy-block">
        <span class="copy-label">英文标题</span>
        <h4>${escapeHtml(paper.title || "无标题")}</h4>
      </section>

      <section class="copy-block translated">
        <span class="copy-label">中文标题</span>
        <p>${escapeHtml(paper.titleZh || "翻译暂不可用")}</p>
      </section>

      <section class="copy-block">
        <span class="copy-label">英文摘要</span>
        <p>${escapeHtml(paper.summary || "暂无摘要")}</p>
      </section>

      <section class="copy-block translated">
        <span class="copy-label">中文摘要</span>
        <p>${escapeHtml(paper.summaryZh || "翻译暂不可用")}</p>
      </section>

      <div class="paper-footer">
        <p class="author-line">作者：${authors}</p>
        <div class="paper-links">
          <a href="${escapeHtml(paper.paperUrl || "#")}" target="_blank" rel="noreferrer">查看 arXiv</a>
          <a href="${escapeHtml(paper.pdfUrl || "#")}" target="_blank" rel="noreferrer">打开 PDF</a>
        </div>
      </div>
    </article>
  `;
}

function renderList() {
  const list = currentList();

  refs.allTab.classList.toggle("active", state.activeTab === "all");
  refs.favoriteTab.classList.toggle("active", state.activeTab === "favorites");
  refs.listHint.textContent =
    state.activeTab === "favorites"
      ? "收藏会持久化到本地 SQLite，刷新页面后仍可保留。"
      : "点击卡片右上角即可收藏 / 取消收藏。";

  if (state.loading) {
    refs.paperGrid.innerHTML = "";
    refs.emptyState.classList.add("hidden");
    return;
  }

  if (!list.length) {
    refs.paperGrid.innerHTML = "";
    refs.emptyState.classList.remove("hidden");
    return;
  }

  refs.emptyState.classList.add("hidden");
  refs.paperGrid.innerHTML = list.map(buildPaperCard).join("");
}

async function apiFetch(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));

  if (response.status === 401) {
    window.location.href = "/login";
    throw new Error("登录状态已失效，请重新登录。");
  }

  if (!response.ok) {
    throw new Error(payload.error || "请求失败，请稍后重试。");
  }

  return payload;
}

async function loadSession() {
  const session = await apiFetch("/api/session");
  if (!session.authenticated) {
    window.location.href = "/login";
    return;
  }
  refs.userBadge.textContent = session.username || "admin123";
}

async function loadFavorites() {
  const payload = await apiFetch("/api/favorites");
  state.favorites = payload.favorites || [];
  syncFavoriteFlags();
  updateStats();
  renderList();
}

function buildWindowQuery() {
  const params = new URLSearchParams();
  const selected = refs.windowSelect.value;
  params.set("window", selected);
  if (selected === "custom") {
    params.set("startDate", refs.startDate.value);
    params.set("endDate", refs.endDate.value);
  }
  return params.toString();
}

async function loadPapers() {
  setLoading(true);
  setBanner("");

  try {
    const payload = await apiFetch(`/api/papers?${buildWindowQuery()}`);
    state.papers = payload.papers || [];
    state.source = payload.source || "";
    state.windowLabel = payload.window?.label || "最近 7 天";
    syncFavoriteFlags();

    const tone =
      payload.source === "live"
        ? "success"
        : payload.source === "cache"
          ? "warning"
          : "info";
    setBanner(payload.message || "", tone);
  } catch (error) {
    setBanner(error.message || "论文加载失败，请稍后重试。", "error");
  } finally {
    setLoading(false);
    updateStats();
    renderList();
  }
}

async function toggleFavorite(paperId) {
  const decodedId = decodeURIComponent(paperId);
  const paper =
    state.papers.find((item) => item.id === decodedId) ||
    state.favorites.find((item) => item.id === decodedId);

  if (!paper) {
    return;
  }

  try {
    if (paper.isFavorite) {
      await apiFetch(`/api/favorites/${encodeURIComponent(decodedId)}`, {
        method: "DELETE",
      });
      state.favorites = state.favorites.filter((item) => item.id !== decodedId);
    } else {
      const payload = await apiFetch("/api/favorites", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(paper),
      });
      state.favorites = [payload.paper, ...state.favorites.filter((item) => item.id !== decodedId)];
    }

    syncFavoriteFlags();
    updateStats();
    renderList();
  } catch (error) {
    setBanner(error.message || "收藏操作失败，请稍后重试。", "error");
  }
}

async function logout() {
  try {
    await apiFetch("/api/logout", { method: "POST" });
  } finally {
    window.location.href = "/login";
  }
}

function handleGridClick(event) {
  const button = event.target.closest("[data-action='favorite']");
  if (!button) {
    return;
  }
  toggleFavorite(button.dataset.id);
}

async function handleRefresh(event) {
  event.preventDefault();
  await loadPapers();
}

function activateTab(tab) {
  state.activeTab = tab;
  renderList();
}

async function bootstrap() {
  renderTopicCloud();
  toggleCustomFields();
  await loadSession();
  await loadFavorites();
  await loadPapers();
}

refs.windowSelect?.addEventListener("change", toggleCustomFields);
refs.windowForm?.addEventListener("submit", handleRefresh);
refs.allTab?.addEventListener("click", () => activateTab("all"));
refs.favoriteTab?.addEventListener("click", () => activateTab("favorites"));
refs.paperGrid?.addEventListener("click", handleGridClick);
refs.logoutButton?.addEventListener("click", logout);

bootstrap();
