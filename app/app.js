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
      '<p class="notice">예보 자료(data/forecast.js)를 찾을 수 없어요. src/app/build_forecast.py 를 먼저 실행해 주세요.</p>';
    return;
  }

  // 한 페이지로 묶어 게시할 때(src/app/bundle_single.py): 위치 권한·외부 지도 타일을 쓸 수 없음
  var OPTIONS = window.APP_OPTIONS || {};
  var K = F.kriging;
  var LABEL = { good: "정상", warn: "주의", crit: "위험" };
  var RANK = { good: 0, warn: 1, crit: 2 };
  var WEEK = ["일", "월", "화", "수", "목", "금", "토"];
  var KM_LAT = 111.0, KM_LON = 111.0 * Math.cos(34.5 * Math.PI / 180);

  var ACTIONS = {
    good: [
      "산소공급기·냉각시설을 미리 점검해 둬요.",
      "영양제를 섞은 사료로 물고기 체력을 길러 둬요.",
      "여름철에는 어장 주변 수온을 매일 확인해요."
    ],
    warn: [
      "사료 주는 양을 줄여요.",
      "질병 예방과 치료를 미리 끝내 둬요.",
      "가두리 그물 청소·교체, 산소공급기·냉각시설 점검을 마쳐요.",
      "조기 출하나 분산 수용을 검토해요."
    ],
    crit: [
      "사료 공급을 줄이거나 멈춰요.",
      "액화산소·산소발생기·저층해수 공급 장비를 모두 가동해요.",
      "선별·망갈이처럼 물고기를 놀라게 하는 작업은 하지 마세요.",
      "어장 수온과 용존산소를 하루 여러 번 직접 재요.",
      "폐사가 생기면 시·군청에 바로 신고해요."
    ]
  };
  var SPECIES_ACTIONS = {
    "넙치(광어)": {
      warn: "조기 출하·분산을 하고, 사육 수온과 용존산소를 수시로 재요.",
      crit: "수온이 낮은 지하해수를 넣고 액화산소를 충분히 공급해요."
    },
    "조피볼락(우럭)": {
      warn: "가두리 그물을 교체·청소하고, 긴급 방류에 대비해 질병 검사를 받아 둬요.",
      crit: "저층 물을 퍼 올려 섞어 주거나 가두리를 가라앉히고, 차광막으로 스트레스를 줄여요."
    },
    // 아래는 국립수산과학원 「자연재해 대비 양식장 관리요령」 표 5-6·5-7·5-8 요약
    "전복(참전복)": {
      warn: "조기 출하하고, 먹이(해조류) 공급량을 줄이며, 차광막과 산소 공급 장치를 미리 점검해요.",
      crit: "먹이 공급을 멈추고, 차광막을 치고, 액화산소를 넣어요. 가두리는 저층 물 섞기나 침하를 해요."
    },
    "멍게(우렁쉥이)": {
      warn: "어장 수온을 자주 확인하고, 줄을 깊은 곳으로 내릴 준비를 해요.",
      crit: "작업을 멈추고, 수하연(매단 줄)을 깊이 내려 차가운 물에 둬요."
    },
    "굴(참굴)": {
      warn: "어장 수온을 자주 확인하고, 수하연을 내릴 준비를 해요.",
      crit: "작업을 멈추고, 수온이 지나치게 오르면 수하연을 깊이 내려요."
    },
    // 아래 갯벌(살포식) 패류 4종: 국립수산과학원 「자연재해 대비 양식장 관리요령」 3장 "바닥식
    // 패류(바지락) 및 기타 양식장(굴·멍게) 관리 요령", 표 5-8 "바닥식(바지락 등)" 그대로 반영
    // (종 전용 요령은 없지만 이 표가 바닥식 패류 전반에 적용된다고 명시돼 있음, 2026-09-28)
    "바지락": {
      warn: "조기에 걷어 서식 밀도를 낮추고, 썰물 때 어장에 바닷물이 고이지 않게 물길을 내 둬요.",
      crit: "관할 시·군청(해양수산과)에 바로 신고하고, 폐사체는 2차 오염을 막기 위해 빠르게 걷어내요."
    },
    "새꼬막": {
      warn: "조기에 걷어 서식 밀도를 낮추고, 썰물 때 어장에 바닷물이 고이지 않게 물길을 내 둬요.",
      crit: "관할 시·군청(해양수산과)에 바로 신고하고, 폐사체는 2차 오염을 막기 위해 빠르게 걷어내요."
    },
    "피조개": {
      warn: "조기에 걷어 서식 밀도를 낮추고, 썰물 때 어장에 바닷물이 고이지 않게 물길을 내 둬요.",
      crit: "관할 시·군청(해양수산과)에 바로 신고하고, 폐사체는 2차 오염을 막기 위해 빠르게 걷어내요."
    },
    "꼬막(참꼬막)": {
      warn: "조기에 걷어 서식 밀도를 낮추고, 썰물 때 어장에 바닷물이 고이지 않게 물길을 내 둬요.",
      crit: "관할 시·군청(해양수산과)에 바로 신고하고, 폐사체는 2차 오염을 막기 위해 빠르게 걷어내요."
    },
    // 아래 수하식(밧줄에 매다는) 패류 2종: 같은 표 5-8 "수하식(굴, 멍게)" 요령(작업금지·수하연
    // 침하·신고)을 그대로 적용 - 굴·멍게 항목과 문구를 맞춤
    "홍합(진주담치)": {
      warn: "어장 수온을 자주 확인하고, 수하연을 내릴 준비를 해요.",
      crit: "작업을 멈추고 수하연을 깊이 내리며, 관할 시·군청에 바로 신고해요."
    },
    "미더덕": {
      warn: "어장 수온을 자주 확인하고, 수하연을 내릴 준비를 해요.",
      crit: "작업을 멈추고 수하연을 깊이 내리며, 관할 시·군청에 바로 신고해요."
    }
  };
  // 패류는 사람이 먹이(사료)를 주지 않고 플랑크톤을 걸러 먹으므로, 공통 문구 중 "사료"·"물고기"를
  // 언급하는 줄은 패류에는 안 맞아 보여주지 않는다 (renderActions에서 사용, 2026-09-28)
  var SHELLFISH = { "전복(참전복)": 1, "멍게(우렁쉥이)": 1, "굴(참굴)": 1, "바지락": 1, "새꼬막": 1,
                    "피조개": 1, "꼬막(참꼬막)": 1, "홍합(진주담치)": 1, "미더덕": 1 };

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

  // 육지를 눌렀을 때는 수온을 보여주지 않기 위한 판정 - 해안선(Natural Earth) 다각형 안에
  // 점이 들어있는지 계산한다(레이캐스팅). data/coast.js가 있을 때만 동작 (2026-09-28)
  function pointInRing(lat, lon, ring) {
    var inside = false;
    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      var yi = ring[i][0], xi = ring[i][1], yj = ring[j][0], xj = ring[j][1];
      if (((yi > lat) !== (yj > lat)) && (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi)) inside = !inside;
    }
    return inside;
  }
  function isOnLand(lat, lon) {
    if (!window.COAST) return false;
    for (var r = 0; r < window.COAST.length; r++) if (pointInRing(lat, lon, window.COAST[r])) return true;
    return false;
  }

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
    // 어종은 이름으로 저장 (기준표 순서가 바뀌어도 같은 어종 유지)
    species: (function () {
      var n = load("species_name", "");
      for (var i = 0; i < F.species.length; i++) if (F.species[i].name === n) return i;
      return 0;
    })(),
    date: "latest",
    gps: false,
    screen: "welcome",   // welcome/location/confirm/species/loading/result - 화면마다 할 일 하나씩
    locationChosen: false,  // 사용자가 실제로 위치를 고른 적 있는지(처음 온 사람만 1단계부터 시작)
    viaUrlLink: false    // 이번 방문이 ?place=·?lat=&lon= 딥링크로 들어온 것인지 (탭 기본값 판단용 -
                         // localStorage에 남은 예전 기록과 구분해야 함, 아래 buildTabs 참고)
  };
  (function initFarm() {
    // 검색·지도클릭 등으로 "마지막으로 본 위치"를 저장은 해 두지만(setFarm 참고),
    // 여기서 그걸 자동으로 복원하지는 않는다 - '내 양식장으로 저장'을 누른 적 없는데도
    // 다음 방문에 아무 검색 결과가 미리 채워져 나오면 사용자가 혼란스럽다는 지적 반영
    // (2026-09-28). 진짜 저장된 "내 양식장"(myFarms)만 아래에서 복원한다.
    var q;
    try { q = new URLSearchParams(location.search); } catch (e) { q = null; }
    if (q) {
      var lat = parseFloat(q.get("lat")), lon = parseFloat(q.get("lon"));
      if (isFinite(lat) && isFinite(lon)) { state.farm = { lat: lat, lon: lon, label: "주소로 지정한 위치" }; state.locationChosen = true; state.viaUrlLink = true; }
      var place = q.get("place");
      F.presets.forEach(function (p) { if (p.label === place) { state.farm = presetFarm(p); state.locationChosen = true; state.viaUrlLink = true; } });
      if (q.get("species")) F.species.forEach(function (s, i) { if (s.name.indexOf(q.get("species")) === 0) state.species = i; });
      if (q.get("date")) state.date = q.get("date");
    }
    if (!state.farm) state.farm = presetFarm(F.presets[0]);
  })();

  // ---------- 화면 진행: 인사말 → 위치 → 위치확인 → (어종 물어보기) → 어종 → 불러오는 중 → 결과 ----------
  // 한 화면에 위치·어종·결과를 다 몰아넣지 말고, 화면마다 할 일 하나만 두고 차례차례
  // 넘어가게 함. setFarm()에서도 이 함수를 불러 위치를 고르면 자동으로 다음 화면(확인)으로
  // 넘어가게 한다 - 매번 '다음' 버튼을 더 누르게 하지 않기 위해 (2026-09-28).
  var SCREENS = ["welcome", "location", "location-confirm", "confirm", "species", "loading"];
  var SCREEN_EL_ID = {
    "welcome": "step-welcome",
    "location": "step-location",
    "location-confirm": "step-location-confirm",
    "confirm": "step-confirm",
    "species": "step-species",
    "loading": "step-loading"
  };
  function goScreen(screen) {
    state.screen = screen;
    var controls = document.querySelector(".controls");
    controls.hidden = screen === "result";
    SCREENS.forEach(function (k) {
      var el = document.getElementById(SCREEN_EL_ID[k]);
      if (el) el.hidden = k !== screen;
    });
    render();
    if (screen === "loading") {
      // 실제로는 이미 불러온 자료를 즉시 계산할 뿐이지만, 뭘 하고 있는지 보여주기 위해
      // 아주 잠깐(체감상) 멈췄다가 결과로 넘어간다.
      setTimeout(function () { goScreen("result"); }, 700);
    }
  }

  function presetFarm(p) {
    var s = byCode[p.code];
    return { lat: s.lat, lon: s.lon, label: p.label + " (" + s.name + " 관측소)", code: s.code, preset: p.label };
  }
  function setFarm(f) {
    state.farm = f;
    state.locationChosen = true;  // 실제로 위치를 골랐으니 "선택한 위치: 없음" 표시는 이제 끝
    save("farm", JSON.stringify(f));
    // 위치를 고르는 화면에 있었다면 자동으로 '이 위치가 맞나요?' 확인 화면으로 넘어간다
    if (state.screen === "location") { goScreen("location-confirm"); return; }
    render();
  }

  // ---------- 내 양식장 (이 기기 브라우저에만 저장) ----------
  function loadMy() {
    try {
      var a = JSON.parse(load("myfarms", "[]"));
      return Array.isArray(a) ? a.filter(function (f) { return f && f.name && isFinite(f.lat) && isFinite(f.lon); }) : [];
    } catch (e) { return []; }
  }
  var myFarms = loadMy();
  function saveMy() { save("myfarms", JSON.stringify(myFarms)); }
  function samePlace(a, b) { return a && b && Math.abs(a.lat - b.lat) < 1e-5 && Math.abs(a.lon - b.lon) < 1e-5; }
  function speciesIndexByName(name) {
    for (var i = 0; i < F.species.length; i++) if (F.species[i].name === name) return i;
    return -1;
  }
  function setSpecies(i) {
    if (i < 0) return;
    state.species = i;
    save("species_name", F.species[i].name);
    document.getElementById("species-select").value = i;
  }
  // 옮기기 코드: 목록(JSON)을 글자 코드로 바꿔 다른 기기에 붙여 넣게 함
  function encodeMy(list) {
    try { return "HSW1:" + btoa(unescape(encodeURIComponent(JSON.stringify(list)))); } catch (e) { return ""; }
  }
  function decodeMy(code) {
    var c = String(code || "").trim();
    if (c.indexOf("HSW1:") !== 0) return null;
    try {
      var a = JSON.parse(decodeURIComponent(escape(atob(c.slice(5)))));
      return Array.isArray(a) ? a.filter(function (f) { return f && f.name && isFinite(f.lat) && isFinite(f.lon); }) : null;
    } catch (e) { return null; }
  }

  // ---------- 양식장 찾기 (국립해양조사원 어장정보) ----------
  var FR = (window.FARMS && window.FARMS.rows) || [];
  function norm(s) { return String(s || "").replace(/\s+/g, "").toLowerCase(); }
  var FR_IDX = FR.map(function (r) { return norm(r[0] + r[1] + r[2] + r[3] + r[4] + r[5]); });
  // 어장정보 품종 글자 → 앱 기준표 품종 (기준표: data/external/species_conditions).
  // '새꼬막'·'새고막'처럼 더 구체적인 이름은 일반 '꼬막'보다 앞에 둬야 한다 - 먼저 맞는 키를
  // 찾으면 바로 반환하므로, '꼬막'이 앞에 있으면 '새꼬막'도 그냥 '꼬막'으로 잘못 잡힌다.
  var SPECIES_KEYS = [["넙치", "넙치"], ["광어", "넙치"], ["우럭", "조피볼락"], ["조피볼락", "조피볼락"], ["참돔", "참돔"],
                      ["감성돔", "감성돔"], ["돌돔", "돌돔"], ["강도다리", "강도다리"], ["숭어", "숭어"],
                      ["전복", "전복"], ["우렁쉥이", "멍게"], ["멍게", "멍게"], ["굴", "굴"],
                      ["새꼬막", "새꼬막"], ["새고막", "새꼬막"], ["바지락", "바지락"], ["꼬막", "꼬막"],
                      ["피조개", "피조개"], ["홍합", "홍합"], ["진주담치", "홍합"], ["미더덕", "미더덕"]];
  function speciesFromKind(text) {
    for (var k = 0; k < SPECIES_KEYS.length; k++) {
      if (String(text || "").indexOf(SPECIES_KEYS[k][0]) >= 0) {
        for (var i = 0; i < F.species.length; i++) if (F.species[i].name.indexOf(SPECIES_KEYS[k][1]) === 0) return i;
      }
    }
    return -1;
  }
  function searchFarms(q) {
    var tokens = String(q || "").trim().split(/\s+/).map(norm).filter(Boolean);
    if (!tokens.length) return [];
    var out = [];
    for (var i = 0; i < FR.length && out.length < 30; i++) {
      var ok = true;
      for (var t = 0; t < tokens.length; t++) if (FR_IDX[i].indexOf(tokens[t]) < 0) { ok = false; break; }
      if (ok) out.push(i);
    }
    return out;
  }
  function nearestKm(p) {
    var best = Infinity;
    ST.forEach(function (s) { if (s.issue === LATEST) best = Math.min(best, km(p, s)); });
    return best;
  }
  function chooseFarmRow(i) {
    var r = FR[i];
    state.gps = false;
    var sp = speciesFromKind(r[5] + " " + r[3]);
    if (sp >= 0) setSpecies(sp);
    document.getElementById("farm-search").value = "";
    document.getElementById("farm-results").hidden = true;
    setFarm({ lat: r[6], lon: r[7], label: r[0] + " " + r[1],
              farm: { lcns: r[2], knd: r[3], mthd: r[4], kind: r[5] } });
  }
  function renderResults() {
    var input = document.getElementById("farm-search"), ul = document.getElementById("farm-results");
    var hits = searchFarms(input.value);
    ul.innerHTML = "";
    if (!input.value.trim()) { ul.hidden = true; return; }
    ul.hidden = false;
    if (!hits.length) {
      ul.innerHTML = '<li class="empty">찾는 양식장이 없어요. 마을 이름만 넣어 보거나(예: 불목), 지도에서 직접 눌러 보세요.</li>';
      return;
    }
    hits.forEach(function (i) {
      var r = FR[i], d = nearestKm({ lat: r[6], lon: r[7] });
      var li = document.createElement("li"), b = document.createElement("button");
      b.type = "button";
      var info = [r[3], r[4], r[5]].filter(Boolean).join(" · ");
      b.innerHTML = "<strong>" + r[0] + " " + r[1] + "</strong><small>" + info + (r[2] ? " · 면허 " + r[2] : "") + "</small>" +
        (d > K.max_km ? '<small class="far-note">근처 수온 관측소가 없어 예보를 낼 수 없어요</small>'
                      : (d > K.warn_km ? '<small class="far-note">관측소가 ' + d.toFixed(0) + "km 떨어져 있어 참고용이에요</small>" : ""));
      b.addEventListener("click", function () { chooseFarmRow(i); });
      li.appendChild(b);
      ul.appendChild(li);
    });
  }

  function renderMyFarms() {
    document.getElementById("my-farms-field").hidden = !myFarms.length;
    var box = document.getElementById("my-farms");
    box.innerHTML = "";
    myFarms.forEach(function (f) {
      var b = document.createElement("button");
      b.type = "button";
      b.setAttribute("aria-pressed", samePlace(f, state.farm) ? "true" : "false");
      b.innerHTML = f.name + "<small>" + (f.species || "") + "</small>";
      b.addEventListener("click", function () {
        state.gps = false;
        setSpecies(speciesIndexByName(f.species));
        setFarm({ lat: f.lat, lon: f.lon, label: f.name, farm: f.farm || null, mine: true });
      });
      box.appendChild(b);
    });
    var list = document.getElementById("manage-list");
    list.innerHTML = "";
    myFarms.forEach(function (f, idx) {
      var li = document.createElement("li");
      var span = document.createElement("span");
      span.textContent = f.name + " · " + (f.species || "");
      var del = document.createElement("button");
      del.type = "button";
      del.className = "btn";
      del.textContent = "삭제";
      del.addEventListener("click", function () {
        if (del.dataset.armed !== "1") { del.dataset.armed = "1"; del.textContent = "한 번 더 누르면 삭제"; return; }
        myFarms.splice(idx, 1);
        saveMy();
        render();
      });
      li.appendChild(span);
      li.appendChild(del);
      list.appendChild(li);
    });
    document.getElementById("move-code").value = encodeMy(myFarms);

    var saveBox = document.getElementById("save-box");
    var saved = myFarms.some(function (f) { return samePlace(f, state.farm); });
    saveBox.hidden = saved;
    var nameInput = document.getElementById("save-name");
    if (!saved && document.activeElement !== nameInput) nameInput.value = String(state.farm.label || "").slice(0, 30);
  }

  function buildMyFarmControls() {
    var input = document.getElementById("farm-search");
    input.addEventListener("input", renderResults);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        var hits = searchFarms(input.value);
        if (hits.length) chooseFarmRow(hits[0]);
      }
    });
    document.getElementById("save-btn").addEventListener("click", function () {
      var name = document.getElementById("save-name").value.trim() || String(state.farm.label || "내 양식장");
      myFarms.push({ name: name.slice(0, 30), lat: state.farm.lat, lon: state.farm.lon,
                     species: F.species[state.species].name, farm: state.farm.farm || null });
      saveMy();
      state.farm = { lat: state.farm.lat, lon: state.farm.lon, label: name, farm: state.farm.farm || null, mine: true };
      save("farm", JSON.stringify(state.farm));
      render();
    });
    var mb = document.getElementById("manage-btn");
    mb.addEventListener("click", function () {
      var m = document.getElementById("manage");
      m.hidden = !m.hidden;
      mb.setAttribute("aria-expanded", m.hidden ? "false" : "true");
    });
    var msg = document.getElementById("move-msg");
    document.getElementById("copy-code").addEventListener("click", function () {
      var ta = document.getElementById("move-code");
      var done = function () { msg.textContent = "코드를 복사했어요. 새 휴대폰의 같은 칸에 붙여 넣어 주세요."; };
      var fallback = function () { ta.focus(); ta.select(); msg.textContent = "코드가 선택됐어요. 길게 눌러 '복사'를 골라 주세요."; };
      try { navigator.clipboard.writeText(ta.value).then(done, fallback); } catch (e) { fallback(); }
    });
    document.getElementById("import-code").addEventListener("click", function () {
      var got = decodeMy(document.getElementById("move-code").value);
      if (!got) { msg.textContent = "코드를 읽지 못했어요. HSW1: 로 시작하는 코드 전체를 붙여 넣어 주세요."; return; }
      var added = 0;
      got.forEach(function (f) {
        if (!myFarms.some(function (m) { return samePlace(m, f) && m.name === f.name; })) { myFarms.push(f); added++; }
      });
      saveMy();
      msg.textContent = "양식장 " + added + "곳을 가져왔어요.";
      render();
    });
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
    if (!cand.length) return { none: true, reason: "이 날짜의 관측 자료가 없어요." };
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

  // ---------- 탭 (양식장 / 전국 수온 예측) ----------
  // 등록된 양식장 위치(정확)와 지도 클릭 등 임의 지점(참고용)을 섞어서 보여주면
  // "이 위치가 내 양식장과 관련 있다"는 오해를 준다는 지적을 반영해 입력을 분리했다.
  // 아래에 나오는 예보·판정 결과는 두 탭 어느 쪽으로 골라도 같은 방식으로 계산된다.
  function isFarmTabLocation(f) { return !!(f && (f.farm || f.mine)); }
  function buildTabs() {
    var tabFarm = document.getElementById("tab-btn-farm"), tabExplore = document.getElementById("tab-btn-explore");
    var panelFarm = document.getElementById("panel-farm"), panelExplore = document.getElementById("panel-explore");
    function activate(tab) {
      var onFarm = tab === "farm";
      tabFarm.setAttribute("aria-selected", onFarm ? "true" : "false");
      tabFarm.tabIndex = onFarm ? 0 : -1;
      tabExplore.setAttribute("aria-selected", onFarm ? "false" : "true");
      tabExplore.tabIndex = onFarm ? -1 : 0;
      panelFarm.hidden = !onFarm;
      panelExplore.hidden = onFarm;
      // 지도가 hidden(display:none) 상태에서 만들어지면 Leaflet이 크기를 0으로 계산해
      // 왼쪽 위에 작게 찌그러진 채로만 그려진다 - 탭이 보이게 바뀔 때마다 다시 계산시킨다.
      // (지도는 buildMap()에서 이 함수보다 나중에 만들어지므로 아직 없을 수 있어 null 체크)
      // fitBounds도 같은 이유로 지도가 아직 숨어 있을 때(크기 0) 부르면 NaN 좌표 오류가 나서
      // 여기서 크기를 다시 잰 다음, 처음 한 번만 네 지역이 다 보이도록 시야를 맞춘다.
      if (!onFarm && map) {
        setTimeout(function () {
          map.invalidateSize();
          if (!zoneFitDone && zoneBounds) { map.fitBounds(zoneBounds, { padding: [28, 28] }); zoneFitDone = true; }
        }, 0);
      }
    }
    tabFarm.addEventListener("click", function () { activate("farm"); });
    tabExplore.addEventListener("click", function () { activate("explore"); });
    // 시작할 때는 등록된 양식장(또는 저장해 둔 내 양식장)이면 '양식장' 탭.
    // 그 외에는 전부 기본값이 '양식장' 탭이다 — 이번 방문이 ?place=·?lat=&lon= 딥링크로
    // 들어온 경우(state.viaUrlLink)만 예외로 '전국 수온 예측'을 유지한다.
    // (locationChosen을 기준으로 삼으면 예전에 프리셋 버튼을 한 번이라도 눌러 localStorage에
    //  남은 기록 때문에 다음 방문에도 계속 '전국 수온 예측'으로 가는 버그가 있었음 - 2026-09-28)
    activate((isFarmTabLocation(state.farm) || !state.viaUrlLink) ? "farm" : "explore");
  }

  // ---------- 결과 화면 3분할(오늘 상태 / 7일 예보 / 할 일) ----------
  // 상태카드·7일표·그래프·할일을 한 화면에 다 쌓아두면 토스처럼 "한 화면에 몇 개만
  // 또렷하게" 보여주는 느낌이 안 난다는 지적을 반영해 화면(탭)으로 나눴다 (2026-09-28).
  var resultTab = "today";
  function buildResultTabs() {
    var btns = {
      today: document.getElementById("rtab-btn-today"),
      week: document.getElementById("rtab-btn-week"),
      todo: document.getElementById("rtab-btn-todo")
    };
    var panels = {
      today: document.getElementById("rtab-today"),
      week: document.getElementById("rtab-week"),
      todo: document.getElementById("rtab-todo")
    };
    function activate(tab) {
      resultTab = tab;
      Object.keys(btns).forEach(function (k) {
        var on = k === tab;
        btns[k].setAttribute("aria-selected", on ? "true" : "false");
        btns[k].tabIndex = on ? 0 : -1;
        panels[k].hidden = !on;
      });
      // 그래프(SVG)는 컨테이너가 hidden(display:none)일 때 그리면 폭을 잘못 계산한다
      // (지도와 같은 문제) - '7일 예보' 탭이 보이게 바뀔 때마다 render()를 한 번 더
      // 불러 그 시점의 실제 크기로 다시 그린다. render()는 화면을 새로 계산해 채우기만
      // 하고 데이터를 다시 받아오지 않아 비용이 적다.
      if (tab === "week") setTimeout(function () { render(); }, 0);
    }
    Object.keys(btns).forEach(function (k) {
      btns[k].addEventListener("click", function () { activate(k); });
    });
    activate("today");
  }

  // ---------- 화면 전환 버튼 연결 (실제 화면 전환은 위 goScreen이 처리) ----------
  function buildSteps() {
    document.getElementById("welcome-next").addEventListener("click", function () { goScreen("location"); });
    document.getElementById("loc-confirm-back").addEventListener("click", function () { goScreen("location"); });
    document.getElementById("step1-next").addEventListener("click", function () { goScreen("confirm"); });
    document.getElementById("confirm-yes").addEventListener("click", function () { goScreen("species"); });
    document.getElementById("confirm-no").addEventListener("click", function () { goScreen("loading"); });
    document.getElementById("step2-back").addEventListener("click", function () { goScreen("confirm"); });
    document.getElementById("species-next").addEventListener("click", function () { goScreen("loading"); });
    document.getElementById("result-restart").addEventListener("click", function () { goScreen("location"); });
    goScreen(state.screen);  // 첫 화면 그리기
  }

  // ---------- 조회 조건 ----------
  function buildControls() {
    // 지역 버튼 목록: 지도가 안 뜰 때(!window.L)만 보여주는 대체 수단 (buildMap 참고).
    // 지도가 뜨면 이 목록은 계속 숨겨져 있고, 같은 지역들이 지도 위 색칠된 영역으로 나온다.
    var box = document.getElementById("preset-buttons");
    F.presets.forEach(function (p) {
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = p.label;
      b.dataset.preset = p.label;
      b.addEventListener("click", function () { state.gps = false; setFarm(presetFarm(p)); });
      box.appendChild(b);
    });
    if (!OPTIONS.noGps) {
      document.getElementById("gps-btn").addEventListener("click", locate);
    } else {
      document.getElementById("gps-field").hidden = true;
    }

    var ss = document.getElementById("station-select");
    var first = document.createElement("option");
    first.value = "";
    first.textContent = "관측소를 골라 주세요";
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
    sel.addEventListener("change", function () { state.species = +sel.value; save("species_name", F.species[+sel.value].name); render(); });

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
    if (!navigator.geolocation) { out.textContent = "이 기기에서는 위치 찾기를 쓸 수 없어요. 지도나 관측소 목록에서 골라 주세요."; return; }
    out.textContent = "현재 위치를 찾는 중이에요…";
    navigator.geolocation.getCurrentPosition(function (p) {
      state.gps = true;
      setFarm({ lat: p.coords.latitude, lon: p.coords.longitude, label: "내 위치" });
    }, function () {
      out.textContent = "위치를 찾지 못했어요. 위치 권한을 허용하거나, 지도나 관측소 목록에서 골라 주세요.";
    }, { enableHighAccuracy: true, timeout: 15000 });
  }

  // ---------- 지도 ----------
  var map = null, farmLayer = null, lineLayer = null, presetZoneLayer = null;
  var zoneBounds = null, zoneFitDone = false;
  function buildMap() {
    if (!window.L) {
      document.getElementById("map-wrap").hidden = true;  // 인터넷이 안 되면 지도 없이 사용
      document.getElementById("preset-list-field").hidden = false;  // 대신 목록 버튼으로 고르게 함
      return;
    }
    map = L.map("map", { zoomControl: true, attributionControl: true }).setView([34.62, 127.6], 9);
    // 바탕: 우리 해안선(Natural Earth). 인터넷 지도 타일이 없어도 육지·섬 모양이 보이게 타일 아래 층에 그림
    if (window.COAST) {
      map.createPane("coast").style.zIndex = 150;
      window.COAST.forEach(function (ring) {
        L.polygon(ring, { pane: "coast", color: "#8a96a3", weight: 1, fillColor: "#d7dde3", fillOpacity: 1, interactive: false }).addTo(map);
      });
    }
    if (!OPTIONS.noTiles) {
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 16, minZoom: 7, attribution: "© OpenStreetMap"
      }).addTo(map);
    } else {
      map.attributionControl.addAttribution("해안선: Natural Earth · 행정구역: 통계청(southkorea-maps)");
    }
    ST.forEach(function (s) {
      L.circleMarker([s.lat, s.lon], { radius: 5, color: "#ffffff", weight: 1.5, fillColor: "#1f5fa8", fillOpacity: 1 })
        .bindTooltip(s.name, { direction: "top" })
        .on("click", function () { state.gps = false; setFarm({ lat: s.lat, lon: s.lon, label: s.name + " 관측소", code: s.code }); })
        .addTo(map);
    });
    // 지역 빠른 선택 - 동그라미는 실제 지역 모양과 안 맞고 너무 작다는 지적 반영(2026-09-28).
    // 행정구역 경계 데이터는 없어서, 대신 이 지도의 모든 지점을 "4개 대표 관측소 중 어디에 더
    // 가까운가"로 나눠 칠했다 - 이게 정확히 이 앱이 지도를 눌렀을 때 위치를 고르는 것과 같은
    // 기준(가장 가까운 대표 지점)이라 원보다 실제 동작을 더 정확히 보여준다. 캔버스에 픽셀 단위로
    // 계산해 이미지 한 장으로 얹으므로(보로노이 다이어그램과 같은 결과) 동그라미보다 훨씬 넓고
    // 자연스러운 경계 모양이 나온다.
    // 근사 도형(원, 최근접 구역 칠하기)은 실제 지역 모양과 다르다는 지적 반영 - 통계청이 만들고
    // southkorea/southkorea-maps(공공누리 제1유형)가 정리해 둔 실제 시군구 경계로 바꿈
    // (data/regions.js, 2026-09-28). 나라 국경선처럼 실제 행정구역 모양 그대로 나온다.
    var ZONE_COLORS = ["#3182f6", "#15ad7e", "#e08a2c", "#8f4bc9"];
    presetZoneLayer = L.layerGroup().addTo(map);
    var zoneCoords = [];
    (window.REGIONS || []).forEach(function (r, i) {
      var preset = null;
      for (var k = 0; k < F.presets.length; k++) if (F.presets[k].label === r.label) { preset = F.presets[k]; break; }
      if (!preset) return;
      var s = byCode[preset.code];
      if (s) zoneCoords.push([s.lat, s.lon]);
      var color = ZONE_COLORS[i % ZONE_COLORS.length];
      var onPick = function (e) {
        L.DomEvent.stopPropagation(e);  // 안 막으면 지도 자체 클릭(임의 지점 선택)까지 겹쳐 발생해 방금 고른 지역을 덮어씀
        state.gps = false;
        setFarm(presetFarm(preset));
      };
      L.geoJSON(r.geometry, { style: { color: color, weight: 2, fillColor: color, fillOpacity: 0.3 } })
        .on("click", onPick).addTo(presetZoneLayer);
      if (s) {
        L.marker([s.lat, s.lon], {
          icon: L.divIcon({ className: "zone-label", html: '<span style="background:' + color + '">' + r.label + "</span>", iconSize: [44, 22], iconAnchor: [22, 11] })
        }).on("click", onPick).addTo(presetZoneLayer);
      }
    });
    zoneBounds = zoneCoords.length ? L.latLngBounds(zoneCoords) : null;
    lineLayer = L.layerGroup().addTo(map);
    farmLayer = L.layerGroup().addTo(map);
    map.on("click", function (e) {
      if (isOnLand(e.latlng.lat, e.latlng.lng)) {
        L.popup({ closeButton: false, autoClose: true })
          .setLatLng(e.latlng).setContent("육지예요. 바다 위치를 눌러 주세요.").openOn(map);
        setTimeout(function () { map.closePopup(); }, 1800);
        return;
      }
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
      .bindTooltip(isFarmTabLocation(state.farm) ? "양식장 위치" : "선택한 위치", { direction: "top", permanent: false })
      .addTo(farmLayer);
    if (!map.getBounds().pad(-0.1).contains(f)) map.setView(f, Math.max(map.getZoom(), 10));
  }

  // ---------- 그리기 ----------
  function render() {
    var sp = F.species[state.species];
    var est = estimate();

    Array.prototype.forEach.call(document.querySelectorAll("#preset-buttons button"), function (b) {
      b.setAttribute("aria-pressed", state.farm.preset === b.dataset.preset ? "true" : "false");
    });
    var gpsBtn = document.getElementById("gps-btn");
    if (gpsBtn) gpsBtn.setAttribute("aria-pressed", state.gps ? "true" : "false");
    var ss = document.getElementById("station-select");
    ss.value = state.farm.code && !state.farm.preset ? state.farm.code : "";
    document.body.classList.toggle("showing-past", !est.none && est.past);

    // 위치 이름 / 관측소 거리(보조 정보) / 양식장 등록정보(칩) 를 한 문장으로 뭉치지 않고 줄을 나눠
    // 각각 알아보기 쉽게 한다 (전부 같은 줄글로 붙어 있으면 뭐가 중요한지 안 보인다는 지적 반영)
    var metaEl = document.getElementById("place-meta");
    if (!state.locationChosen) {
      // 아직 직접 고른 적 없는 화면 기본값(예시 관측소)을 실제로 고른 것처럼 보여주지 않음
      document.getElementById("place-now").textContent = "선택한 위치: 없음";
      metaEl.hidden = true;
    } else {
      document.getElementById("place-now").innerHTML = "선택한 위치: <strong>" + state.farm.label + "</strong>";
      if (est.nn) {
        metaEl.hidden = false;
        metaEl.textContent = "가장 가까운 관측소 " + est.nn.s.name + " · " + est.nn.d.toFixed(1) + "km";
      } else {
        metaEl.hidden = true;
      }
    }
    var fmInfo = state.farm.farm;
    var farmLineEl = document.getElementById("place-farm");
    if (fmInfo && fmInfo.lcns) {
      farmLineEl.hidden = false;
      farmLineEl.textContent = "면허 " + fmInfo.lcns + " · " + [fmInfo.knd, fmInfo.mthd].filter(Boolean).join(" · ");
    } else {
      farmLineEl.hidden = true;
    }
    var note = document.getElementById("farm-note");
    if (fmInfo && speciesFromKind((fmInfo.kind || "") + " " + (fmInfo.knd || "")) < 0) {
      note.hidden = false;
      note.textContent = "이 양식장 품종(" + (fmInfo.kind || fmInfo.knd || "등록 정보 없음") + ")은 앱에 기준 수온이 없어요. " +
        "아래 '기르는 어종'에서 가장 가까운 어종을 골라 주세요. 지금은 " + sp.name + " 기준으로 보여 줘요.";
    } else {
      note.hidden = true;
    }
    renderMyFarms();
    drawMap(est);
    document.getElementById("step-place-echo").innerHTML = "선택한 위치: <strong>" + state.farm.label + "</strong>";

    // '결과' 화면에 이르기 전에는 예보 결과를 보여주지 않는다 - 화면마다 할 일 하나씩만
    if (state.screen !== "result") {
      document.getElementById("unavailable").hidden = true;
      document.getElementById("result").hidden = true;
      return;
    }

    document.getElementById("unavailable").hidden = !est.none;
    document.getElementById("result").hidden = est.none;
    if (est.none) {
      document.getElementById("unavailable-msg").textContent = est.nn
        ? "가장 가까운 수온 관측소(" + est.nn.s.name + ")가 " + est.nn.d.toFixed(0) + "km 떨어져 있어 이 위치의 예보를 믿을 수 없어요. " +
          "관측소에서 " + K.max_km + "km 안쪽의 양식장 위치를 골라 주세요."
        : est.reason;
      return;
    }

    // 김은 '위험 상한'이 아니라 '채묘 적정 온도' 기준이라 다른 어종과 계산 방식이 다름 -
    // 정상/주의/위험 분류를 쓰지 않고 별도의 중립 안내로 대체 (2026-09-28)
    if (sp.name === "김") { renderSeaweed(est, sp); return; }

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
      msg = (est.past ? "이날 수온이" : "현재 수온이") + " 위험 수온(" + sp.danger + "℃) 이상이에요. 바로 대비해요.";
    } else if (firstCrit >= 0) {
      msg = mdw(est.days[firstCrit].date) + " 전후로 위험 수온(" + sp.danger +
            "℃)에 가까워질 것으로 예상돼요. 하루 이틀 빠를 수 있으니 미리 대비해요.";
    } else if (overall === "warn") {
      msg = "적정 수온(" + sp.opt_max + "℃)보다 높은 날이 있어요. 7일 안에 위험 수온 도달은 예상되지 않아요.";
    } else {
      msg = "앞으로 7일 동안 적정 수온 범위에서 유지될 것으로 예상돼요.";
    }
    document.getElementById("status-msg").textContent = msg;
    var warn = document.getElementById("status-warn");
    warn.hidden = est.nn.d <= K.warn_km;
    warn.textContent = "가장 가까운 관측소가 " + est.nn.d.toFixed(1) + "km 떨어져 있어 이 위치의 정확도가 낮아요. 참고용으로만 봐 주세요.";

    document.getElementById("fact-now-label").textContent = est.past ? "기준일 수온" : "현재 수온";
    document.getElementById("fact-now").innerHTML =
      t1(est.today) + "<small>" + md(est.issue) + " 하루 평균 · 이 위치 추정</small>";
    document.getElementById("fact-danger-label").textContent = "위험 수온";  // 김 화면에서 바뀐 라벨 원복
    document.getElementById("fact-danger").innerHTML =
      sp.danger.toFixed(1) + "℃<small>" + (sp.danger - F.alert_margin).toFixed(2).replace(/0$/, "") + "℃부터 위험 표시</small>";
    document.getElementById("fact-opt-box").hidden = false;
    document.getElementById("fact-opt").innerHTML =
      sp.opt_min + "~" + sp.opt_max + "℃<small>고수온 특보 기준 " + F.official_alert_temp + "℃</small>";
    document.getElementById("fact-src").textContent = sp.src ? "기준 수온 출처: " + sp.src : "";

    renderTable(est, lvDays, lvToday === "crit" ? -1 : firstCrit);
    renderChart(est, sp);
    renderActions(overall, sp);
    renderSources(est);
    renderAccuracy(est);
  }

  // 김: 여름 고수온 위험이 아니라 가을 채묘(종자 붙이기) 적정 온도와 지금 수온을 비교해서만
  // 보여준다. 정상/주의/위험 색·차트 위험선·할 일 문구는 다른 어종 것을 그대로 쓰면 틀린 말이
  // 되므로 쓰지 않는다 (2026-09-28).
  function renderSeaweed(v, sp) {
    document.getElementById("status").className = "status none";
    document.getElementById("status-word").textContent = "채묘 시기 참고";
    document.getElementById("status-scope").textContent = "김 기준 · 여름 고수온 위험과는 다른 기준";
    var diff = v.today - sp.opt_max;
    var msg;
    if (Math.abs(diff) < 0.3) {
      msg = "지금 이 위치 수온(" + t1(v.today) + ")이 김 채묘 적정 기준(" + sp.opt_max + "℃)과 거의 같아요.";
    } else if (diff > 0) {
      msg = "지금 이 위치 수온(" + t1(v.today) + ")이 김 채묘 적정 기준(" + sp.opt_max + "℃)보다 " +
            diff.toFixed(1) + "℃ 높아요. 아직 물이 덜 식어서 채묘(종자 붙이기)를 시작하기엔 일러요.";
    } else {
      msg = "지금 이 위치 수온(" + t1(v.today) + ")이 김 채묘 적정 기준(" + sp.opt_max + "℃)보다 " +
            (-diff).toFixed(1) + "℃ 낮아요.";
    }
    document.getElementById("status-msg").textContent = msg;
    var warnEl = document.getElementById("status-warn");
    warnEl.hidden = v.nn.d <= K.warn_km;
    warnEl.textContent = "가장 가까운 관측소가 " + v.nn.d.toFixed(1) + "km 떨어져 있어 이 위치의 정확도가 낮아요. 참고용으로만 봐 주세요.";

    document.getElementById("fact-now-label").textContent = v.past ? "기준일 수온" : "현재 수온";
    document.getElementById("fact-now").innerHTML =
      t1(v.today) + "<small>" + md(v.issue) + " 하루 평균 · 이 위치 추정</small>";
    document.getElementById("fact-danger-label").textContent = "채묘 적정 기준";
    document.getElementById("fact-danger").innerHTML = sp.opt_max + "℃<small>이 온도로 식으면 채묘 시작</small>";
    document.getElementById("fact-opt-box").hidden = true;
    document.getElementById("fact-src").textContent = sp.src ? "기준 출처: " + sp.src : "";

    // 7일 온도 자체는 참고가 되므로 표는 그대로 보여주되, 위험/주의 색 표시는 다 빼서(null) 태그
    // 칸이 "-"로만 나오게 한다 - 이 숫자로 위험을 판단하는 게 아니라서 색을 칠하면 오해를 줌
    renderTable(v, v.days.map(function () { return null; }), -1);
    document.getElementById("legend").innerHTML = "";
    document.getElementById("chart").innerHTML =
      '<p class="hint">김은 채묘 시기 비교로만 안내돼요. 위 "오늘 상태" 값을 참고해 주세요.</p>';
    renderSources(v);
    renderAccuracy(v);

    var ol = document.getElementById("actions");
    ol.innerHTML = "";
    var li = document.createElement("li");
    li.textContent = "김은 가을~봄에 기르는 해조류라 여름철 폐사 대응요령은 따로 없어요. " +
      "위 '오늘 상태'의 채묘 시기 비교만 참고해 주세요.";
    ol.appendChild(li);
    document.getElementById("action-note").textContent = "김 · 참고 정보";
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
    var isShellfish = !!SHELLFISH[sp.name];
    ACTIONS[level].forEach(function (t) {
      if (isShellfish && /사료|물고기/.test(t)) return;  // 패류엔 안 맞는 문구는 건너뜀
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
      "주변 관측소 " + est.nb.length + "곳의 예보를, 거리와 관측소끼리 수온이 얼마나 비슷하게 움직이는지에 따라 섞었어요(크리깅). " +
      "양식장 위치를 관측소 값으로 추정하면서 생기는 오차는 약 ±" + est.sd.toFixed(1) + "℃이고, 표의 예상 범위에 들어 있어요.";
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
    if (!vals.length) { box.textContent = "표시할 수온 자료가 없어요."; return; }
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
    if (!showDanger) lg.insertAdjacentHTML("beforeend", "<span>위험 수온 " + sp.danger + "℃는 그래프보다 훨씬 위에 있어요</span>");

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
      "위 네 줄은 대표 관측소 4곳, 아래 두 줄은 이 위치에 쓴 관측소 기준이에요. " + V["기간"] +
      " 실제 수온으로 확인했고, 이 기간은 예보 모델을 만들 때 쓰지 않았어요. 관측소에서 멀어질수록 추정 오차가 커져요.";
  }

  function renderMeta() {
    document.getElementById("generated").textContent = "예보 생성: " + F.generated_at + " · 관측소 " + ST.length + "곳";
    // 결과(예보 수치)에 관한 안내라 결과 화면에만 둔다 - 인사말·위치 고르기 등 다른 화면에서는
    // 아직 상관없는 내용이라 매번 보이면 그 화면에서 할 일이 뭔지 헷갈린다.
    if (F.notes && F.notes.length) {
      var n = document.createElement("p");
      n.className = "notice";
      n.textContent = "최신 관측 자료를 받지 못해 이전 자료로 만든 예보예요. 기준일을 확인해 주세요.";
      document.getElementById("result").insertBefore(n, document.getElementById("result-restart").nextSibling);
    }
  }

  // 저장된 내 양식장이 있으면 그걸 먼저 보여줌 (그 외에는 초기 화면 - 위 initFarm 참고)
  if (!state.locationChosen && myFarms.length) {
    var f0 = myFarms[0];
    state.farm = { lat: f0.lat, lon: f0.lon, label: f0.name, farm: f0.farm || null, mine: true };
    var s0 = speciesIndexByName(f0.species);
    if (s0 >= 0) state.species = s0;
    state.locationChosen = true;
  }
  // 매번 인사말 화면부터 시작 - 이전 기록이 있다고 중간 화면으로 건너뛰면
  // 뭘 보고 있는지 헷갈린다는 지적. state.locationChosen은 "선택한 위치" 표시 여부에만 쓴다.
  // 단, ?place=·?lat=&lon= 링크로 바로 들어온 경우(state.viaUrlLink)는 공유받은 결과를
  // 바로 보려는 것이므로 인사말·위치·어종 화면을 거치지 않고 결과로 바로 간다.
  state.screen = state.viaUrlLink ? "result" : "welcome";

  buildControls();
  buildMyFarmControls();
  buildTabs();
  buildResultTabs();
  buildSteps();
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
