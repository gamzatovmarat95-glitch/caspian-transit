/* Progressive enhancement only: Django renders pages and owns all business rules. */
(() => {
  "use strict";
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [
    ...root.querySelectorAll(selector),
  ];
  const date = (value) =>
    new Intl.DateTimeFormat("ru-RU", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "Europe/Moscow",
    }).format(new Date(value));
  const notice = (host, text) => {
    if (host) host.textContent = text;
  };
  function storageGet(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  }
  function storageSet(key, value) {
    try {
      if (value === null) localStorage.removeItem(key);
      else localStorage.setItem(key, value);
    } catch {}
  }
  $$("[data-method]").forEach((button) =>
    button.addEventListener("click", () => $("#method-dialog").showModal()),
  );
  $$("[data-close]").forEach((button) =>
    button.addEventListener("click", () =>
      document.getElementById(button.dataset.close).close(),
    ),
  );
  $$("[data-reset]").forEach((button) =>
    button.addEventListener("click", () => $("#reset-dialog").showModal()),
  );
  $$("[data-go]").forEach((row) =>
    row.addEventListener("click", (event) => {
      if (!event.target.closest("a,button,input,select,label"))
        location.href = row.dataset.go;
    }),
  );
  $$("[data-auto-submit] select").forEach((input) =>
    input.addEventListener("change", () => input.form.requestSubmit()),
  );
  $$("[data-search-form] input[name=q]").forEach((input) => {
    let timer;
    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => input.form.requestSubmit(), 600);
    });
    input.form.addEventListener("submit", () => clearTimeout(timer));
    const riskForm = input
      .closest(".table-controls")
      ?.querySelector("form:not([data-search-form])");
    riskForm?.addEventListener("submit", () => {
      clearTimeout(timer);
      $("input[name=q]", riskForm).value = input.value;
    });
  });
  $$("input[type=range]").forEach((input) => {
    const update = () => {
      const output = document.querySelector(`output[for="${input.id}"]`);
      if (output) output.value = Number(input.value).toLocaleString("ru-RU");
    };
    input.addEventListener("input", update);
    input.addEventListener("change", update);
  });
  $$("[data-upload-submit] input[type=file]").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.files?.length) input.form.requestSubmit();
    });
  });
  $("#pack-json-upload")?.addEventListener("change", async (event) => {
    const file = event.currentTarget.files?.[0],
      form = $(".document-form");
    if (!file || !form) return;
    try {
      if (file.size > 50000) throw Error("Выберите JSON до 50 КБ");
      const value = JSON.parse(await file.text());
      const fields = [
        "invoice",
        "packingList",
        "hsCode",
        "consignee",
        "massTon",
        "reference",
      ];
      if (!value || typeof value !== "object" || Array.isArray(value))
        throw Error("Нужен объект реквизитов");
      for (const name of fields) {
        if (name === "massTon") {
          if (
            typeof value[name] !== "number" ||
            !Number.isFinite(value[name]) ||
            value[name] <= 0 ||
            value[name] > 100
          )
            throw Error("Проверьте массу партии");
        } else if (
          typeof value[name] !== "string" ||
          value[name].length > (name === "consignee" ? 200 : 100)
        )
          throw Error("Проверьте поле " + name);
      }
      for (const name of fields)
        $(`[name="${name}"]`, form).value = value[name];
      notice(
        $("#pack-upload-status"),
        "Реквизиты подставлены. Сохраните или проверьте пакет.",
      );
    } catch (error) {
      notice($("#pack-upload-status"), error.message);
    }
  });
  $$("dialog").forEach((dialog) =>
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) {
        const r = dialog.getBoundingClientRect();
        if (
          event.clientX < r.left ||
          event.clientX > r.right ||
          event.clientY < r.top ||
          event.clientY > r.bottom
        )
          dialog.close();
      }
    }),
  );
  $("#fill-document-example")?.addEventListener("click", () => {
    const form = $(".document-form"),
      id = $("[name=cargoId]", form).value.slice(4);
    $("[name=packingList]", form).value = "PL-DEMO-" + id;
    $("[name=invoice]", form).value = "INV-DEMO-" + id;
    $("[name=hsCode]", form).value = "6907210000";
    $("[name=reference]", form).value = "DEMO-" + id;
    $("[name=consignee]", form).value = "Demo consignee / учебная партия";
  });
  $("#fill-declaration-example")?.addEventListener("click", (event) => {
    const form = event.currentTarget.closest("form"),
      id = $("[name=cargoId]", form).value.slice(4);
    $("[name=originCountry]", form).value = "RU";
    $("[name=destinationCountry]", form).value = "IR";
    $("[name=transportDocument]", form).value = "TR-DEMO-" + id;
    $("[name=originCertificate]", form).value = "ORIGIN-DEMO-" + id;
    $("[name=declaredValueRub]", form).value = "100000";
  });
  $$("[data-verify]").forEach((button) =>
    button.addEventListener("click", async () => {
      const result = $(".proof-result", button.parentElement);
      button.disabled = true;
      try {
        const r = await fetch(button.dataset.verify, { cache: "no-store" });
        const value = await r.json();
        if (!r.ok) throw Error(value.error || "Не удалось проверить");
        const fields = [
          ["hashValid", "Хеш пакета"],
          ["signatureValid", "Подпись"],
          ["contentsValid", "Актуальное содержимое"],
          ["auditChainValid", "Цепочка журнала"],
        ];
        notice(
          result,
          fields
            .filter(([key]) => key in value)
            .map(
              ([key, label]) =>
                `${label}: ${value[key] ? "подтверждено" : "НЕ подтверждено"}`,
            )
            .join(" · "),
        );
      } catch (e) {
        notice(result, e.message);
      } finally {
        button.disabled = false;
      }
    }),
  );
  const eventKind = $("#event-form [name=kind]");
  function updateEventFields() {
    if (!eventKind) return;
    const needed = {
      delayHours: "inland_delay",
      queueUnits: "queue_changed",
      holdHours: "weather_hold",
    };
    Object.entries(needed).forEach(([key, kind]) => {
      const row = $(`[data-event-field="${key}"]`),
        input = $(`[name="${key}"]`, row);
      row.hidden = eventKind.value !== kind;
      input.disabled = row.hidden;
    });
  }
  eventKind?.addEventListener("change", updateEventFields);
  updateEventFields();

  const weatherHost = $("#weather-reading");
  let weather = null,
    currentWeatherPoint = null,
    weatherUsable = false;
  function showWeather() {
    if (!weatherHost || !weather) return;
    const id = $("#scenario-form [name=portId]")?.value,
      port = weather.ports.find((p) => p.id === id),
      now = Date.now();
    const point = port?.points.find((p) => p.at >= now) || port?.points.at(-1);
    currentWeatherPoint = point;
    weatherHost.replaceChildren();
    const line = document.createElement("div");
    line.className = "weather-value";
    const value = document.createElement("strong");
    value.textContent =
      point?.windMs != null ? `${point.windMs} м/с` : "Нет значения";
    const details = document.createElement("div"),
      gust = document.createElement("span");
    gust.textContent = `Порывы: ${point?.gustMs ?? "—"} м/с`;
    details.append(value, gust);
    const icon =
      $("#weather-icon")?.content?.firstElementChild?.cloneNode(true);
    const badge = document.createElement("span");
    badge.className = "badge " + (weather.fallback ? "warning" : "neutral");
    badge.textContent = weather.fallback
      ? "Сохранённый прогноз"
      : "Внешний прогноз";
    if (icon) line.append(icon);
    line.append(details, badge);
    weatherHost.append(line);
    const old =
      now - Date.parse(weather.fetchedAt) > 6 * 3600000 ||
      !point ||
      point.at < now - 3600000;
    weatherUsable =
      !!point &&
      point.windMs != null &&
      !old &&
      Number.isFinite(point.windMs) &&
      point.windMs >= 0 &&
      point.windMs <= 35;
    const meta = document.createElement("p");
    meta.textContent = point
      ? `На ${date(point.at)} МСК · порывы ${point.gustMs ?? "—"} м/с · получен ${date(weather.fetchedAt)}.${old ? " Кеш устарел или горизонт истёк." : ""}`
      : "В источнике нет подходящего прогноза.";
    weatherHost.append(meta);
    $("#use-weather").disabled = !weatherUsable;
  }
  async function refreshWeather() {
    if (!weatherHost) return;
    const button = $("#refresh-weather");
    button.disabled = true;
    try {
      const r = await fetch("/api/weather", { cache: "no-store" });
      if (!r.ok) throw Error();
      weather = await r.json();
      showWeather();
    } catch {
      notice(
        weatherHost,
        "Прогноз недоступен. Расчётная модель продолжает работать со сценарным ветром.",
      );
    } finally {
      button.disabled = false;
    }
  }
  $("#refresh-weather")?.addEventListener("click", refreshWeather);
  $("#scenario-form [name=portId]")?.addEventListener("change", showWeather);
  $("#use-weather")?.addEventListener("click", () => {
    if (weatherUsable && currentWeatherPoint) {
      $("#scenario-form [name=wind]").value = currentWeatherPoint.windMs;
      $("#scenario-form [name=wind]").dispatchEvent(
        new Event("input", { bubbles: true }),
      );
      $("#scenario-form [name=wind]").focus();
    }
  });
  if (weatherHost) void refreshWeather();

  const mapData = $("#map-data");
  if (!mapData) return;
  const data = JSON.parse(mapData.textContent),
    scheme = $("#schematic-map"),
    host = $("#yandex-layer"),
    mapError = $("#map-error"),
    loading = $("#map-loading");
  $("#scenario-form [name=portId]")?.addEventListener("change", (event) => {
    const port = data.ports.find(
      (value) => value.id === event.currentTarget.value,
    );
    if (!port) return;
    const values = {
      queue: port.queueUnits,
      wind: port.windMs,
      closureHours:
        port.closureStart == null
          ? 0
          : (port.closureEnd - port.closureStart) / 3600000,
    };
    for (const [name, value] of Object.entries(values)) {
      const input = $(`#scenario-form [name="${name}"]`);
      input.value = value;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
  });
  let configuredKey = null,
    browserKey =
      storageGet("caspian-django-yandex-key") ||
      storageGet("caspian-transit:yandex-browser-key") ||
      "",
    map = null,
    api = null,
    loadPromise = null,
    activeKey = null,
    provider = "scheme",
    generation = 0;
  function showMapError(text) {
    mapError.hidden = !text;
    notice(mapError, text);
  }
  function validKey(key) {
    return /^[a-zA-Z0-9_-]{16,160}$/.test(key || "");
  }
  function loadYandex(key) {
    if (!validKey(key))
      return Promise.reject(
        Error("Нужен корректный ключ JavaScript API Яндекс Карт."),
      );
    if (activeKey && activeKey !== key)
      return Promise.reject(
        Error("Ключ изменён. Обновите страницу для подключения новой карты."),
      );
    activeKey = key;
    if (window.ymaps3)
      return Promise.resolve(window.ymaps3.ready).then(() => window.ymaps3);
    if (loadPromise) return loadPromise;
    loadPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      let settled = false;
      const timer = setTimeout(() => {
        if (!settled) {
          settled = true;
          script.remove();
          loadPromise = null;
          reject(
            Error(
              "Яндекс Карты не ответили за 30 секунд. Доступна встроенная схема.",
            ),
          );
        }
      }, 30000);
      function fail() {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        script.remove();
        loadPromise = null;
        reject(
          Error(
            "Не удалось подключить Яндекс Карты. Проверьте ключ, localhost и интернет.",
          ),
        );
      }
      script.referrerPolicy = "strict-origin-when-cross-origin";
      script.src =
        "https://api-maps.yandex.ru/v3/?apikey=" +
        encodeURIComponent(key) +
        "&lang=ru_RU";
      script.async = true;
      script.onerror = fail;
      script.onload = async () => {
        try {
          if (!window.ymaps3) throw Error();
          await window.ymaps3.ready;
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          resolve(window.ymaps3);
        } catch {
          fail();
        }
      };
      document.head.append(script);
    });
    return loadPromise;
  }
  function routeURL(route) {
    const p = new URLSearchParams({
      page: data.page,
      cargo: data.cargoId,
      route,
    });
    return "/?" + p + "#decision";
  }
  const routeEntities = new Map();
  const landEntities = new Map();
  const originalRoute = data.selectedRoute;
  const originalRouteDescription = $("#map-route-description")?.textContent;
  let mathematicalRoute = null;
  const corridorPoints = [
    ...data.routes.flatMap((route) => route.geometry),
    ...(data.landSegments || []).flatMap((segment) => segment.geometry),
    ...data.ports.map((port) => [port.lat, port.lon]),
  ];
  const corridorBounds = [
    [
      Math.min(...corridorPoints.map((point) => point[1])) - 0.45,
      Math.min(...corridorPoints.map((point) => point[0])) - 1,
    ],
    [
      Math.max(...corridorPoints.map((point) => point[1])) + 0.45,
      Math.max(...corridorPoints.map((point) => point[0])) + 1,
    ],
  ];
  function routeStyle(id) {
    const color = data.routes.find((r) => r.id === id)?.color || "#536477";
    const selected = id === data.selectedRoute;
    const width = selected ? (mathematicalRoute ? 6 : 5) : 2.5;
    return {
      zIndex: selected ? 30 : 10,
      simplificationRate: 0,
      stroke: [
        {
          color:
            selected
              ? mathematicalRoute
                ? "#df0879"
                : color
              : color,
          width,
          opacity: selected ? 0.92 : 0.72,
        },
        { color: "#ffffff", width: width + 2, opacity: 0.85 },
      ],
    };
  }
  function landStyle(segment) {
    const selected = segment.routeIds.includes(data.selectedRoute);
    return {
      zIndex: selected ? 8 : 5,
      simplificationRate: 0,
      stroke: [{
        color: "#566c7a",
        width: selected ? 2.5 : 1.7,
        opacity: selected ? 0.85 : 0.4,
        dash: segment.mode === "rail" ? [9, 4, 2, 4] : [5, 5],
      }],
    };
  }
  window.addEventListener("caspian:optimized-route", (event) => {
    const selected = data.routes.find(
      (route) => route.id === event.detail?.routeId,
    );
    mathematicalRoute = selected?.id || null;
    data.selectedRoute = mathematicalRoute || originalRoute;
    const svg = $("#route-svg");
    let layer = $("#optimized-route-layer");
    if (!layer && svg) {
      layer = document.createElementNS("http://www.w3.org/2000/svg", "g");
      layer.id = "optimized-route-layer";
      svg.insertBefore(layer, svg.querySelector(".city-label"));
    }
    layer?.replaceChildren();
    $$(".active-sea-route").forEach(
      (path) => (path.style.opacity = mathematicalRoute ? ".18" : "1"),
    );
    if (selected && layer) {
      const path = document.createElementNS(
        "http://www.w3.org/2000/svg",
        "path",
      );
      path.setAttribute(
        "d",
        selected.geometry
          .map(
            ([lat, lon], i) =>
              (i ? "L" : "M") +
              ((lon - 42) / 14) * 900 +
              "," +
              ((49.3 - lat) / 14.3) * 680,
          )
          .join(" "),
      );
      path.setAttribute("fill", "none");
      const halo = path.cloneNode(true);
      halo.setAttribute("stroke", "white");
      halo.setAttribute("stroke-width", "8");
      halo.setAttribute("stroke-linecap", "round");
      layer.append(halo);
      path.setAttribute("stroke", "#df0879");
      path.setAttribute("stroke-width", "6");
      path.setAttribute("stroke-opacity", ".92");
      path.setAttribute("stroke-linecap", "round");
      layer.append(path);
    }
    for (const [id, feature] of routeEntities)
      feature.update?.({ style: routeStyle(id) });
    for (const { segment, feature } of landEntities.values())
      feature.update?.({ style: landStyle(segment) });
    $$("#land-route-layer path").forEach((path) => {
      const selected = path.dataset.routeIds.split(" ").includes(data.selectedRoute);
      path.setAttribute("stroke-width", selected ? "2.5" : "1.7");
      path.setAttribute("stroke-opacity", selected ? ".85" : ".4");
    });
    const note = $("#optimized-map-note");
    if (note) {
      note.hidden = !selected;
      note.textContent = selected ? "Расчётный оптимум: " + selected.name : "";
    }
    const shownRoute =
      selected || data.routes.find((r) => r.id === originalRoute);
    const description = $("#map-route-description");
    if (description)
      description.textContent = selected
        ? "Рекомендация расчёта: " + selected.name
        : originalRouteDescription;
    const chain = $("#map-route-chain");
    if (chain && shownRoute?.chain) chain.textContent = shownRoute.chain;
    $$(".map-route-tabs button[name=route]").forEach((button) => {
      button.classList.toggle("selected", button.value === data.selectedRoute);
      if (button.value === data.selectedRoute)
        button.setAttribute("aria-current", "true");
      else button.removeAttribute("aria-current");
    });
  });
  function drawYandex() {
    routeEntities.clear();
    landEntities.clear();
    map = new api.YMap(host, {
      location: {
        bounds: corridorBounds,
      },
      mode: "auto",
      margin: [55, 45, 65, 45],
      copyrightsPosition: "bottom right",
    });
    map.addChild(new api.YMapDefaultSchemeLayer());
    map.addChild(new api.YMapDefaultFeaturesLayer());
    (data.landSegments || []).forEach((segment) => {
      const feature = new api.YMapFeature({
        id: segment.id,
        geometry: {
          type: "LineString",
          coordinates: segment.geometry.map(([lat, lon]) => [lon, lat]),
        },
        style: landStyle(segment),
      });
      landEntities.set(segment.id, { segment, feature });
      map.addChild(feature);
    });
    (data.approaches || []).forEach((approach) => {
      map.addChild(
        new api.YMapFeature({
          geometry: {
            type: "LineString",
            coordinates: approach.geometry.map(([lat, lon]) => [lon, lat]),
          },
          style: { stroke: [{ color: "#7d8793", width: 1.5, dash: [3, 5], opacity: 0.65 }] },
        }),
      );
    });
    [...data.routes]
      .sort(
        (a, b) =>
          Number(a.id === data.selectedRoute) -
          Number(b.id === data.selectedRoute),
      )
      .forEach((route) => {
        const feature = new api.YMapFeature({
          geometry: {
            type: "LineString",
            coordinates: route.geometry.map(([lat, lon]) => [lon, lat]),
          },
          style: routeStyle(route.id),
          onClick: () => location.assign(routeURL(route.id)),
        });
        routeEntities.set(route.id, feature);
        map.addChild(feature);
      });
    data.ports.forEach((port) => {
      const element = document.createElement("button");
      element.type = "button";
      element.className =
        "yandex-port" + (port.closureStart !== null ? " closed" : "");
      element.setAttribute(
        "aria-label",
        `Порт ${port.name}, очередь ${port.queueUnits}`,
      );
      const dot = document.createElement("i"),
        label = document.createElement("span"),
        title = document.createElement("strong"),
        meta = document.createElement("small");
      title.textContent = port.name;
      const windLabel = Number(port.windMs).toLocaleString("ru-RU", {
        maximumFractionDigits: 1,
      });
      meta.textContent = `Модель: ${port.queueUnits} ед. · ${windLabel} м/с`;
      label.append(title, meta);
      element.append(dot, label);
      element.addEventListener("click", () =>
        location.assign(
          "/?" +
            new URLSearchParams({
              page: "scenarios",
              port: port.id,
              cargo: data.cargoId,
            }),
        ),
      );
      map.addChild(
        new api.YMapMarker(
          { coordinates: [port.lon, port.lat], zIndex: 100 },
          element,
        ),
      );
    });
    [
      [44.51, 48.71, "Волгоград"],
      [51.39, 35.69, "Тегеран"],
    ].forEach(([lon, lat, name]) => {
      const e = document.createElement("span");
      e.className = "yandex-city";
      e.textContent = name;
      map.addChild(new api.YMapMarker({ coordinates: [lon, lat] }, e));
    });
    window.caspianLiveMap = { map, api };
    window.dispatchEvent(
      new CustomEvent("caspian:map-ready", { detail: { map, api } }),
    );
  }
  function controls() {
    $$("[data-map-provider]").forEach((b) =>
      b.setAttribute(
        "aria-pressed",
        String(b.dataset.mapProvider === provider),
      ),
    );
  }
  function useScheme(persist = true) {
    host.closest(".map-canvas")?.classList.remove("is-yandex");
    window.caspianLiveMap = null;
    window.dispatchEvent(new Event("caspian:map-destroyed"));
    generation++;
    map?.destroy();
    map = null;
    provider = "scheme";
    host.hidden = true;
    scheme.hidden = false;
    loading.hidden = true;
    controls();
    if (persist) storageSet("caspian-django-map-provider", "scheme");
  }
  async function useYandex(persist = true) {
    const key = configuredKey || browserKey;
    if (!validKey(key)) {
      $("#map-settings-dialog").showModal();
      notice(
        $("#map-key-status"),
        "Введите ключ JavaScript API или используйте встроенную схему.",
      );
      return;
    }
    if (provider === "yandex" && map) return;
    const token = ++generation;
    loading.hidden = false;
    showMapError("");
    try {
      api = await loadYandex(key);
      if (token !== generation) return;
      map?.destroy();
      host.hidden = false;
      scheme.hidden = true;
      drawYandex();
      host.closest(".map-canvas")?.classList.add("is-yandex");
      provider = "yandex";
      controls();
      if (persist) storageSet("caspian-django-map-provider", "yandex");
    } catch (e) {
      if (token !== generation) return;
      useScheme(false);
      showMapError(e.message);
    } finally {
      if (token === generation) loading.hidden = true;
    }
  }
  $$("[data-map-provider]").forEach((b) =>
    b.addEventListener("click", () => {
      if (b.dataset.mapProvider === "scheme") {
        showMapError("");
        useScheme();
      } else void useYandex();
    }),
  );
  $("#map-settings-button").addEventListener("click", () =>
    $("#map-settings-dialog").showModal(),
  );
  $("#map-key-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const value = $("#map-key-input").value.trim();
    if (value && !validKey(value)) {
      notice(
        $("#map-key-status"),
        "Ключ должен содержать 16–160 латинских букв, цифр, _ или -.",
      );
      return;
    }
    if (value) {
      browserKey = value;
      storageSet("caspian-django-yandex-key", value);
    }
    if (!configuredKey && !browserKey) {
      notice($("#map-key-status"), "Введите ключ.");
      return;
    }
    $("#map-settings-dialog").close();
    await useYandex();
  });
  $("#map-reset-key").addEventListener("click", () => {
    browserKey = "";
    storageSet("caspian-django-yandex-key", null);
    $("#map-key-input").value = "";
    notice(
      $("#map-key-status"),
      configuredKey
        ? "Ключ удалён из браузера; ключ локального приложения по-прежнему настроен."
        : "Ключ удалён из браузера.",
    );
    if (!configuredKey) useScheme();
  });
  let zoom = 1,
    pan = [0, 0],
    drag = null;
  const svg = $("#route-svg");
  function view() {
    const w = 900 / zoom,
      h = 800 / zoom;
    svg.setAttribute(
      "viewBox",
      `${450 + pan[0] - w / 2} ${340 + pan[1] - h / 2} ${w} ${h}`,
    );
    svg.dataset.zoom = String(zoom);
  }
  $$("[data-map-zoom]").forEach((button) =>
    button.addEventListener("click", () => {
      const step = Number(button.dataset.mapZoom);
      if (map) {
        if (step === 0)
          map.setLocation({
            bounds: corridorBounds,
            duration: 300,
          });
        else
          map.setLocation({
            zoom: Math.max(3, Math.min(13, map.zoom + step)),
            duration: 200,
          });
        return;
      }
      if (step === 0) {
        zoom = 1;
        pan = [0, 0];
      } else zoom = Math.max(1, Math.min(4, zoom + step * 0.5));
      view();
    }),
  );
  svg.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || zoom <= 1 || e.target.closest("a")) return;
    drag = { x: e.clientX, y: e.clientY, pan: [...pan] };
    svg.setPointerCapture?.(e.pointerId);
  });
  svg.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const rect = svg.getBoundingClientRect(),
      scale = Math.max(900 / zoom / rect.width, 800 / zoom / rect.height);
    pan = [
      Math.max(-350, Math.min(350, drag.pan[0] - (e.clientX - drag.x) * scale)),
      Math.max(-350, Math.min(350, drag.pan[1] - (e.clientY - drag.y) * scale)),
    ];
    view();
  });
  ["pointerup", "pointercancel"].forEach((name) =>
    svg.addEventListener(name, () => (drag = null)),
  );
  window.addEventListener("pagehide", () => {
    generation++;
    map?.destroy();
    map = null;
  });
  fetch("/api/map-config", { cache: "no-store" })
    .then(async (r) => {
      if (!r.ok) throw Error();
      const value = await r.json();
      configuredKey = validKey(value.apiKey) ? value.apiKey : null;
      notice(
        $("#map-key-status"),
        configuredKey
          ? "Ключ локального приложения настроен. Он имеет приоритет."
          : "Используется ключ этого браузера, если он указан.",
      );
      const preference = storageGet("caspian-django-map-provider");
      if (
        preference === "yandex" ||
        (!preference && (configuredKey || validKey(browserKey)))
      )
        void useYandex(false);
    })
    .catch(() => {
      showMapError(
        "Настройки Яндекс Карт недоступны. Встроенная схема продолжает работать.",
      );
    });
})();
