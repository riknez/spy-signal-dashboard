<?php
if ( ! defined( 'ABSPATH' ) ) {
	exit;
}
?>
<div class="argus-spy" id="argus-spy-app" data-config="<?php echo esc_attr( $config ); ?>">
	<header class="as-top">
		<div class="as-brand">
			<span class="as-mark" aria-hidden="true"></span>
			<div>
				<h2 class="as-title">SPY Signal Desk</h2>
				<p class="as-sub">Educational decision support · no broker connection · no orders</p>
			</div>
		</div>
		<div class="as-pills" aria-live="polite">
			<span class="as-pill" data-k="feed">Connecting…</span>
			<span class="as-pill as-pill-quiet" data-k="session">—</span>
			<span class="as-pill as-pill-quiet" data-k="updated">—</span>
		</div>
	</header>

	<div class="as-banner" data-k="banner" hidden></div>

	<nav class="as-tabs" role="tablist">
		<button role="tab" class="is-on" data-tab="live">Live</button>
		<button role="tab" data-tab="review">Session review</button>
		<button role="tab" data-tab="signals">Signals</button>
		<button role="tab" data-tab="journal">Journal</button>
	</nav>

	<section class="as-panel" data-panel="live">
		<div class="as-grid">
			<article class="as-card as-signal">
				<div class="as-label">Direction</div>
				<div class="as-call" data-k="signal">—</div>
				<div class="as-price"><span data-k="price">—</span><small data-k="pricetime"></small></div>
				<div class="as-meter" aria-hidden="true"><span data-k="meter"></span></div>
				<div class="as-meta"><span data-k="strength">Signal strength —</span></div>
				<p class="as-fine">Rule-based score out of 100, not a probability of profit.</p>
				<dl class="as-kv">
					<dt>A+ setup</dt><dd data-k="aplus">—</dd>
					<dt>Phase</dt><dd data-k="phase">—</dd>
					<dt>Stability</dt><dd data-k="stability">—</dd>
				</dl>
				<details class="as-why"><summary>Why this call</summary><p data-k="why">—</p></details>
			</article>

			<article class="as-card as-chart-card">
				<div class="as-label">Price vs VWAP <small data-k="chartnote"></small></div>
				<svg class="as-chart" data-k="chart" viewBox="0 0 600 220" preserveAspectRatio="none" role="img" aria-label="Recent SPY price and VWAP"></svg>
				<div class="as-legend"><i class="l-price"></i>Price <i class="l-vwap"></i>VWAP</div>
			</article>

			<article class="as-card">
				<div class="as-label">Levels</div>
				<dl class="as-kv">
					<dt>VWAP</dt><dd data-k="vwap">—</dd>
					<dt>Opening range</dt><dd data-k="or">—</dd>
					<dt>Support</dt><dd data-k="support">—</dd>
					<dt>Resistance</dt><dd data-k="resistance">—</dd>
					<dt>Invalidation</dt><dd data-k="invalid">—</dd>
					<dt>Bull trigger</dt><dd data-k="bulltrig">—</dd>
					<dt>Bear trigger</dt><dd data-k="beartrig">—</dd>
				</dl>
			</article>

			<article class="as-card">
				<div class="as-label">Structure</div>
				<dl class="as-kv">
					<dt>Market structure</dt><dd data-k="structure">—</dd>
					<dt>Regime</dt><dd data-k="regime">—</dd>
					<dt>Advantage</dt><dd data-k="advantage">—</dd>
					<dt>Reversal</dt><dd data-k="reversal">—</dd>
					<dt>Volume filter</dt><dd data-k="volume">—</dd>
				</dl>
				<div class="as-label as-mt">Timeframes</div>
				<div class="as-chips" data-k="mtf"></div>
			</article>

			<article class="as-card">
				<div class="as-label">A+ confluence <small data-k="confscore"></small></div>
				<ul class="as-factors" data-k="factors"></ul>
				<p class="as-fine" data-k="blockers"></p>
			</article>

			<article class="as-card">
				<div class="as-label">Breadth &amp; engine <small data-k="breadthclass"></small></div>
				<table class="as-table as-compact"><tbody data-k="engine"></tbody></table>
			</article>

			<article class="as-card as-wide as-risk">
				<div class="as-label">Options reality check</div>
				<p>A correct SPY direction is not the same as a profitable option trade. Spreads, slippage, theta decay and changes in implied volatility can turn a right call into a loss, especially on short-dated contracts. Results on this page measure SPY's move only.</p>
			</article>
		</div>
	</section>

	<section class="as-panel" data-panel="review" hidden>
		<div class="as-card">
			<div class="as-row">
				<label for="as-date" class="as-label">Session</label>
				<select id="as-date" data-k="dates"></select>
			</div>
			<svg class="as-chart as-chart-tall" data-k="reviewchart" viewBox="0 0 600 260" preserveAspectRatio="none" role="img" aria-label="Session price, VWAP and signals"></svg>
			<div class="as-legend"><i class="l-price"></i>Price <i class="l-vwap"></i>VWAP <i class="l-call"></i>CALL <i class="l-put"></i>PUT</div>
			<p class="as-fine" data-k="reviewsummary"></p>
		</div>
	</section>

	<section class="as-panel" data-panel="signals" hidden>
		<div class="as-card">
			<div class="as-label">Signal outcomes</div>
			<p class="as-fine">Scored on SPY's own move, not option P&amp;L. Alert results: WIN if the best move within 120 s reaches +$0.20 in the signal's direction, LOSS if the worst reaches −$0.20, otherwise FLAT (WIN is checked first). Signal results: SPY_PRICE_CONFIRMED / FLAT / REVERSED by the scanner's 60 s check (±$0.10).</p>
			<div class="as-statrow" data-k="stats"></div>
			<div class="as-scroll"><table class="as-table"><thead><tr><th>Time (ET)</th><th>Dir</th><th>Entry</th><th>Source</th><th>Result</th></tr></thead><tbody data-k="signals"></tbody></table></div>
		</div>
	</section>

	<section class="as-panel" data-panel="journal" hidden>
		<div class="as-grid as-grid-2">
			<form class="as-card as-form" data-k="jform">
				<div class="as-label">New entry</div>
				<div class="as-row">
					<label>Type <select name="entry_type"><option value="note">Note</option><option value="paper">Paper trade</option></select></label>
					<label>Direction <select name="direction"><option value="">—</option><option>CALL</option><option>PUT</option></select></label>
				</div>
				<div class="as-row">
					<label>Entry <input name="entry_price" inputmode="decimal" placeholder="Option premium, e.g. 1.25"></label>
					<label>Exit <input name="exit_price" inputmode="decimal"></label>
					<label>Contracts <input name="contracts" inputmode="numeric"></label>
				</div>
				<label>Linked signal time (ET) <input name="signal_time_et" placeholder="2026-11-12 10:41:00"></label>
				<label>Notes <textarea name="notes" rows="4" maxlength="4000"></textarea></label>
				<button type="submit" class="as-btn">Save entry</button>
				<p class="as-fine" data-k="jmsg"></p>
			</form>
			<div class="as-card">
				<div class="as-label">Your entries <small data-k="jsummary"></small></div>
				<div class="as-scroll"><table class="as-table"><thead><tr><th>When</th><th>Type</th><th>Dir</th><th>Entry</th><th>Exit</th><th>Notes</th><th></th></tr></thead><tbody data-k="journal"></tbody></table></div>
			</div>
		</div>
	</section>

	<footer class="as-foot">Paper testing and education only. Nothing here is investment advice. Data: <span data-k="source">—</span>.</footer>
</div>
