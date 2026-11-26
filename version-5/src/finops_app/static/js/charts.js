/* Overview charts, drawn with Chart.js from the JSON API.
 * Each canvas names its data source in a data-* attribute; the numbers are
 * also in a table on the page, so the charts are an extra, not the only view. */
(function () {
  'use strict';
  if (typeof window.Chart === 'undefined') { return; }

  // Resolve a CSS colour token (OKLCH) to rgba() that Chart.js understands.
  var probe = document.createElement('canvas').getContext('2d', { willReadFrequently: true });
  function token(name, alpha) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#000';
    probe.clearRect(0, 0, 1, 1);
    probe.fillStyle = value;
    probe.fillRect(0, 0, 1, 1);
    var d = probe.getImageData(0, 0, 1, 1).data;
    return 'rgba(' + d[0] + ',' + d[1] + ',' + d[2] + ',' + (alpha === undefined ? 1 : alpha) + ')';
  }
  function fontFamily(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || 'sans-serif';
  }
  var money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
  var money2 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  var C = window.Chart;
  function render() {
  C.defaults.font.family = fontFamily('--font-body');
  C.defaults.font.size = 12;
  C.defaults.color = token('--color-muted');
  C.defaults.borderColor = token('--color-rule');
  C.defaults.animation = reduceMotion ? false : { duration: 400 };
  C.defaults.plugins.legend.labels.boxWidth = 12;
  C.defaults.plugins.tooltip.backgroundColor = token('--color-print');
  C.defaults.plugins.tooltip.callbacks.label = function (ctx) {
    var v = ctx.parsed.y !== undefined ? ctx.parsed.y : ctx.parsed.x;
    return (ctx.dataset.label ? ctx.dataset.label + ': ' : '') + money2.format(v);
  };

  function getJSON(url) {
    return fetch(url, { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (body) { return body.success ? body.data : Promise.reject(body.error); });
  }

  function failed(canvas) {
    var note = document.createElement('p');
    note.className = 'empty';
    note.textContent = 'The chart could not be loaded. The numbers are in the table.';
    canvas.parentNode.replaceWith(note);
  }

  function spendChart(canvas) {
    getJSON(canvas.dataset.seriesUrl).then(function (s) {
      var days = s.daily.dates.concat(s.forecast.dates);
      var pad = function (arr, before) { return new Array(before).fill(null).concat(arr); };
      var n = s.daily.dates.length;
      // Join the forecast to the last actual day so the lines connect.
      var last = n ? s.daily.costs[n - 1] : null;
      var joined = function (arr) { return pad([last].concat(arr), Math.max(n - 1, 0)); };
      new C(canvas, {
        type: 'line',
        data: {
          labels: days,
          datasets: [
            { label: 'Daily spend', data: s.daily.costs, borderColor: token('--color-print'),
              backgroundColor: token('--color-print'), borderWidth: 1.75, pointRadius: 0, tension: 0.2 },
            { label: '95% range (upper)', data: joined(s.forecast.upper), borderWidth: 0, pointRadius: 0,
              backgroundColor: token('--color-accent', 0.18), fill: '+1' },
            { label: '95% range (lower)', data: joined(s.forecast.lower), borderWidth: 0, pointRadius: 0 },
            { label: 'Forecast (as is)', data: joined(s.forecast.values), borderColor: token('--color-accent-2'),
              backgroundColor: token('--color-accent-2'), borderWidth: 2, borderDash: [6, 4], pointRadius: 2 },
            { label: 'Forecast (after fixes)', data: joined(s.forecast.optimised), borderColor: token('--color-success'),
              backgroundColor: token('--color-success'), borderWidth: 2, borderDash: [2, 3], pointRadius: 2 }
          ]
        },
        options: {
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          scales: {
            x: { grid: { display: false }, ticks: { maxTicksLimit: 8, maxRotation: 0 } },
            y: { beginAtZero: true, ticks: { callback: function (v) { return money.format(v); } } }
          },
          plugins: {
            legend: { position: 'bottom', labels: { filter: function (item) { return item.text.indexOf('95%') !== 0; } } },
            tooltip: { filter: function (item) { return item.raw !== null && item.dataset.label.indexOf('95%') !== 0; } }
          }
        }
      });
    }).catch(function () { failed(canvas); });
  }

  function serviceChart(canvas) {
    getJSON(canvas.dataset.summaryUrl).then(function (a) {
      var entries = Object.entries(a.waste_by_service || {}).slice(0, 5);
      new C(canvas, {
        type: 'bar',
        data: {
          labels: entries.map(function (e) { return e[0]; }),
          datasets: [{ label: 'Estimated waste', data: entries.map(function (e) { return e[1]; }),
            backgroundColor: token('--color-accent-2'), borderRadius: 3, maxBarThickness: 22 }]
        },
        options: {
          indexAxis: 'y',
          maintainAspectRatio: false,
          scales: {
            x: { beginAtZero: true, ticks: { callback: function (v) { return money.format(v); }, maxTicksLimit: 5 } },
            y: { grid: { display: false } }
          },
          plugins: { legend: { display: false } }
        }
      });
    }).catch(function () { failed(canvas); });
  }

  var spend = document.getElementById('spend-chart');
  if (spend) { spendChart(spend); }
  var service = document.getElementById('service-chart');
  if (service) { serviceChart(service); }
  }

  render();
  // Colours come from the theme's tokens, so redraw when it changes.
  document.addEventListener('themechange', function () {
    Object.values(C.instances).forEach(function (chart) { chart.destroy(); });
    render();
  });
})();
