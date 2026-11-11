/* Argus SPY Signal Desk. All values are written with textContent (no HTML
 * injection). Polls /status every ~3 s while the tab is visible. */
(function () {
	'use strict';
	var root = document.getElementById('argus-spy-app');
	if (!root) { return; }
	var cfg = {};
	try { cfg = JSON.parse(root.getAttribute('data-config') || '{}'); } catch (e) { cfg = {}; }
	if (!cfg.api) { return; }

	var $ = function (k) { return root.querySelector('[data-k="' + k + '"]'); };
	var set = function (k, v) { var el = $(k); if (el) { el.textContent = (v === null || v === undefined || v === '') ? '—' : String(v); } };
	var num = function (v) { var n = parseFloat(v); return isFinite(n) ? n : null; };
	var fmt = function (v, d) { var n = num(v); return n === null ? '—' : n.toFixed(d === undefined ? 2 : d); };
	var SVGNS = 'http://www.w3.org/2000/svg';

	function api(path, opts) {
		opts = opts || {};
		opts.credentials = 'same-origin';
		opts.headers = Object.assign({ 'X-WP-Nonce': cfg.nonce }, opts.headers || {});
		return fetch(cfg.api + path, opts).then(function (r) {
			if (!r.ok) { return r.json().catch(function () { return {}; }).then(function (b) { throw new Error((b && b.message) || ('HTTP ' + r.status)); }); }
			return r.json();
		});
	}

	/* ---------- tabs ---------- */
	root.querySelectorAll('.as-tabs button').forEach(function (b) {
		b.addEventListener('click', function () {
			root.querySelectorAll('.as-tabs button').forEach(function (x) { x.classList.toggle('is-on', x === b); });
			root.querySelectorAll('.as-panel').forEach(function (p) { p.hidden = p.getAttribute('data-panel') !== b.getAttribute('data-tab'); });
			var t = b.getAttribute('data-tab');
			if (t === 'review') { loadDates(); }
			if (t === 'signals') { loadSignals(); }
			if (t === 'journal') { loadJournal(); }
		});
	});

	/* ---------- chart ---------- */
	function drawChart(svg, pts, opts) {
		opts = opts || {};
		while (svg.firstChild) { svg.removeChild(svg.firstChild); }
		var W = 600, H = parseFloat(svg.getAttribute('viewBox').split(' ')[3]), pad = 8;
		var vals = [];
		pts.forEach(function (p) { if (p.p !== null) { vals.push(p.p); } if (p.v !== null) { vals.push(p.v); } });
		if (vals.length < 2) {
			var t = document.createElementNS(SVGNS, 'text'); t.setAttribute('x', 12); t.setAttribute('y', 24); t.textContent = 'Waiting for data…'; svg.appendChild(t); return;
		}
		var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
		if (hi - lo < 0.2) { var mid = (hi + lo) / 2; lo = mid - 0.1; hi = mid + 0.1; }
		var x = function (i) { return pad + i * (W - 2 * pad) / Math.max(1, pts.length - 1); };
		var y = function (v) { return H - pad - (v - lo) * (H - 2 * pad) / (hi - lo); };
		[0.25, 0.5, 0.75].forEach(function (f) {
			var l = document.createElementNS(SVGNS, 'line'); l.setAttribute('class', 'grid');
			l.setAttribute('x1', 0); l.setAttribute('x2', W); l.setAttribute('y1', H * f); l.setAttribute('y2', H * f); svg.appendChild(l);
		});
		function path(key, cls) {
			var d = '', started = false;
			pts.forEach(function (p, i) { if (p[key] === null) { started = false; return; } d += (started ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(p[key]).toFixed(1); started = true; });
			if (d) { var e = document.createElementNS(SVGNS, 'path'); e.setAttribute('d', d); e.setAttribute('class', cls); svg.appendChild(e); }
		}
		path('v', 'vwap'); path('p', 'price');
		if (opts.markers) {
			pts.forEach(function (p, i) {
				if ((p.s === 'CALL' || p.s === 'PUT') && p.p !== null) {
					var c = document.createElementNS(SVGNS, 'circle'); c.setAttribute('cx', x(i)); c.setAttribute('cy', y(p.p)); c.setAttribute('r', 4); c.setAttribute('class', 'm-' + p.s); svg.appendChild(c);
				}
			});
		}
		[[hi, 14], [lo, H - 4]].forEach(function (a) {
			var t = document.createElementNS(SVGNS, 'text'); t.setAttribute('x', W - 4); t.setAttribute('y', a[1]); t.setAttribute('text-anchor', 'end'); t.textContent = a[0].toFixed(2); svg.appendChild(t);
		});
	}

	/* ---------- live ---------- */
	var FEED_CLASS = { LIVE: 'is-live', STALE: 'is-stale', OFFLINE: 'is-off', 'NO DATA': 'is-off', HISTORICAL: 'is-hist' };

	function renderStatus(s) {
		var p = s.payload || {}, L = p.latest || {}, sess = p.session || {}, sc = p.scanner || {};
		var feed = $('feed'); feed.className = 'as-pill ' + (FEED_CLASS[s.feed] || '');
		feed.textContent = s.feed === 'LIVE' ? 'LIVE' : s.feed;
		set('session', sess.label === 'LIVE' ? 'Market open' + (sess.early_close ? ' · early close' : '') : 'Market closed · last session ' + (sess.session_date || '—'));
		set('updated', L.time ? 'Updated ' + L.time + ' ET' : 'No update yet');

		var banner = $('banner'), msg = '', bad = false;
		if (s.feed === 'OFFLINE') { msg = 'No update from the scanner PC for ' + Math.round(s.push_age_seconds / 60) + ' min during market hours. Check that the PC is on and awake.'; bad = true; }
		else if (s.feed === 'STALE') { var sa = num(sc.seconds_since_update); msg = 'Data is delayed: last push ' + (s.push_age_seconds || 0) + ' s ago, last scanner update ' + (sa === null ? 'unknown' : sa > 3600 ? Math.round(sa / 3600) + ' h ago' : Math.round(sa) + ' s ago') + '. Treat the signal as out of date.'; }
		else if (s.feed === 'HISTORICAL') { msg = 'Market closed. Showing the last completed session (' + (sess.session_date || '—') + ') — historical data, not live.' + (sess.next_open ? ' Next open ' + sess.next_open.replace('T', ' ').slice(0, 16) + ' ET.' : ''); }
		else if (s.feed === 'NO DATA') { msg = 'Waiting for the first update from the scanner PC.'; }
		if (sc.pc_sleep_detected_at) { msg += (msg ? ' ' : '') + 'PC sleep/pause detected at ' + sc.pc_sleep_detected_at.replace('T', ' ').slice(0, 19) + '.'; }
		banner.hidden = !msg; banner.textContent = msg; banner.classList.toggle('is-bad', bad);

		var sig = (L.prediction || 'WAIT').toUpperCase();
		var call = $('signal'); call.textContent = sig; call.className = 'as-call is-' + sig;
		set('price', L.spy_price ? '$' + fmt(L.spy_price) : '—');
		set('pricetime', L.time ? L.time.slice(11) + ' ET' : '');
		var str = num(L.confidence);
		$('meter').style.width = (str === null ? 0 : Math.max(0, Math.min(100, str))) + '%';
		set('strength', 'Signal strength ' + (str === null ? '—' : Math.round(str)) + '/100');
		set('aplus', L.a_plus_setup);
		set('phase', L.market_phase);
		set('stability', L.mode_stability);
		set('why', L.reason);

		set('vwap', L.vwap ? fmt(L.vwap) + ' · ' + (L.vwap_position || '') : '—');
		set('or', (L.opening_range_low && L.opening_range_high) ? fmt(L.opening_range_low) + ' – ' + fmt(L.opening_range_high) + ' · ' + (L.opening_range_position || '') : '—');
		set('support', L.nearest_support ? fmt(L.nearest_support) + (L.support_distance ? ' (' + fmt(L.support_distance) + ' away)' : '') : '—');
		set('resistance', L.nearest_resistance ? fmt(L.nearest_resistance) + (L.resistance_distance ? ' (' + fmt(L.resistance_distance) + ' away)' : '') : '—');
		set('invalid', L.invalid_level ? fmt(L.invalid_level) : (L.invalidation_reason || '—'));
		set('bulltrig', L.bullish_trigger); set('beartrig', L.bearish_trigger);
		set('structure', L.market_structure); set('regime', L.regime); set('advantage', L.current_advantage);
		set('reversal', L.reversal_state); set('volume', L.volume_filter);

		var mtf = $('mtf'); mtf.textContent = '';
		[['1m', L.mtf_1m_status], ['3m', L.mtf_3m_status], ['5m', L.mtf_5m_status], ['All', L.mtf_overall_signal]].forEach(function (m) {
			var c = document.createElement('span'); var v = (m[1] || '—');
			c.className = 'as-chip ' + (/CALL|BULL/i.test(v) ? 'is-CALL' : /PUT|BEAR/i.test(v) ? 'is-PUT' : '');
			c.textContent = m[0] + ': ' + v; mtf.appendChild(c);
		});

		var fl = $('factors'); fl.textContent = '';
		String(L.confluence_factors || '').split('; ').forEach(function (kv) {
			var i = kv.indexOf('='); if (i < 0) { return; }
			var li = document.createElement('li'), a = document.createElement('span'), b = document.createElement('b');
			a.textContent = kv.slice(0, i); b.textContent = kv.slice(i + 1); b.className = 'is-' + kv.slice(i + 1);
			li.appendChild(a); li.appendChild(b); fl.appendChild(li);
		});
		set('confscore', L.confluence_score ? L.confluence_score + ' of 11 agree (needs 8)' : '');
		set('blockers', L.a_plus_setup === 'YES' ? 'No hard conflicts.' : (L.a_plus_wait_reason ? 'Waiting because: ' + L.a_plus_wait_reason : ''));

		var eng = $('engine'); eng.textContent = '';
		var e = p.engine || {};
		Object.keys(e).sort().forEach(function (t) {
			var tr = document.createElement('tr'), a = document.createElement('td'), b = document.createElement('td'), c = document.createElement('td');
			var ch = num(e[t].day_change_percent);
			a.textContent = t; b.textContent = ch === null ? '—' : (ch > 0 ? '+' : '') + ch.toFixed(2) + '%'; b.className = ch > 0 ? 'pos' : ch < 0 ? 'neg' : '';
			c.textContent = e[t].status || ''; tr.appendChild(a); tr.appendChild(b); tr.appendChild(c); eng.appendChild(tr);
		});
		set('breadthclass', (p.breadth && p.breadth.classification) || '');
		set('source', sc.data_source || '—');

		drawChart($('chart'), (p.history || []).map(function (h) { return { p: num(h.p), v: num(h.v), s: h.s }; }));
		set('chartnote', (p.history || []).length ? 'last ' + p.history.length + ' scans' : '');
	}

	var timer = null, failures = 0;
	function tick() {
		api('status').then(function (s) { failures = 0; renderStatus(s); })
			.catch(function (err) { failures++; var f = $('feed'); f.className = 'as-pill is-off'; f.textContent = 'Connection error'; if (failures > 2) { var b = $('banner'); b.hidden = false; b.classList.add('is-bad'); b.textContent = 'Cannot reach the dashboard API: ' + err.message + '. If this persists, reload the page (your login may have expired).'; } })
			.then(schedule);
	}
	function schedule() {
		clearTimeout(timer);
		if (document.hidden) { return; }
		timer = setTimeout(tick, failures ? Math.min(30000, cfg.refresh * (failures + 1)) : cfg.refresh);
	}
	document.addEventListener('visibilitychange', function () { if (!document.hidden) { tick(); } else { clearTimeout(timer); } });
	tick();

	/* ---------- session review ---------- */
	var datesLoaded = false;
	function loadDates() {
		if (datesLoaded) { return; }
		api('sessions').then(function (r) {
			var sel = $('dates'); sel.textContent = '';
			(r.dates || []).forEach(function (d) { var o = document.createElement('option'); o.value = d; o.textContent = d; sel.appendChild(o); });
			datesLoaded = true;
			if (r.dates && r.dates.length) { loadSession(r.dates[0]); } else { set('reviewsummary', 'No stored sessions yet. Sessions are saved minute by minute while the market is open.'); }
			sel.addEventListener('change', function () { loadSession(sel.value); });
		}).catch(function (e) { set('reviewsummary', e.message); });
	}
	function loadSession(date) {
		api('session?date=' + encodeURIComponent(date)).then(function (r) {
			var m = r.minutes || [], pts = m.map(function (x) { return { p: num(x.price), v: num(x.vwap), s: x.signal_value }; });
			drawChart($('reviewchart'), pts, { markers: true });
			var c = pts.filter(function (x) { return x.s === 'CALL'; }).length, pu = pts.filter(function (x) { return x.s === 'PUT'; }).length;
			set('reviewsummary', date + ' · ' + m.length + ' minutes stored · CALL minutes ' + c + ' · PUT minutes ' + pu + ' · WAIT minutes ' + (m.length - c - pu) + '. Historical data.');
		}).catch(function (e) { set('reviewsummary', e.message); });
	}

	/* ---------- signals ---------- */
	function loadSignals() {
		api('signals').then(function (r) {
			var tb = $('signals'); tb.textContent = '';
			var rows = r.signals || [], tally = { WIN: 0, LOSS: 0, FLAT: 0, SPY_PRICE_CONFIRMED: 0, REVERSED: 0 };
			rows.forEach(function (x) {
				if (tally.hasOwnProperty(x.result)) { tally[x.result]++; }
				var tr = document.createElement('tr');
				[x.signal_time_et, x.direction, fmt(x.entry_price), x.source.replace('_', ' '), x.result || '—'].forEach(function (v, i) {
					var td = document.createElement('td'); td.textContent = v;
					if (i === 1) { td.className = v === 'CALL' ? 'pos' : 'neg'; }
					tr.appendChild(td);
				});
				tb.appendChild(tr);
			});
			if (!rows.length) { var tr = document.createElement('tr'), td = document.createElement('td'); td.colSpan = 5; td.textContent = 'No CALL/PUT signals stored yet.'; tr.appendChild(td); tb.appendChild(tr); }
			var st = $('stats'); st.textContent = '';
			var scored = tally.WIN + tally.LOSS + tally.FLAT;
			[['Alert results', scored], ['Wins', tally.WIN], ['Losses', tally.LOSS], ['Flat', tally.FLAT], ['Win rate', scored ? Math.round(100 * tally.WIN / scored) + '%' : '—']].forEach(function (k) {
				var d = document.createElement('div'), b = document.createElement('b'), s = document.createElement('span');
				d.className = 'as-stat'; b.textContent = k[1]; s.textContent = k[0]; d.appendChild(b); d.appendChild(s); st.appendChild(d);
			});
			if (scored && scored < 30) { var n = document.createElement('div'); n.className = 'as-stat'; var s2 = document.createElement('span'); s2.textContent = 'Fewer than 30 results — too few to judge.'; n.appendChild(s2); st.appendChild(n); }
		}).catch(function (e) { set('stats', e.message); });
	}

	/* ---------- journal ---------- */
	function loadJournal() {
		api('journal').then(function (r) {
			var tb = $('journal'); tb.textContent = '';
			var pnl = 0, paper = 0;
			(r.entries || []).forEach(function (x) {
				var tr = document.createElement('tr');
				[x.created_at, x.entry_type, x.direction, fmt(x.entry_price), fmt(x.exit_price), x.notes].forEach(function (v) { var td = document.createElement('td'); td.textContent = v === null ? '—' : v; tr.appendChild(td); });
				var td = document.createElement('td'), del = document.createElement('button');
				del.type = 'button'; del.className = 'as-link'; del.textContent = 'Delete';
				del.addEventListener('click', function () { if (window.confirm('Delete this entry?')) { api('journal/' + x.id, { method: 'DELETE' }).then(loadJournal); } });
				td.appendChild(del); tr.appendChild(td); tb.appendChild(tr);
				if (x.entry_type === 'paper' && num(x.entry_price) !== null && num(x.exit_price) !== null) {
					paper++; pnl += (num(x.exit_price) - num(x.entry_price)) * (num(x.contracts) || 1) * 100;
				}
			});
			set('jsummary', paper ? paper + ' closed paper trades · net $' + pnl.toFixed(2) + ' (long options: (exit − entry) × 100 × contracts, before fees)' : '');
		}).catch(function (e) { set('jmsg', e.message); });
	}
	$('jform').addEventListener('submit', function (ev) {
		ev.preventDefault();
		var f = ev.target, body = {};
		['entry_type', 'direction', 'entry_price', 'exit_price', 'contracts', 'signal_time_et', 'notes'].forEach(function (n) { body[n] = f.elements[n].value; });
		api('journal', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
			.then(function () { f.reset(); set('jmsg', 'Saved.'); loadJournal(); })
			.catch(function (e) { set('jmsg', e.message); });
	});
}());
