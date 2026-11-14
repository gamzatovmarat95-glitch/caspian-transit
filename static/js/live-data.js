/* Display-only external observations. Routing, persistence and decisions stay in Django. */
(() => {
  "use strict";
  const finite = (value, low, high) =>
    typeof value === "number" &&
    Number.isFinite(value) &&
    value >= low &&
    value <= high;
  const number = (v, unit = "") =>
    v == null
      ? "нет данных"
      : `${v.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}${unit}`;
  const date = (at) =>
    new Intl.DateTimeFormat("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "Europe/Moscow",
    }).format(new Date(at));
  const directions = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"];
  const direction = (v) =>
    v == null ? "—" : `${directions[Math.round(v / 45) % 8]} ${Math.round(v)}°`;
  function windInfo(point) {
    const speed = point.windMs;
    return {
      color: point.stale
        ? "#8a969d"
        : speed < 3
          ? "#479cc3"
          : speed < 7
            ? "#258ba0"
            : speed < 12
              ? "#329c87"
              : speed < 17
                ? "#c3a04a"
                : speed < 23
                  ? "#ca7547"
                  : "#be4f5c",
      toDeg: finite(point.directionDeg, 0, 360)
        ? (point.directionDeg + 180) % 360
        : null,
      duration: Math.max(1.1, 3.2 - Math.min(speed, 30) * 0.07),
    };
  }
  function normalizeWeather(raw, points) {
    if (!Array.isArray(raw) || raw.length !== points.length)
      throw Error("Неверный ответ погоды");
    const rows = [];
    raw.forEach((item, index) => {
      const current = item?.current,
        units = item?.current_units;
      if (
        !current ||
        units?.wind_speed_10m !== "m/s" ||
        units?.wind_gusts_10m !== "m/s" ||
        !finite(current.time, 946684800, 4102444800) ||
        !finite(current.wind_speed_10m, 0, 150)
      )
        return;
      const get = (key, low, high) =>
        finite(current[key], low, high) ? current[key] : null;
      const age = Date.now() - current.time * 1000;
      rows.push({
        ...points[index],
        at: current.time * 1000,
        windMs: current.wind_speed_10m,
        gustMs: get("wind_gusts_10m", 0, 200),
        directionDeg: get("wind_direction_10m", 0, 360),
        temperatureC: get("temperature_2m", -100, 100),
        stale: age > 3 * 3600000 || age < -1800000,
      });
    });
    if (!rows.length) throw Error("Нет текущих погодных значений");
    return rows;
  }
  function normalizeAis(raw) {
    if (
      raw?.type !== "FeatureCollection" ||
      !Array.isArray(raw.features) ||
      raw.features.length > 10000
    )
      throw Error("Неверный ответ AIS");
    const rows = [],
      ids = new Set();
    raw.features.forEach((feature) => {
      const p = feature?.properties || {},
        c = feature?.geometry?.coordinates;
      if (
        feature?.geometry?.type !== "Point" ||
        !Array.isArray(c) ||
        !finite(c[0], 46.5, 55) ||
        !finite(c[1], 35.8, 47.5)
      )
        return;
      const mmsi = String(p.mmsi ?? feature.id ?? ""),
        seen = p.seen,
        at = Date.parse(seen);
      if (
        !/^\d{9}$/.test(mmsi) ||
        !Number.isFinite(at) ||
        typeof seen !== "string" ||
        !/(Z|[+-]\d\d:\d\d)$/.test(seen) ||
        ids.has(mmsi)
      )
        return;
      const age = Date.now() - at,
        course = finite(p.heading, 0, 359.999) ? p.heading : p.cog;
      if (age > 86400000 || age < -300000) return;
      ids.add(mmsi);
      rows.push({
        mmsi,
        name: String(p.name || "Без названия").slice(0, 100),
        lon: c[0],
        lat: c[1],
        seen,
        speed: finite(p.sog, 0, 102.2) ? p.sog : null,
        course: finite(course, 0, 359.999) ? course : null,
        stale: age > 1800000 || age < -300000,
      });
    });
    return rows.sort((a, b) => Date.parse(b.seen) - Date.parse(a.seen));
  }
  // Export pure parsers for adapter checks; they contain no credentials or application state.
  window.CaspianLive = Object.freeze({
    normalizeWeather,
    normalizeAis,
    windInfo,
  });
  const configNode = document.getElementById("live-config");
  if (!configNode) return;
  const config = JSON.parse(configNode.textContent),
    $ = (id) => document.getElementById(id);
  const svgNS = "http://www.w3.org/2000/svg";
  const make = (tag, text, cls) => {
    const e = document.createElement(tag);
    if (text != null) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  };
  const svg = (tag, attrs = {}) => {
    const e = document.createElementNS(svgNS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
    return e;
  };
  const project = (lat, lon) => [
    ((lon - 42) / 14) * 900,
    ((49.3 - lat) / 14.3) * 680,
  ];
  let prefs = {};
  try {
    prefs = JSON.parse(
      localStorage.getItem("caspian-live-preferences-v2") || "{}",
    );
  } catch {}
  if (!prefs || typeof prefs !== "object") prefs = {};
  const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  let weatherRows = [],
    vessels = [],
    shipsVisible = config.shipOverlayEnabled !== false && prefs.ships !== false,
    windVisible = config.windOverlayEnabled !== false && prefs.wind !== false,
    labelsVisible = prefs.labels !== false,
    animationEnabled = prefs.animation ?? !reducedMotion?.matches,
    markers = [],
    mapState = window.caspianLiveMap || null;
  let aisProvider =
      prefs.provider === "marinetraffic" ||
      (!prefs.provider && config.marineTrafficConfigured)
        ? "marinetraffic"
        : "openwaters",
    aisGeneration = 0;
  let busy = false,
    weatherAt = 0,
    stopped = false;
  function shipIcon(vessel) {
    const e = svg("svg", { viewBox: "0 0 28 28", "aria-hidden": "true" });
    const shape =
      vessel.course == null
        ? svg("circle", {
            cx: 14,
            cy: 14,
            r: 6,
            fill: "currentColor",
            stroke: "white",
            "stroke-width": 2,
          })
        : svg("path", {
            d: "M14 2 L22 21 L14 18 L6 21 Z",
            fill: "currentColor",
            stroke: "white",
            "stroke-width": 1.5,
            transform: `rotate(${vessel.course} 14 14)`,
          });
    e.append(shape);
    return e;
  }
  function vesselTitle(v) {
    return `${v.name} · MMSI ${v.mmsi}\n${number(v.speed, " уз.")} · сигнал ${date(v.seen)} МСК${v.stale ? " · устаревший сигнал" : ""}\n${v.lat.toFixed(5)}, ${v.lon.toFixed(5)}`;
  }
  function windGlyph(point) {
    const info = windInfo(point),
      e = svg("svg", {
        viewBox: "-42 -42 84 84",
        width: 76,
        height: 76,
        "aria-hidden": "true",
        class: "wind-glyph",
        "data-wind-to": info.toDeg ?? "unknown",
      });
    e.style.color = info.color;
    e.append(
      svg("circle", {
        r: 27,
        fill: "white",
        "fill-opacity": 0.76,
        stroke: "currentColor",
        "stroke-opacity": 0.24,
        "stroke-width": 1,
      }),
    );
    if (info.toDeg == null) {
      e.append(
        svg("circle", {
          r: 7,
          fill: "none",
          stroke: "currentColor",
          "stroke-width": 2,
        }),
      );
      return e;
    }
    const group = svg("g", { transform: `rotate(${info.toDeg})` });
    group.append(
      svg("path", {
        d: "M0 20V-18",
        fill: "none",
        stroke: "currentColor",
        "stroke-width": 1.6,
        "stroke-opacity": 0.4,
      }),
    );
    const trail = svg("path", {
      d: "M0 27V-16",
      fill: "none",
      stroke: "currentColor",
      "stroke-width": 3,
      "stroke-linecap": "round",
      class: "wind-flow-trail",
    });
    const active = animationEnabled && !point.stale && point.windMs > 0.05;
    trail.style.animationPlayState = active ? "running" : "paused";
    trail.style.animationDuration = info.duration + "s";
    group.append(
      trail,
      svg("path", {
        d: "M0 -25 L-6 -14 L0 -17 L6 -14 Z",
        fill: "currentColor",
      }),
    );
    e.append(group);
    return e;
  }
  function syncControls() {
    const states = {
      ships: shipsVisible,
      wind: windVisible,
      animation: animationEnabled,
      labels: labelsVisible,
    };
    document
      .querySelectorAll("[data-live-toggle]")
      .forEach((button) =>
        button.setAttribute(
          "aria-pressed",
          String(states[button.dataset.liveToggle]),
        ),
      );
    $("live-ships-toggle")?.setAttribute("aria-pressed", String(shipsVisible));
    $("live-wind-toggle")?.setAttribute("aria-pressed", String(windVisible));
    document
      .querySelectorAll("[data-ais-provider]")
      .forEach((button) =>
        button.setAttribute(
          "aria-pressed",
          String(button.dataset.aisProvider === aisProvider),
        ),
      );
    if ($("live-wind-legend")) $("live-wind-legend").hidden = !windVisible;
    if ($("live-map-summary"))
      $("live-map-summary").textContent =
        config.shipOverlayEnabled === false
          ? "Наблюдения — во вкладках «Суда» и «Погода»"
          : `${weatherRows.length ? weatherRows.length + " погодных точек" : "Ветер: ожидаем данные"} · ${vessels.length ? vessels.length + " судов" : "AIS: нет отметок"}`;
    try {
      localStorage.setItem(
        "caspian-live-preferences-v2",
        JSON.stringify({ ...states, provider: aisProvider }),
      );
    } catch {}
  }
  function drawLayers() {
    if (config.windOverlayEnabled === false) windVisible = false;
    if (config.shipOverlayEnabled === false) shipsVisible = false;
    const windLayer = $("live-wind-layer"),
      shipLayer = $("live-vessel-layer");
    windLayer?.replaceChildren();
    shipLayer?.replaceChildren();
    for (const marker of markers) mapState?.map?.removeChild?.(marker);
    markers = [];
    if (windVisible)
      weatherRows.forEach((p) => {
        const [x, y] = project(p.lat, p.lon),
          offsetX = p.kind === "port" ? (p.lon >= 52 ? -75 : 65) : 0,
          offsetY = p.kind === "port" ? -50 : 0,
          group = svg("g", {
            transform: `translate(${x + offsetX},${y + offsetY})`,
            class: "live-wind-svg",
          });
        const title = svg("title");
        title.textContent = `${p.name}: ${number(p.windMs, " м/с")}; порывы ${number(p.gustMs, " м/с")}; откуда: ${direction(p.directionDeg)}; ${date(p.at)} МСК${p.stale ? "; данные устарели" : ""}`;
        const glyph = windGlyph(p);
        const size = p.detail ? 54 : 68;
        glyph.setAttribute("width", size);
        glyph.setAttribute("height", size);
        glyph.setAttribute("x", -size / 2);
        glyph.setAttribute("y", -size / 2);
        if (p.kind === "port")
          group.append(
            svg("path", {
              d: `M${-offsetX} ${-offsetY} L0 0`,
              stroke: "#7198a8",
              "stroke-width": 1.4,
              "stroke-dasharray": "3 4",
              fill: "none",
            }),
          );
        group.append(title, glyph);
        if (labelsVisible && !p.detail) {
          group.append(
            svg("rect", {
              x: 27,
              y: 8,
              width: 98,
              height: 25,
              rx: 6,
              fill: "#ffffff",
              stroke: "#b2cbd3",
            }),
          );
          const text = svg("text", { x: 34, y: 25, "font-size": 17 });
          text.style.fontSize = "17px";
          text.textContent = number(p.windMs, " м/с");
          group.append(text);
        }
        windLayer?.append(group);
        if (mapState) {
          const label = make("span", null, "live-wind-glyph-marker");
          if (p.kind === "port")
            label.style.transform = `translate(calc(-50% + ${offsetX * 0.65}px), calc(-50% + ${offsetY * 0.65}px))`;
          label.title = title.textContent;
          label.append(windGlyph(p));
          if (labelsVisible && !p.detail)
            label.append(
              make("span", number(p.windMs, " м/с"), "wind-value-label"),
            );
          const marker = new mapState.api.YMapMarker(
            { coordinates: [p.lon, p.lat], zIndex: 110 },
            label,
          );
          mapState.map.addChild(marker);
          markers.push(marker);
        }
      });
    syncControls();
    if (shipsVisible)
      vessels.forEach((v) => {
        const [x, y] = project(v.lat, v.lon),
          group = svg("g", {
            transform: `translate(${x - 14},${y - 14})`,
            class: "live-vessel-svg",
            tabindex: 0,
            role: "img",
            "aria-label": vesselTitle(v),
            color: v.stale ? "#7a8790" : "#12647b",
          });
        const title = svg("title");
        title.textContent = vesselTitle(v);
        group.append(title, shipIcon(v));
        shipLayer?.append(group);
        if (mapState) {
          const button = make(
            "button",
            null,
            "live-marker" + (v.stale ? " live-stale" : ""),
          );
          button.type = "button";
          button.title = vesselTitle(v);
          button.setAttribute("aria-label", vesselTitle(v));
          button.append(shipIcon(v));
          const marker = new mapState.api.YMapMarker(
            { coordinates: [v.lon, v.lat], zIndex: 150 },
            button,
          );
          mapState.map.addChild(marker);
          markers.push(marker);
        }
      });
  }
  function renderWeather(result, via) {
    weatherRows = result.points || [];
    const fresh = weatherRows.filter((p) => !p.stale).length,
      host = $("live-weather-status");
    host.className = fresh ? "live-connection-ok" : "live-connection-error";
    host.textContent = weatherRows.length
      ? `Ветер: ${fresh} актуальных точек из ${config.weatherPoints.length}. Данные модели на ${date(weatherRows[0].at)} МСК · получены ${date(result.fetchedAt)} МСК${via ? " · прямое соединение браузера" : ""}.`
      : "Текущая погода недоступна: источник не ответил. Архивные значения не показаны как текущие.";
    const grid = $("live-weather-readings");
    grid.replaceChildren();
    if ($("live-map-weather-time"))
      $("live-map-weather-time").textContent = weatherRows.length
        ? `${date(weatherRows[0].at)} МСК${fresh ? "" : " · устарело"}`
        : "Нет текущего ответа";
    weatherRows
      .filter((p) => !p.detail)
      .forEach((p) => {
        const card = make("div", null, "live-weather-card");
        card.style.setProperty("--wind-color", windInfo(p).color);
        card.append(
          make("span", p.name),
          make("strong", number(p.windMs, " м/с")),
          make("small", `Порывы ${number(p.gustMs, " м/с")}`),
          make("small", `Откуда: ${direction(p.directionDeg)}`),
          make(
            "small",
            `Воздух ${number(p.temperatureC, " °C")} · ${date(p.at)} МСК`,
          ),
        );
        if (p.stale)
          card.append(make("small", "Данные устарели", "live-stale"));
        if (
          document.querySelector("#scenario-form") &&
          p.kind === "port" &&
          !p.stale &&
          p.windMs <= 35
        ) {
          const button = make(
            "button",
            "Взять ветер для сценария",
            "live-apply-wind",
          );
          button.type = "button";
          button.addEventListener("click", () => {
            const port = document.querySelector("#scenario-form [name=portId]"),
              input = document.querySelector("#scenario-form [name=wind]");
            port.value = p.id;
            port.dispatchEvent(new Event("change", { bubbles: true }));
            input.value = p.windMs;
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.focus();
          });
          card.append(button);
        }
        grid.append(card);
      });
    drawLayers();
  }
  function renderAis(result, via) {
    vessels = result.vessels || [];
    const host = $("live-ais-status"),
      fresh = vessels.filter((v) => !v.stale).length;
    const name =
        aisProvider === "marinetraffic" ? "MarineTraffic" : "Open Waters",
      failed = ["unavailable", "not_configured", "loading"].includes(
        result.status,
      );
    host.className = failed ? "live-connection-error" : "live-connection-ok";
    host.textContent = failed
      ? `${name}: ${result.message || "источник недоступен. Последние позиции не подменяются."}`
      : vessels.length
        ? `${name}: ${vessels.length} судов, ${fresh} сигналов не старше 30 минут. Остальные — последние известные позиции за 24 часа${result.truncated ? "; источник ограничил выдачу, это не все суда" : ""}. Получено ${date(result.fetchedAt)} МСК${via ? " · прямое соединение браузера" : ""}.`
        : `${name} ответил, но за 24 часа в области нет наблюдений. Это может означать отсутствие покрытия, а не отсутствие судов.`;
    const list = $("live-vessel-list");
    list.replaceChildren();
    if (vessels.length) {
      const wrap = make("div", null, "live-table-wrap"),
        table = make("table", null, "live-table"),
        head = make("thead"),
        tr = make("tr");
      for (const t of [
        "Судно / MMSI",
        "Координаты",
        "Скорость",
        "Последний сигнал · МСК",
      ])
        tr.append(make("th", t));
      head.append(tr);
      table.append(head);
      const body = make("tbody");
      for (const v of vessels.slice(0, list.dataset.full ? 500 : 20)) {
        const row = make("tr"),
          name = make("td", v.name);
        name.append(make("small", v.mmsi));
        row.append(
          name,
          make("td", `${v.lat.toFixed(4)}, ${v.lon.toFixed(4)}`),
          make("td", number(v.speed, " уз.")),
          make("td", `${date(v.seen)}${v.stale ? " · старый сигнал" : ""}`),
        );
        body.append(row);
      }
      table.append(body);
      wrap.append(table);
      list.append(wrap);
      if (!list.dataset.full && vessels.length > 20)
        list.append(
          make(
            "p",
            `Показаны первые 20 из ${vessels.length}; полный список — в разделе AIS.`,
          ),
        );
    }
    $("live-ais-attribution").textContent = [
      `AIS: ${name}`,
      ...Object.entries(result.attribution || {}).map(
        ([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`,
      ),
    ].join(" · ");
    drawLayers();
  }
  async function getJson(url, external = false) {
    const controller = new AbortController(),
      timer = setTimeout(() => controller.abort(), 8000);
    try {
      const reply = await fetch(url, {
        cache: "no-store",
        signal: controller.signal,
        credentials: external ? "omit" : "same-origin",
        referrerPolicy: external ? "no-referrer" : "same-origin",
      });
      const text = await reply.text();
      if (text.length > 2_000_000) throw Error("Ответ слишком большой");
      const value = JSON.parse(text);
      if (!reply.ok && value.status !== "unavailable") {
        const error = Error("Источник недоступен");
        error.status = reply.status;
        throw error;
      }
      return value;
    } finally {
      clearTimeout(timer);
    }
  }
  async function localOrUnavailable(url) {
    try {
      return await getJson(url);
    } catch (error) {
      if (error.status === 401 || error.status === 403) throw error;
      return { status: "unavailable" };
    }
  }
  async function updateWeather() {
    try {
      let result = await localOrUnavailable("/api/weather/current"),
        direct = false;
      if (result.status === "unavailable") {
        const raw = await getJson(config.weatherUrl, true);
        result = {
          points: normalizeWeather(raw, config.weatherPoints),
          fetchedAt: new Date().toISOString(),
        };
        direct = true;
      }
      if (!Array.isArray(result.points)) throw Error();
      renderWeather(result, direct);
    } catch {
      renderWeather({ points: [] });
    }
    weatherAt = Date.now();
  }
  async function updateAis() {
    if (config.aisEnabled === false) return;
    const token = ++aisGeneration,
      requested = aisProvider;
    try {
      let result = await localOrUnavailable(
          requested === "marinetraffic"
            ? "/api/vessels?provider=marinetraffic"
            : "/api/vessels",
        ),
        direct = false;
      if (stopped || token !== aisGeneration) return;
      if (requested === "marinetraffic") {
        renderAis(result, false);
        return;
      }
      if (result.status === "unavailable") {
        const raw = await getJson(config.aisUrl, true);
        result = {
          status: "available",
          vessels: normalizeAis(raw),
          attribution: raw.attribution || {},
          truncated: !!raw.truncated,
          fetchedAt: new Date().toISOString(),
        };
        direct = true;
      }
      if (stopped || token !== aisGeneration) return;
      if (!Array.isArray(result.vessels)) throw Error();
      renderAis(result, direct);
    } catch {
      if (!stopped && token === aisGeneration)
        renderAis({ status: "unavailable", vessels: [] });
    }
  }
  async function refresh(force = false) {
    if (busy || stopped) return;
    busy = true;
    $("live-refresh").disabled = true;
    const jobs = config.aisEnabled === false ? [] : [updateAis()];
    if (force || Date.now() - weatherAt >= 300000) jobs.push(updateWeather());
    await Promise.allSettled(jobs);
    busy = false;
    $("live-refresh").disabled = false;
  }
  $("live-refresh").addEventListener("click", () => void refresh(true));
  $("live-ships-toggle")?.addEventListener("click", () => {
    shipsVisible = !shipsVisible;
    $("live-ships-toggle").setAttribute("aria-pressed", String(shipsVisible));
    drawLayers();
  });
  $("live-wind-toggle")?.addEventListener("click", () => {
    windVisible = !windVisible;
    $("live-wind-toggle").setAttribute("aria-pressed", String(windVisible));
    drawLayers();
  });
  document.querySelectorAll("[data-live-toggle]").forEach((button) =>
    button.addEventListener("click", () => {
      const kind = button.dataset.liveToggle;
      if (kind === "ships") shipsVisible = !shipsVisible;
      if (kind === "wind") windVisible = !windVisible;
      if (kind === "animation") animationEnabled = !animationEnabled;
      if (kind === "labels") labelsVisible = !labelsVisible;
      drawLayers();
    }),
  );
  document.querySelectorAll("[data-ais-provider]").forEach((button) =>
    button.addEventListener("click", () => {
      if (config.aisEnabled === false) return;
      if (aisProvider === button.dataset.aisProvider) return;
      aisProvider = button.dataset.aisProvider;
      vessels = [];
      drawLayers();
      $("live-ais-status").textContent = "Подключаем источник…";
      void updateAis();
    }),
  );
  reducedMotion?.addEventListener?.("change", (event) => {
    if (event.matches) {
      animationEnabled = false;
      drawLayers();
    }
  });
  window.addEventListener("caspian:map-ready", (event) => {
    mapState = event.detail;
    markers = [];
    drawLayers();
  });
  window.addEventListener("caspian:map-destroyed", () => {
    mapState = null;
    markers = [];
  });
  const timer = setInterval(() => {
    if (!document.hidden) void refresh();
  }, 60000);
  window.addEventListener("pagehide", () => {
    stopped = true;
    clearInterval(timer);
  });
  syncControls();
  void refresh(true);
})();
