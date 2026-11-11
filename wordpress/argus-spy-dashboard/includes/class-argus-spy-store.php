<?php
/**
 * Storage: latest snapshot (option, not autoloaded) + three small tables.
 *  - {prefix}argus_spy_minutes  one row per Eastern minute (session review)
 *  - {prefix}argus_spy_signals  CALL/PUT events + results (deduplicated)
 *  - {prefix}argus_spy_journal  per-user journal / paper-trade entries
 * All times stored as Eastern wall-clock strings exactly as the scanner logs
 * them (market time), plus received_at in UTC.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class Argus_Spy_Store {

	const OPT_LATEST   = 'argus_spy_latest';
	const OPT_RECEIVED = 'argus_spy_received_at';
	const OPT_DB       = 'argus_spy_db_version';

	public static function table( $name ) {
		global $wpdb;
		return $wpdb->prefix . 'argus_spy_' . $name;
	}

	public static function activate() {
		self::install_tables();
		$role = get_role( 'administrator' );
		if ( $role ) {
			$role->add_cap( ARGUS_SPY_CAP );
		}
	}

	public static function deactivate() {
		// Data and capability are kept on deactivation on purpose.
	}

	public static function maybe_upgrade() {
		if ( get_option( self::OPT_DB ) !== ARGUS_SPY_DB_VERSION ) {
			self::install_tables();
		}
	}

	public static function install_tables() {
		global $wpdb;
		require_once ABSPATH . 'wp-admin/includes/upgrade.php';
		$charset = $wpdb->get_charset_collate();
		$minutes = self::table( 'minutes' );
		$signals = self::table( 'signals' );
		$journal = self::table( 'journal' );

		dbDelta(
			"CREATE TABLE {$minutes} (
				id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
				session_date DATE NOT NULL,
				minute_et DATETIME NOT NULL,
				price DECIMAL(12,4) NULL,
				vwap DECIMAL(12,4) NULL,
				signal_value VARCHAR(8) NOT NULL DEFAULT '',
				strength SMALLINT NULL,
				data LONGTEXT NULL,
				received_at DATETIME NOT NULL,
				PRIMARY KEY  (id),
				UNIQUE KEY minute_et (minute_et),
				KEY session_date (session_date)
			) {$charset};"
		);
		dbDelta(
			"CREATE TABLE {$signals} (
				id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
				signal_time_et DATETIME NOT NULL,
				direction VARCHAR(8) NOT NULL,
				entry_price DECIMAL(12,4) NULL,
				source VARCHAR(32) NOT NULL DEFAULT '',
				result VARCHAR(32) NOT NULL DEFAULT '',
				detail LONGTEXT NULL,
				received_at DATETIME NOT NULL,
				PRIMARY KEY  (id),
				UNIQUE KEY signal_key (signal_time_et,direction,source)
			) {$charset};"
		);
		dbDelta(
			"CREATE TABLE {$journal} (
				id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
				user_id BIGINT UNSIGNED NOT NULL,
				created_at DATETIME NOT NULL,
				entry_type VARCHAR(16) NOT NULL DEFAULT 'note',
				direction VARCHAR(8) NOT NULL DEFAULT '',
				entry_price DECIMAL(12,4) NULL,
				exit_price DECIMAL(12,4) NULL,
				contracts INT NULL,
				signal_time_et DATETIME NULL,
				notes TEXT NULL,
				PRIMARY KEY  (id),
				KEY user_id (user_id)
			) {$charset};"
		);
		update_option( self::OPT_DB, ARGUS_SPY_DB_VERSION, false );
	}

	private static function num( $v ) {
		return ( is_numeric( $v ) ) ? (float) $v : null;
	}

	private static function et_datetime( $s ) {
		$s = is_string( $s ) ? trim( $s ) : '';
		return preg_match( '/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?$/', $s ) ? $s : null;
	}

	/** Persist one validated payload. Returns array with counts. */
	public static function save( array $payload ) {
		global $wpdb;
		$now_utc = gmdate( 'Y-m-d H:i:s' );

		update_option( self::OPT_LATEST, $payload, false );
		update_option( self::OPT_RECEIVED, time(), false );

		$counts = array( 'minute' => 0, 'signals' => 0 );
		$latest = isset( $payload['latest'] ) && is_array( $payload['latest'] ) ? $payload['latest'] : array();
		$t      = self::et_datetime( isset( $latest['time'] ) ? $latest['time'] : '' );
		$open   = ! empty( $payload['session']['is_open'] );

		if ( $t && $open ) {
			$minute = substr( $t, 0, 16 ) . ':00';
			$keep   = array_intersect_key(
				$latest,
				array_flip( array( 'regime', 'market_phase', 'market_structure', 'vwap_position', 'opening_range_position', 'a_plus_setup', 'mtf_overall_signal', 'reason' ) )
			);
			// Latest row of each minute wins (REPLACE on the unique minute key).
			$counts['minute'] = (int) $wpdb->replace(
				self::table( 'minutes' ),
				array(
					'session_date' => substr( $t, 0, 10 ),
					'minute_et'    => $minute,
					'price'        => self::num( isset( $latest['spy_price'] ) ? $latest['spy_price'] : null ),
					'vwap'         => self::num( isset( $latest['vwap'] ) ? $latest['vwap'] : null ),
					'signal_value' => substr( sanitize_text_field( isset( $latest['prediction'] ) ? $latest['prediction'] : '' ), 0, 8 ),
					'strength'     => is_numeric( isset( $latest['confidence'] ) ? $latest['confidence'] : null ) ? (int) $latest['confidence'] : null,
					'data'         => wp_json_encode( $keep ),
					'received_at'  => $now_utc,
				)
			);
		}

		$sources = array(
			'alerts'         => array( 'time', 'option_type', 'spy_price', '' ),
			'alert_results'  => array( 'time', 'option_type', 'entry_spy_price', 'result' ),
			'signal_events'  => array( 'time', 'direction', 'entry_spy_price', '' ),
			'signal_results' => array( 'time', 'direction', 'entry_spy_price', 'result' ),
		);
		foreach ( $sources as $key => $map ) {
			if ( empty( $payload[ $key ] ) || ! is_array( $payload[ $key ] ) ) {
				continue;
			}
			foreach ( $payload[ $key ] as $row ) {
				if ( ! is_array( $row ) ) {
					continue;
				}
				$time = self::et_datetime( isset( $row[ $map[0] ] ) ? $row[ $map[0] ] : ( isset( $row['time'] ) ? $row['time'] : '' ) );
				$dir  = strtoupper( sanitize_text_field( isset( $row[ $map[1] ] ) ? $row[ $map[1] ] : '' ) );
				if ( ! $time || ! in_array( $dir, array( 'CALL', 'PUT' ), true ) ) {
					continue;
				}
				// INSERT IGNORE: the unique key makes repeated pushes harmless.
				$sql = $wpdb->prepare(
					'INSERT IGNORE INTO ' . self::table( 'signals' ) . ' (signal_time_et, direction, entry_price, source, result, detail, received_at) VALUES (%s, %s, %s, %s, %s, %s, %s)',
					$time,
					$dir,
					(string) self::num( isset( $row[ $map[2] ] ) ? $row[ $map[2] ] : null ),
					$key,
					$map[3] ? sanitize_text_field( isset( $row[ $map[3] ] ) ? $row[ $map[3] ] : '' ) : '',
					wp_json_encode( $row ),
					$now_utc
				);
				$counts['signals'] += (int) $wpdb->query( $sql );
			}
		}
		return $counts;
	}

	public static function latest() {
		$p = get_option( self::OPT_LATEST, array() );
		return is_array( $p ) ? $p : array();
	}

	public static function received_at() {
		return (int) get_option( self::OPT_RECEIVED, 0 );
	}

	public static function session_dates( $limit = 60 ) {
		global $wpdb;
		return $wpdb->get_col(
			$wpdb->prepare( 'SELECT DISTINCT session_date FROM ' . self::table( 'minutes' ) . ' ORDER BY session_date DESC LIMIT %d', $limit )
		);
	}

	public static function session_minutes( $date ) {
		global $wpdb;
		return $wpdb->get_results(
			$wpdb->prepare( 'SELECT minute_et, price, vwap, signal_value, strength, data FROM ' . self::table( 'minutes' ) . ' WHERE session_date = %s ORDER BY minute_et ASC', $date ),
			ARRAY_A
		);
	}

	public static function signals( $limit = 100 ) {
		global $wpdb;
		return $wpdb->get_results(
			$wpdb->prepare( 'SELECT signal_time_et, direction, entry_price, source, result, detail FROM ' . self::table( 'signals' ) . ' ORDER BY signal_time_et DESC LIMIT %d', $limit ),
			ARRAY_A
		);
	}

	public static function journal_list( $user_id ) {
		global $wpdb;
		return $wpdb->get_results(
			$wpdb->prepare( 'SELECT id, created_at, entry_type, direction, entry_price, exit_price, contracts, signal_time_et, notes FROM ' . self::table( 'journal' ) . ' WHERE user_id = %d ORDER BY created_at DESC LIMIT 200', $user_id ),
			ARRAY_A
		);
	}

	public static function journal_add( $user_id, array $e ) {
		global $wpdb;
		$wpdb->insert(
			self::table( 'journal' ),
			array(
				'user_id'        => $user_id,
				'created_at'     => current_time( 'mysql' ),
				'entry_type'     => $e['entry_type'],
				'direction'      => $e['direction'],
				'entry_price'    => $e['entry_price'],
				'exit_price'     => $e['exit_price'],
				'contracts'      => $e['contracts'],
				'signal_time_et' => $e['signal_time_et'],
				'notes'          => $e['notes'],
			)
		);
		return (int) $wpdb->insert_id;
	}

	public static function journal_delete( $user_id, $id ) {
		global $wpdb;
		return (bool) $wpdb->delete( self::table( 'journal' ), array( 'id' => $id, 'user_id' => $user_id ), array( '%d', '%d' ) );
	}
}
