<?php
/**
 * Plugin Name:       Argus SPY Signal Dashboard
 * Description:       Private SPY signal dashboard. Receives signed updates from Erik's scanner PC and shows them to authorized, logged-in users only. Educational decision support; no broker connection, no orders.
 * Version:           0.1.0
 * Requires at least: 6.4
 * Requires PHP:      7.4
 * Author:            Argus
 * License:           Proprietary
 * Text Domain:       argus-spy
 *
 * Security model
 * - Ingest: POST /wp-json/argus-spy/v1/ingest, HMAC-SHA256 over "timestamp.body"
 *   with ARGUS_SPY_INGEST_SECRET (defined in wp-config.php, never stored in the
 *   database, never sent to browsers). 5-minute timestamp window.
 * - Read: GET endpoints require a logged-in user with the `argus_spy_view`
 *   capability (granted to Administrators on activation) and a REST nonce.
 * - The page shortcode renders nothing to anyone else.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'ARGUS_SPY_VERSION', '0.1.0' );
define( 'ARGUS_SPY_DB_VERSION', '1' );
define( 'ARGUS_SPY_FILE', __FILE__ );
define( 'ARGUS_SPY_DIR', plugin_dir_path( __FILE__ ) );
define( 'ARGUS_SPY_URL', plugin_dir_url( __FILE__ ) );
define( 'ARGUS_SPY_CAP', 'argus_spy_view' );

require_once ARGUS_SPY_DIR . 'includes/class-argus-spy-store.php';
require_once ARGUS_SPY_DIR . 'includes/class-argus-spy-rest.php';
require_once ARGUS_SPY_DIR . 'includes/class-argus-spy-page.php';

register_activation_hook( __FILE__, array( 'Argus_Spy_Store', 'activate' ) );
register_deactivation_hook( __FILE__, array( 'Argus_Spy_Store', 'deactivate' ) );

add_action( 'plugins_loaded', array( 'Argus_Spy_Store', 'maybe_upgrade' ) );
add_action( 'rest_api_init', array( 'Argus_Spy_Rest', 'register_routes' ) );
Argus_Spy_Page::init();
