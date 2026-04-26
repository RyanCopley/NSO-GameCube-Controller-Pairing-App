"""
Internationalization — lightweight string translation for the UI.

Auto-detects the system language and falls back to English.
Use ``t("key")`` to get a translated string.
"""

import locale
import logging

logger = logging.getLogger(__name__)

_STRINGS: dict[str, dict[str, str]] = {
    # ── Common buttons ────────────────────────────────────────────
    "btn.continue": {
        "en": "Continue",
        "fr": "Continuer",
    },
    "btn.cancel": {
        "en": "Cancel",
        "fr": "Annuler",
    },
    "btn.retry": {
        "en": "Retry",
        "fr": "Réessayer",
    },
    "btn.scan": {
        "en": "Scan",
        "fr": "Scanner",
    },
    "btn.connect": {
        "en": "Connect",
        "fr": "Connecter",
    },
    "btn.disconnect": {
        "en": "Disconnect",
        "fr": "Déconnecter",
    },
    "btn.save": {
        "en": "Save",
        "fr": "Enregistrer",
    },
    "btn.cancel_cal": {
        "en": "Cancel",
        "fr": "Annuler",
    },
    "btn.show_all": {
        "en": "Show All",
        "fr": "Tout afficher",
    },
    "btn.show_all_devices": {
        "en": "Show All Devices",
        "fr": "Afficher tous les appareils",
    },

    # ── Controller UI ─────────────────────────────────────────────
    "ui.ready": {
        "en": "Ready to Connect",
        "fr": "Prêt à connecter",
    },
    "ui.connect_usb": {
        "en": "Connect USB",
        "fr": "Connecter USB",
    },
    "ui.pair_wireless": {
        "en": "Pair New Wireless Controller",
        "fr": "Appairer une manette sans fil",
    },
    "ui.cal_wizard": {
        "en": "Calibration Wizard",
        "fr": "Assistant de calibration",
    },
    "ui.cal_triggers": {
        "en": "Calibrate Triggers",
        "fr": "Calibrer les gâchettes",
    },
    "ui.connected_ble": {
        "en": "Connected via BLE",
        "fr": "Connecté via BLE",
    },
    "ui.connected_usb": {
        "en": "Connected",
        "fr": "Connecté",
    },
    "ui.reconnected": {
        "en": "Reconnected",
        "fr": "Reconnecté",
    },
    "ui.auto_connected_ble": {
        "en": "Auto-connected via BLE",
        "fr": "Connecté automatiquement via BLE",
    },
    "ui.disconnected_reconnecting": {
        "en": "Controller disconnected \u2014 reconnecting...",
        "fr": "Manette déconnectée \u2014 reconnexion...",
    },
    "ui.ble_disconnected_reconnecting": {
        "en": "BLE disconnected \u2014 reconnecting...",
        "fr": "BLE déconnecté \u2014 reconnexion...",
    },
    "ui.no_free_slots": {
        "en": "No free slots available",
        "fr": "Aucun emplacement libre",
    },
    "ui.no_unclaimed": {
        "en": "No unclaimed controllers found",
        "fr": "Aucune manette non attribuée trouvée",
    },
    "ui.new_controller_cal": {
        "en": "Connected \u2014 click Calibration Wizard to configure",
        "fr": "Connectée \u2014 cliquez sur Assistant de calibration pour configurer",
    },
    "ui.dual_connection_warning": {
        "en": "Connected via USB and Bluetooth \u2014 you may want to disconnect one",
        "fr": "Connectée en USB et Bluetooth \u2014 vous pouvez déconnecter l'un des deux",
    },

    # ── BLE statuses ──────────────────────────────────────────────
    "ble.initializing": {
        "en": "Initializing...",
        "fr": "Initialisation...",
    },
    "ble.connecting": {
        "en": "Connecting...",
        "fr": "Connexion...",
    },
    "ble.connected": {
        "en": "Connected: {mac}",
        "fr": "Connecté : {mac}",
    },
    "ble.error": {
        "en": "Error: {error}",
        "fr": "Erreur : {error}",
    },
    "ble.pairing_cancelled": {
        "en": "Pairing cancelled",
        "fr": "Appairage annulé",
    },
    "ble.no_devices": {
        "en": "No devices found",
        "fr": "Aucun appareil trouvé",
    },
    "ble.scanning_known": {
        "en": "Scanning for known controllers...",
        "fr": "Recherche des manettes connues...",
    },
    "ble.found_known": {
        "en": "Found known controller: {addr}",
        "fr": "Manette connue trouvée : {addr}",
    },
    "ble.reconnecting": {
        "en": "Reconnecting...",
        "fr": "Reconnexion...",
    },
    "ble.reconnected": {
        "en": "Reconnected via BLE",
        "fr": "Reconnecté via BLE",
    },

    # ── BLE scan dialog ───────────────────────────────────────────
    "scan.title": {
        "en": "Wireless Controller Setup",
        "fr": "Configuration manette sans fil",
    },
    "scan.heading": {
        "en": "Scan for Controllers",
        "fr": "Rechercher des manettes",
    },
    "scan.instructions": {
        "en": "Press and hold the pairing button on your controller.\n"
              "Wait for the LED to flash, then click Scan.",
        "fr": "Appuyez sur le bouton de synchronisation de votre manette\n"
              "et maintenez-le. Quand la LED clignote, cliquez sur Scanner.",
    },
    "scan.live_instructions": {
        "en": "Press the pairing button on your controller.\n"
              "It will appear here automatically when detected.",
        "fr": "Appuyez sur le bouton de synchronisation de votre manette.\n"
              "Elle apparaîtra ici automatiquement une fois détectée.",
    },
    "scan.scanning": {
        "en": "Scanning for controllers...",
        "fr": "Recherche de manettes...",
    },
    "scan.found_n": {
        "en": "{n} controller(s) detected — select and click Connect",
        "fr": "{n} manette(s) détectée(s) — sélectionnez et cliquez Connecter",
    },
    "scan.no_controllers": {
        "en": "No Controllers Found",
        "fr": "Aucune manette trouvée",
    },
    "scan.no_controllers_detail": {
        "en": "No Nintendo controllers were detected.\n"
              "Make sure your controller is in pairing mode\n"
              "(LED should be flashing) and try again.",
        "fr": "Aucune manette Nintendo n'a été détectée.\n"
              "Vérifiez que votre manette est en mode appairage\n"
              "(la LED doit clignoter) et réessayez.",
    },
    "scan.controllers_found": {
        "en": "Controllers Found",
        "fr": "Manettes trouvées",
    },
    "scan.controllers_found_detail": {
        "en": "Found {n_ctrl} controller(s) out of {n_total} nearby devices.",
        "fr": "{n_ctrl} manette(s) trouvée(s) parmi {n_total} appareils à proximité.",
    },
    "scan.all_devices": {
        "en": "All Nearby Devices",
        "fr": "Tous les appareils à proximité",
    },
    "scan.all_devices_detail": {
        "en": "{n} device(s) found. Select your controller:",
        "fr": "{n} appareil(s) trouvé(s). Sélectionnez votre manette :",
    },
    "scan.col_type": {
        "en": "Type",
        "fr": "Type",
    },
    "scan.col_address": {
        "en": "Address",
        "fr": "Adresse",
    },
    "scan.col_signal": {
        "en": "Signal",
        "fr": "Signal",
    },
    "scan.nintendo_controller": {
        "en": "Nintendo Controller",
        "fr": "Manette Nintendo",
    },
    "scan.unknown_device": {
        "en": "(unknown device)",
        "fr": "(appareil inconnu)",
    },

    # ── Calibration wizard ────────────────────────────────────────
    "cal.sticks_instruction": {
        "en": "Move sticks to all extremes, then click Continue",
        "fr": "Bougez les sticks dans toutes les directions, puis cliquez Continuer",
    },
    "cal.trigger_release": {
        "en": "Release both triggers, then click Continue",
        "fr": "Relâchez les deux gâchettes, puis cliquez Continuer",
    },
    "cal.trigger_left_bump": {
        "en": "LEFT trigger \u2192 press to max \u25b6 BEFORE the click \u25c0 then release",
        "fr": "Gâchette GAUCHE \u2192 enfoncez au max \u25b6 AVANT le clic \u25c0 puis relâchez",
    },
    "cal.trigger_left_max": {
        "en": "LEFT trigger \u2192 press fully \u25b6 PAST the click \u25c0 then release",
        "fr": "Gâchette GAUCHE \u2192 enfoncez à fond \u25b6 AU-DELÀ du clic \u25c0 puis relâchez",
    },
    "cal.trigger_right_bump": {
        "en": "RIGHT trigger \u2192 press to max \u25b6 BEFORE the click \u25c0 then release",
        "fr": "Gâchette DROITE \u2192 enfoncez au max \u25b6 AVANT le clic \u25c0 puis relâchez",
    },
    "cal.trigger_right_max": {
        "en": "RIGHT trigger \u2192 press fully \u25b6 PAST the click \u25c0 then release",
        "fr": "Gâchette DROITE \u2192 enfoncez à fond \u25b6 AU-DELÀ du clic \u25c0 puis relâchez",
    },
    "cal.trigger_completed": {
        "en": "Trigger calibration completed",
        "fr": "Calibration des gâchettes terminée",
    },
    "cal.trigger_retry_left": {
        "en": "Left trigger not detected (peak={val}, base={base}). "
              "Press it fully and click again",
        "fr": "Gâchette gauche non détectée (pic={val}, base={base}). "
              "Appuyez à fond et réessayez",
    },
    "cal.trigger_retry_right": {
        "en": "Right trigger not detected (peak={val}, base={base}). "
              "Press it fully and click again",
        "fr": "Gâchette droite non détectée (pic={val}, base={base}). "
              "Appuyez à fond et réessayez",
    },
    "cal.btn_retry_or_force": {
        "en": "Retry (or force)",
        "fr": "Réessayer (ou forcer)",
    },

    # ── Settings dialog ───────────────────────────────────────────
    "settings.emulation_mode": {
        "en": "Emulation Mode",
        "fr": "Mode d'émulation",
    },
    "settings.trigger_mode": {
        "en": "Trigger Mode",
        "fr": "Mode des gâchettes",
    },
    "settings.stick_deadzone": {
        "en": "Stick Deadzone",
        "fr": "Zone morte des sticks",
    },
    "settings.auto_connect_usb": {
        "en": "Auto-connect USB",
        "fr": "Connexion USB automatique",
    },
    "settings.auto_scan_ble": {
        "en": "Auto-scan BLE at startup",
        "fr": "Recherche BLE automatique au démarrage",
    },
    "settings.minimize_tray": {
        "en": "Minimize to system tray",
        "fr": "Réduire dans la zone de notification",
    },
    "settings.run_at_startup": {
        "en": "Run at startup",
        "fr": "Lancer au démarrage",
    },
    "settings.test_rumble": {
        "en": "Test Rumble",
        "fr": "Tester les vibrations",
    },
    "settings.paired_controllers": {
        "en": "Paired Controllers",
        "fr": "Manettes appairées",
    },
    "settings.no_paired": {
        "en": "No paired controllers",
        "fr": "Aucune manette appairée",
    },
    "settings.forget": {
        "en": "Forget",
        "fr": "Oublier",
    },
    "settings.forget_all": {
        "en": "Forget All",
        "fr": "Tout oublier",
    },
    "settings.device_links": {
        "en": "Device Links (USB \u2194 BT)",
        "fr": "Liens entre appareils (USB \u2194 BT)",
    },
    "settings.no_links": {
        "en": "No linked devices",
        "fr": "Aucun appareil lié",
    },
    "settings.unlink": {
        "en": "Unlink",
        "fr": "Délier",
    },
    "settings.about": {
        "en": "About",
        "fr": "À propos",
    },
    "settings.source_code": {
        "en": "Source Code on GitHub",
        "fr": "Code source sur GitHub",
    },
    "settings.credits": {
        "en": "Credits & Special Thanks",
        "fr": "Crédits et remerciements",
    },
    "settings.language": {
        "en": "Language",
        "fr": "Langue",
    },
}

