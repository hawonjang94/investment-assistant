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
    appendChatBubble(container, role, text) {
      const msgDiv = document.createElement("div");
      msgDiv.className = `chat-msg ${role}`;
      const bubble = document.createElement("div");
      bubble.className = "chat-bubble";
      bubble.textContent = text;
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
  const tab1ResetBtn = document.getElementById("tab1-reset-btn");
  const tab1QuickBtns = document.querySelectorAll(".tab1-quick");
  const tab1ChatForm = document.getElementById("tab1-chat-form");
  const tab1QuestionInput = document.getElementById("tab1-question-input");
  const tab1SendBtn = document.getElementById("tab1-send-btn");
  const tab1Messages = document.getElementById("tab1-chat-messages");
  const tab1Error = document.getElementById("tab1-error");
  const tab1SnapshotCard = document.getElementById("tab1-snapshot-card");
  const tab1PartialErrors = document.getElementById("tab1-partial-errors");

  function resetTab1Chat(noticeText = "새 대화를 시작했습니다. 종목과 질문을 입력해 주세요.") {
    tab1ConversationId = null;
    tab1Messages.innerHTML = "";
    window.InvestmentHelpers.appendChatBubble(tab1Messages, "bot", noticeText);
    tab1Error.classList.add("hidden");
  }

  tab1ResetBtn.addEventListener("click", () => resetTab1Chat());

  tab1QuickBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const code = btn.dataset.code || "";
      tab1CodeInput.value = code;
      resetTab1Chat(`${btn.textContent} 선택 완료! 궁금한 점을 질문해 주세요.`);
    });
  });

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
      loadingBubble.querySelector(".chat-bubble").textContent = data.answer || "(응답 내용이 없습니다.)";

      if (data.stock) {
        renderTab1Snapshot(data.stock);
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
    }
  });

  function renderTab1Snapshot(stock) {
    const { formatPrice, formatKoreanWon, formatUnit } = window.InvestmentHelpers;
    const snap = stock.snapshot || {};

    document.getElementById("tab1-stock-name").textContent = stock.name || "-";
    document.getElementById("tab1-stock-code").textContent = stock.code || "-";

    const priceEl = document.getElementById("tab1-price");
    const rateEl = document.getElementById("tab1-rate");
    priceEl.textContent = formatPrice(snap.current_price);
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

    document.getElementById("tab1-mcap").textContent = formatKoreanWon(snap.market_cap);
    document.getElementById("tab1-per").textContent = `${formatUnit(snap.per, "배")} / ${formatUnit(snap.estimated_per, "배")}`;
    document.getElementById("tab1-pbr").textContent = formatUnit(snap.pbr, "배");
    document.getElementById("tab1-news-count").textContent = `${(stock.news || []).length}건`;

    const errors = stock.errors || [];
    if (errors.length > 0) {
      tab1PartialErrors.textContent = `참고(일부 수집 제한): ${errors.join(" | ")}`;
      tab1PartialErrors.classList.remove("hidden");
    } else {
      tab1PartialErrors.classList.add("hidden");
    }

    tab1SnapshotCard.classList.remove("hidden");
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
      loadingBubble.querySelector(".chat-bubble").textContent = data.answer || "(응답 내용이 없습니다.)";
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
});
