/* Read-only mathematical recommendations. A separate action is required to accept a plan. */
(() => {
  "use strict";
  const node = document.getElementById("optimization-config"),
    mapNode = document.getElementById("map-data");
  if (!node || !mapNode) return;
  const config = JSON.parse(node.textContent),
    data = JSON.parse(mapNode.textContent),
    $ = (id) => document.getElementById(id);
  const el = (tag, text) => {
    const e = document.createElement(tag);
    if (text != null) e.textContent = text;
    return e;
  };
  const number = (v) => v.toLocaleString("ru-RU", { maximumFractionDigits: 1 });
  const date = (v) =>
    new Intl.DateTimeFormat("ru-RU", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "Europe/Moscow",
    }).format(new Date(v));
  let latest = null,
    busy = false,
    stopped = false,
    generation = 0,
    rerun = false;
  try {
    const prefs = JSON.parse(
      localStorage.getItem("caspian-optimization") || "{}",
    );
    for (const [key, id] of [
      ["objective", "optimization-objective"],
      ["source", "optimization-source"],
      ["wind", "optimization-wind-limit"],
      ["gust", "optimization-gust-limit"],
    ])
      if (prefs[key] != null) $(id).value = prefs[key];
    if (prefs.auto === false) $("optimization-auto").checked = false;
  } catch {}
  function fields() {
    return {
      cargo: data.cargoId,
      source: $("optimization-source").value,
      objective: $("optimization-objective").value,
      windLimit: $("optimization-wind-limit").value,
      gustLimit: $("optimization-gust-limit").value,
    };
  }
  function save() {
    const f = fields();
    try {
      localStorage.setItem(
        "caspian-optimization",
        JSON.stringify({
          objective: f.objective,
          source: f.source,
          wind: f.windLimit,
          gust: f.gustLimit,
          auto: $("optimization-auto").checked,
        }),
      );
    } catch {}
  }
  async function json(url, options = {}) {
    const controller = new AbortController(),
      timer = setTimeout(() => controller.abort(), 60000);
    try {
      const reply = await fetch(url, {
        cache: "no-store",
        signal: controller.signal,
        ...options,
      });
      const raw = await reply.text();
      if (raw.length > 2_000_000) throw Error("Слишком большой ответ");
      return { ok: reply.ok, value: JSON.parse(raw) };
    } finally {
      clearTimeout(timer);
    }
  }
  function render(report) {
    if (data.version != null && report.version !== data.version)
      throw Error(
        "Данные изменились в другой вкладке. Обновите страницу перед новым расчётом.",
      );
    latest = report;
    $("optimization-json").disabled = false;
    $("optimization-html").disabled = false;
    if ($("optimization-accept"))
      $("optimization-accept").disabled = !(
        report.best &&
        report.executionReady &&
        report.canAccept
      );
    const host = $("optimization-results");
    host.replaceChildren();
    const best = report.best,
      source = report.weatherProfile;
    $("optimization-status").textContent =
      (best
        ? `Рекомендовано: ${best.routeName}. `
        : "Подтверждённого расчётом варианта нет. ") +
      `${source.provider} / ${source.model} · проверено ${report.evaluated} отправлений · состояние данных #${report.version}. Это рекомендация, план принимается отдельно.`;
    if (best) {
      const summary = el("div");
      summary.className = "optimization-best";
      summary.append(
        el("strong", best.routeName),
        el(
          "span",
          `Отправление ${date(best.departure)} → номинальный ETA ${date(best.arrival)} МСК`,
        ),
        el(
          "span",
          `${number(best.costRub)} ₽ · ${number(best.co2Kg / 1000)} т CO₂e · опоздание ${number(best.lateHours)} ч`,
        ),
        el(
          "small",
          `Ветер до ${number(best.weather.peakWindMs)} м/с, порывы до ${number(best.weather.peakGustMs)} м/с по проверенным точкам/временам.`,
        ),
      );
      const link = el("a", "Открыть этот коридор для просмотра");
      link.href =
        "/?" +
        new URLSearchParams({
          page: data.page,
          cargo: data.cargoId,
          route: best.routeId,
        }) +
        "#decision";
      summary.append(link);
      host.append(summary);
    }
    const wrap = el("div");
    wrap.className = "optimization-table-wrap";
    const table = el("table");
    table.className = "optimization-table";
    const head = el("tr");
    ["Коридор", "Номинальный ETA, МСК", "Затраты", "CO₂e / результат"].forEach(
      (t) => head.append(el("th", t)),
    );
    const thead = el("thead");
    thead.append(head);
    table.append(thead);
    const body = el("tbody");
    for (const route of report.routes) {
      const tr = el("tr"),
        choice = route.best;
      tr.append(
        el("td", route.name),
        el(
          "td",
          choice ? date(choice.arrival) : "Нет подтверждённого варианта",
        ),
        el("td", choice ? number(choice.costRub) + " ₽" : "—"),
      );
      const result = el("td", choice ? number(choice.co2Kg / 1000) + " т" : "");
      if (!choice) {
        const reasons = [...new Set(route.rejected.map((r) => r.reason))];
        result.textContent = reasons.join("; ");
      }
      tr.append(result);
      body.append(tr);
    }
    table.append(body);
    wrap.append(table);
    host.append(wrap);
    if (!report.executionReady)
      host.append(
        el(
          "p",
          "До выполнения перевозки нужно отдельно завершить проверку документов. Рекомендация не означает принятие или бронирование плана.",
        ),
      );
    const details = el("details"),
      title = el("summary", "Источник, входы и ограничения");
    details.append(
      title,
      el(
        "p",
        `Получено ${source.fetchedAt}. Происхождение: ${source.provenance}. SHA256 входов: ${report.inputHash}. SHA256 погоды: ${report.weatherHash}.`,
      ),
    );
    for (const limitation of report.limitations)
      details.append(el("p", limitation));
    host.append(details);
    window.dispatchEvent(
      new CustomEvent("caspian:optimized-route", {
        detail: { routeId: best?.routeId || null },
      }),
    );
  }
  function invalidate(message = "") {
    latest = null;
    $("optimization-results").replaceChildren();
    $("optimization-json").disabled = true;
    $("optimization-html").disabled = true;
    if ($("optimization-accept")) $("optimization-accept").disabled = true;
    window.dispatchEvent(
      new CustomEvent("caspian:optimized-route", { detail: { routeId: null } }),
    );
    if (message) $("optimization-status").textContent = message;
  }
  async function recalculate() {
    if (stopped) return;
    invalidate("Получаем числовой прогноз и перебираем отправления…");
    if (busy) {
      generation++;
      rerun = true;
      return;
    }
    busy = true;
    const token = ++generation;
    save();
    $("optimization-refresh").disabled = true;
    $("optimization-status").textContent =
      "Получаем числовой прогноз и перебираем отправления…";
    try {
      const input = fields();
      let result = await json(
        "/api/optimization?" + new URLSearchParams(input),
      );
      if (
        !result.ok &&
        result.value.status === "weather_unavailable" &&
        input.source === "openmeteo"
      ) {
        const forecast = await json(config.forecastUrl, {
          credentials: "omit",
          referrerPolicy: "no-referrer",
        });
        if (!forecast.ok) throw Error("Открытый числовой прогноз недоступен");
        const csrf = document.cookie
          .split("; ")
          .find((v) => v.startsWith("csrftoken="))
          ?.slice(10);
        result = await json("/api/optimization", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrf || "",
            "X-Caspian-Request": "optimization",
          },
          body: JSON.stringify({ ...input, forecast: forecast.value }),
        });
      }
      if (stopped || token !== generation) return;
      if (!result.ok) throw Error(result.value.error || "Расчёт недоступен");
      render(result.value);
    } catch (error) {
      if (!stopped && token === generation) {
        latest = null;
        $("optimization-results").replaceChildren();
        $("optimization-json").disabled = true;
        $("optimization-html").disabled = true;
        if ($("optimization-accept")) $("optimization-accept").disabled = true;
        $("optimization-status").textContent =
          error.message || "Нет свежего числового прогноза";
        window.dispatchEvent(
          new CustomEvent("caspian:optimized-route", {
            detail: { routeId: null },
          }),
        );
      }
    } finally {
      busy = false;
      if (!stopped) $("optimization-refresh").disabled = false;
      if (rerun && !stopped) {
        rerun = false;
        void recalculate();
      }
    }
  }
  function download(kind) {
    if (!latest) return;
    const content =
      kind === "html"
        ? latest.html
        : JSON.stringify(
            Object.fromEntries(
              Object.entries(latest).filter(([k]) => k !== "html"),
            ),
            null,
            2,
          );
    const url = URL.createObjectURL(
      new Blob([content], {
        type: kind === "html" ? "text/html;charset=utf-8" : "application/json",
      }),
    );
    const a = el("a");
    a.href = url;
    a.download = `caspian-${latest.cargoId}-math-report.${kind}`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  $("optimization-refresh").addEventListener("click", () => void recalculate());
  $("optimization-accept")?.addEventListener("click", async () => {
    if (!latest?.best) return;
    const acceptedCargo = latest.cargoId;
    const button = $("optimization-accept");
    button.disabled = true;
    try {
      const csrf = document.cookie
        .split("; ")
        .find((v) => v.startsWith("csrftoken="))
        ?.slice(10);
      const result = await json("/api/workspace", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrf || "",
          "X-Caspian-Request": "workspace",
        },
        body: JSON.stringify({
          type: "accept_mathematical",
          version: latest.version,
          key: latest.acceptanceKey || crypto.randomUUID(),
          cargoId: latest.cargoId,
          routeId: latest.best.routeId,
          planningAt: latest.planningAt,
          inputHash: latest.inputHash,
          weatherProfile: latest.weatherProfile,
          weatherSignature: latest.weatherSignature,
          objective: latest.objective,
          windLimit: latest.inputs.windLimit,
          gustLimit: latest.inputs.gustLimit,
        }),
      });
      if (!result.ok) throw Error(result.value.error || "План не принят");
      location.assign(
        "/?" + new URLSearchParams({ page: data.page, cargo: acceptedCargo }),
      );
    } catch (error) {
      $("optimization-status").textContent =
        error.message +
        " Нажмите «Пересчитать», проверьте отчёт и повторите подтверждение.";
    }
  });
  $("optimization-json").addEventListener("click", () => download("json"));
  $("optimization-html").addEventListener("click", () => download("html"));
  for (const id of [
    "optimization-objective",
    "optimization-source",
    "optimization-wind-limit",
    "optimization-gust-limit",
  ])
    $(id).addEventListener("change", () => {
      save();
      generation++;
      invalidate(
        "Параметры изменены. Для них ещё нет расчёта: нажмите «Пересчитать».",
      );
      if ($("optimization-auto").checked) void recalculate();
    });
  $("optimization-auto").addEventListener("change", () => {
    save();
    if ($("optimization-auto").checked) void recalculate();
  });
  const timer = setInterval(() => {
    if (!document.hidden && $("optimization-auto").checked) void recalculate();
  }, 900000);
  window.addEventListener("pagehide", () => {
    stopped = true;
    generation++;
    clearInterval(timer);
  });
  if ($("optimization-auto").checked) void recalculate();
  else
    $("optimization-status").textContent =
      "Автообновление отключено. Нажмите «Пересчитать».";
})();
