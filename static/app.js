document.addEventListener("DOMContentLoaded", () => {
  console.log("[PAGE]      페이지 로드 및 탭 초기화 완료");

  // ================= 1. 공통 포맷터 & 유틸 =================
  window.InvestmentHelpers = {
    formatPrice(val) {
      if (val === null || val === undefined) return "-";
      return `${Number(val).toLocaleString("ko-KR")}원`;
    },
    formatKoreanWon(val) {
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
    },
    formatUnit(val, unit) {
      if (val === null || val === undefined) return "-";
      return `${val}${unit}`;
    },
    formatMarkdown(text) {
      if (!text) return "";
      // XSS 방지를 위한 HTML 이스케이프
      let html = String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");

      // 코드 블록 및 인라인 코드
      html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
      // 굵은 글씨 (**text**)
      html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

      // 줄 단위 변환 (제목, 구분선, 목록)
      const lines = html.split("\n");
      const out = [];
      let inList = false;

      for (const rawLine of lines) {
        const line = rawLine.trim();
        if (/^---+$/.test(line)) {
          if (inList) { out.push("</ul>"); inList = false; }
          out.push("<hr>");
        } else if (/^###\s+(.+)$/.test(line)) {
          if (inList) { out.push("</ul>"); inList = false; }
          out.push(`<h4>${line.replace(/^###\s+/, "")}</h4>`);
        } else if (/^##\s+(.+)$/.test(line)) {
          if (inList) { out.push("</ul>"); inList = false; }
          out.push(`<h3>${line.replace(/^##\s+/, "")}</h3>`);
        } else if (/^[-*]\s+(.+)$/.test(line)) {
          if (!inList) { out.push("<ul>"); inList = true; }
          out.push(`<li>${line.replace(/^[-*]\s+/, "")}</li>`);
        } else if (line === "") {
          if (inList) { out.push("</ul>"); inList = false; }
          out.push('<div class="md-gap"></div>');
        } else {
          if (inList) { out.push("</ul>"); inList = false; }
          out.push(`<p>${line}</p>`);
        }
      }
      if (inList) out.push("</ul>");
      return out.join("");
    },
    setBubbleContent(bubble, role, text) {
      if (role === "bot") {
        bubble.innerHTML = this.formatMarkdown(text);
      } else {
        bubble.textContent = text;
      }
    },
    appendChatBubble(container, role, text) {
      const msgDiv = document.createElement("div");
      msgDiv.className = `chat-msg ${role}`;
      const bubble = document.createElement("div");
      bubble.className = "chat-bubble";
      this.setBubbleContent(bubble, role, text);
      msgDiv.appendChild(bubble);
      container.appendChild(msgDiv);
      container.scrollTop = container.scrollHeight;
      return msgDiv;
    },
  };

  // ================= 2. 3탭 전환 제어 =================
  const tabBtns = document.querySelectorAll(".tab-btn");
  const tabPanels = document.querySelectorAll(".tab-panel");

  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetId = btn.dataset.tab;
      tabBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      tabPanels.forEach((panel) => {
        const isTarget = panel.id === targetId;
        panel.classList.toggle("active", isTarget);
        panel.classList.toggle("hidden", !isTarget);
      });

      console.log(`[TAB]       탭 전환 (${targetId})`);
    });
  });

  // ================= 3. 탭 1: 종목 심층분석 챗봇 (Dify①) =================
  let tab1ConversationId = null;
  let tab1CurrentCode = "";

  const tab1CodeInput = document.getElementById("tab1-code-input");
  const tab1LoadBtn = document.getElementById("tab1-load-btn");
  const tab1ResetBtn = document.getElementById("tab1-reset-btn");
  const tab1QuickBtns = document.querySelectorAll(".tab1-quick");
  const tab1LoadingData = document.getElementById("tab1-loading-data");
  const tab1ChatForm = document.getElementById("tab1-chat-form");
  const tab1QuestionInput = document.getElementById("tab1-question-input");
  const tab1SendBtn = document.getElementById("tab1-send-btn");
  const tab1Messages = document.getElementById("tab1-chat-messages");
  const tab1Error = document.getElementById("tab1-error");
  const tab1SnapshotCard = document.getElementById("tab1-snapshot-card");
  const tab1PartialErrors = document.getElementById("tab1-partial-errors");
  const tab1SuggestedList = document.getElementById("tab1-suggested-questions");
  const tab1DetailsCard = document.getElementById("tab1-details-card");

  let tab1LoadedDeepCode = "";
  let tab1Charts = {
    incomeBar: null,
    incomeLine: null,
    balanceBar: null,
    balanceLine: null,
    cashflowBar: null,
    cashflowLine: null,
  };
  let tab1AllDisclosures = [];
  let tab1ActiveCategory = "전체";
  let tab1DiscExpanded = false;
  let tab1DiscPage = 1;
  const DISC_PAGE_SIZE = 5;

  // 탭 1 내부 빠른 이동 앵커 활성화 표시
  const subtabBtns = document.querySelectorAll(".subtab-btn");
  subtabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      subtabBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
    });
  });

  function getStockLabelForSuggestions(rawVal) {
    const val = (rawVal || "").trim().toUpperCase();
    if (!val) return "이 종목";
    const quickMap = {
      "000660": "SK하이닉스",
      "005930": "삼성전자",
      "069500": "KODEX 200",
      "035420": "NAVER",
      "NVDA": "엔비디아",
      "AAPL": "Apple",
      "SPY": "SPY",
      "SCHD": "SCHD",
    };
    return quickMap[val] || rawVal.trim();
  }

  function renderSuggestedQuestions(stockLabel) {
    const label = getStockLabelForSuggestions(stockLabel);
    const questions = [
      `📊 ${label} 핵심 지표와 밸류에이션(PER·PBR) 요약해줘`,
      `📈 ${label} 최근 실적 추이와 수익성(영업이익률·ROE) 분석해줘`,
      `📰 ${label} 최신 뉴스와 최근 업데이트 이슈 정리해줘`,
      `⚠️ ${label} 현재 기회 요인과 위험 요인은 뭐야?`,
    ];

    tab1SuggestedList.innerHTML = "";
    questions.forEach((q) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "suggested-btn";
      btn.textContent = q;
      btn.addEventListener("click", () => {
        if (tab1SendBtn.disabled) return;
        tab1QuestionInput.value = q;
        tab1ChatForm.requestSubmit();
      });
      tab1SuggestedList.appendChild(btn);
    });
  }

  // 초기 추천 질문 렌더링 및 입력창 변경 시 추천 질문 실시간 반영
  renderSuggestedQuestions(tab1CodeInput.value);
  tab1CodeInput.addEventListener("input", () => {
    renderSuggestedQuestions(tab1CodeInput.value.trim());
  });

  function resetTab1Chat(noticeText = "새 대화를 시작했습니다. 종목과 질문을 입력해 주세요.") {
    tab1ConversationId = null;
    tab1Messages.innerHTML = "";
    window.InvestmentHelpers.appendChatBubble(tab1Messages, "bot", noticeText);
    tab1Error.classList.add("hidden");
  }

  tab1ResetBtn.addEventListener("click", () => resetTab1Chat());

  let tab1LoadSeq = 0;

  async function loadTab1DeepInfo(code, includeBasicFetch = false) {
    const cleanCode = (code || "").trim();
    if (!cleanCode) return;

    const seq = ++tab1LoadSeq;
    tab1LoadingData.classList.remove("hidden");
    tab1Error.classList.add("hidden");

    try {
      const requests = [
        fetch("/api/financials", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code: cleanCode }),
        }).then((r) => r.json().then((d) => ({ ok: r.ok, data: d }))),
        fetch("/api/disclosures", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code: cleanCode }),
        }).then((r) => r.json().then((d) => ({ ok: r.ok, data: d }))),
      ];

      if (includeBasicFetch) {
        requests.push(
          fetch("/fetch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ code: cleanCode }),
          }).then((r) => r.json().then((d) => ({ ok: r.ok, data: d })))
        );
      }

      const results = await Promise.all(requests);
      if (seq !== tab1LoadSeq) return;

      const finRes = results[0];
      const discRes = results[1];
      const fetchRes = includeBasicFetch ? results[2] : null;

      if (fetchRes && fetchRes.ok) {
        renderTab1Snapshot(fetchRes.data);
      } else if (finRes && !finRes.ok) {
        throw new Error(finRes.data.error || "종목 정보를 불러오지 못했습니다.");
      }

      if (finRes && finRes.ok) {
        renderTab1CorpAndStatements(finRes.data);
        tab1LoadedDeepCode = cleanCode;
      }
      if (discRes && discRes.ok) {
        renderTab1DisclosuresSection(discRes.data);
      }
    } catch (err) {
      if (seq !== tab1LoadSeq) return;
      tab1Error.textContent = err.message;
      tab1Error.classList.remove("hidden");
      console.error(`[ERROR]     심층분석 데이터 조회 오류 (${err.message})`);
    } finally {
      if (seq === tab1LoadSeq) {
        tab1LoadingData.classList.add("hidden");
      }
    }
  }

  tab1LoadBtn.addEventListener("click", () => {
    const code = tab1CodeInput.value.trim();
    if (!code) return;
    renderSuggestedQuestions(code);
    resetTab1Chat(`${code} 종목 정보를 불러왔습니다. 아래 추천 질문을 누르거나 직접 질문해 주세요.`);
    loadTab1DeepInfo(code, true);
  });

  tab1CodeInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      tab1LoadBtn.click();
    }
  });

  tab1QuickBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const code = btn.dataset.code || "";
      tab1CodeInput.value = code;
      renderSuggestedQuestions(code);
      resetTab1Chat(`${btn.textContent} 선택 완료! 아래 추천 질문을 누르거나 직접 질문해 주세요.`);
      loadTab1DeepInfo(code, true);
    });
  });

  // 초기 접속 시 기본 종목(000660 SK하이닉스) 데이터·재무분석·공시 즉시 로드
  loadTab1DeepInfo(tab1CodeInput.value || "000660", true);

  tab1ChatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const code = tab1CodeInput.value.trim();
    const question = tab1QuestionInput.value.trim();

    if (!code) {
      tab1Error.textContent = "종목코드 6자리 또는 종목명을 입력해 주세요.";
      tab1Error.classList.remove("hidden");
      return;
    }
    if (!question) return;

    // 종목이 바뀌면 기존 대화 세션 초기화
    if (tab1CurrentCode && tab1CurrentCode !== code) {
      tab1ConversationId = null;
    }
    tab1CurrentCode = code;

    tab1Error.classList.add("hidden");
    window.InvestmentHelpers.appendChatBubble(tab1Messages, "user", `[${code}] ${question}`);
    tab1QuestionInput.value = "";

    const loadingBubble = window.InvestmentHelpers.appendChatBubble(
      tab1Messages,
      "bot",
      "네이버 금융 및 뉴스 데이터를 수집해 Dify 종목분석기가 답변을 작성 중입니다..."
    );

    tab1SendBtn.disabled = true;
    tab1SendBtn.textContent = "분석 중...";
    tab1SuggestedList.querySelectorAll(".suggested-btn").forEach((b) => { b.disabled = true; });
    console.log(`[CHAT]      Dify 챗봇 요청 시작 (tab=tab1, code=${code})`);

    try {
      const resp = await fetch("/api/chat/analysis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code,
          question,
          conversation_id: tab1ConversationId,
        }),
      });
      const data = await resp.json();

      if (!resp.ok) {
        throw new Error(data.error || `요청 실패 (HTTP ${resp.status})`);
      }

      tab1ConversationId = data.conversation_id || tab1ConversationId;
      window.InvestmentHelpers.setBubbleContent(
        loadingBubble.querySelector(".chat-bubble"),
        "bot",
        data.answer || "(응답 내용이 없습니다.)"
      );
      tab1Messages.scrollTop = tab1Messages.scrollHeight;

      if (data.stock) {
        renderTab1Snapshot(data.stock);
        if (tab1LoadedDeepCode !== data.stock.code) {
          loadTab1DeepInfo(data.stock.code, false);
        }
      }
      console.log("[CHAT]      Dify 챗봇 응답 렌더링 완료 (tab=tab1)");
    } catch (err) {
      loadingBubble.remove();
      tab1Error.textContent = err.message;
      tab1Error.classList.remove("hidden");
      console.error(`[ERROR]     요청 중 오류 발생 (${err.message})`);
    } finally {
      tab1SendBtn.disabled = false;
      tab1SendBtn.textContent = "질문 전송";
      tab1SuggestedList.querySelectorAll(".suggested-btn").forEach((b) => { b.disabled = false; });
    }
  });

  function renderTab1Snapshot(stock) {
    const { formatPrice, formatKoreanWon, formatUnit } = window.InvestmentHelpers;
    const snap = stock.snapshot || {};
    const isUsd = stock.currency === "USD";
    const fmtMoney = (v) => (v === null || v === undefined ? "-" : isUsd ? `$${Number(v).toLocaleString("en-US")}` : formatPrice(v));
    const fmtMcap = (v) => {
      if (v === null || v === undefined) return "-";
      if (!isUsd) return formatKoreanWon(v);
      return v >= 1_000_000_000 ? `$${(v / 1_000_000_000).toFixed(2)}B` : `$${(v / 1_000_000).toFixed(1)}M`;
    };

    if (stock.name) {
      renderSuggestedQuestions(stock.name);
    }

    document.getElementById("tab1-stock-name").textContent = stock.name || "-";
    document.getElementById("tab1-stock-code").textContent = `${stock.code || "-"}${stock.is_etf ? " · ETF" : ""}`;

    const priceEl = document.getElementById("tab1-price");
    const rateEl = document.getElementById("tab1-rate");
    priceEl.textContent = fmtMoney(snap.current_price);
    priceEl.className = "current-price";
    rateEl.className = "change-rate";

    if (snap.change_rate > 0) {
      rateEl.textContent = `+${snap.change_rate}%`;
      priceEl.classList.add("up");
      rateEl.classList.add("up");
    } else if (snap.change_rate < 0) {
      rateEl.textContent = `${snap.change_rate}%`;
      priceEl.classList.add("down");
      rateEl.classList.add("down");
    } else {
      rateEl.textContent = snap.change_rate === 0 ? "0.00%" : "-";
      rateEl.classList.add("flat");
    }

    document.getElementById("tab1-mcap").textContent = fmtMcap(snap.market_cap);
    document.getElementById("tab1-per").textContent = `${formatUnit(snap.per, "배")} / ${formatUnit(snap.estimated_per, "배")}`;
    document.getElementById("tab1-pbr").textContent = formatUnit(snap.pbr, "배");
    document.getElementById("tab1-foreign").textContent = formatUnit(snap.foreign_rate, "%");
    document.getElementById("tab1-dividend").textContent = formatUnit(snap.dividend_yield, "%");
    document.getElementById("tab1-52w").textContent = `${fmtMoney(snap.high_52w)} / ${fmtMoney(snap.low_52w)}`;
    document.getElementById("tab1-news-count").textContent = `${(stock.news || []).length}건`;
    document.getElementById("tab1-updated-at").textContent = new Date().toLocaleTimeString("ko-KR", {
      hour: "2-digit",
      minute: "2-digit",
    });

    const errors = stock.errors || [];
    if (errors.length > 0) {
      tab1PartialErrors.textContent = `참고(일부 수집 제한): ${errors.join(" | ")}`;
      tab1PartialErrors.classList.remove("hidden");
    } else {
      tab1PartialErrors.classList.add("hidden");
    }

    tab1SnapshotCard.classList.remove("hidden");

    // 핵심 실적 업데이트 내역 테이블 렌더링
    const finTbody = document.getElementById("tab1-financials-tbody");
    finTbody.innerHTML = "";
    const financials = stock.financials || [];
    if (financials.length === 0) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 6;
      td.style.textAlign = "center";
      td.textContent = "표시할 실적 데이터가 없습니다.";
      tr.appendChild(td);
      finTbody.appendChild(tr);
    } else {
      financials.forEach((row) => {
        const tr = document.createElement("tr");
        if (row.is_consensus) tr.classList.add("consensus-row");

        const periodTd = document.createElement("td");
        periodTd.textContent = row.period || "-";
        tr.appendChild(periodTd);

        const typeTd = document.createElement("td");
        const badge = document.createElement("span");
        badge.className = row.is_consensus ? "consensus-badge" : "actual-badge";
        badge.textContent = row.is_consensus ? "추정(E)" : "확정";
        typeTd.appendChild(badge);
        tr.appendChild(typeTd);

        [
          formatKoreanWon(row.revenue),
          formatKoreanWon(row.operating_income),
          formatUnit(row.operating_margin, "%"),
          formatUnit(row.roe, "%"),
        ].forEach((txt) => {
          const td = document.createElement("td");
          td.textContent = txt;
          tr.appendChild(td);
        });

        finTbody.appendChild(tr);
      });
    }

    // 관련 최신 뉴스 링크 리스트 렌더링 (제목 + 클릭 시 새 창 바로 이동)
    const newsUl = document.getElementById("tab1-news-list");
    newsUl.innerHTML = "";
    const newsList = stock.news || [];
    if (newsList.length === 0) {
      const li = document.createElement("li");
      li.className = "news-item";
      li.textContent = "수집된 최신 뉴스가 없습니다.";
      newsUl.appendChild(li);
    } else {
      newsList.forEach((item) => {
        const li = document.createElement("li");
        li.className = "news-item";

        const link = document.createElement("a");
        link.className = "news-title";
        link.href = item.url || "#";
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = `${item.title || "(제목 없음)"} ↗`;

        const snippet = document.createElement("p");
        snippet.className = "news-snippet";
        snippet.textContent = item.snippet || "";

        const meta = document.createElement("span");
        meta.className = "news-meta";
        meta.textContent = item.date ? `발행일: ${item.date}` : "";

        li.appendChild(link);
        li.appendChild(snippet);
        li.appendChild(meta);
        newsUl.appendChild(li);
      });
    }

    tab1DetailsCard.classList.remove("hidden");
  }

  // ================= 4. 탭 2: 리밸런싱 도우미 (Dify 없음 - 순수 Python 계산) =================
  let weightChartInstance = null;
  let frontierChartInstance = null;

  const tab2Form = document.getElementById("tab2-form");
  const tab2CodesInput = document.getElementById("tab2-codes-input");
  const tab2CalcBtn = document.getElementById("tab2-calc-btn");
  const tab2QuickBtns = document.querySelectorAll(".tab2-quick");
  const tab2Loading = document.getElementById("tab2-loading");
  const tab2Error = document.getElementById("tab2-error");
  const tab2Result = document.getElementById("tab2-result");

  tab2QuickBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      tab2CodesInput.value = btn.dataset.codes || "";
      tab2Form.requestSubmit();
    });
  });

  tab2Form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const codes = tab2CodesInput.value.trim();
    if (!codes) return;

    console.log(`[REBALANCE] 리밸런싱 시뮬레이션 요청 (codes=${codes})`);
    tab2Loading.classList.remove("hidden");
    tab2Error.classList.add("hidden");
    tab2CalcBtn.disabled = true;
    tab2CalcBtn.textContent = "계산 중...";

    try {
      const resp = await fetch("/api/rebalance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ codes }),
      });
      const data = await resp.json();

      if (!resp.ok) {
        throw new Error(data.error || `계산 실패 (HTTP ${resp.status})`);
      }

      renderTab2Result(data);
      tab2Result.classList.remove("hidden");
      console.log("[REBALANCE] 리밸런싱 결과 및 차트 렌더링 완료");
    } catch (err) {
      tab2Result.classList.add("hidden");
      tab2Error.textContent = err.message;
      tab2Error.classList.remove("hidden");
      console.error(`[ERROR]     요청 중 오류 발생 (${err.message})`);
    } finally {
      tab2Loading.classList.add("hidden");
      tab2CalcBtn.disabled = false;
      tab2CalcBtn.textContent = "적정 비중 계산";
    }
  });

  function renderTab2Result(data) {
    const opt = data.optimal || {};
    const period = data.period || {};
    const assets = data.assets || [];

    document.getElementById("tab2-period").textContent =
      `분석 기간: ${period.start} ~ ${period.end} (${period.trading_days}거래일)`;
    document.getElementById("tab2-opt-ret").textContent = `${opt.expected_return}%`;
    document.getElementById("tab2-opt-vol").textContent = `${opt.volatility}%`;
    document.getElementById("tab2-opt-sharpe").textContent = `${opt.sharpe_ratio}`;
    document.getElementById("tab2-opt-mdd").textContent = `${opt.mdd}%`;

    // 종목별 표 렌더링
    const tbody = document.getElementById("tab2-tbody");
    tbody.innerHTML = "";
    assets.forEach((a) => {
      const tr = document.createElement("tr");
      const cols = [
        a.name,
        a.code,
        `${a.weight}%`,
        `${a.min_vol_weight}%`,
        `${a.annual_return}%`,
        `${a.annual_volatility}%`,
        `${a.mdd}%`,
      ];
      cols.forEach((txt, idx) => {
        const td = document.createElement("td");
        td.textContent = txt;
        if (idx === 2) {
          td.style.fontWeight = "700";
          td.style.color = "#3182f6";
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });

    // 1) 적정 비중 도넛 차트
    const weightCtx = document.getElementById("rebalance-weight-chart").getContext("2d");
    if (weightChartInstance) weightChartInstance.destroy();
    weightChartInstance = new Chart(weightCtx, {
      type: "doughnut",
      data: {
        labels: assets.map((a) => `${a.name} (${a.weight}%)`),
        datasets: [
          {
            data: assets.map((a) => a.weight),
            backgroundColor: ["#3182f6", "#f04452", "#10b981", "#f59e0b", "#8b5cf6", "#06b6d4"],
            borderWidth: 2,
            borderColor: "#ffffff",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom" },
        },
      },
    });

    // 2) 효율적 프론티어 산점도 차트
    const frontierCtx = document.getElementById("rebalance-frontier-chart").getContext("2d");
    if (frontierChartInstance) frontierChartInstance.destroy();
    const samples = (data.frontier_samples || []).map((pt) => ({ x: pt.x, y: pt.y }));

    frontierChartInstance = new Chart(frontierCtx, {
      type: "scatter",
      data: {
        datasets: [
          {
            label: "시뮬레이션 조합",
            data: samples,
            backgroundColor: "rgba(49, 130, 246, 0.35)",
            pointRadius: 3.5,
          },
          {
            label: "최적 포트폴리오 (최대 샤프)",
            data: [{ x: opt.volatility, y: opt.expected_return }],
            backgroundColor: "#f04452",
            pointRadius: 8,
            pointHoverRadius: 10,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { title: { display: true, text: "연 변동성 (위험도 %)" } },
          y: { title: { display: true, text: "연 기대수익률 (%)" } },
        },
        plugins: {
          legend: { position: "bottom" },
        },
      },
    });
  }

  // ================= 5. 탭 3: 기술지표 차트 + Dify 지표해석기 챗봇 (Dify③) =================
  let techPriceChartInstance = null;
  let techRsiChartInstance = null;
  let tab3Indicators = null;
  let tab3StockInfo = { code: "", name: "" };
  let tab3ConversationId = null;

  const tab3CalcForm = document.getElementById("tab3-calc-form");
  const tab3CodeInput = document.getElementById("tab3-code-input");
  const tab3CalcBtn = document.getElementById("tab3-calc-btn");
  const tab3QuickBtns = document.querySelectorAll(".tab3-quick");
  const tab3Loading = document.getElementById("tab3-loading");
  const tab3Error = document.getElementById("tab3-error");
  const tab3Result = document.getElementById("tab3-result");

  const tab3ChatForm = document.getElementById("tab3-chat-form");
  const tab3QuestionInput = document.getElementById("tab3-question-input");
  const tab3SendBtn = document.getElementById("tab3-send-btn");
  const tab3ChatMessages = document.getElementById("tab3-chat-messages");
  const tab3ChatError = document.getElementById("tab3-chat-error");

  tab3QuickBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      tab3CodeInput.value = btn.dataset.code || "";
      tab3CalcForm.requestSubmit();
    });
  });

  tab3CalcForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const code = tab3CodeInput.value.trim();
    if (!code) return;

    tab3Loading.classList.remove("hidden");
    tab3Error.classList.add("hidden");
    tab3CalcBtn.disabled = true;
    tab3CalcBtn.textContent = "계산 중...";

    try {
      const resp = await fetch("/api/technical", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
      const data = await resp.json();

      if (!resp.ok) {
        throw new Error(data.error || `계산 실패 (HTTP ${resp.status})`);
      }

      tab3Indicators = data.latest;
      tab3StockInfo = { code: data.code, name: data.name };
      tab3ConversationId = null;

      // 새 종목 계산 시 채팅창 안내 초기화
      tab3ChatMessages.innerHTML = "";
      window.InvestmentHelpers.appendChatBubble(
        tab3ChatMessages,
        "bot",
        `${data.name}(${data.code}) 기술지표 계산이 완료되었습니다! RSI(${data.latest.rsi14}), 볼린저밴드, MACD에 대해 질문해 보세요.`
      );
      tab3ChatError.classList.add("hidden");

      renderTab3Charts(data);
      tab3Result.classList.remove("hidden");
      console.log(`[TECH]      기술지표 계산 및 차트 렌더링 완료 (code=${data.code})`);
    } catch (err) {
      tab3Result.classList.add("hidden");
      tab3Error.textContent = err.message;
      tab3Error.classList.remove("hidden");
      console.error(`[ERROR]     요청 중 오류 발생 (${err.message})`);
    } finally {
      tab3Loading.classList.add("hidden");
      tab3CalcBtn.disabled = false;
      tab3CalcBtn.textContent = "차트 & 지표 계산";
    }
  });

  function renderTab3Charts(data) {
    const { formatPrice } = window.InvestmentHelpers;
    const latest = data.latest || {};
    const series = data.series || {};

    document.getElementById("tab3-stock-title").textContent = `${data.name} (${data.code}) 최신 기술지표`;
    document.getElementById("tab3-latest-date").textContent = `기준일: ${latest.date || "-"}`;

    document.getElementById("tab3-close").textContent = formatPrice(latest.close);
    document.getElementById("tab3-ma").textContent =
      `${formatPrice(latest.ma5)} / ${formatPrice(latest.ma20)} / ${formatPrice(latest.ma60)}`;
    document.getElementById("tab3-rsi").textContent = latest.rsi14 !== null ? `${latest.rsi14}` : "-";
    document.getElementById("tab3-macd").textContent =
      `${latest.macd ?? "-"} / ${latest.macd_signal ?? "-"}`;
    document.getElementById("tab3-bb-upper").textContent = formatPrice(latest.bb_upper);
    document.getElementById("tab3-bb-lower").textContent = formatPrice(latest.bb_lower);

    // 1) 주가 + 이동평균선 + 볼린저밴드 차트
    const priceCtx = document.getElementById("tech-price-chart").getContext("2d");
    if (techPriceChartInstance) techPriceChartInstance.destroy();
    techPriceChartInstance = new Chart(priceCtx, {
      type: "line",
      data: {
        labels: series.dates || [],
        datasets: [
          { label: "종가", data: series.close, borderColor: "#191f28", borderWidth: 2.2, pointRadius: 0 },
          { label: "MA5", data: series.ma5, borderColor: "#f59e0b", borderWidth: 1.5, pointRadius: 0 },
          { label: "MA20", data: series.ma20, borderColor: "#3182f6", borderWidth: 1.5, pointRadius: 0 },
          { label: "MA60", data: series.ma60, borderColor: "#8b5cf6", borderWidth: 1.5, pointRadius: 0 },
          {
            label: "볼린저 상단",
            data: series.bb_upper,
            borderColor: "rgba(240, 68, 82, 0.55)",
            borderWidth: 1.2,
            borderDash: [5, 5],
            pointRadius: 0,
          },
          {
            label: "볼린저 하단",
            data: series.bb_lower,
            borderColor: "rgba(49, 130, 246, 0.55)",
            borderWidth: 1.2,
            borderDash: [5, 5],
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } } },
        scales: { x: { ticks: { maxTicksLimit: 8 } } },
      },
    });

    // 2) RSI (14) 차트
    const rsiCtx = document.getElementById("tech-rsi-chart").getContext("2d");
    if (techRsiChartInstance) techRsiChartInstance.destroy();
    const dates = series.dates || [];
    techRsiChartInstance = new Chart(rsiCtx, {
      type: "line",
      data: {
        labels: dates,
        datasets: [
          { label: "RSI (14)", data: series.rsi14, borderColor: "#3182f6", borderWidth: 2, pointRadius: 0 },
          {
            label: "과매수 (70)",
            data: dates.map(() => 70),
            borderColor: "rgba(240, 68, 82, 0.6)",
            borderWidth: 1,
            borderDash: [4, 4],
            pointRadius: 0,
          },
          {
            label: "과매도 (30)",
            data: dates.map(() => 30),
            borderColor: "rgba(16, 185, 129, 0.7)",
            borderWidth: 1,
            borderDash: [4, 4],
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } } },
        scales: {
          x: { ticks: { maxTicksLimit: 8 } },
          y: { min: 0, max: 100 },
        },
      },
    });
  }

  tab3ChatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const question = tab3QuestionInput.value.trim();
    if (!question) return;
    if (!tab3Indicators) {
      tab3ChatError.textContent = "먼저 위에서 '차트 & 지표 계산'을 실행해 주세요.";
      tab3ChatError.classList.remove("hidden");
      return;
    }

    tab3ChatError.classList.add("hidden");
    window.InvestmentHelpers.appendChatBubble(tab3ChatMessages, "user", question);
    tab3QuestionInput.value = "";

    const loadingBubble = window.InvestmentHelpers.appendChatBubble(
      tab3ChatMessages,
      "bot",
      "계산된 기술지표 숫자를 지표해석기 챗봇에 전달해 설명을 작성 중입니다..."
    );

    tab3SendBtn.disabled = true;
    tab3SendBtn.textContent = "해석 중...";
    console.log(`[CHAT]      Dify 챗봇 요청 시작 (tab=tab3, code=${tab3StockInfo.code})`);

    try {
      const resp = await fetch("/api/chat/technical", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code: tab3StockInfo.code,
          name: tab3StockInfo.name,
          indicators: tab3Indicators,
          question,
          conversation_id: tab3ConversationId,
        }),
      });
      const data = await resp.json();

      if (!resp.ok) {
        throw new Error(data.error || `요청 실패 (HTTP ${resp.status})`);
      }

      tab3ConversationId = data.conversation_id || tab3ConversationId;
      window.InvestmentHelpers.setBubbleContent(
        loadingBubble.querySelector(".chat-bubble"),
        "bot",
        data.answer || "(응답 내용이 없습니다.)"
      );
      tab3ChatMessages.scrollTop = tab3ChatMessages.scrollHeight;
      console.log("[CHAT]      Dify 챗봇 응답 렌더링 완료 (tab=tab3)");
    } catch (err) {
      loadingBubble.remove();
      tab3ChatError.textContent = err.message;
      tab3ChatError.classList.remove("hidden");
      console.error(`[ERROR]     요청 중 오류 발생 (${err.message})`);
    } finally {
      tab3SendBtn.disabled = false;
      tab3SendBtn.textContent = "지표 해석 요청";
    }
  });

  // ================= 6. 탭 1 내부: 기업설명 + 재무분석(3대 표) + 최근 공시 =================
  function renderStatementTable(tableId, stmt) {
    const table = document.getElementById(tableId);
    table.innerHTML = "";
    const periods = stmt.periods || [];
    const rows = stmt.rows || [];

    if (periods.length === 0 || rows.length === 0) {
      table.innerHTML = "<tbody><tr><td style='text-align:center'>표시할 재무 데이터가 없습니다.</td></tr></tbody>";
      return;
    }

    const thead = document.createElement("thead");
    const headTr = document.createElement("tr");
    const firstTh = document.createElement("th");
    firstTh.textContent = "계정명 (억원)";
    headTr.appendChild(firstTh);
    periods.forEach((p) => {
      const th = document.createElement("th");
      th.textContent = p;
      headTr.appendChild(th);
    });
    thead.appendChild(headTr);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const nameTd = document.createElement("td");
      nameTd.textContent = row.name;
      tr.appendChild(nameTd);

      row.values.forEach((val) => {
        const td = document.createElement("td");
        td.textContent = val === null || val === undefined ? "-" : Number(val).toLocaleString("ko-KR");
        if (val !== null && val < 0) td.style.color = "#3182f6";
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
  }

  function renderStatementDualCharts(barKey, lineKey, barCanvasId, lineCanvasId, stmt, targetKeywords, colors) {
    const periods = stmt.periods || [];
    const rows = stmt.rows || [];

    const barDatasets = [];
    const lineDatasets = [];

    targetKeywords.forEach((kw, idx) => {
      const found = rows.find((r) => r.name.includes(kw));
      if (found) {
        const color = colors[idx % colors.length];
        barDatasets.push({
          label: found.name,
          data: found.values,
          backgroundColor: color,
          borderRadius: 6,
        });
        lineDatasets.push({
          label: found.name,
          data: found.values,
          borderColor: color,
          backgroundColor: color,
          borderWidth: 2.5,
          pointRadius: 4,
          pointHoverRadius: 6,
          tension: 0.25,
          fill: false,
        });
      }
    });

    // 왼쪽: 막대그래프
    const barCtx = document.getElementById(barCanvasId).getContext("2d");
    if (tab1Charts[barKey]) tab1Charts[barKey].destroy();
    tab1Charts[barKey] = new Chart(barCtx, {
      type: "bar",
      data: { labels: periods, datasets: barDatasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } } },
      },
    });

    // 오른쪽: 꺾은선형 차트
    const lineCtx = document.getElementById(lineCanvasId).getContext("2d");
    if (tab1Charts[lineKey]) tab1Charts[lineKey].destroy();
    tab1Charts[lineKey] = new Chart(lineCtx, {
      type: "line",
      data: { labels: periods, datasets: lineDatasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } } },
      },
    });
  }

  // 그래프 아래 상세 표 펼치기/접기 토글 버튼 (중복 텍스트 없이 data-title 기반 고정)
  document.querySelectorAll(".toggle-table-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetId = btn.dataset.target;
      const wrap = document.getElementById(targetId);
      if (!wrap) return;
      const isHidden = wrap.classList.toggle("hidden");
      const baseTitle = btn.dataset.title || "📋 전체 표";
      btn.textContent = isHidden ? `${baseTitle} 보기 ▼` : `${baseTitle} 접기 ▲`;
    });
  });

  let tab1EtfHoldingsChart = null;

  function renderTab1EtfSection(data) {
    const etf = data.etf_info || {};
    document.getElementById("tab1-etf-base-badge").textContent = `기초지수: ${etf.base_index || "-"}`;
    document.getElementById("tab1-etf-issuer").textContent = etf.issuer || "-";
    document.getElementById("tab1-etf-nav").textContent = etf.total_nav || "-";
    document.getElementById("tab1-etf-fee").textContent =
      etf.total_fee !== null && etf.total_fee !== undefined ? `${etf.total_fee}%` : "-";
    document.getElementById("tab1-etf-div").textContent =
      etf.dividend_yield !== null && etf.dividend_yield !== undefined ? `${etf.dividend_yield}%` : "-";
    document.getElementById("tab1-etf-dev").textContent =
      etf.deviation_rate !== null && etf.deviation_rate !== undefined ? `${etf.deviation_rate}%` : "-";
    document.getElementById("tab1-etf-ret1y").textContent =
      etf.return_1y !== null && etf.return_1y !== undefined ? `${etf.return_1y}%` : "-";

    const holdings = etf.holdings || [];
    const tbody = document.getElementById("tab1-etf-holdings-tbody");
    tbody.innerHTML = "";

    if (holdings.length === 0) {
      tbody.innerHTML = "<tr><td colspan='3' style='text-align:center'>구성종목 정보가 없습니다.</td></tr>";
    } else {
      holdings.forEach((h) => {
        const tr = document.createElement("tr");
        const nameTd = document.createElement("td");
        nameTd.textContent = h.name;
        const codeTd = document.createElement("td");
        codeTd.textContent = h.code || "-";
        const wTd = document.createElement("td");
        wTd.textContent = `${h.weight}%`;
        wTd.style.fontWeight = "700";
        wTd.style.color = "#1d4ed8";
        tr.appendChild(nameTd);
        tr.appendChild(codeTd);
        tr.appendChild(wTd);
        tbody.appendChild(tr);
      });
    }

    const ctx = document.getElementById("tab1-etf-holdings-chart").getContext("2d");
    if (tab1EtfHoldingsChart) tab1EtfHoldingsChart.destroy();
    tab1EtfHoldingsChart = new Chart(ctx, {
      type: "doughnut",
      data: {
        labels: holdings.map((h) => `${h.name} (${h.weight}%)`),
        datasets: [
          {
            data: holdings.map((h) => h.weight),
            backgroundColor: [
              "#1d4ed8", "#2563eb", "#3b82f6", "#60a5fa", "#93c5fd",
              "#0f766e", "#10b981", "#f59e0b", "#64748b", "#94a3b8",
            ],
            borderWidth: 2,
            borderColor: "#ffffff",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: "bottom", labels: { boxWidth: 11 } } },
      },
    });
  }

  function renderTab1CorpAndStatements(data) {
    const descBox = document.getElementById("tab1-descriptions");
    descBox.innerHTML = "";
    const descs = data.descriptions || [];
    if (descs.length === 0) {
      descBox.innerHTML = "<p>등록된 종목 설명이 없습니다.</p>";
    } else {
      descs.forEach((text) => {
        const p = document.createElement("p");
        p.textContent = `• ${text}`;
        descBox.appendChild(p);
      });
    }

    const sources = data.description_sources || [];
    if (sources.length > 0) {
      const srcP = document.createElement("p");
      srcP.style.marginTop = "8px";
      srcP.style.fontSize = "0.85rem";
      srcP.style.color = "#64748b";
      srcP.appendChild(document.createTextNode("🔎 검증 출처: "));
      sources.forEach((src, idx) => {
        if (idx > 0) srcP.appendChild(document.createTextNode(" · "));
        const a = document.createElement("a");
        a.href = src.url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.textContent = `${src.label} ↗`;
        a.style.color = "#2563eb";
        a.style.textDecoration = "underline";
        srcP.appendChild(a);
      });
      descBox.appendChild(srcP);
    }

    const etfPanel = document.getElementById("subtab-etf");
    const finPanel = document.getElementById("subtab-finance");
    const discPanel = document.getElementById("subtab-disclosure");

    if (data.is_etf) {
      etfPanel.classList.remove("hidden");
      finPanel.classList.add("hidden");
      discPanel.classList.add("hidden");
      renderTab1EtfSection(data);
    } else {
      etfPanel.classList.add("hidden");
      finPanel.classList.remove("hidden");
      discPanel.classList.remove("hidden");

      const stmts = data.statements || {};
      const income = stmts.income || {};
      const balance = stmts.balance || {};
      const cashflow = stmts.cashflow || {};

      renderStatementTable("tab1-income-table", income);
      renderStatementDualCharts(
        "incomeBar",
        "incomeLine",
        "tab1-income-bar-chart",
        "tab1-income-line-chart",
        income,
        ["매출액", "영업이익", "당기순이익"],
        ["rgba(29, 78, 216, 0.85)", "rgba(225, 29, 72, 0.85)", "rgba(16, 185, 129, 0.9)"]
      );

      renderStatementTable("tab1-balance-table", balance);
      renderStatementDualCharts(
        "balanceBar",
        "balanceLine",
        "tab1-balance-bar-chart",
        "tab1-balance-line-chart",
        balance,
        ["자산총계", "부채총계", "자본총계"],
        ["rgba(29, 78, 216, 0.85)", "rgba(245, 158, 11, 0.9)", "rgba(16, 185, 129, 0.9)"]
      );

      renderStatementTable("tab1-cashflow-table", cashflow);
      renderStatementDualCharts(
        "cashflowBar",
        "cashflowLine",
        "tab1-cashflow-bar-chart",
        "tab1-cashflow-line-chart",
        cashflow,
        ["영업활동", "투자활동", "재무활동"],
        ["rgba(16, 185, 129, 0.9)", "rgba(225, 29, 72, 0.85)", "rgba(139, 92, 246, 0.9)"]
      );
    }

    tab1SnapshotCard.classList.remove("hidden");
    tab1DetailsCard.classList.remove("hidden");
  }

  function renderTab1DisclosuresSection(data) {
    tab1AllDisclosures = data.disclosures || [];
    tab1ActiveCategory = "전체";
    tab1DiscExpanded = false;
    tab1DiscPage = 1;

    const isUs = Boolean(data.is_us);
    const sourceLabel = isUs ? "SEC" : "DART";

    document.getElementById("tab1-disc-title").textContent = `${data.name} (${data.code}) 최근 공시 (${sourceLabel})`;
    document.getElementById("tab1-market-badge").textContent = data.market || (isUs ? "US (SEC EDGAR)" : "KOSPI");

    const linksTitle = document.getElementById("tab1-disc-links-title");
    const homeLink = document.getElementById("tab1-disc-home-link");
    const link2 = document.getElementById("tab1-disc-link-2");
    const link3 = document.getElementById("tab1-disc-link-3");
    const dartCorpLink = document.getElementById("tab1-dart-corp-link");

    if (isUs) {
      linksTitle.textContent = "🏛️ SEC EDGAR 바로가기:";
      homeLink.href = data.dart_links?.home || "https://www.sec.gov/edgar/searchedgar/companysearch";
      homeLink.textContent = "SEC EDGAR 검색 ↗";
      link2.href = data.dart_links?.browse || data.dart_links?.corp_search || "https://www.sec.gov/edgar/searchedgar/companysearch";
      link2.textContent = `${data.code} SEC 기업페이지 ↗`;
      link2.classList.remove("hidden");
      link3.classList.add("hidden");
      if (data.dart_links?.corp_search) {
        dartCorpLink.href = data.dart_links.corp_search;
        dartCorpLink.textContent = `${data.name} SEC 공시검색 ↗`;
        dartCorpLink.classList.remove("hidden");
      }
    } else {
      linksTitle.textContent = "🏛️ DART 바로가기:";
      homeLink.href = data.dart_links?.home || "https://dart.fss.or.kr/";
      homeLink.textContent = "DART 메인 ↗";
      link2.href = data.dart_links?.kospi || "https://dart.fss.or.kr/dsac001/mainY.do";
      link2.textContent = "유가증권시장(코스피) 최근공시 ↗";
      link2.classList.remove("hidden");
      link3.href = data.dart_links?.kosdaq || "https://dart.fss.or.kr/dsac001/mainK.do?selectDate=&sort=&series=&mdayCnt=0";
      link3.textContent = "코스닥시장 최근공시 ↗";
      link3.classList.remove("hidden");
      if (data.dart_links?.corp_search) {
        dartCorpLink.href = data.dart_links.corp_search;
        dartCorpLink.textContent = `${data.name} DART 공시검색 ↗`;
        dartCorpLink.classList.remove("hidden");
      }
    }

    renderTab1CategoryFilters();
    renderTab1Disclosures();
    tab1DetailsCard.classList.remove("hidden");
  }

  document.getElementById("tab1-disc-toggle-btn").addEventListener("click", () => {
    tab1DiscExpanded = !tab1DiscExpanded;
    tab1DiscPage = 1;
    renderTab1Disclosures();
  });

  function renderTab1CategoryFilters() {
    const categories = [
      "전체",
      "정기보고서",
      "실적",
      "자사주 취득",
      "자사주 처분",
      "주주환원",
      "임원/주요주주",
      "기타 공시",
    ];
    const bar = document.getElementById("tab1-category-filters");
    bar.innerHTML = "";

    categories.forEach((cat) => {
      const count =
        cat === "전체"
          ? tab1AllDisclosures.length
          : tab1AllDisclosures.filter((d) => d.category === cat).length;

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `filter-chip ${tab1ActiveCategory === cat ? "active" : ""}`;
      btn.textContent = `${cat} (${count})`;
      btn.addEventListener("click", () => {
        tab1ActiveCategory = cat;
        tab1DiscPage = 1;
        renderTab1CategoryFilters();
        renderTab1Disclosures();
      });
      bar.appendChild(btn);
    });
  }

  function renderTab1Disclosures() {
    const ul = document.getElementById("tab1-disclosure-list");
    const paginationBar = document.getElementById("tab1-disc-pagination");
    const toggleBtn = document.getElementById("tab1-disc-toggle-btn");

    ul.innerHTML = "";
    paginationBar.innerHTML = "";

    const filtered =
      tab1ActiveCategory === "전체"
        ? tab1AllDisclosures
        : tab1AllDisclosures.filter((d) => d.category === tab1ActiveCategory);

    if (filtered.length === 0) {
      paginationBar.classList.add("hidden");
      toggleBtn.classList.add("hidden");
      const li = document.createElement("li");
      li.className = "news-item";
      li.textContent = `'${tab1ActiveCategory}' 분류에 해당하는 최근 공시가 없습니다.`;
      ul.appendChild(li);
      return;
    }

    const totalPages = Math.ceil(filtered.length / DISC_PAGE_SIZE);
    if (tab1DiscPage > totalPages) tab1DiscPage = totalPages;

    let visibleItems = [];
    if (!tab1DiscExpanded) {
      visibleItems = filtered.slice(0, DISC_PAGE_SIZE);
      paginationBar.classList.add("hidden");
    } else {
      const startIdx = (tab1DiscPage - 1) * DISC_PAGE_SIZE;
      visibleItems = filtered.slice(startIdx, startIdx + DISC_PAGE_SIZE);

      // 하단 1, 2, 3... 페이지 번호 버튼 생성
      if (totalPages > 1) {
        for (let p = 1; p <= totalPages; p++) {
          const pBtn = document.createElement("button");
          pBtn.type = "button";
          pBtn.className = `page-btn ${p === tab1DiscPage ? "active" : ""}`;
          pBtn.textContent = String(p);
          pBtn.addEventListener("click", () => {
            tab1DiscPage = p;
            renderTab1Disclosures();
          });
          paginationBar.appendChild(pBtn);
        }
        paginationBar.classList.remove("hidden");
      } else {
        paginationBar.classList.add("hidden");
      }
    }

    // 5개 초과일 때만 전체 보기 / 접기 버튼 표시
    if (filtered.length > DISC_PAGE_SIZE) {
      toggleBtn.classList.remove("hidden");
      toggleBtn.textContent = tab1DiscExpanded
        ? "📑 공시 5개만 보기 ▲"
        : `📑 전체 공시 보기 (총 ${filtered.length}건 · 페이지 이동) ▼`;
    } else {
      toggleBtn.classList.add("hidden");
    }

    visibleItems.forEach((item) => {
      const li = document.createElement("li");
      li.className = "news-item";

      const badge = document.createElement("span");
      badge.className = "disc-cat-badge";
      badge.textContent = item.category;

      const link = document.createElement("a");
      link.className = "news-title";
      link.href = item.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = `${item.title} ↗`;

      const actions = document.createElement("div");
      actions.className = "disc-actions";

      const meta = document.createElement("span");
      meta.className = "news-meta";
      meta.textContent = `${item.datetime} · ${item.author}`;

      const dartLink = document.createElement("a");
      dartLink.className = "disc-dart-link";
      dartLink.href = item.dart_url;
      dartLink.target = "_blank";
      dartLink.rel = "noopener noreferrer";
      dartLink.textContent = item.source === "SEC" ? "SEC EDGAR에서 전체공시 보기 ↗" : "DART에서 전체공시 보기 ↗";

      actions.appendChild(meta);
      actions.appendChild(dartLink);

      li.appendChild(badge);
      li.appendChild(link);
      li.appendChild(actions);
      ul.appendChild(li);
    });
  }
});
