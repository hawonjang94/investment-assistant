document.addEventListener("DOMContentLoaded", () => {
  console.log("[PAGE]    페이지 로드 완료");

  const searchForm = document.getElementById("search-form");
  const codeInput = document.getElementById("stock-code-input");
  const fetchBtn = document.getElementById("fetch-btn");
  const quickBtns = document.querySelectorAll(".quick-btn");

  const loadingBox = document.getElementById("loading-box");
  const errorBox = document.getElementById("error-box");
  const partialErrorsBox = document.getElementById("partial-errors-box");
  const resultContainer = document.getElementById("result-container");

  // 빠른 입력 버튼 이벤트
  quickBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const code = btn.dataset.code || "";
      codeInput.value = code;
      searchForm.requestSubmit();
    });
  });

  // 폼 제출 (데이터 수집 요청)
  searchForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const code = codeInput.value.trim();

    if (!/^\d{6}$/.test(code)) {
      showError("종목코드는 6자리 숫자여야 합니다. (예: 000660)");
      console.error("[ERROR]   수집 중 오류 발생 (유효하지 않은 종목코드 형식)");
      return;
    }

    console.log(`[SEARCH]  종목 수집 요청 시작 (${code})`);
    setLoading(true);
    hideMessages();

    try {
      const response = await fetch("/fetch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });

      const data = await response.json();

      if (!response.ok) {
        const message = data.error || `요청 처리 중 오류가 발생했습니다. (HTTP ${response.status})`;
        throw new Error(message);
      }

      const currentPrice = data.snapshot?.current_price;
      console.log(`[PARSED]  기본 정보 수집 완료 (${data.name}, ${formatPrice(currentPrice)})`);
      console.log(`[NEWS]    뉴스 수집 완료 (${(data.news || []).length}건)`);

      renderStockData(data);
      console.log("[RENDER]  화면 데이터 카드 렌더링 완료");
    } catch (err) {
      console.error(`[ERROR]   수집 중 오류 발생 (${err.message})`);
      resultContainer.classList.add("hidden");
      showError(err.message);
    } finally {
      setLoading(false);
    }
  });

  function setLoading(isLoading) {
    fetchBtn.disabled = isLoading;
    fetchBtn.textContent = isLoading ? "수집 중..." : "데이터 수집";
    loadingBox.classList.toggle("hidden", !isLoading);
  }

  function hideMessages() {
    errorBox.classList.add("hidden");
    errorBox.textContent = "";
    partialErrorsBox.classList.add("hidden");
    partialErrorsBox.innerHTML = "";
  }

  function showError(message) {
    errorBox.textContent = message;
    errorBox.classList.remove("hidden");
  }

  function showPartialErrors(errors) {
    if (!errors || errors.length === 0) return;

    partialErrorsBox.innerHTML = "";
    const title = document.createElement("strong");
    title.textContent = "일부 항목을 가져오지 못했습니다:";
    partialErrorsBox.appendChild(title);

    const list = document.createElement("ul");
    list.style.marginTop = "6px";
    list.style.paddingLeft = "20px";

    errors.forEach((msg) => {
      const li = document.createElement("li");
      li.textContent = msg;
      list.appendChild(li);
    });

    partialErrorsBox.appendChild(list);
    partialErrorsBox.classList.remove("hidden");
  }

  function formatPrice(val) {
    if (val === null || val === undefined) return "-";
    return `${Number(val).toLocaleString("ko-KR")}원`;
  }

  function formatKoreanWon(val) {
    if (val === null || val === undefined) return "-";
    const sign = val < 0 ? "-" : "";
    const absVal = Math.abs(val);
    const eok = Math.round(absVal / 1_0000_0000);

    if (eok >= 10000) {
      const jo = Math.floor(eok / 10000);
      const restEok = eok % 10000;
      return restEok > 0
        ? `${sign}${jo.toLocaleString("ko-KR")}조 ${restEok.toLocaleString("ko-KR")}억`
        : `${sign}${jo.toLocaleString("ko-KR")}조`;
    }
    return `${sign}${eok.toLocaleString("ko-KR")}억`;
  }

  function formatUnit(val, unit) {
    if (val === null || val === undefined) return "-";
    return `${val}${unit}`;
  }

  function renderStockData(data) {
    const snap = data.snapshot || {};

    // 1. 종목 헤더 & 현재가
    document.getElementById("stock-name").textContent = data.name || "-";
    document.getElementById("stock-code-badge").textContent = data.code || "-";

    const priceEl = document.getElementById("current-price");
    const rateEl = document.getElementById("change-rate");
    priceEl.textContent = formatPrice(snap.current_price);

    priceEl.className = "current-price";
    rateEl.className = "change-rate";

    if (snap.change_rate === null || snap.change_rate === undefined) {
      rateEl.textContent = "-";
      rateEl.classList.add("flat");
    } else if (snap.change_rate > 0) {
      rateEl.textContent = `+${snap.change_rate}%`;
      priceEl.classList.add("up");
      rateEl.classList.add("up");
    } else if (snap.change_rate < 0) {
      rateEl.textContent = `${snap.change_rate}%`;
      priceEl.classList.add("down");
      rateEl.classList.add("down");
    } else {
      rateEl.textContent = "0.00%";
      rateEl.classList.add("flat");
    }

    // 2. 핵심 투자 스냅샷 8종
    document.getElementById("metric-market-cap").textContent = formatKoreanWon(snap.market_cap);
    document.getElementById("metric-per").textContent = formatUnit(snap.per, "배");
    document.getElementById("metric-est-per").textContent = formatUnit(snap.estimated_per, "배");
    document.getElementById("metric-pbr").textContent = formatUnit(snap.pbr, "배");
    document.getElementById("metric-foreign-rate").textContent = formatUnit(snap.foreign_rate, "%");
    document.getElementById("metric-dividend-yield").textContent = formatUnit(snap.dividend_yield, "%");
    document.getElementById("metric-high-52w").textContent = formatPrice(snap.high_52w);
    document.getElementById("metric-low-52w").textContent = formatPrice(snap.low_52w);

    // 3. 연간 기업 실적 표
    renderFinancials(data.financials || []);

    // 4. 최신 관련 뉴스
    renderNews(data.news || []);

    // 5. 부분 오류 알림 (있을 경우에만)
    showPartialErrors(data.errors || []);

    resultContainer.classList.remove("hidden");
  }

  function renderFinancials(financials) {
    const tbody = document.getElementById("financials-tbody");
    tbody.innerHTML = "";

    if (financials.length === 0) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 8;
      td.style.textAlign = "center";
      td.textContent = "표시할 실적 데이터가 없습니다.";
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }

    financials.forEach((row) => {
      const tr = document.createElement("tr");
      if (row.is_consensus) {
        tr.classList.add("consensus-row");
      }

      const periodTd = document.createElement("td");
      periodTd.textContent = row.period || "-";
      tr.appendChild(periodTd);

      const typeTd = document.createElement("td");
      const badge = document.createElement("span");
      if (row.is_consensus) {
        badge.className = "consensus-badge";
        badge.textContent = "추정(E)";
      } else {
        badge.className = "actual-badge";
        badge.textContent = "확정";
      }
      typeTd.appendChild(badge);
      tr.appendChild(typeTd);

      const cells = [
        formatKoreanWon(row.revenue),
        formatKoreanWon(row.operating_income),
        formatKoreanWon(row.net_income),
        formatUnit(row.operating_margin, "%"),
        formatUnit(row.roe, "%"),
        formatUnit(row.debt_ratio, "%"),
      ];

      cells.forEach((text) => {
        const td = document.createElement("td");
        td.textContent = text;
        tr.appendChild(td);
      });

      tbody.appendChild(tr);
    });
  }

  function renderNews(newsList) {
    const ul = document.getElementById("news-list");
    ul.innerHTML = "";

    if (newsList.length === 0) {
      const li = document.createElement("li");
      li.className = "news-item";
      li.textContent = "표시할 뉴스가 없습니다.";
      ul.appendChild(li);
      return;
    }

    newsList.forEach((item) => {
      const li = document.createElement("li");
      li.className = "news-item";

      const link = document.createElement("a");
      link.className = "news-title";
      link.href = item.url || "#";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = item.title || "(제목 없음)";

      const snippet = document.createElement("p");
      snippet.className = "news-snippet";
      snippet.textContent = item.snippet || "";

      const meta = document.createElement("span");
      meta.className = "news-meta";
      meta.textContent = item.date ? `발행: ${item.date}` : "";

      li.appendChild(link);
      li.appendChild(snippet);
      li.appendChild(meta);
      ul.appendChild(li);
    });
  }
});
