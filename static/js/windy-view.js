/* Official public Windy embed, independently switched; no scraping or private API. */
(() => {
  "use strict";
  const canvas = document.getElementById("corridor-map"),
    view = document.getElementById("windy-view"),
    frame = document.getElementById("windy-frame"),
    overlay = document.getElementById("windy-overlay"),
    note = document.getElementById("windy-provider-note");
  if (!canvas || !view || !frame || !overlay) return;
  let active = "operations";
  const marineView = document.getElementById("marine-view"),
    marineFrame = document.getElementById("marine-frame"),
    marineNote = document.getElementById("marine-provider-note");
  function url() {
    const layer = ["wind", "gust", "rain", "clouds", "temp"].includes(
      overlay.value,
    )
      ? overlay.value
      : "wind";
    const params = new URLSearchParams({
      type: "map",
      location: "coordinates",
      lat: "41.4",
      lon: "51.2",
      zoom: "6",
      level: "surface",
      overlay: layer,
      product: "ecmwf",
      metricWind: "m/s",
      metricTemp: "°C",
      metricRain: "mm",
    });
    return "https://embed.windy.com/embed.html?" + params;
  }
  function select(kind) {
    active = kind;
    view.hidden = active !== "windy";
    canvas.classList.toggle("windy-active", active === "windy");
    canvas.classList.toggle("marine-active", active === "marine");
    if (note) note.hidden = active !== "windy";
    if (marineView) marineView.hidden = active !== "marine";
    if (marineNote) marineNote.hidden = active !== "marine";
    const routes = document.getElementById("route-selection-bar");
    if (routes) routes.hidden = active !== "operations";
    document
      .querySelectorAll("[data-weather-view]")
      .forEach((button) =>
        button.setAttribute(
          "aria-pressed",
          String(button.dataset.weatherView === active),
        ),
      );
    if (active === "windy") frame.src = url();
    else frame.removeAttribute("src");
    if (marineFrame) {
      if (active === "marine")
        marineFrame.src =
          "https://www.marinetraffic.com/en/ais/embed/zoom:6/centery:41.4/centerx:51.2/maptype:0/shownames:true/";
      else marineFrame.removeAttribute("src");
    }
  }
  document
    .querySelectorAll("[data-weather-view]")
    .forEach((button) =>
      button.addEventListener("click", () =>
        select(button.dataset.weatherView),
      ),
    );
  overlay.addEventListener("change", () => {
    if (active === "windy") frame.src = url();
  });
  window.addEventListener("pagehide", () => {
    frame.removeAttribute("src");
    marineFrame?.removeAttribute("src");
  });
})();
