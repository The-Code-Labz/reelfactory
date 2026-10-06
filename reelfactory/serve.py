"""Minimal HTTP status/dashboard server for a deployed ReelFactory job dir.

Stdlib only. Serves:
  GET /          -> job state JSON
  GET /report    -> report.json
  GET /videos    -> list of rendered final_*.mp4
  GET /video/<n> -> stream a rendered video
  GET /ui        -> HTML status dashboard (reads the endpoints above)
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "4050"))
JOB_DIR = os.environ.get("REELFACTORY_DIR", ".")
# Default to loopback-only: this server ships with no TLS and no rate
# limiting. Set REELFACTORY_HOST=0.0.0.0 explicitly to expose it, and set
# REELFACTORY_TOKEN to require a bearer token on every request when you do.
HOST = os.environ.get("REELFACTORY_HOST", "127.0.0.1")
AUTH_TOKEN = os.environ.get("REELFACTORY_TOKEN")


def _rf(*parts):
    return os.path.join(JOB_DIR, *parts)


def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# /ui dashboard (dark-mode, stdlib-only, self-contained HTML/CSS/JS)
# ---------------------------------------------------------------------------

HTML_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ReelFactory &mdash; Status</title>
<style>
  :root {
    --bg: #0B0D10;
    --surface: #14181D;
    --hover: #1B2128;
    --text: #F2F5F7;
    --text-secondary: #9CA8B3;
    --border: #2A323B;
    --accent: #4DA3FF;
    --success: #45C486;
    --warning: #F2B84B;
    --error: #F06464;
    --focus: #8CC4FF;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0;
    background: var(--bg); color: var(--text);
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 15px; line-height: 1.5;
  }
  code, pre, .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  a { color: var(--accent); }
  button {
    font: inherit; color: var(--text); background: var(--surface);
    border: 1px solid var(--border); border-radius: 6px;
    padding: 8px 14px; min-height: 44px; min-width: 44px;
    cursor: pointer;
  }
  button:hover { background: var(--hover); }
  button:disabled { opacity: .5; cursor: not-allowed; }
  :focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }

  header.topbar {
    position: sticky; top: 0; z-index: 10;
    display: flex; align-items: center; gap: 14px;
    flex-wrap: wrap;
    background: var(--surface); border-bottom: 1px solid var(--border);
    padding: 12px 20px;
  }
  header.topbar h1 { font-size: 17px; margin: 0; font-weight: 600; }
  .version { color: var(--text-secondary); font-size: 12px; }
  .status-pill { display: flex; align-items: center; gap: 7px; font-size: 13px; }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--text-secondary); flex: none; }
  .dot.ok { background: var(--success); }
  .dot.warn { background: var(--warning); }
  .dot.err { background: var(--error); }
  .dot.run { background: var(--accent); }
  .spacer { flex: 1; }
  .last-updated { color: var(--text-secondary); font-size: 12px; }

  main { max-width: 1200px; margin: 0 auto; padding: 20px; }

  .banner {
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
    background: var(--surface); border: 1px solid var(--warning); color: var(--warning);
    border-radius: 8px; padding: 10px 14px; margin-bottom: 16px; font-size: 13px;
  }
  .banner.err { border-color: var(--error); color: var(--error); }

  .job-summary {
    background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
    padding: 16px 18px; margin-bottom: 20px;
  }
  .job-summary dl { margin: 0; display: grid; grid-template-columns: auto 1fr; gap: 6px 14px; }
  .job-summary dt { color: var(--text-secondary); font-size: 12px; align-self: center; }
  .job-summary dd { margin: 0; word-break: break-all; }
  .progress-wrap { grid-column: 1 / -1; margin-top: 6px; }
  .progress-track {
    width: 100%; height: 10px; background: var(--hover); border-radius: 5px; overflow: hidden;
    border: 1px solid var(--border);
  }
  .progress-fill { height: 100%; background: var(--accent); border-radius: 5px; transition: width .3s ease; }
  .progress-label { color: var(--text-secondary); font-size: 12px; margin-top: 4px; }

  .columns { display: grid; grid-template-columns: 3fr 2fr; gap: 20px; align-items: start; }
  @media (max-width: 800px) { .columns { grid-template-columns: 1fr; } }

  section.panel {
    background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
    padding: 16px 18px;
  }
  section.panel + section.panel { margin-top: 20px; }
  section.panel h2 { font-size: 14px; margin: 0 0 12px; color: var(--text); font-weight: 600; }

  ul.list { list-style: none; margin: 0; padding: 0; }
  .empty-msg, .loading-msg { color: var(--text-secondary); font-size: 13px; padding: 10px 2px; }

  .track-row {
    width: 100%; text-align: left; background: transparent; border: 1px solid var(--border);
    border-radius: 8px; padding: 10px 12px; margin-bottom: 8px; min-height: 44px;
    display: block;
  }
  .track-row:hover { background: var(--hover); }
  .track-head { display: flex; align-items: center; gap: 10px; }
  .track-id { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; }
  .track-status { font-size: 12px; color: var(--text-secondary); margin-left: auto; white-space: nowrap; }
  .track-progress { margin-top: 8px; }
  .bar-track {
    width: 100%; height: 6px; background: var(--hover); border-radius: 3px; overflow: hidden;
    border: 1px solid var(--border); position: relative;
  }
  .bar-fill { height: 100%; background: var(--accent); border-radius: 3px; }
  .bar-fill.indeterminate {
    position: absolute; width: 40%; animation: indeterminate 1.3s ease-in-out infinite;
  }
  @keyframes indeterminate {
    0% { left: -40%; }
    100% { left: 100%; }
  }
  @media (prefers-reduced-motion: reduce) {
    .bar-fill.indeterminate { animation: none; left: 0; width: 100%; opacity: .5; }
  }
  .track-pct { font-size: 11px; color: var(--text-secondary); margin-top: 3px; }
  .track-report {
    margin-top: 10px; max-height: 320px; overflow: auto;
    background: var(--bg); border: 1px solid var(--border); border-radius: 6px;
    padding: 10px; font-size: 12px; white-space: pre-wrap; word-break: break-word;
  }

  .video-card { border: 1px solid var(--border); border-radius: 8px; padding: 10px; margin-bottom: 14px; }
  .video-stage {
    width: 100%; aspect-ratio: 16 / 9; max-height: 420px; background: #000;
    border-radius: 6px; overflow: hidden; display: flex; align-items: center; justify-content: center;
  }
  .video-stage video { width: 100%; height: 100%; }
  .video-meta { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 8px; flex-wrap: wrap; }
  .video-name { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; word-break: break-all; }
  .video-size { color: var(--text-secondary); font-size: 12px; }
  .video-error { color: var(--error); font-size: 12px; padding: 10px; text-align: center; }

  .sr-only {
    position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
    overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0;
  }

  .gate {
    max-width: 420px; margin: 80px auto; background: var(--surface);
    border: 1px solid var(--border); border-radius: 10px; padding: 24px;
  }
  .gate h1 { font-size: 16px; margin: 0 0 6px; }
  .gate p { color: var(--text-secondary); font-size: 13px; margin: 0 0 16px; }
  .gate form { display: flex; gap: 8px; }
  .gate input {
    flex: 1; min-height: 44px; background: var(--bg); border: 1px solid var(--border);
    border-radius: 6px; color: var(--text); padding: 0 10px; font-family: ui-monospace, monospace;
  }
  .gate .gate-error { color: var(--error); font-size: 12px; margin-top: 10px; min-height: 16px; }

  .skeleton { background: linear-gradient(90deg, var(--hover), var(--surface), var(--hover)); background-size: 200% 100%; border-radius: 6px; }
  .skeleton.line { height: 14px; margin-bottom: 8px; }
  @media (prefers-reduced-motion: no-preference) {
    .skeleton { animation: shimmer 1.4s linear infinite; }
  }
  @keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
</style>
</head>
<body>

<div id="app"></div>
<div id="live" class="sr-only" aria-live="polite"></div>

<script>
(function () {
  "use strict";

  var SERVER_AUTHORIZED = __AUTHORIZED__;
  var token = null;
  var pollTimer = null;
  var fetching = false;
  var authGated = !SERVER_AUTHORIZED;
  var initialLoaded = false;
  var initialError = null;
  var lastGood = { root: null, videos: null, report: null };
  var staleError = null;
  var expandedId = null;
  var videoDom = {}; // name -> <video> element, preserved across renders

  var app = document.getElementById("app");
  var live = document.getElementById("live");

  function announce(msg) { live.textContent = msg; }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  }
  function fmtBytes(n) {
    if (typeof n !== "number" || isNaN(n)) return "unknown size";
    var units = ["B", "KB", "MB", "GB", "TB"]; var i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return (i === 0 ? n : n.toFixed(1)) + " " + units[i];
  }
  function fmtTime(d) {
    try { return d.toLocaleTimeString(); } catch (e) { return d.toString(); }
  }
  function authHeaders() {
    return token ? { "Authorization": "Bearer " + token } : {};
  }

  function statusClass(status) {
    status = (status || "").toLowerCase();
    if (["done", "complete", "completed", "success", "ok"].indexOf(status) !== -1) return "ok";
    if (["error", "failed", "failure"].indexOf(status) !== -1) return "err";
    if (["running", "in_progress", "working"].indexOf(status) !== -1) return "run";
    if (["queued", "pending", "never run"].indexOf(status) !== -1) return "";
    return "";
  }

  function fetchJSON(url) {
    return fetch(url, { headers: authHeaders() }).then(function (res) {
      if (res.status === 401) { var e = new Error("unauthorized"); e.code = 401; throw e; }
      if (!res.ok) { var e2 = new Error("http " + res.status); e2.code = res.status; throw e2; }
      return res.text().then(function (text) {
        try { return JSON.parse(text); }
        catch (parseErr) { var e3 = new Error("malformed JSON from " + url); e3.code = "parse"; throw e3; }
      });
    });
  }

  // ---- rendering ----------------------------------------------------

  function renderGate(errMsg) {
    app.innerHTML =
      '<div class="gate">' +
      '<h1>Authentication required</h1>' +
      '<p>This ReelFactory instance requires a bearer token. Enter it below to connect.</p>' +
      '<form id="gate-form">' +
      '<input id="gate-token" type="password" autocomplete="off" aria-label="Access token" placeholder="Access token">' +
      '<button type="submit">Connect</button>' +
      '</form>' +
      '<div class="gate-error" role="alert">' + (errMsg ? esc(errMsg) : "") + '</div>' +
      '</div>';
    var form = document.getElementById("gate-form");
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var val = document.getElementById("gate-token").value.trim();
      if (!val) return;
      token = val;
      loadAll(true);
    });
    document.getElementById("gate-token").focus();
  }

  function renderSkeleton() {
    app.innerHTML =
      '<header class="topbar"><h1>ReelFactory</h1><span class="version">&nbsp;</span></header>' +
      '<main><div class="job-summary">' +
      '<div class="skeleton line" style="width:60%"></div>' +
      '<div class="skeleton line" style="width:40%"></div>' +
      '<div class="skeleton line" style="width:100%;height:10px"></div>' +
      '</div><div class="loading-msg">Loading status&hellip;</div></main>';
  }

  function renderFatal(message) {
    app.innerHTML =
      '<header class="topbar"><h1>ReelFactory</h1></header>' +
      '<main><div class="banner err" role="alert"><span>Could not load status: ' + esc(message) + '</span>' +
      '<button id="retry-btn">Retry</button></div></main>';
    document.getElementById("retry-btn").addEventListener("click", function () { loadAll(true); });
  }

  function shell() {
    if (!document.getElementById("track-list")) {
      app.innerHTML =
        '<header class="topbar">' +
        '<h1>ReelFactory</h1>' +
        '<span class="version" id="hdr-version"></span>' +
        '<span class="status-pill"><span class="dot" id="hdr-dot"></span><span id="hdr-status">&mdash;</span></span>' +
        '<span class="spacer"></span>' +
        '<span class="last-updated" id="hdr-updated"></span>' +
        '<button id="refresh-btn" aria-label="Refresh now">Refresh</button>' +
        '</header>' +
        '<main>' +
        '<div id="stale-banner"></div>' +
        '<section class="job-summary" id="job-summary" aria-label="Job summary"></section>' +
        '<div class="columns">' +
        '<section class="panel" aria-label="Tracks"><h2>Tracks</h2><ul class="list" id="track-list"></ul></section>' +
        '<section class="panel" aria-label="Videos"><h2>Videos</h2><ul class="list" id="video-list"></ul></section>' +
        '</div>' +
        '</main>';
      document.getElementById("refresh-btn").addEventListener("click", function () { loadAll(false); });
    }
  }

  function renderStale(msg) {
    var el = document.getElementById("stale-banner");
    if (!el) return;
    if (!msg) { el.innerHTML = ""; return; }
    el.innerHTML = '<div class="banner" role="alert"><span>Showing last known data &mdash; refresh failed: ' +
      esc(msg) + '</span><button id="stale-retry">Retry</button></div>';
    document.getElementById("stale-retry").addEventListener("click", function () { loadAll(false); });
  }

  function renderHeader(root, updatedAt) {
    var dot = document.getElementById("hdr-dot");
    var statusEl = document.getElementById("hdr-status");
    var status = root && root.state ? (root.state.status || "unknown") : "unknown";
    dot.className = "dot " + statusClass(status);
    statusEl.textContent = status;
    document.getElementById("hdr-version").textContent = root && root.version ? ("v" + root.version) : "";
    document.getElementById("hdr-updated").textContent = "Updated " + fmtTime(updatedAt);
  }

  function renderJobSummary(root) {
    var el = document.getElementById("job-summary");
    if (!root) { el.innerHTML = '<div class="empty-msg">No job data available.</div>'; return; }
    var state = root.state || {};
    var tracks = Array.isArray(state.tracks) ? state.tracks : [];
    var total = tracks.length;
    var completed = tracks.filter(function (t) {
      return statusClass(t.status) === "ok";
    }).length;
    var pct = total > 0 ? Math.round((completed / total) * 100) : 0;
    el.innerHTML =
      '<dl>' +
      '<dt>Job directory</dt><dd class="mono">' + esc(root.job_dir || "&mdash;") + '</dd>' +
      '<dt>Status</dt><dd>' + esc(state.status || "unknown") + '</dd>' +
      '<dt>Tracks</dt><dd>' + completed + ' / ' + total + ' completed</dd>' +
      '<div class="progress-wrap">' +
      '<div class="progress-track"><div class="progress-fill" style="width:' + pct + '%"></div></div>' +
      '<div class="progress-label">' + pct + '% overall</div>' +
      '</div>' +
      '</dl>';
  }

  function findReportEntry(report, trackId) {
    if (!report) return null;
    if (Array.isArray(report)) {
      for (var i = 0; i < report.length; i++) {
        var item = report[i];
        if (item && (item.id === trackId || item.track_id === trackId)) return item;
      }
      return null;
    }
    if (typeof report === "object") {
      if (Object.prototype.hasOwnProperty.call(report, trackId)) return report[trackId];
      if (report.tracks && report.tracks[trackId]) return report.tracks[trackId];
    }
    return null;
  }

  function renderTracks(root, report) {
    var ul = document.getElementById("track-list");
    var state = root && root.state;
    var tracks = state && Array.isArray(state.tracks) ? state.tracks : [];
    if (!tracks.length) {
      ul.innerHTML = '<li class="empty-msg">No tracks yet.</li>';
      return;
    }
    ul.innerHTML = "";
    tracks.forEach(function (t, idx) {
      var id = t.id !== undefined ? String(t.id) : "track-" + idx;
      var status = t.status || "unknown";
      var sClass = statusClass(status);
      var pctRaw = (typeof t.progress === "number") ? t.progress :
                   (typeof t.percent === "number") ? t.percent : null;
      var pct = pctRaw !== null ? Math.round(pctRaw <= 1 ? pctRaw * 100 : pctRaw) : null;
      var indeterminate = pct === null && sClass === "run";

      var li = document.createElement("li");
      var panelId = "report-panel-" + idx;
      var isOpen = expandedId === id;

      var barHtml;
      if (pct !== null) {
        barHtml = '<div class="bar-track"><div class="bar-fill" style="width:' + pct + '%"></div></div>' +
          '<div class="track-pct">' + pct + '%</div>';
      } else if (indeterminate) {
        barHtml = '<div class="bar-track"><div class="bar-fill indeterminate"></div></div>' +
          '<div class="track-pct">Running&hellip;</div>';
      } else {
        barHtml = '<div class="track-pct">No progress data</div>';
      }

      li.innerHTML =
        '<button class="track-row" aria-expanded="' + isOpen + '" aria-controls="' + panelId + '" data-id="' + esc(id) + '">' +
        '<div class="track-head">' +
        '<span class="dot ' + sClass + '"></span>' +
        '<span class="track-id">' + esc(id) + '</span>' +
        '<span class="track-status">' + esc(status) + '</span>' +
        '</div>' +
        '<div class="track-progress">' + barHtml + '</div>' +
        '</button>' +
        '<div id="' + panelId + '" role="region" ' + (isOpen ? "" : "hidden") + '></div>';

      ul.appendChild(li);

      li.querySelector(".track-row").addEventListener("click", function () {
        expandedId = (expandedId === id) ? null : id;
        renderTracks(root, report);
      });

      if (isOpen) {
        var panel = li.querySelector("#" + panelId);
        panel.removeAttribute("hidden");
        var entry = findReportEntry(report, id);
        if (report === undefined) {
          panel.innerHTML = '<div class="track-report empty-msg">Report unavailable.</div>';
        } else if (entry === null) {
          panel.innerHTML = '<div class="track-report empty-msg">No matching report entry.</div>';
        } else {
          var pre = document.createElement("pre");
          pre.className = "track-report";
          pre.textContent = JSON.stringify(entry, null, 2);
          panel.innerHTML = "";
          panel.appendChild(pre);
        }
      }
    });
  }

  function renderVideos(data) {
    var ul = document.getElementById("video-list");
    var videos = data && Array.isArray(data.videos) ? data.videos : [];
    if (!videos.length) {
      ul.innerHTML = '<li class="empty-msg">No videos rendered yet.</li>';
      videoDom = {};
      return;
    }
    var seen = {};
    // Remove stale cards (videos no longer present)
    Array.prototype.slice.call(ul.children).forEach(function (child) {
      var name = child.getAttribute("data-name");
      if (name && videos.every(function (v) { return v.name !== name; })) {
        ul.removeChild(child);
        delete videoDom[name];
      }
    });
    videos.forEach(function (v, idx) {
      seen[v.name] = true;
      var existing = ul.querySelector('[data-name="' + CSS.escape(v.name) + '"]');
      if (existing) {
        // reorder if needed, update meta text only (don't touch <video>)
        if (ul.children[idx] !== existing) ul.insertBefore(existing, ul.children[idx] || null);
        var sizeEl = existing.querySelector(".video-size");
        if (sizeEl) sizeEl.textContent = fmtBytes(v.size);
        return;
      }
      var li = document.createElement("li");
      li.className = "video-card";
      li.setAttribute("data-name", v.name);
      li.innerHTML =
        '<div class="video-stage"></div>' +
        '<div class="video-meta">' +
        '<span class="video-name">' + esc(v.name) + '</span>' +
        '<span class="video-size">' + fmtBytes(v.size) + '</span>' +
        '</div>' +
        '<div class="video-meta"><a href="' + esc(v.url) + '">Open video</a></div>';
      var stage = li.querySelector(".video-stage");
      var video = document.createElement("video");
      video.controls = true;
      video.preload = "metadata";
      video.src = v.url;
      video.addEventListener("error", function () {
        stage.innerHTML = '<div class="video-error">Video could not be loaded.<br>' +
          '<a href="' + esc(v.url) + '">Open directly</a></div>';
      });
      stage.appendChild(video);
      ul.insertBefore(li, ul.children[idx] || null);
      videoDom[v.name] = video;
    });
  }

  // ---- data loading ---------------------------------------------------

  function loadAll(isInitial) {
    if (fetching) return;
    fetching = true;
    var now = new Date();

    Promise.allSettled ? doLoad() : doLoadFallback();

    function settle(p) {
      return p.then(function (v) { return { status: "fulfilled", value: v }; },
                     function (e) { return { status: "rejected", reason: e }; });
    }

    function doLoadFallback() {
      Promise.all([
        settle(fetchJSON("/")), settle(fetchJSON("/videos")), settle(fetchJSON("/report"))
      ]).then(handleResults);
    }
    function doLoad() {
      Promise.all([
        fetchJSON("/").then(function (v) { return { status: "fulfilled", value: v }; }, function (e) { return { status: "rejected", reason: e }; }),
        fetchJSON("/videos").then(function (v) { return { status: "fulfilled", value: v }; }, function (e) { return { status: "rejected", reason: e }; }),
        fetchJSON("/report").then(function (v) { return { status: "fulfilled", value: v }; }, function (e) { return { status: "rejected", reason: e }; })
      ]).then(handleResults);
    }

    function handleResults(results) {
      fetching = false;
      var rootR = results[0], videosR = results[1], reportR = results[2];

      var any401 = [rootR, videosR, reportR].some(function (r) {
        return r.status === "rejected" && r.reason && r.reason.code === 401;
      });
      if (any401) {
        stopPolling();
        authGated = true;
        renderGate(isInitial && token ? "Invalid token." : null);
        return;
      }

      if (rootR.status === "rejected") {
        if (isInitial || !lastGood.root) {
          initialError = rootR.reason.message;
          renderFatal(initialError);
          return;
        }
        renderStale(rootR.reason.message);
      } else {
        lastGood.root = rootR.value;
      }

      // from here we have at least a shell to render
      initialLoaded = true;
      shell();
      renderHeader(lastGood.root, now);
      renderJobSummary(lastGood.root);

      if (videosR.status === "fulfilled") lastGood.videos = videosR.value;
      if (reportR.status === "fulfilled") lastGood.report = reportR.value;

      var anyStale = rootR.status === "rejected" || videosR.status === "rejected" || reportR.status === "rejected";
      if (!isInitial) {
        renderStale(anyStale && rootR.status === "rejected" ? rootR.reason.message : null);
      } else {
        renderStale(null);
      }

      renderTracks(lastGood.root, reportR.status === "fulfilled" ? reportR.value : lastGood.report);
      renderVideos(lastGood.videos || { videos: [] });

      announce("Status updated at " + fmtTime(now) +
        (anyStale ? ". Some sections failed to refresh." : "."));

      schedulePoll();
    }
  }

  function schedulePoll() {
    if (pollTimer) clearTimeout(pollTimer);
    if (authGated) return;
    pollTimer = setTimeout(function () {
      if (document.hidden) { schedulePoll(); return; }
      loadAll(false);
    }, 5000);
  }
  function stopPolling() {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  }

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden && initialLoaded && !authGated) loadAll(false);
  });

  // ---- boot -------------------------------------------------------------

  if (authGated) {
    renderGate(null);
  } else {
    renderSkeleton();
    loadAll(true);
  }
})();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "reelfactory/0.1"

    def _json(self, obj, code=200):
        body = json.dumps(obj, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self):
        self._json({"error": "not found"}, 404)

    def _authorized(self):
        if not AUTH_TOKEN:
            return True
        got = self.headers.get("Authorization", "")
        return got == f"Bearer {AUTH_TOKEN}"

    def _ui(self):
        authorized = self._authorized()
        body = HTML_PAGE.replace("__AUTHORIZED__", "true" if authorized else "false").encode("utf-8")
        self.send_response(200 if authorized else 401)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"

        if path == "/ui":
            return self._ui()

        if not self._authorized():
            return self._json({"error": "unauthorized"}, 401)

        if path == "/":
            state = _read_json(_rf("output", ".reelfactory", "state.json"))
            vids = self._videos()
            self._json({
                "service": "reelfactory",
                "version": "0.1.0",
                "job_dir": os.path.abspath(JOB_DIR),
                "state": state or {"status": "never run"},
                "videos": [v["name"] for v in vids],
            })
        elif path == "/report":
            report = _read_json(_rf("output", ".reelfactory", "report.json"))
            self._json(report) if report else self._not_found()
        elif path == "/videos":
            self._json({"videos": self._videos()})
        elif path.startswith("/video/"):
            name = os.path.basename(path[len("/video/"):])
            fp = _rf("output", name)
            if not os.path.isfile(fp):
                return self._not_found()
            size = os.path.getsize(fp)
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with open(fp, "rb") as f:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        else:
            self._not_found()

    def _videos(self):
        out = _rf("output")
        if not os.path.isdir(out):
            return []
        vids = []
        for n in sorted(os.listdir(out)):
            if n.startswith("final_") and n.endswith(".mp4"):
                p = os.path.join(out, n)
                vids.append({"name": n, "size": os.path.getsize(p),
                             "url": f"/video/{n}"})
        return vids

    def log_message(self, fmt, *args):
        sys.stderr.write("[serve] " + fmt % args + "\n")


def main():
    os.makedirs(_rf("output"), exist_ok=True)
    if HOST not in ("127.0.0.1", "localhost") and not AUTH_TOKEN:
        print("WARNING: REELFACTORY_HOST is non-local and REELFACTORY_TOKEN is unset; "
              "this server has no authentication. Set REELFACTORY_TOKEN.", file=sys.stderr)
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"reelfactory status server on http://{HOST}:{PORT} (dir={os.path.abspath(JOB_DIR)})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
