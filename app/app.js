/* 남해안 고수온 예보 - 화면 동작 (양식장 위치별)
   데이터: data/forecast.js (src/app/build_forecast.py 가 매일 생성) - 관측소별 7일 예보
   양식장 위치 예보: 주변 관측소 예보를 정규 크리깅으로 섞음
     (근거: reports/spatial_experiment - 관측소 하나 빼고 맞히기에서 최근접보다 오차 11% 적고,
      크리깅이 내놓는 불확실성 범위 안에 실제값이 96% 들어옴)
   판정 규칙 (어종별):
     위험 = 예상 수온 >= 위험 수온 - 여유폭(0.75℃)   ※ 모델이 급상승을 작게 예측하는 경향 보정
            (관측된 현재 수온은 여유폭 없이 위험 수온 이상일 때만 위험)
     주의 = 적정 수온 상한보다 높음
     정상 = 그 외 */
(function () {
  "use strict";

  var F = window.FORECAST;
  if (!F || !F.stations) {
    document.querySelector("main").innerHTML =
      '<p class="notice">예보 자료(data/forecast.js)를 찾을 수 없습니다. src/app/build_forecast.py 를 먼저 실행하십시오.</p>';
    return;
  }

  var K = F.kriging;
  var LABEL = { good: "정상", warn: "주의", crit: "위험" };
  var RANK = { good: 0, warn: 1, crit: 2 };
  var WEEK = ["일", "월", "화", "수", "목", "금", "토"];
  var KM_LAT = 111.0, KM_LON = 111.0 * Math.cos(34.5 * Math.PI / 180);

  var ACTIONS = {
    good: [
      "산소공급기·냉각시설을 미리 점검해 두십시오.",
      "영양제를 섞은 사료로 물고기 체력을 길러 두십시오.",
      "여름철에는 어장 주변 수온을 매일 확인하십시오."
    ],
    warn: [
      "사료 주는 양을 줄이십시오.",
      "질병 예방과 치료를 미리 끝내 두십시오.",
      "가두리 그물 청소·교체, 산소공급기·냉각시설 점검을 마치십시오.",
      "조기 출하나 분산 수용을 검토하십시오."
    ],
    crit: [
      "사료 공급을 줄이거나 멈추십시오.",
      "액화산소·산소발생기·저층해수 공급 장비를 모두 가동하십시오.",
      "선별·망갈이처럼 물고기를 놀라게 하는 작업은 하지 마십시오.",
      "어장 수온과 용존산소를 하루 여러 번 직접 재십시오.",
      "폐사가 생기면 시·군청에 바로 신고하십시오."
    ]
  };
  var SPECIES_ACTIONS = {
    "넙치(광어)": {
      warn: "조기 출하·분산을 하고, 사육 수온과 용존산소를 수시로 재십시오.",
      crit: "수온이 낮은 지하해수를 넣고 액화산소를 충분히 공급하십시오."
    },
    "조피볼락(우럭)": {
      warn: "가두리 그물을 교체·청소하고, 긴급 방류에 대비해 질병 검사를 받아 두십시오.",
      crit: "저층 물을 퍼 올려 섞어 주거나 가두리를 가라앉히고, 차광막으로 스트레스를 줄이십시오."
    }
  };

  // ---------- 저장 ----------
  function load(key, fallback) {
    try { var v = localStorage.getItem("hsw2." + key); return v === null ? fallback : v; } catch (e) { return fallback; }
  }
  function save(key, value) {
    try { localStorage.setItem("hsw2." + key, value); } catch (e) { /* 저장 불가 환경은 무시 */ }
  }

  // ---------- 날짜 ----------
  function parse(s) { var p = s.split("-"); return new Date(+p[0], +p[1] - 1, +p[2]); }
  function iso(d) {
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }
  function addDays(s, n) { var d = parse(s); d.setDate(d.getDate() + n); return iso(d); }
  function md(s) { var d = parse(s); return (d.getMonth() + 1) + "월 " + d.getDate() + "일"; }
  function mdw(s) { var d = parse(s); return md(s) + "(" + WEEK[d.getDay()] + ")"; }
  function weekday(s) { return WEEK[parse(s).getDay()] + "요일"; }
  function relative(s) {
    var today = iso(new Date());
    if (s === today) return "오늘";
    if (s === addDays(today, 1)) return "내일";
    if (s === addDays(today, 2)) return "모레";
    return "";
  }
  function t1(v) { return v === null || v === undefined || isNaN(v) ? "-" : v.toFixed(1) + "℃"; }

  // ---------- 관측소 ----------
  var ST = F.stations;
  var byCode = {};
  ST.forEach(function (s) { byCode[s.code] = s; });
  // 최신 예보는 가장 많은 관측소가 가진 기준일로 맞춘다 (자료가 늦게 들어온 관측소는 제외)
  var LATEST = (function () {
    var c = {};
    ST.forEach(function (s) { c[s.issue] = (c[s.issue] || 0) + 1; });
    return Object.keys(c).sort(function (a, b) { return c[b] - c[a]; })[0];
  })();
  var ARCHIVE_DATES = (function () {
    var set = {};
    Object.keys(F.archive).forEach(function (code) { Object.keys(F.archive[code]).forEach(function (d) { set[d] = 1; }); });
    return Object.keys(set).sort().reverse();
  })();

  function km(a, b) { return Math.hypot((a.lon - b.lon) * KM_LON, (a.lat - b.lat) * KM_LAT); }

  // 관측소의 (기준일 수온, 7일 예보, 실제) - 모드별
  function stationValues(s, dateKey) {
    if (dateKey === "latest") {
      if (s.issue !== LATEST) return null;
      return { today: s.today, fc: s.fc, actual: null };
    }
    var a = F.archive[s.code] && F.archive[s.code][dateKey];
    if (!a) return null;
    return { today: a[0], fc: a.slice(1, 8), actual: a.slice(8, 15) };
  }
  function observedOn(s, day, dateKey) {
    if (dateKey === "latest") {
      var i = 13 - Math.round((parse(LATEST) - parse(day)) / 86400000);
      return i >= 0 && i < 14 ? s.obs[i] : null;
    }
    var a = F.archive[s.code] && F.archive[s.code][day];
    return a ? a[0] : null;
  }

  // ---------- 크리깅 ----------
  function vgam(h) { return K.nugget + K.sill * (1 - Math.exp(-h / K.range)); }
  function solve(A, b) {  // 가우스 소거 (부분 피벗)
    var n = b.length, M = A.map(function (row, i) { return row.concat([b[i]]); });
    for (var c = 0; c < n; c++) {
      var p = c;
      for (var r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
      var tmp = M[c]; M[c] = M[p]; M[p] = tmp;
      if (Math.abs(M[c][c]) < 1e-12) return null;
      for (var r2 = c + 1; r2 < n; r2++) {
        var f = M[r2][c] / M[c][c];
        for (var k = c; k <= n; k++) M[r2][k] -= f * M[c][k];
      }
    }
    var x = new Array(n);
    for (var i = n - 1; i >= 0; i--) {
      var sum = M[i][n];
      for (var j = i + 1; j < n; j++) sum -= M[i][j] * x[j];
      x[i] = sum / M[i][i];
    }
    return x;
  }
  // 목표점과 주변 관측소 목록(nb: {s, d}) → 가중치와 추정 표준편차
  function krige(nb) {
    var n = nb.length;
    if (n === 1) return { w: [1], sd: Math.sqrt(vgam(nb[0].d)) };
    var A = [], b = [];
    for (var i = 0; i < n; i++) {
      var row = [];
      for (var j = 0; j < n; j++) row.push(i === j ? 0 : vgam(km(nb[i].s, nb[j].s)));
      row.push(1);
      A.push(row);
      b.push(vgam(nb[i].d));
    }
    A.push(nb.map(function () { return 1; }).concat([0]));
    b.push(1);
    var x = solve(A, b);
    if (!x) {  // 드물게 풀리지 않으면 거리 가중 평균으로
      var ws = nb.map(function (o) { return 1 / Math.pow(Math.max(o.d, 0.1), 2); });
      var tot = ws.reduce(function (a, c) { return a + c; }, 0);
      return { w: ws.map(function (v) { return v / tot; }), sd: Math.sqrt(vgam(nb[0].d)) };
    }
    var w = x.slice(0, n), v = x[n];
    for (var k = 0; k < n; k++) v += w[k] * b[k];
    return { w: w, sd: Math.sqrt(Math.max(v, 0)) };
  }
  // 값이 있는 이웃만으로 섞기
  function blend(nb, getter) {
    var sub = [], vals = [];
    nb.forEach(function (o) { var v = getter(o.s); if (v !== null && v !== undefined && !isNaN(v)) { sub.push(o); vals.push(v); } });
    if (!sub.length) return null;
    var k = krige(sub);
    return vals.reduce(function (a, v, i) { return a + k.w[i] * v; }, 0);
  }

  // ---------- 상태 ----------
  var state = {
    farm: null,  // {lat, lon, label, code(관측소 선택 시)}
    species: Math.min(Number(load("species", 1)) || 0, F.species.length - 1),
    date: "latest",
    gps: false
  };
  (function initFarm() {
    try {
      var f = JSON.parse(load("farm", "null"));
      if (f && isFinite(f.lat) && isFinite(f.lon)) state.farm = f;
    } catch (e) { /* 무시 */ }
    var q;
    try { q = new URLSearchParams(location.search); } catch (e) { q = null; }
    if (q) {
      var lat = parseFloat(q.get("lat")), lon = parseFloat(q.get("lon"));
      if (isFinite(lat) && isFinite(lon)) state.farm = { lat: lat, lon: lon, label: "주소로 지정한 위치" };
      var place = q.get("place");
      F.presets.forEach(function (p) { if (p.label === place) state.farm = presetFarm(p); });
      if (q.get("species")) F.species.forEach(function (s, i) { if (s.name.indexOf(q.get("species")) === 0) state.species = i; });
      if (q.get("date")) state.date = q.get("date");
    }
    if (!state.farm) state.farm = presetFarm(F.presets[0]);
  })();

  function presetFarm(p) {
    var s = byCode[p.code];
    return { lat: s.lat, lon: s.lon, label: p.label + " (" + s.name + " 관측소)", code: s.code, preset: p.label };
  }
  function setFarm(f) {
    state.farm = f;
    save("farm", JSON.stringify(f));
    render();
  }

  // ---------- 이 위치의 예보 계산 ----------
  function estimate() {
    var dateKey = state.date;
    var farm = state.farm;
    var cand = [];
    ST.forEach(function (s) {
      var v = stationValues(s, dateKey);
      if (v && v.today !== null) cand.push({ s: s, v: v, d: km(farm, s) });
    });
    cand.sort(function (a, b) { return a.d - b.d; });
    if (!cand.length) return { none: true, reason: "이 날짜의 관측 자료가 없습니다." };
    var nn = cand[0];
    if (nn.d > K.max_km) return { none: true, nn: nn };
    var nb = cand.slice(0, K.neighbors);
    var kr = krige(nb);
    var issue = dateKey === "latest" ? LATEST : dateKey;
    var today = blend(nb, function (s) { return nb.filter(function (o) { return o.s === s; })[0].v.today; });
    var wabs = kr.w.map(Math.abs), wsum = wabs.reduce(function (a, c) { return a + c; }, 0);
    var days = [];
    for (var h = 1; h <= 7; h++) {
      var pred = blend(nb, (function (hh) { return function (s) { return nb.filter(function (o) { return o.s === s; })[0].v.fc[hh - 1]; }; })(h));
      var actual = dateKey === "latest" ? null :
        blend(nb, (function (hh) { return function (s) { var a = nb.filter(function (o) { return o.s === s; })[0].v.actual; return a ? a[hh - 1] : null; }; })(h));
      var fe = nb.reduce(function (a, o, i) { return a + wabs[i] * o.s.err[h - 1]; }, 0) / wsum;
      days.push({ date: addDays(issue, h), h: h, pred: pred, actual: actual,
                  range: Math.sqrt(kr.sd * kr.sd + fe * fe) });
    }
    var obs = {};
    for (var k = -13; k <= 0; k++) {
      var day = addDays(issue, k);
      var val = blend(nb, function (s) { return observedOn(s, day, dateKey); });
      if (val !== null) obs[day] = val;
    }
    var acc3 = nb.reduce(function (a, o, i) { return a + wabs[i] * o.s.acc3; }, 0) / wsum;
    return { none: false, past: dateKey !== "latest", issue: issue, today: today, days: days, obs: obs,
             nb: nb, w: kr.w, sd: kr.sd, nn: nn, acc3: acc3 };
  }

  // ---------- 판정 ----------
  function levelForecast(temp, sp) {
    if (temp === null || temp === undefined) return null;
    if (temp >= sp.danger - F.alert_margin) return "crit";
    if (temp > sp.opt_max) return "warn";
    return "good";
  }
  function levelObserved(temp, sp) {
    if (temp === null || temp === undefined) return null;
    if (temp >= sp.danger) return "crit";
    if (temp > sp.opt_max) return "warn";
    return "good";
  }
  function worst(levels) {
    return levels.reduce(function (a, b) { return !b ? a : (!a || RANK[b] > RANK[a] ? b : a); }, null);
  }

  // ---------- 조회 조건 ----------
  function buildControls() {
    var box = document.getElementById("preset-buttons");
    F.presets.forEach(function (p) {
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = p.label;
      b.dataset.preset = p.label;
      b.addEventListener("click", function () { state.gps = false; setFarm(presetFarm(p)); });
      box.appendChild(b);
    });
    var g = document.createElement("button");
    g.type = "button";
    g.className = "gps";
    g.textContent = "내 위치";
    g.addEventListener("click", locate);
    box.appendChild(g);

    var ss = document.getElementById("station-select");
    var first = document.createElement("option");
    first.value = "";
    first.textContent = "관측소를 고르십시오";
    ss.appendChild(first);
    var groups = {};
    ST.slice().sort(function (a, b) { return a.name.localeCompare(b.name, "ko"); }).forEach(function (s) {
      var key = s.name.split(" ")[0];
      if (!groups[key]) {
        groups[key] = document.createElement("optgroup");
        groups[key].label = key;
        ss.appendChild(groups[key]);
      }
      var o = document.createElement("option");
      o.value = s.code;
      o.textContent = s.name;
      groups[key].appendChild(o);
    });
    ss.addEventListener("change", function () {
      var s = byCode[ss.value];
      if (s) { state.gps = false; setFarm({ lat: s.lat, lon: s.lon, label: s.name + " 관측소", code: s.code }); }
    });

    var sel = document.getElementById("species-select");
    F.species.forEach(function (s, i) {
      var o = document.createElement("option");
      o.value = i;
      o.textContent = s.name;
      sel.appendChild(o);
    });
    sel.value = state.species;
    sel.addEventListener("change", function () { state.species = +sel.value; save("species", sel.value); render(); });

    var ds = document.getElementById("date-select");
    var o0 = document.createElement("option");
    o0.value = "latest";
    o0.textContent = "최신 예보 (" + md(LATEST) + " 관측 기준)";
    ds.appendChild(o0);
    var og = document.createElement("optgroup");
    og.label = "지난 예보 다시 보기 (실제 수온과 비교)";
    ARCHIVE_DATES.forEach(function (d) {
      var x = document.createElement("option");
      x.value = d;
      x.textContent = mdw(d) + " 기준 예보";
      og.appendChild(x);
    });
    ds.appendChild(og);
    if (state.date !== "latest" && ARCHIVE_DATES.indexOf(state.date) < 0) state.date = "latest";
    ds.value = state.date;
    ds.addEventListener("change", function () { state.date = ds.value; render(); });
  }

  function locate() {
    var out = document.getElementById("place-now");
    if (!navigator.geolocation) { out.textContent = "이 기기에서는 위치 찾기를 쓸 수 없습니다. 지도나 관측소 목록에서 고르십시오."; return; }
    out.textContent = "현재 위치를 찾는 중입니다…";
    navigator.geolocation.getCurrentPosition(function (p) {
      state.gps = true;
      setFarm({ lat: p.coords.latitude, lon: p.coords.longitude, label: "내 위치" });
    }, function () {
      out.textContent = "위치를 찾지 못했습니다. 위치 권한을 허용하거나, 지도나 관측소 목록에서 고르십시오.";
    }, { enableHighAccuracy: true, timeout: 15000 });
  }

  // ---------- 지도 ----------
  var map = null, farmLayer = null, lineLayer = null;
  function buildMap() {
    if (!window.L) {
      document.getElementById("map-wrap").hidden = true;  // 인터넷이 안 되면 지도 없이 사용
      return;
    }
    map = L.map("map", { zoomControl: true, attributionControl: true }).setView([34.62, 127.6], 9);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 16, minZoom: 7, attribution: "© OpenStreetMap"
    }).addTo(map);
    ST.forEach(function (s) {
      L.circleMarker([s.lat, s.lon], { radius: 5, color: "#ffffff", weight: 1.5, fillColor: "#1f5fa8", fillOpacity: 1 })
        .bindTooltip(s.name, { direction: "top" })
        .on("click", function () { state.gps = false; setFarm({ lat: s.lat, lon: s.lon, label: s.name + " 관측소", code: s.code }); })
        .addTo(map);
    });
    lineLayer = L.layerGroup().addTo(map);
    farmLayer = L.layerGroup().addTo(map);
    map.on("click", function (e) {
      state.gps = false;
      setFarm({ lat: e.latlng.lat, lon: e.latlng.lng, label: "지도에서 고른 위치" });
    });
  }
  function drawMap(est) {
    if (!map) return;
    farmLayer.clearLayers();
    lineLayer.clearLayers();
    var f = [state.farm.lat, state.farm.lon];
    if (est && !est.none) {
      est.nb.forEach(function (o, i) {
        var share = Math.max(0, est.w[i]);
        if (share < 0.02) return;
        L.polyline([f, [o.s.lat, o.s.lon]], { color: "#12324f", weight: 1 + 6 * share, opacity: 0.7 }).addTo(lineLayer);
      });
    }
    L.circleMarker(f, { radius: 10, color: "#d03b3b", weight: 3, fillColor: "#ffffff", fillOpacity: 1 })
      .bindTooltip("양식장 위치", { direction: "top", permanent: false }).addTo(farmLayer);
    if (!map.getBounds().pad(-0.1).contains(f)) map.setView(f, Math.max(map.getZoom(), 10));
  }

  // ---------- 그리기 ----------
  function render() {
    var sp = F.species[state.species];
    var est = estimate();

    Array.prototype.forEach.call(document.querySelectorAll("#preset-buttons button"), function (b) {
      var on = b.classList.contains("gps") ? state.gps : state.farm.preset === b.dataset.preset;
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
    var ss = document.getElementById("station-select");
    ss.value = state.farm.code && !state.farm.preset ? state.farm.code : "";
    document.body.classList.toggle("showing-past", !est.none && est.past);

    var place = document.getElementById("place-now");
    if (est.nn) {
      place.innerHTML = "선택한 위치: <strong>" + state.farm.label + "</strong> · 가장 가까운 관측소 " +
        est.nn.s.name + " " + est.nn.d.toFixed(1) + "km";
    } else {
      place.innerHTML = "선택한 위치: <strong>" + state.farm.label + "</strong>";
    }
    drawMap(est);

    document.getElementById("unavailable").hidden = !est.none;
    document.getElementById("result").hidden = est.none;
    if (est.none) {
      document.getElementById("unavailable-msg").textContent = est.nn
        ? "가장 가까운 수온 관측소(" + est.nn.s.name + ")가 " + est.nn.d.toFixed(0) + "km 떨어져 있어 이 위치의 예보를 믿을 수 없습니다. " +
          "관측소에서 " + K.max_km + "km 안쪽의 양식장 위치를 고르십시오."
        : est.reason;
      return;
    }

    var lvDays = est.days.map(function (d) { return levelForecast(d.pred, sp); });
    var lvToday = levelObserved(est.today, sp);
    var overall = worst([lvToday].concat(lvDays)) || "good";
    var firstCrit = lvDays.indexOf("crit");

    var st = document.getElementById("status");
    st.className = "status " + overall;
    document.getElementById("status-word").textContent = LABEL[overall];
    document.getElementById("status-scope").textContent =
      sp.name + " 기준 · " + (est.past ? mdw(est.issue) + " 예보" : "앞으로 7일");
    var msg;
    if (lvToday === "crit") {
      msg = (est.past ? "이날 수온이" : "현재 수온이") + " 위험 수온(" + sp.danger + "℃) 이상입니다. 바로 대비하십시오.";
    } else if (firstCrit >= 0) {
      msg = mdw(est.days[firstCrit].date) + " 전후로 위험 수온(" + sp.danger +
            "℃)에 가까워질 것으로 예상됩니다. 하루 이틀 빠를 수 있으니 미리 대비하십시오.";
    } else if (overall === "warn") {
      msg = "적정 수온(" + sp.opt_max + "℃)보다 높은 날이 있습니다. 7일 안에 위험 수온 도달은 예상되지 않습니다.";
    } else {
      msg = "앞으로 7일 동안 적정 수온 범위에서 유지될 것으로 예상됩니다.";
    }
    document.getElementById("status-msg").textContent = msg;
    var warn = document.getElementById("status-warn");
    warn.hidden = est.nn.d <= K.warn_km;
    warn.textContent = "가장 가까운 관측소가 " + est.nn.d.toFixed(1) + "km 떨어져 있어 이 위치의 정확도가 낮습니다. 참고용으로 보십시오.";

    document.getElementById("fact-now-label").textContent = est.past ? "기준일 수온" : "현재 수온";
    document.getElementById("fact-now").innerHTML =
      t1(est.today) + "<small>" + md(est.issue) + " 하루 평균 · 이 위치 추정</small>";
    document.getElementById("fact-danger").innerHTML =
      sp.danger.toFixed(1) + "℃<small>" + (sp.danger - F.alert_margin).toFixed(2).replace(/0$/, "") + "℃부터 위험 표시</small>";
    document.getElementById("fact-opt").innerHTML =
      sp.opt_min + "~" + sp.opt_max + "℃<small>고수온 특보 기준 " + F.official_alert_temp + "℃</small>";

    renderTable(est, lvDays, lvToday === "crit" ? -1 : firstCrit);
    renderChart(est, sp);
    renderActions(overall, sp);
    renderSources(est);
    renderAccuracy(est);
  }

  function renderTable(v, lvDays, firstCrit) {
    document.getElementById("table-note").textContent =
      v.past ? mdw(v.issue) + "에 냈을 예보와 실제 수온" : md(v.issue) + " 관측까지 반영";
    var tb = document.querySelector("#days tbody");
    tb.innerHTML = "";
    v.days.forEach(function (d, i) {
      var tr = document.createElement("tr");
      if (d.h >= 4) tr.className = "far";
      var rel = v.past ? "" : relative(d.date);
      var lo = d.pred === null ? null : d.pred - d.range, hi = d.pred === null ? null : d.pred + d.range;
      var lv = lvDays[i];
      tr.innerHTML =
        '<td class="date"><strong>' + md(d.date) + "</strong><small>" + weekday(d.date) + (rel ? " · " + rel : "") + "</small></td>" +
        '<td class="num"><strong>' + t1(d.pred) + "</strong>" +
          (lo === null ? "" : "<small>" + lo.toFixed(1) + "~" + hi.toFixed(1) + "℃</small>") + "</td>" +
        '<td class="num actual-col">' + (v.past ? "<strong>" + t1(d.actual) + "</strong>" : "") + "</td>" +
        "<td>" + (lv ? '<span class="tag ' + lv + (i === firstCrit ? " first-danger" : "") + '">' + LABEL[lv] + "</span>" : "-") + "</td>";
      tb.appendChild(tr);
    });
  }

  function renderActions(level, sp) {
    var ol = document.getElementById("actions");
    ol.innerHTML = "";
    var extra = SPECIES_ACTIONS[sp.name] && SPECIES_ACTIONS[sp.name][level];
    if (extra) {
      var li = document.createElement("li");
      li.innerHTML = '<span class="sp">' + sp.name.replace(/\(.*\)/, "") + ":</span> " + extra;
      ol.appendChild(li);
    }
    ACTIONS[level].forEach(function (t) {
      var li = document.createElement("li");
      li.textContent = t;
      ol.appendChild(li);
    });
    document.getElementById("action-note").textContent = sp.name + " · '" + LABEL[level] + "' 단계";
  }

  function renderSources(est) {
    var tb = document.querySelector("#nb tbody");
    tb.innerHTML = "";
    est.nb.forEach(function (o, i) {
      var share = Math.max(0, est.w[i]);
      var tr = document.createElement("tr");
      tr.innerHTML = "<td>" + o.s.name + "</td><td class=\"num\">" + o.d.toFixed(1) + "km</td>" +
        '<td class="num"><span class="bar" style="width:' + Math.round(share * 60) + 'px"></span>' +
        (share < 0.01 ? "1% 미만" : Math.round(share * 100) + "%") + "</td>" +
        '<td class="num">' + t1(o.v.today) + "</td>";
      tb.appendChild(tr);
    });
    document.getElementById("nb-note").textContent =
      "주변 관측소 " + est.nb.length + "곳의 예보를, 거리와 관측소끼리 수온이 얼마나 비슷하게 움직이는지에 따라 섞었습니다(크리깅). " +
      "양식장 위치를 관측소 값으로 추정하면서 생기는 오차는 약 ±" + est.sd.toFixed(1) + "℃이며, 표의 예상 범위에 포함되어 있습니다.";
  }

  // ---------- 차트 (관측 14일 + 예보 7일) ----------
  var SVGNS = "http://www.w3.org/2000/svg";
  function el(name, attrs, parent) {
    var e = document.createElementNS(SVGNS, name);
    Object.keys(attrs).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(e);
    return e;
  }

  function renderChart(v, sp) {
    var box = document.getElementById("chart");
    box.innerHTML = "";
    var W = Math.max(300, Math.round(box.clientWidth || 700));
    var narrow = W < 520;
    var H = narrow ? 280 : 320, M = { t: 18, r: narrow ? 78 : 104, b: 36, l: 48 };
    var pts = [];
    for (var k = -13; k <= 7; k++) {
      var d = addDays(v.issue, k);
      var day = k > 0 ? v.days[k - 1] : null;
      pts.push({ k: k, date: d, obs: k <= 0 ? (v.obs[d] === undefined ? null : v.obs[d]) : null,
                 pred: day ? day.pred : null, range: day ? day.range : 0, actual: day ? day.actual : null });
    }
    var vals = [];
    pts.forEach(function (p) {
      if (p.obs !== null) vals.push(p.obs);
      if (p.pred !== null) { vals.push(p.pred - p.range, p.pred + p.range); }
      if (p.actual !== null) vals.push(p.actual);
    });
    if (!vals.length) { box.textContent = "표시할 수온 자료가 없습니다."; return; }
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    var showDanger = sp.danger - hi <= 4, showOpt = sp.opt_max >= lo - 1 && sp.opt_max - hi <= 4;
    if (showDanger) hi = Math.max(hi, sp.danger);
    if (showOpt) { hi = Math.max(hi, sp.opt_max); lo = Math.min(lo, sp.opt_max); }
    lo = Math.floor(lo - 0.3); hi = Math.ceil(hi + 0.3);
    var step = hi - lo > 8 ? 2 : 1;

    var x = function (kk) { return M.l + (kk + 13) / 20 * (W - M.l - M.r); };
    var y = function (t) { return M.t + (hi - t) / (hi - lo) * (H - M.t - M.b); };

    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img",
      "aria-label": "선택한 양식장 위치의 최근 2주 수온과 7일 예상 수온 그래프" }, box);
    var grid = el("g", { "class": "grid" }, svg), axis = el("g", { "class": "axis" }, svg);
    for (var t = lo; t <= hi + 1e-9; t += step) {
      el("line", { x1: M.l, x2: W - M.r, y1: y(t), y2: y(t) }, grid);
      el("text", { x: M.l - 8, y: y(t) + 4, "text-anchor": "end" }, axis).textContent = t + "℃";
    }
    [-13, -7, 0, 7].forEach(function (kk) {
      var tx = el("text", { x: x(kk), y: H - 10, "text-anchor": kk === -13 ? "start" : (kk === 7 ? "end" : "middle") }, axis);
      tx.textContent = md(addDays(v.issue, kk)).replace("월 ", "/").replace("일", "");
    });
    function hline(tv, color, label) {
      el("line", { x1: M.l, x2: W - M.r, y1: y(tv), y2: y(tv), stroke: color, "stroke-width": 1.5, "stroke-dasharray": "6 4" }, svg);
      el("text", { x: W - M.r + 6, y: y(tv) + 4, "class": "th-label", fill: "#16202b" }, svg).textContent = label;
    }
    if (showOpt) hline(sp.opt_max, "#b07a00", (narrow ? "적정 " : "적정 상한 ") + sp.opt_max + "℃");
    if (showDanger) hline(sp.danger, "#d03b3b", "위험 " + sp.danger + "℃");
    el("line", { x1: x(0), x2: x(0), y1: M.t, y2: H - M.b, "class": "today-rule" }, svg);
    el("text", { x: x(0) + 4, y: M.t + 10, "class": "today-label" }, svg).textContent = v.past ? "예보한 날" : "기준일";

    var fp = pts.filter(function (p) { return p.k > 0 && p.pred !== null; });
    var base = pts[13];
    if (fp.length) {
      var up = fp.map(function (p) { return x(p.k) + "," + y(p.pred + p.range); });
      var dn = fp.slice().reverse().map(function (p) { return x(p.k) + "," + y(p.pred - p.range); });
      var start = base.obs !== null ? [x(0) + "," + y(base.obs)] : [];
      el("polygon", { points: start.concat(up, dn).join(" "), fill: "rgba(31,95,168,0.14)" }, svg);
    }
    function path(list, get) {
      var dd = "", pen = false;
      list.forEach(function (p) {
        var val = get(p);
        if (val === null) { pen = false; return; }
        dd += (pen ? "L" : "M") + x(p.k).toFixed(1) + "," + y(val).toFixed(1);
        pen = true;
      });
      return dd;
    }
    el("path", { d: path(pts.filter(function (p) { return p.k <= 0; }), function (p) { return p.obs; }),
                 fill: "none", stroke: "#1f5fa8", "stroke-width": 2.5, "stroke-linejoin": "round" }, svg);
    var predLine = (base.obs !== null ? [{ k: 0, v: base.obs }] : []).concat(fp.map(function (p) { return { k: p.k, v: p.pred }; }));
    el("path", { d: path(predLine, function (p) { return p.v; }), fill: "none", stroke: "#1f5fa8",
                 "stroke-width": 2.5, "stroke-dasharray": "7 5", "stroke-linejoin": "round" }, svg);
    fp.forEach(function (p) { el("circle", { cx: x(p.k), cy: y(p.pred), r: 4, fill: "#fff", stroke: "#1f5fa8", "stroke-width": 2 }, svg); });
    if (v.past) {
      var ap = (base.obs !== null ? [{ k: 0, v: base.obs }] : []).concat(
        pts.filter(function (p) { return p.k > 0 && p.actual !== null; }).map(function (p) { return { k: p.k, v: p.actual }; }));
      el("path", { d: path(ap, function (p) { return p.v; }), fill: "none", stroke: "#3a4754", "stroke-width": 2.5 }, svg);
      ap.forEach(function (p) { if (p.k > 0) el("rect", { x: x(p.k) - 4, y: y(p.v) - 4, width: 8, height: 8, fill: "#3a4754" }, svg); });
    }

    var lg = document.getElementById("legend");
    var items = ['<span><i></i>관측 수온</span>', '<span><i class="dash"></i>예상 수온</span>', '<span><i class="band"></i>예상 범위</span>'];
    if (v.past) items.push('<span><i class="actual"></i>실제 수온</span>');
    if (showDanger) items.push('<span><i class="crit"></i>위험 수온</span>');
    if (showOpt) items.push('<span><i class="warn"></i>적정 수온 상한</span>');
    lg.innerHTML = items.join("");
    if (!showDanger) lg.insertAdjacentHTML("beforeend", "<span>위험 수온 " + sp.danger + "℃는 그래프보다 훨씬 위에 있습니다</span>");

    var tip = document.createElement("div");
    tip.className = "tooltip"; tip.hidden = true; box.appendChild(tip);
    var cross = el("line", { y1: M.t, y2: H - M.b, stroke: "#16202b", "stroke-width": 1, visibility: "hidden" }, svg);
    var hit = el("rect", { x: M.l, y: 0, width: W - M.l - M.r, height: H, fill: "transparent" }, svg);
    function show(evt) {
      var r = svg.getBoundingClientRect();
      var sx = (evt.clientX - r.left) / r.width * W;
      var kk = Math.max(-13, Math.min(7, Math.round((sx - M.l) / (W - M.l - M.r) * 20 - 13)));
      var p = pts[kk + 13];
      var parts = [mdw(p.date)];
      if (p.obs !== null) parts.push("관측 " + t1(p.obs));
      if (p.pred !== null) parts.push("예상 " + t1(p.pred));
      if (p.actual !== null) parts.push("실제 " + t1(p.actual));
      if (parts.length === 1) parts.push("자료 없음");
      tip.textContent = parts.join(" · ");
      var ref = p.obs !== null ? p.obs : (p.pred !== null ? p.pred : p.actual);
      tip.style.left = (x(kk) / W * r.width) + "px";
      tip.style.top = ((ref === null ? M.t : y(ref)) / H * r.height) + "px";
      tip.hidden = false;
      cross.setAttribute("x1", x(kk)); cross.setAttribute("x2", x(kk)); cross.setAttribute("visibility", "visible");
    }
    function hide() { tip.hidden = true; cross.setAttribute("visibility", "hidden"); }
    hit.addEventListener("pointermove", show);
    hit.addEventListener("pointerdown", show);
    hit.addEventListener("pointerleave", hide);
  }

  // ---------- 정확도 안내 ----------
  function renderAccuracy(est) {
    var V = F.validation;
    var pct = function (x) { return Math.round(x * 100); };
    var rows = [
      ["다음 날 수온", "100번 중 " + pct(V["1일"]) + "번", "±1℃ 안쪽"],
      ["3일 뒤 수온", "100번 중 " + pct(V["3일"]) + "번", "±1℃ 안쪽"],
      ["7일 뒤 수온", "100번 중 " + pct(V["7일"]) + "번", "±1℃ 안쪽"],
      ["고수온(28℃) 도달", "10번 중 " + Math.round(V["도달포착"] * 10) + "번 미리 알림", "날짜는 평균 " + V["도달일오차"] + "일 차이"],
      ["주변 관측소 3일 뒤 예보", "100번 중 " + pct(est.acc3) + "번", "±1℃ 안쪽 (이 위치에 쓴 관측소 평균)"],
      ["관측소 → 이 위치 추정", "약 ±" + est.sd.toFixed(1) + "℃", "가장 가까운 관측소 " + est.nn.d.toFixed(1) + "km"]
    ];
    document.getElementById("acc").innerHTML = rows.map(function (r) {
      return "<tr><th scope=\"row\">" + r[0] + "</th><td>" + r[1] + " <small>" + r[2] + "</small></td></tr>";
    }).join("");
    document.getElementById("acc-note").textContent =
      "위 네 줄은 대표 관측소 4곳, 아래 두 줄은 이 위치에 쓴 관측소 기준입니다. " + V["기간"] +
      " 실제 수온으로 확인했으며, 이 기간은 예보 모델을 만들 때 쓰지 않았습니다. 관측소에서 멀어질수록 추정 오차가 커집니다.";
  }

  function renderMeta() {
    document.getElementById("generated").textContent = "예보 생성: " + F.generated_at + " · 관측소 " + ST.length + "곳";
    if (F.notes && F.notes.length) {
      var n = document.createElement("p");
      n.className = "notice";
      n.textContent = "최신 관측 자료를 받지 못해 이전 자료로 만든 예보입니다. 기준일을 확인하십시오.";
      document.querySelector(".controls").appendChild(n);
    }
  }

  buildControls();
  buildMap();
  renderMeta();
  render();

  var lastW = document.getElementById("chart").clientWidth, timer = null;
  window.addEventListener("resize", function () {
    clearTimeout(timer);
    timer = setTimeout(function () {
      var w = document.getElementById("chart").clientWidth;
      if (w !== lastW) { lastW = w; render(); }
    }, 150);
  });
})();