_current_lang = "en"


def _detect_language() -> str:
    """Detect the system language, returning 'fr' or 'en'.

    On macOS, locale env vars are often unset ('C'), so we read the
    native AppleLanguages preference via subprocess as a fallback.
    """
    import sys

    # Try standard locale detection first
    try:
        loc = locale.getlocale()[0] or ""
        if loc.lower().startswith("fr"):
            return "fr"
    except Exception:
        pass

    # macOS fallback: read the system language preference
    if sys.platform == 'darwin':
        try:
            import subprocess
            result = subprocess.run(
                ['defaults', 'read', '-g', 'AppleLanguages'],
                capture_output=True, text=True, timeout=2)
            if result.returncode == 0 and 'fr' in result.stdout.lower():
                return "fr"
        except Exception:
            pass

    return "en"


def init(lang: str | None = None):
    """Initialize the i18n system.

    Args:
        lang: Force a language ('en', 'fr'). If None, auto-detect.
    """
    global _current_lang
    if lang:
        _current_lang = lang
    else:
        _current_lang = _detect_language()
    logger.info("i18n: language set to '%s'", _current_lang)


def get_language() -> str:
    """Return the current language code."""
    return _current_lang


def set_language(lang: str):
    """Change the language at runtime."""
    global _current_lang
    _current_lang = lang
    logger.info("i18n: language changed to '%s'", _current_lang)


def t(key: str, **kwargs) -> str:
    """Translate a string key, with optional format arguments.

    Falls back to English if the key or language is missing.
    """
    entry = _STRINGS.get(key)
    if entry is None:
        logger.debug("i18n: missing key '%s'", key)
        return key

    text = entry.get(_current_lang) or entry.get("en", key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return text
