// Test instrumentation executed by the native wrapper only with GRIDBOT_DESKTOP_QA=1.
// It clicks actual product controls, reads the actual WKWebView DOM and sends no orders.
(() => {
  // Return a plain value to WKWebView's evaluation callback. Async work runs
  // separately; Rust reads its real result without relying on a second IPC route.
  window.__GRIDBOT_NATIVE_QA__ = {
    result: "RUNNING",
    checks: [],
    failure: null,
  };
  setTimeout(async () => {
    const checks = [];
    const pause = () => new Promise((resolve) => setTimeout(resolve, 100));
    const wait = async (condition, name) => {
      const deadline = Date.now() + 15000;
      while (!condition()) {
        if (Date.now() > deadline) throw new Error(name);
        await pause();
      }
    };
    const check = (name, condition) => {
      if (!condition) throw new Error(name);
      checks.push({ name, passed: true });
      window.__GRIDBOT_NATIVE_QA__.checks = [...checks];
    };
    const button = (scope, text) =>
      [...scope.querySelectorAll("button")].find(
        (element) => element.textContent.trim() === text,
      );
    const nav = (text) => button(document.querySelector("nav"), text).click();
    try {
      await wait(
        () => document.querySelector(".wizard"),
        "First-run wizard did not render",
      );
      check(
        "First-run wizard and DEMO default",
        document.querySelector(".wizard-env").textContent.includes("DEMO"),
      );
      document
        .querySelector('[aria-label="Chiudi configurazione guidata"]')
        .click();
      await wait(
        () => !document.querySelector(".wizard"),
        "Wizard close did not work",
      );
      await wait(
        () => document.querySelector(".home-layout"),
        "Home did not render",
      );
      check(
        "Home portfolio, bot and Recovery cards",
        [".portfolio-card", ".bot-card", ".recovery-card"].every((selector) =>
          document.querySelector(selector),
        ),
      );
      check(
        "Disconnected equity contains no fabricated amount",
        document.querySelector(".equity-value").textContent.includes("—") &&
          !/\d/.test(document.querySelector(".equity-value").textContent) &&
          document
            .querySelector(".portfolio-card")
            .textContent.includes("NON CONNESSO"),
      );
      check(
        "Offline Start is disabled",
        document.querySelector(".bot-card .primary").disabled,
      );
      await wait(
        () => document.querySelector('[data-testid="price-chart"] canvas'),
        "Native chart canvas did not initialize",
      );
      check(
        "Lightweight Charts actual native canvas",
        document
          .querySelector('[data-testid="price-chart"]')
          .getBoundingClientRect().width > 0,
      );

      nav("Attività");
      await wait(
        () => document.querySelector(".activity-panel"),
        "Activity did not render",
      );
      check(
        "Activity timeline renders real empty state",
        document
          .querySelector(".activity-panel")
          .textContent.includes("Nessuna attività registrata"),
      );
      button(document, "Mostra dettagli tecnici").click();
      await wait(
        () => document.querySelector(".orders-panel"),
        "Technical order details did not render",
      );
      check(
        "Activity technical details contain no fabricated orders",
        document
          .querySelector(".orders-panel")
          .textContent.includes("Nessun ordine disponibile"),
      );

      nav("Impostazioni");
      await wait(
        () => document.querySelector(".connection-form"),
        "Connection settings did not render",
      );
      const picker = document.querySelector('[aria-label="Ambiente Bybit"]');
      [...picker.querySelectorAll("button")]
        .find((element) => element.textContent.includes("LIVE"))
        .click();
      await wait(
        () =>
          document
            .querySelector(".connection-form")
            .textContent.includes("LIVE utilizza fondi reali"),
        "LIVE warning did not render",
      );
      check(
        "LIVE selection warns about real funds and backend confirmation",
        document
          .querySelector(".connection-form")
          .textContent.includes("abilitazione backend") &&
          document.querySelector(".live-selected"),
      );
      [...picker.querySelectorAll("button")]
        .find((element) => element.textContent.includes("DEMO"))
        .click();
      await wait(
        () =>
          document
            .querySelector(".endpoint-info")
            .textContent.includes("api-demo.bybit.com"),
        "DEMO endpoint did not restore",
      );
      check(
        "Saved Keychain credentials are never refilled into inputs",
        [...document.querySelectorAll(".connection-form input")].every(
          (element) => element.value === "",
        ),
      );
      const sections = document.querySelector(
        '[aria-label="Sezioni impostazioni"]',
      );
      for (const [section, title] of [
        ["Grid", "Una Grid, due direzioni."],
        ["Recovery", "Recupero con limiti chiari."],
        ["Rischio", "Il controllo prima di tutto."],
        ["App", "La tua app, in locale."],
      ]) {
        button(sections, section).click();
        await wait(
          () =>
            document.querySelector(".settings-heading h2").textContent ===
            title,
          `${section} settings did not render`,
        );
      }
      check("Grid, Recovery, Risk and App settings render natively", true);
      nav("Home");
      await wait(
        () => document.querySelector(".home-layout"),
        "Final Home did not restore",
      );
      window.__GRIDBOT_NATIVE_QA__ = { result: "PASS", checks, failure: null };
    } catch (error) {
      window.__GRIDBOT_NATIVE_QA__ = {
        result: "FAIL",
        checks,
        failure: String(error.message ?? error).slice(0, 256),
      };
    }
  }, 0);
  return window.__GRIDBOT_NATIVE_QA__;
})();
