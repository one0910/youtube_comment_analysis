(() => {
  const root = document.documentElement;
  const intro = document.getElementById("first-visit-intro");

  if (!intro || !root.classList.contains("tubesense-first-visit")) {
    return;
  }

  const storageKey = "tubesense:first-visit-intro:v1";
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const duration = reducedMotion ? 700 : 5500;
  const backgroundElements = Array.from(document.body.children).filter(
    (element) => element !== intro && element.tagName !== "SCRIPT",
  );
  let finished = false;

  intro.setAttribute("aria-hidden", "false");
  backgroundElements.forEach((element) => {
    element.inert = true;
  });

  const finish = () => {
    if (finished) {
      return;
    }

    finished = true;

    try {
      window.localStorage.setItem(storageKey, "seen");
    } catch (error) {
      // 儲存空間不可用時只略過記錄，不影響網站操作。
    }

    intro.setAttribute("aria-hidden", "true");
    root.classList.remove("tubesense-first-visit");
    backgroundElements.forEach((element) => {
      element.inert = false;
    });
  };

  window.setTimeout(finish, duration);
})();
