const TOPIC_OPTIONS = [
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
  activeView: "all",
  papers: [],
  favorites: [],
  selectedTopics: new Set(TOPIC_OPTIONS),
  loading: false,
  source: "",
  dateLabel: "未设置",
  aiSummaryEnabled: false,
  summaryLoadingIds: new Set(),
};

const refs = {
  filterForm: document.querySelector("#filterForm"),
  startDate: document.querySelector("#startDate"),
  endDate: document.querySelector("#endDate"),
  refreshButton: document.querySelector("#refreshButton"),
  resetFiltersButton: document.querySelector("#resetFiltersButton"),
  selectAllTopicsButton: document.querySelector("#selectAllTopicsButton"),
  topicSelector: document.querySelector("#topicSelector"),
  selectedTopicCount: document.querySelector("#selectedTopicCount"),
  favoritesShortcut: document.querySelector("#favoritesShortcut"),
  allTab: document.querySelector("#allTab"),
  favoriteTab: document.querySelector("#favoriteTab"),
  paperGrid: document.querySelector("#paperGrid"),
  emptyState: document.querySelector("#emptyState"),
  loadingState: document.querySelector("#loadingState"),
  banner: document.querySelector("#banner"),
  paperCount: document.querySelector("#paperCount"),
  favoriteCount: document.querySelector("#favoriteCount"),
  favoriteCountHero: document.querySelector("#favoriteCountHero"),
  sourceLabel: document.querySelector("#sourceLabel"),
  dateLabel: document.querySelector("#dateLabel"),
  listHint: document.querySelector("#listHint"),
  userBadge: document.querySelector("#userBadge"),
  summaryCapability: document.querySelector("#summaryCapability"),
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

function toHtmlWithBreaks(value = "") {
  return escapeHtml(value).replaceAll("\n", "<br />");
}

function setDefaultDates() {
  const now = new Date();
  const end = now.toISOString().slice(0, 10);
  const start = new Date(now.getTime() - 6 * 24 * 60 * 60 * 1000)
    .toISOString()
    .slice(0, 10);
  refs.startDate.value = refs.startDate.value || start;
  refs.endDate.value = refs.endDate.value || end;
}

function renderTopicSelector() {
  refs.topicSelector.innerHTML = TOPIC_OPTIONS.map((topic) => {
    const active = state.selectedTopics.has(topic);
    return `<button type="button" class="topic-filter ${active ? "active" : ""}" data-topic="${escapeHtml(topic)}">${escapeHtml(topic)}</button>`;
  }).join("");
  refs.selectedTopicCount.textContent = `${state.selectedTopics.size} / ${TOPIC_OPTIONS.length}`;
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

function syncPaperState() {
  const favoriteMap = new Map(state.favorites.map((paper) => [paper.id, paper]));
  state.papers = state.papers.map((paper) => {
    const favorite = favoriteMap.get(paper.id);
    return favorite
      ? { ...paper, ...favorite, isFavorite: true }
      : { ...paper, isFavorite: false };
  });
}

function updateStats() {
  refs.paperCount.textContent = String(state.papers.length);
  refs.favoriteCount.textContent = String(state.favorites.length);
  refs.favoriteCountHero.textContent = String(state.favorites.length);
  refs.sourceLabel.textContent =
    state.source === "live"
      ? "实时 arXiv"
      : state.source === "cache"
        ? "本地缓存"
        : state.source === "demo"
          ? "演示数据"
          : "未加载";
  refs.dateLabel.textContent = state.dateLabel;
  refs.summaryCapability.textContent = state.aiSummaryEnabled
    ? "已检测到标准百炼配置，可以生成并缓存 AI Summary。"
    : "未检测到标准百炼配置；AI Summary 按钮会提示如何启用。";
}

function currentList() {
  return state.activeView === "favorites" ? state.favorites : state.papers;
}

function summarySourceLabel(source) {
  if (source === "pdf") {
    return "基于全文";
  }
  if (source === "abstract") {
    return "基于题目与摘要";
  }
  return "已缓存";
}

function downloadUrl(paper) {
  const params = new URLSearchParams({
    paperId: paper.id,
    pdfUrl: paper.pdfUrl || "",
  });
  return `/api/download?${params.toString()}`;
}

function buildPaperCard(paper, index) {
  const favoriteLabel = paper.isFavorite ? "已收藏" : "收藏";
  const favoriteClass = paper.isFavorite ? "favorite active" : "favorite";
  const summaryLoading = state.summaryLoadingIds.has(paper.id);
  const summaryLabel = summaryLoading
    ? "生成中..."
    : paper.aiSummary
      ? "刷新 AI Summary"
      : "AI Summary";
  const topics = (paper.matchedTopics || [])
    .map((topic) => `<span class="mini-pill">${escapeHtml(topic)}</span>`)
    .join("");
  const keywords = (paper.keywords || [])
    .slice(0, 8)
    .map((keyword) => `<span class="keyword-pill">${escapeHtml(keyword)}</span>`)
    .join("");
  const authors = (paper.authors || []).length
    ? escapeHtml(paper.authors.join(", "))
    : "未知作者";
  const summaryBlock = paper.aiSummary
    ? `
      <section class="summary-panel">
        <div class="summary-head">
          <span>AI Summary</span>
          <span>${escapeHtml(summarySourceLabel(paper.aiSummarySource))}</span>
        </div>
        <div class="summary-body">${toHtmlWithBreaks(paper.aiSummary)}</div>
        <div class="summary-foot">${paper.aiSummaryUpdatedAt ? `更新于 ${escapeHtml(formatDate(paper.aiSummaryUpdatedAt))}` : ""}</div>
      </section>
    `
    : "";

  return `
    <article class="paper-card" style="animation-delay:${index * 45}ms">
      <div class="paper-top">
        <div>
          <div class="paper-meta">
            <span>${escapeHtml(paper.primaryCategory || "未分类")}</span>
            <span>${escapeHtml(formatDate(paper.published))}</span>
          </div>
          <h3 class="paper-title">${escapeHtml(paper.title || "无标题")}</h3>
          <p class="paper-title-zh">${escapeHtml(paper.titleZh || "翻译暂不可用")}</p>
        </div>
        <button class="${favoriteClass}" type="button" data-action="favorite" data-id="${encodeURIComponent(paper.id)}">${favoriteLabel}</button>
      </div>

      <div class="chip-row">
        ${topics}
        ${keywords}
      </div>

      <div class="abstract-pair">
        <p class="abstract-text">${escapeHtml(paper.summary || "暂无摘要")}</p>
        <div class="abstract-divider"></div>
        <p class="abstract-text translated">${escapeHtml(paper.summaryZh || "翻译暂不可用")}</p>
      </div>

      ${summaryBlock}

      <div class="paper-footer">
        <p class="author-line">作者：${authors}</p>
        <div class="action-row">
          <button class="secondary-button compact" type="button" data-action="summary" data-id="${encodeURIComponent(paper.id)}" ${summaryLoading ? "disabled" : ""}>${summaryLabel}</button>
          <a class="ghost-link" href="${escapeHtml(downloadUrl(paper))}">下载 PDF</a>
          <a class="ghost-link" href="${escapeHtml(paper.paperUrl || "#")}" target="_blank" rel="noreferrer">查看 arXiv</a>
        </div>
      </div>
    </article>
  `;
}

function renderList() {
  const list = currentList();
  refs.allTab.classList.toggle("active", state.activeView === "all");
  refs.favoriteTab.classList.toggle("active", state.activeView === "favorites");
  refs.listHint.textContent =
    state.activeView === "favorites"
      ? "这里保留的是你历史收藏的论文；下载 PDF 与 AI Summary 都可以直接从这里触发。"
      : "每次更新都会结合日期范围与选中的主题进行过滤。";

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
  state.aiSummaryEnabled = Boolean(session.aiSummaryEnabled);
}

function upsertPaperInCollections(updatedPaper) {
  state.papers = state.papers.map((paper) =>
    paper.id === updatedPaper.id ? { ...paper, ...updatedPaper } : paper
  );

  const index = state.favorites.findIndex((paper) => paper.id === updatedPaper.id);
  if (index >= 0) {
    state.favorites[index] = { ...state.favorites[index], ...updatedPaper, isFavorite: true };
  } else if (updatedPaper.isFavorite) {
    state.favorites = [{ ...updatedPaper, isFavorite: true }, ...state.favorites];
  }
}

async function loadFavorites() {
  const payload = await apiFetch("/api/favorites");
  state.favorites = payload.favorites || [];
  syncPaperState();
  updateStats();
  renderList();
}

function buildQuery() {
  const params = new URLSearchParams({
    startDate: refs.startDate.value,
    endDate: refs.endDate.value,
  });
  [...state.selectedTopics].forEach((topic) => params.append("topic", topic));
  return params.toString();
}

async function loadPapers() {
  if (!state.selectedTopics.size) {
    setBanner("至少选择一个关注主题后再更新。", "warning");
    return;
  }

  setLoading(true);
  setBanner("");
  try {
    const payload = await apiFetch(`/api/papers?${buildQuery()}`);
    state.papers = payload.papers || [];
    state.source = payload.source || "";
    state.dateLabel = payload.filters?.label || "未设置";
    syncPaperState();
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
  const paper =
    state.papers.find((item) => item.id === paperId) ||
    state.favorites.find((item) => item.id === paperId);

  if (!paper) {
    return;
  }

  try {
    if (paper.isFavorite) {
      await apiFetch(`/api/favorites/${encodeURIComponent(paperId)}`, { method: "DELETE" });
      state.favorites = state.favorites.filter((item) => item.id !== paperId);
      state.papers = state.papers.map((item) =>
        item.id === paperId ? { ...item, isFavorite: false } : item
      );
      setBanner("已取消收藏。", "info");
    } else {
      const payload = await apiFetch("/api/favorites", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(paper),
      });
      upsertPaperInCollections({ ...payload.paper, isFavorite: true });
      setBanner(payload.message || "已加入收藏。", "success");
    }
    syncPaperState();
    updateStats();
    renderList();
  } catch (error) {
    setBanner(error.message || "收藏操作失败，请稍后重试。", "error");
  }
}

async function generateSummary(paperId) {
  const paper =
    state.papers.find((item) => item.id === paperId) ||
    state.favorites.find((item) => item.id === paperId);

  if (!paper) {
    return;
  }

  state.summaryLoadingIds.add(paperId);
  renderList();

  try {
    const payload = await apiFetch("/api/summary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        paper,
        favorite: paper.isFavorite,
        force: Boolean(paper.aiSummary),
      }),
    });
    upsertPaperInCollections({
      ...payload.paper,
      isFavorite: paper.isFavorite || payload.paper.isFavorite,
    });
    syncPaperState();
    setBanner(payload.message || "AI Summary 已更新。", "success");
  } catch (error) {
    setBanner(error.message || "AI Summary 生成失败，请稍后重试。", "error");
  } finally {
    state.summaryLoadingIds.delete(paperId);
    updateStats();
    renderList();
  }
}

