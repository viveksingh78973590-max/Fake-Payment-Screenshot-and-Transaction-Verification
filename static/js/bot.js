/* PayGuard 3D voice bot: hover help, page intros, login guidance and a multi-page guided tour.
   Ported from the standalone PayGuard AI app; works across normal Django pages. */
(function () {
  "use strict";
  var body = document.body, page = body.dataset.page || "";
  var authed = body.dataset.auth === "1";
  var tourUrls = (body.dataset.tour || "").split(",").filter(Boolean);
  var store = {
    get: function (k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { sessionStorage.setItem(k, v); } catch (e) {} },
    del: function (k) { try { sessionStorage.removeItem(k); } catch (e) {} }
  };
  var mute = false;
  try { mute = localStorage.getItem("pgMute") === "1"; } catch (e) {}

  var INTRO = {
    home: "Hello! I'm the PayGuard bot. This is the home page, with the project overview and all the features.",
    about: "This page explains the problem, the solution and the technology stack behind PayGuard AI.",
    register: "This is the register page. Enter a username, email and a strong password to create an account.",
    login: "This is the login page. If you are new here, please register yourself first, and then log in.",
    dashboard: "This is your dashboard. It counts your confirmed, pending, failed and suspicious verifications. You can also load demo data here.",
    upload: "This is the verify page. Upload a payment screenshot and the system reads it, checks it, and compares the promise with reality.",
    result: "This is the verification result. Every verdict comes with reasons, the OCR details, the provider check and the full evidence timeline.",
    history: "This is your verification history. Search by reference or filter by result.",
    timeline: "This is the payment dispute time machine. Every verification and its full evidence trail is kept here, and you can download a CSV report.",
    family: "This is the screenshot family tree. Similar, cropped or edited screenshots are linked together here.",
    chain: "This is the fraud chain page. It connects the user, screenshot, reference, provider and scam messages into a graph.",
    whatif: "This is the what-if simulator. Flip the switches and watch the decision change, using the real decision engine.",
    admin_dashboard: "This is the admin dashboard, with all users' flagged payments and the trusted ledger."
  };

  /* ---------- DOM ---------- */
  var bot = document.createElement("div");
  bot.id = "pgbot";
  bot.innerHTML = '<div id="pgbt"><div class="arm l"></div><div class="arm r"></div><div class="bd"></div>' +
    '<div class="hd"><div class="ear l"></div><div class="ear r"></div><div class="vs"><div class="ey l"></div>' +
    '<div class="ey r"></div><div class="sm"></div></div></div></div><div id="pgbb" role="status" aria-live="polite"></div>';
  var ctl = document.createElement("div");
  ctl.id = "pgctl";
  ctl.innerHTML = '<button type="button" class="btn btn-primary btn-sm" id="pgTour" ' +
    'data-t="This button starts a guided tour of the whole project.">🤖 Start bot tour</button>' +
    '<button type="button" class="btn btn-secondary btn-sm" id="pgMute">' + (mute ? "🔇 Voice off" : "🔊 Voice on") + '</button>';
  body.appendChild(bot); body.appendChild(ctl);
  var bb = document.getElementById("pgbb"), bt = document.getElementById("pgbt");
  var tmo, last = "", touring = false;

  /* ---------- speech + movement ---------- */
  function say(text, cb) {
    bb.textContent = text; bb.classList.add("s", "m");
    clearTimeout(tmo);
    bot.classList.toggle("r", parseInt(bot.style.left || "20", 10) > innerWidth / 2);
    var finished = false, safety;
    var done = function () {
      if (finished) return; finished = true; clearTimeout(safety);
      tmo = setTimeout(function () { bb.classList.remove("s", "m"); }, 2500);
      if (cb) cb();
    };
    var wait = Math.min(6000, text.length * 60 + 800);
    if (mute || !window.speechSynthesis) { safety = setTimeout(done, wait); return; }
    try {
      speechSynthesis.cancel();
      var u = new SpeechSynthesisUtterance(text); u.lang = "en-US";
      var v = speechSynthesis.getVoices().filter(function (x) { return x.lang && x.lang.indexOf("en") === 0; })[0];
      if (v) u.voice = v;
      u.onend = done; u.onerror = done;
      speechSynthesis.speak(u);
      safety = setTimeout(done, text.length * 90 + 4000);   // browsers may block speech without a click
    } catch (e) { safety = setTimeout(done, wait); }
  }
  function go(x, y) {
    bot.style.left = Math.max(8, Math.min(innerWidth - 130, x)) + "px";
    bot.style.top = Math.max(70, Math.min(innerHeight - 160, y)) + "px";
  }
  addEventListener("mousemove", function (e) {
    var r = bot.getBoundingClientRect();
    var dx = (e.clientX - r.left - 60) / innerWidth, dy = (e.clientY - r.top - 70) / innerHeight;
    bt.style.transform = "rotateY(" + dx * 80 + "deg) rotateX(" + (-dy * 50) + "deg)";
  });
  document.addEventListener("mouseover", function (e) {
    if (touring || !e.target.closest) return;
    var el = e.target.closest("[data-t]"); if (!el) return;
    var t = el.dataset.t; if (t === last) return; last = t;
    var r = el.getBoundingClientRect();
    go(r.right > innerWidth - 380 ? r.left - 140 : r.right + 10, r.top - 20);
    say(t);
    setTimeout(function () { if (last === t) last = ""; }, 6000);
  });
  document.getElementById("pgMute").onclick = function (e) {
    mute = !mute;
    try { localStorage.setItem("pgMute", mute ? "1" : "0"); } catch (x) {}
    if (window.speechSynthesis) speechSynthesis.cancel();
    e.target.textContent = mute ? "🔇 Voice off" : "🔊 Voice on";
  };

  /* ---------- guided tour across pages (state kept in sessionStorage) ---------- */
  var tourBtn = document.getElementById("pgTour");
  var SPOTS = [[60, 160], [600, 200], [100, 420], [560, 380], [300, 250], [700, 150], [120, 300], [500, 420]];
  function setTouring(on) { touring = on; tourBtn.textContent = on ? "⏹ Stop tour" : "🤖 Start bot tour"; }
  function stopTour() { store.del("pgTour"); setTouring(false); if (window.speechSynthesis) speechSynthesis.cancel(); }
  function path(u) { try { return new URL(u, location.href).pathname; } catch (e) { return u; } }

  function runTourStep() {
    var s = parseInt(store.get("pgTour"), 10);
    if (isNaN(s) || !tourUrls[s] || path(tourUrls[s]) !== location.pathname) { stopTour(); return false; }
    setTouring(true);
    var spot = SPOTS[s % SPOTS.length]; go(spot[0], spot[1]);
    setTimeout(function () {
      if (!store.get("pgTour")) return;
      say(INTRO[page] || "This is another page of PayGuard AI.", function () {
        setTimeout(function () {
          if (!store.get("pgTour")) return;
          if (s + 1 < tourUrls.length) { store.set("pgTour", String(s + 1)); location.href = tourUrls[s + 1]; }
          else {
            stopTour();
            say("The tour is complete. Now try it yourself. Put your cursor on anything and I will explain it.");
          }
        }, 600);
      });
    }, 1200);
    return true;
  }
  tourBtn.onclick = function () {
    if (touring) { stopTour(); return; }
    if (!tourUrls.length) return;
    store.set("pgTour", "0");
    if (path(tourUrls[0]) === location.pathname) runTourStep(); else location.href = tourUrls[0];
  };

  /* ---------- on page load ---------- */
  if (store.get("pgTour") !== null && runTourStep()) return;
  go(innerWidth > 800 ? innerWidth - 420 : 20, 160);
  setTimeout(function () {
    var m = document.querySelector("[data-say]");               // flash messages are read out loud first
    if (m) { say(m.dataset.say); return; }
    if (page === "login" && body.dataset.next) {
      say("Please log in first. This page opens only after login. If you are new here, please register first.");
      return;
    }
    if (INTRO[page]) say(INTRO[page]);
  }, 700);
})();
