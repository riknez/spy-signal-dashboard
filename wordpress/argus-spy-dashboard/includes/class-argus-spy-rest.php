<?php
/**
 * REST API (namespace argus-spy/v1).
 *   POST /ingest          signed by the scanner PC (HMAC), no cookies
 *   GET  /status          latest snapshot + server-side freshness verdict
 *   GET  /sessions        list of stored session dates
 *   GET  /session?date=   minute rows for one session (historical review)
 *   GET  /signals         stored CALL/PUT events and results
 *   GET  /journal         current user's journal / paper trades
 *   POST /journal         add an entry
 *   DELETE /journal/{id}  delete own entry
 * Every GET/POST except /ingest requires a logged-in user with ARGUS_SPY_CAP.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class Argus_Spy_Rest {

	const NS             = 'argus-spy/v1';
	const MAX_BODY_BYTES = 524288;   // 512 KB
	const MAX_SKEW       = 300;      // seconds
	const STALE_AFTER    = 30;       // seconds without a push during market hours
	const OFFLINE_AFTER  = 180;

	public static function register_routes() {
		register_rest_route(
			self::NS,
			'/ingest',
			array(
				'methods'             => 'POST',
				'callback'            => array( __CLASS__, 'ingest' ),
				'permission_callback' => array( __CLASS__, 'verify_signature' ),
			)
		);
		$read = array( __CLASS__, 'can_view' );
		register_rest_route( self::NS, '/status', array( 'methods' => 'GET', 'callback' => array( __CLASS__, 'status' ), 'permission_callback' => $read ) );
		register_rest_route( self::NS, '/sessions', array( 'methods' => 'GET', 'callback' => array( __CLASS__, 'sessions' ), 'permission_callback' => $read ) );
		register_rest_route(
			self::NS,
			'/session',
			array(
				'methods'             => 'GET',
				'callback'            => array( __CLASS__, 'session' ),
				'permission_callback' => $read,
				'args'                => array(
					'date' => array(
						'required'          => true,
						'validate_callback' => function ( $v ) {
							return is_string( $v ) && preg_match( '/^\d{4}-\d{2}-\d{2}$/', $v );
						},
					),
				),
			)
		);
		register_rest_route( self::NS, '/signals', array( 'methods' => 'GET', 'callback' => array( __CLASS__, 'signals' ), 'permission_callback' => $read ) );
		register_rest_route(
			self::NS,
			'/journal',
			array(
				array( 'methods' => 'GET', 'callback' => array( __CLASS__, 'journal_list' ), 'permission_callback' => $read ),
				array( 'methods' => 'POST', 'callback' => array( __CLASS__, 'journal_add' ), 'permission_callback' => $read ),
			)
		);
		register_rest_route(
			self::NS,
			'/journal/(?P<id>\d+)',
			array( 'methods' => 'DELETE', 'callback' => array( __CLASS__, 'journal_delete' ), 'permission_callback' => $read )
		);
	}

	/* ---------- auth ---------- */

	public static function can_view() {
		return is_user_logged_in() && current_user_can( ARGUS_SPY_CAP );
	}

	private static function secret() {
		return defined( 'ARGUS_SPY_INGEST_SECRET' ) ? (string) ARGUS_SPY_INGEST_SECRET : '';
	}

	public static function verify_signature( WP_REST_Request $request ) {
		$secret = self::secret();
		if ( strlen( $secret ) < 32 ) {
			return new WP_Error( 'argus_spy_not_configured', 'Ingest disabled: ARGUS_SPY_INGEST_SECRET is not defined in wp-config.php.', array( 'status' => 503 ) );
		}
		$ts   = (string) $request->get_header( 'x_argus_spy_timestamp' );
		$sig  = strtolower( (string) $request->get_header( 'x_argus_spy_signature' ) );
		$body = $request->get_body();
		if ( strlen( $body ) > self::MAX_BODY_BYTES ) {
			return new WP_Error( 'argus_spy_too_large', 'Payload too large.', array( 'status' => 413 ) );
		}
		if ( ! ctype_digit( $ts ) || abs( time() - (int) $ts ) > self::MAX_SKEW ) {
			return new WP_Error( 'argus_spy_stale', 'Missing or expired timestamp.', array( 'status' => 401 ) );
		}
		$expected = hash_hmac( 'sha256', $ts . '.' . $body, $secret );
		if ( '' === $sig || ! hash_equals( $expected, $sig ) ) {
			return new WP_Error( 'argus_spy_bad_signature', 'Invalid signature.', array( 'status' => 401 ) );
		}
		// Reject replays of an older signed message (timestamps must not go backwards).
		$last = (int) get_option( 'argus_spy_last_ingest_ts', 0 );
		if ( (int) $ts < $last - 5 ) {
			return new WP_Error( 'argus_spy_replay', 'Out-of-order timestamp.', array( 'status' => 409 ) );
		}
		update_option( 'argus_spy_last_ingest_ts', max( $last, (int) $ts ), false );
		return true;
	}

	/* ---------- ingest ---------- */

	public static function ingest( WP_REST_Request $request ) {
		$payload = json_decode( $request->get_body(), true );
		if ( ! is_array( $payload ) || 1 !== (int) ( isset( $payload['schema'] ) ? $payload['schema'] : 0 ) ) {
			return new WP_Error( 'argus_spy_bad_payload', 'Expected JSON payload with schema 1.', array( 'status' => 400 ) );
		}
		foreach ( array( 'session', 'scanner', 'latest' ) as $k ) {
			if ( ! isset( $payload[ $k ] ) || ! is_array( $payload[ $k ] ) ) {
				return new WP_Error( 'argus_spy_bad_payload', "Missing {$k}.", array( 'status' => 400 ) );
			}
		}
		$counts = Argus_Spy_Store::save( $payload );
		return rest_ensure_response( array( 'ok' => true, 'stored' => $counts, 'server_time' => time() ) );
	}

	/* ---------- reads ---------- */

	public static function status() {
		$p        = Argus_Spy_Store::latest();
		$received = Argus_Spy_Store::received_at();
		$age      = $received ? time() - $received : null;
		$open     = ! empty( $p['session']['is_open'] );
		$scanner_age = isset( $p['scanner']['seconds_since_update'] ) ? $p['scanner']['seconds_since_update'] : null;

		if ( ! $received ) {
			$feed = 'NO DATA';
		} elseif ( $open && $age > self::OFFLINE_AFTER ) {
			$feed = 'OFFLINE';
		} elseif ( $open && ( $age > self::STALE_AFTER || ( is_numeric( $scanner_age ) && $scanner_age > 60 ) ) ) {
			$feed = 'STALE';
		} elseif ( $open ) {
			$feed = 'LIVE';
		} else {
			$feed = 'HISTORICAL';
		}
		// If the PC stopped pushing during what it thought was an open session,
		// the stored "is_open" is outdated - say so instead of claiming LIVE.
		$response = rest_ensure_response(
			array(
				'feed'                => $feed,
				'push_age_seconds'    => $age,
				'server_time'         => time(),
				'payload'             => $p,
				'strength_disclaimer' => 'Signal strength is a rule-based score out of 100, not a calibrated probability of profit.',
			)
		);
		$response->header( 'Cache-Control', 'no-store' );
		return $response;
	}

	public static function sessions() {
		return rest_ensure_response( array( 'dates' => Argus_Spy_Store::session_dates() ) );
	}

	public static function session( WP_REST_Request $request ) {
		$rows = Argus_Spy_Store::session_minutes( $request['date'] );
		return rest_ensure_response( array( 'date' => $request['date'], 'minutes' => $rows ) );
	}

	public static function signals() {
		return rest_ensure_response( array( 'signals' => Argus_Spy_Store::signals() ) );
	}

	/* ---------- journal / paper trades ---------- */

	public static function journal_list() {
		return rest_ensure_response( array( 'entries' => Argus_Spy_Store::journal_list( get_current_user_id() ) ) );
	}

	private static function price( $v ) {
		return ( '' === $v || null === $v || ! is_numeric( $v ) ) ? null : round( (float) $v, 4 );
	}

	public static function journal_add( WP_REST_Request $r ) {
		$type = in_array( $r['entry_type'], array( 'note', 'paper' ), true ) ? $r['entry_type'] : 'note';
		$dir  = in_array( $r['direction'], array( 'CALL', 'PUT', '' ), true ) ? (string) $r['direction'] : '';
		$sig  = is_string( $r['signal_time_et'] ) && preg_match( '/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?$/', $r['signal_time_et'] ) ? $r['signal_time_et'] : null;
		$notes = sanitize_textarea_field( (string) $r['notes'] );
		if ( 'note' === $type && '' === trim( $notes ) ) {
			return new WP_Error( 'argus_spy_empty', 'Write a note first.', array( 'status' => 400 ) );
		}
		$id = Argus_Spy_Store::journal_add(
			get_current_user_id(),
			array(
				'entry_type'     => $type,
				'direction'      => $dir,
				'entry_price'    => self::price( $r['entry_price'] ),
				'exit_price'     => self::price( $r['exit_price'] ),
				'contracts'      => is_numeric( $r['contracts'] ) ? max( 0, min( 10000, (int) $r['contracts'] ) ) : null,
				'signal_time_et' => $sig,
				'notes'          => mb_substr( $notes, 0, 4000 ),
			)
		);
		return rest_ensure_response( array( 'id' => $id ) );
	}

	public static function journal_delete( WP_REST_Request $r ) {
		$ok = Argus_Spy_Store::journal_delete( get_current_user_id(), (int) $r['id'] );
		return $ok ? rest_ensure_response( array( 'deleted' => true ) ) : new WP_Error( 'argus_spy_not_found', 'Not found.', array( 'status' => 404 ) );
	}
}