async function logout() {
  try {
    await apiFetch("/api/logout", { method: "POST" });
  } finally {
    window.location.href = "/login";
  }
}

function activateView(view) {
  state.activeView = view;
  renderList();
  document.querySelector(".list-card")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function toggleTopic(topic) {
  if (state.selectedTopics.has(topic)) {
    state.selectedTopics.delete(topic);
  } else {
    state.selectedTopics.add(topic);
  }
  renderTopicSelector();
}

function resetFilters() {
  setDefaultDates();
  state.selectedTopics = new Set(TOPIC_OPTIONS);
  renderTopicSelector();
  setBanner("筛选条件已重置。", "info");
}

function handleTopicClick(event) {
  const button = event.target.closest("[data-topic]");
  if (!button) {
    return;
  }
  toggleTopic(button.dataset.topic);
}

function handleGridClick(event) {
  const button = event.target.closest("[data-action]");
  if (!button) {
    return;
  }
  const paperId = decodeURIComponent(button.dataset.id);
  const action = button.dataset.action;
  if (action === "favorite") {
    toggleFavorite(paperId);
  } else if (action === "summary") {
    generateSummary(paperId);
  }
}

async function handleRefresh(event) {
  event.preventDefault();
  await loadPapers();
}

async function bootstrap() {
  setDefaultDates();
  renderTopicSelector();
  await loadSession();
  await loadFavorites();
  await loadPapers();
}

refs.filterForm?.addEventListener("submit", handleRefresh);
refs.resetFiltersButton?.addEventListener("click", resetFilters);
refs.selectAllTopicsButton?.addEventListener("click", () => {
  state.selectedTopics = new Set(TOPIC_OPTIONS);
  renderTopicSelector();
});
refs.topicSelector?.addEventListener("click", handleTopicClick);
refs.paperGrid?.addEventListener("click", handleGridClick);
refs.allTab?.addEventListener("click", () => activateView("all"));
refs.favoriteTab?.addEventListener("click", () => activateView("favorites"));
refs.favoritesShortcut?.addEventListener("click", () => activateView("favorites"));
refs.logoutButton?.addEventListener("click", logout);

bootstrap();
