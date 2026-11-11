<?php
/**
 * Front end: [argus_spy_dashboard] shortcode.
 * - Not logged in: login link only.
 * - Logged in without the capability: "no access" message.
 * - Authorized: app shell; assets load only on that page.
 * Pages containing the shortcode are sent with noindex + no-store.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class Argus_Spy_Page {

	public static function init() {
		add_shortcode( 'argus_spy_dashboard', array( __CLASS__, 'shortcode' ) );
		add_action( 'template_redirect', array( __CLASS__, 'headers' ) );
		add_action( 'wp_enqueue_scripts', array( __CLASS__, 'register_assets' ) );
	}

	private static function page_has_shortcode() {
		if ( ! is_singular() ) {
			return false;
		}
		$post = get_post();
		return $post && has_shortcode( (string) $post->post_content, 'argus_spy_dashboard' );
	}

	public static function headers() {
		if ( ! self::page_has_shortcode() ) {
			return;
		}
		nocache_headers();
		header( 'X-Robots-Tag: noindex, nofollow', true );
		add_filter(
			'wp_robots',
			function ( $robots ) {
				$robots['noindex']  = true;
				$robots['nofollow'] = true;
				return $robots;
			}
		);
	}

	public static function register_assets() {
		wp_register_style( 'argus-spy', ARGUS_SPY_URL . 'assets/spy.css', array(), ARGUS_SPY_VERSION );
		wp_register_script( 'argus-spy', ARGUS_SPY_URL . 'assets/spy.js', array(), ARGUS_SPY_VERSION, true );
	}

	public static function shortcode() {
		if ( ! is_user_logged_in() ) {
			$url = wp_login_url( get_permalink() );
			return '<div class="argus-spy-gate"><p>This dashboard is private.</p><p><a href="' . esc_url( $url ) . '">Log in</a></p></div>';
		}
		if ( ! current_user_can( ARGUS_SPY_CAP ) ) {
			return '<div class="argus-spy-gate"><p>Your account does not have access to the SPY dashboard.</p></div>';
		}
		// Block themes render shortcodes before wp_enqueue_scripts runs, so make
		// sure the handles exist, and pass config on the element itself.
		if ( ! wp_script_is( 'argus-spy', 'registered' ) ) {
			self::register_assets();
		}
		wp_enqueue_style( 'argus-spy' );
		wp_enqueue_script( 'argus-spy' );
		$config = wp_json_encode(
			array(
				'api'     => esc_url_raw( rest_url( 'argus-spy/v1/' ) ),
				'nonce'   => wp_create_nonce( 'wp_rest' ),
				'refresh' => 3000,
			)
		);
		ob_start();
		include ARGUS_SPY_DIR . 'templates/dashboard.php';
		return ob_get_clean();
	}
}
