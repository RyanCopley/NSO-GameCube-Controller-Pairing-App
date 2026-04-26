"""
Internationalization — lightweight string translation for the UI.

Auto-detects the system language and falls back to English.
Use ``t("key")`` to get a translated string.

Supported languages: en, fr, ja, es, de, pt, it
"""

import locale
import logging

logger = logging.getLogger(__name__)

_SUPPORTED_LANGS = ("en", "fr", "ja", "es", "de", "pt", "it")

_STRINGS: dict[str, dict[str, str]] = {
    # ── Common buttons ────────────────────────────────────────────
    "btn.continue": {
        "en": "Continue",
        "fr": "Continuer",
        "ja": "続行",
        "es": "Continuar",
        "de": "Weiter",
        "pt": "Continuar",
        "it": "Continua",
    },
    "btn.cancel": {
        "en": "Cancel",
        "fr": "Annuler",
        "ja": "キャンセル",
        "es": "Cancelar",
        "de": "Abbrechen",
        "pt": "Cancelar",
        "it": "Annulla",
    },
    "btn.retry": {
        "en": "Retry",
        "fr": "Réessayer",
        "ja": "再試行",
        "es": "Reintentar",
        "de": "Erneut versuchen",
        "pt": "Tentar novamente",
        "it": "Riprova",
    },
    "btn.scan": {
        "en": "Scan",
        "fr": "Scanner",
        "ja": "スキャン",
        "es": "Escanear",
        "de": "Scannen",
        "pt": "Escanear",
        "it": "Scansiona",
    },
    "btn.connect": {
        "en": "Connect",
        "fr": "Connecter",
        "ja": "接続",
        "es": "Conectar",
        "de": "Verbinden",
        "pt": "Conectar",
        "it": "Connetti",
    },
    "btn.disconnect": {
        "en": "Disconnect",
        "fr": "Déconnecter",
        "ja": "切断",
        "es": "Desconectar",
        "de": "Trennen",
        "pt": "Desconectar",
        "it": "Disconnetti",
    },
    "btn.save": {
        "en": "Save",
        "fr": "Enregistrer",
        "ja": "保存",
        "es": "Guardar",
        "de": "Speichern",
        "pt": "Salvar",
        "it": "Salva",
    },
    "btn.cancel_cal": {
        "en": "Cancel",
        "fr": "Annuler",
        "ja": "キャンセル",
        "es": "Cancelar",
        "de": "Abbrechen",
        "pt": "Cancelar",
        "it": "Annulla",
    },
    "btn.show_all": {
        "en": "Show All",
        "fr": "Tout afficher",
        "ja": "すべて表示",
        "es": "Mostrar todo",
        "de": "Alle anzeigen",
        "pt": "Mostrar tudo",
        "it": "Mostra tutto",
    },
    "btn.show_all_devices": {
        "en": "Show All Devices",
        "fr": "Afficher tous les appareils",
        "ja": "すべてのデバイスを表示",
        "es": "Mostrar todos los dispositivos",
        "de": "Alle Geräte anzeigen",
        "pt": "Mostrar todos os dispositivos",
        "it": "Mostra tutti i dispositivi",
    },

    # ── Controller UI ─────────────────────────────────────────────
    "ui.ready": {
        "en": "Ready to Connect",
        "fr": "Prêt à connecter",
        "ja": "接続準備完了",
        "es": "Listo para conectar",
        "de": "Verbindungsbereit",
        "pt": "Pronto para conectar",
        "it": "Pronto per la connessione",
    },
    "ui.connect_usb": {
        "en": "Connect USB",
        "fr": "Connecter USB",
        "ja": "USB接続",
        "es": "Conectar USB",
        "de": "USB verbinden",
        "pt": "Conectar USB",
        "it": "Connetti USB",
    },
    "ui.pair_wireless": {
        "en": "Pair New Wireless Controller",
        "fr": "Appairer une manette sans fil",
        "ja": "ワイヤレスコントローラーをペアリング",
        "es": "Emparejar mando inalámbrico",
        "de": "Neuen Wireless-Controller koppeln",
        "pt": "Parear controle sem fio",
        "it": "Associa controller wireless",
    },
    "ui.cal_wizard": {
        "en": "Calibration Wizard",
        "fr": "Assistant de calibration",
        "ja": "キャリブレーション",
        "es": "Asistente de calibración",
        "de": "Kalibrierungsassistent",
        "pt": "Assistente de calibração",
        "it": "Calibrazione guidata",
    },
    "ui.cal_triggers": {
        "en": "Calibrate Triggers",
        "fr": "Calibrer les gâchettes",
        "ja": "トリガーのキャリブレーション",
        "es": "Calibrar gatillos",
        "de": "Trigger kalibrieren",
        "pt": "Calibrar gatilhos",
        "it": "Calibra grilletti",
    },
    "ui.connected_ble": {
        "en": "Connected via BLE",
        "fr": "Connecté via BLE",
        "ja": "BLEで接続済み",
        "es": "Conectado por BLE",
        "de": "Über BLE verbunden",
        "pt": "Conectado via BLE",
        "it": "Connesso via BLE",
    },
    "ui.connected_usb": {
        "en": "Connected",
        "fr": "Connecté",
        "ja": "接続済み",
        "es": "Conectado",
        "de": "Verbunden",
        "pt": "Conectado",
        "it": "Connesso",
    },
    "ui.reconnected": {
        "en": "Reconnected",
        "fr": "Reconnecté",
        "ja": "再接続済み",
        "es": "Reconectado",
        "de": "Wieder verbunden",
        "pt": "Reconectado",
        "it": "Riconnesso",
    },
    "ui.auto_connected_ble": {
        "en": "Auto-connected via BLE",
        "fr": "Connecté automatiquement via BLE",
        "ja": "BLEで自動接続済み",
        "es": "Conectado automáticamente por BLE",
        "de": "Automatisch über BLE verbunden",
        "pt": "Conectado automaticamente via BLE",
        "it": "Connesso automaticamente via BLE",
    },
    "ui.disconnected_reconnecting": {
        "en": "Controller disconnected \u2014 reconnecting...",
        "fr": "Manette déconnectée \u2014 reconnexion...",
        "ja": "コントローラー切断 \u2014 再接続中...",
        "es": "Mando desconectado \u2014 reconectando...",
        "de": "Controller getrennt \u2014 Neuverbindung...",
        "pt": "Controle desconectado \u2014 reconectando...",
        "it": "Controller disconnesso \u2014 riconnessione...",
    },
    "ui.ble_disconnected_reconnecting": {
        "en": "BLE disconnected \u2014 press Sync to reconnect",
        "fr": "BLE déconnecté \u2014 appuyez sur Sync pour reconnecter",
        "ja": "BLE切断 \u2014 Syncボタンで再接続",
        "es": "BLE desconectado \u2014 pulsa Sync para reconectar",
        "de": "BLE getrennt \u2014 Sync drücken zum Neuverbinden",
        "pt": "BLE desconectado \u2014 pressione Sync para reconectar",
        "it": "BLE disconnesso \u2014 premi Sync per riconnettere",
    },
    "ui.no_free_slots": {
        "en": "No free slots available",
        "fr": "Aucun emplacement libre",
        "ja": "空きスロットがありません",
        "es": "No hay ranuras disponibles",
        "de": "Keine freien Slots verfügbar",
        "pt": "Nenhum slot disponível",
        "it": "Nessuno slot disponibile",
    },
    "ui.no_unclaimed": {
        "en": "No unclaimed controllers found",
        "fr": "Aucune manette non attribuée trouvée",
        "ja": "未割り当てのコントローラーが見つかりません",
        "es": "No se encontraron mandos sin asignar",
        "de": "Keine nicht zugewiesenen Controller gefunden",
        "pt": "Nenhum controle não atribuído encontrado",
        "it": "Nessun controller non assegnato trovato",
    },
    "ui.new_controller_cal": {
        "en": "Connected \u2014 click Calibration Wizard to configure",
        "fr": "Connectée \u2014 cliquez sur Assistant de calibration pour configurer",
        "ja": "接続済み \u2014 キャリブレーションをクリックして設定",
        "es": "Conectado \u2014 haz clic en Calibración para configurar",
        "de": "Verbunden \u2014 Kalibrierungsassistent klicken zum Einrichten",
        "pt": "Conectado \u2014 clique em Calibração para configurar",
        "it": "Connesso \u2014 clicca su Calibrazione per configurare",
    },
    "ui.dual_connection_warning": {
        "en": "Connected via USB and Bluetooth \u2014 you may want to disconnect one",
        "fr": "Connectée en USB et Bluetooth \u2014 vous pouvez déconnecter l'un des deux",
        "ja": "USBとBluetoothの両方で接続中 \u2014 どちらかを切断してください",
        "es": "Conectado por USB y Bluetooth \u2014 puedes desconectar uno",
        "de": "Über USB und Bluetooth verbunden \u2014 Sie können eines trennen",
        "pt": "Conectado via USB e Bluetooth \u2014 você pode desconectar um",
        "it": "Connesso via USB e Bluetooth \u2014 puoi disconnetterne uno",
    },
    "ui.controller_tab": {
        "en": "Controller {n}",
        "fr": "Manette {n}",
        "ja": "コントローラー {n}",
        "es": "Mando {n}",
        "de": "Controller {n}",
        "pt": "Controle {n}",
        "it": "Controller {n}",
    },
    "ui.disconnect_usb": {
        "en": "Disconnect USB",
        "fr": "Déconnecter USB",
        "ja": "USB切断",
        "es": "Desconectar USB",
        "de": "USB trennen",
        "pt": "Desconectar USB",
        "it": "Disconnetti USB",
    },

    # ── Emulation statuses ─────────────────────────────────────────
    "emu.connected_ready": {
        "en": "Connected & Ready",
        "fr": "Connecté et prêt",
        "ja": "接続済み・準備完了",
        "es": "Conectado y listo",
        "de": "Verbunden & bereit",
        "pt": "Conectado e pronto",
        "it": "Connesso e pronto",
    },
    "emu.dsu_ready": {
        "en": "DSU :{port} \u2014 Ready",
        "fr": "DSU :{port} \u2014 Prêt",
        "ja": "DSU :{port} \u2014 準備完了",
        "es": "DSU :{port} \u2014 Listo",
        "de": "DSU :{port} \u2014 Bereit",
        "pt": "DSU :{port} \u2014 Pronto",
        "it": "DSU :{port} \u2014 Pronto",
    },
    "emu.waiting_dolphin": {
        "en": "Waiting for Dolphin...",
        "fr": "En attente de Dolphin...",
        "ja": "Dolphinを待機中...",
        "es": "Esperando a Dolphin...",
        "de": "Warten auf Dolphin...",
        "pt": "Aguardando Dolphin...",
        "it": "In attesa di Dolphin...",
    },
    "emu.start": {
        "en": "Start Emulation",
        "fr": "Démarrer l'émulation",
        "ja": "エミュレーション開始",
        "es": "Iniciar emulación",
        "de": "Emulation starten",
        "pt": "Iniciar emulação",
        "it": "Avvia emulazione",
    },
    "emu.stop": {
        "en": "Stop Emulation",
        "fr": "Arrêter l'émulation",
        "ja": "エミュレーション停止",
        "es": "Detener emulación",
        "de": "Emulation stoppen",
        "pt": "Parar emulação",
        "it": "Ferma emulazione",
    },

    # ── BLE statuses ──────────────────────────────────────────────
    "ble.initializing": {
        "en": "Initializing...",
        "fr": "Initialisation...",
        "ja": "初期化中...",
        "es": "Inicializando...",
        "de": "Initialisierung...",
        "pt": "Inicializando...",
        "it": "Inizializzazione...",
    },
    "ble.connecting": {
        "en": "Connecting...",
        "fr": "Connexion...",
        "ja": "接続中...",
        "es": "Conectando...",
        "de": "Verbindung wird hergestellt...",
        "pt": "Conectando...",
        "it": "Connessione in corso...",
    },
    "ble.connected": {
        "en": "Connected: {mac}",
        "fr": "Connecté : {mac}",
        "ja": "接続済み: {mac}",
        "es": "Conectado: {mac}",
        "de": "Verbunden: {mac}",
        "pt": "Conectado: {mac}",
        "it": "Connesso: {mac}",
    },
    "ble.error": {
        "en": "Error: {error}",
        "fr": "Erreur : {error}",
        "ja": "エラー: {error}",
        "es": "Error: {error}",
        "de": "Fehler: {error}",
        "pt": "Erro: {error}",
        "it": "Errore: {error}",
    },
    "ble.pairing_cancelled": {
        "en": "Pairing cancelled",
        "fr": "Appairage annulé",
        "ja": "ペアリングがキャンセルされました",
        "es": "Emparejamiento cancelado",
        "de": "Kopplung abgebrochen",
        "pt": "Pareamento cancelado",
        "it": "Associazione annullata",
    },
    "ble.no_devices": {
        "en": "No devices found",
        "fr": "Aucun appareil trouvé",
        "ja": "デバイスが見つかりません",
        "es": "No se encontraron dispositivos",
        "de": "Keine Geräte gefunden",
        "pt": "Nenhum dispositivo encontrado",
        "it": "Nessun dispositivo trovato",
    },
    "ble.scanning_known": {
        "en": "Scanning for known controllers...",
        "fr": "Recherche des manettes connues...",
        "ja": "登録済みコントローラーを検索中...",
        "es": "Buscando mandos conocidos...",
        "de": "Suche nach bekannten Controllern...",
        "pt": "Procurando controles conhecidos...",
        "it": "Ricerca controller noti...",
    },
    "ble.found_known": {
        "en": "Found known controller: {addr}",
        "fr": "Manette connue trouvée : {addr}",
        "ja": "登録済みコントローラーを検出: {addr}",
        "es": "Mando conocido encontrado: {addr}",
        "de": "Bekannter Controller gefunden: {addr}",
        "pt": "Controle conhecido encontrado: {addr}",
        "it": "Controller noto trovato: {addr}",
    },
    "ble.reconnecting": {
        "en": "Waiting for Sync button...",
        "fr": "En attente du bouton Sync...",
        "ja": "Syncボタン待機中...",
        "es": "Esperando botón Sync...",
        "de": "Warte auf Sync-Taste...",
        "pt": "Aguardando botão Sync...",
        "it": "In attesa del pulsante Sync...",
    },
    "ble.reconnected": {
        "en": "Reconnected via BLE",
        "fr": "Reconnecté via BLE",
        "ja": "BLEで再接続済み",
        "es": "Reconectado por BLE",
        "de": "Über BLE wieder verbunden",
        "pt": "Reconectado via BLE",
        "it": "Riconnesso via BLE",
    },

    # ── BLE scan dialog ───────────────────────────────────────────
    "scan.title": {
        "en": "Wireless Controller Setup",
        "fr": "Configuration manette sans fil",
        "ja": "ワイヤレスコントローラーの設定",
        "es": "Configuración del mando inalámbrico",
        "de": "Wireless-Controller einrichten",
        "pt": "Configuração do controle sem fio",
        "it": "Configurazione controller wireless",
    },
    "scan.heading": {
        "en": "Scan for Controllers",
        "fr": "Rechercher des manettes",
        "ja": "コントローラーを検索",
        "es": "Buscar mandos",
        "de": "Nach Controllern suchen",
        "pt": "Buscar controles",
        "it": "Cerca controller",
    },
    "scan.instructions": {
        "en": "Press and hold the pairing button on your controller.\n"
              "Wait for the LED to flash, then click Scan.",
        "fr": "Appuyez sur le bouton de synchronisation de votre manette\n"
              "et maintenez-le. Quand la LED clignote, cliquez sur Scanner.",
        "ja": "コントローラーのペアリングボタンを長押ししてください。\n"
              "LEDが点滅したら、スキャンをクリックしてください。",
        "es": "Mantén pulsado el botón de emparejamiento del mando.\n"
              "Cuando el LED parpadee, haz clic en Escanear.",
        "de": "Halten Sie die Kopplungstaste am Controller gedrückt.\n"
              "Wenn die LED blinkt, klicken Sie auf Scannen.",
        "pt": "Pressione e segure o botão de pareamento do controle.\n"
              "Quando o LED piscar, clique em Escanear.",
        "it": "Tieni premuto il pulsante di associazione del controller.\n"
              "Quando il LED lampeggia, clicca su Scansiona.",
    },
    "scan.live_instructions": {
        "en": "Press the pairing button on your controller.\n"
              "It will appear here automatically when detected.",
        "fr": "Appuyez sur le bouton de synchronisation de votre manette.\n"
              "Elle apparaîtra ici automatiquement une fois détectée.",
        "ja": "コントローラーのペアリングボタンを押してください。\n"
              "検出されると自動的にここに表示されます。",
        "es": "Pulsa el botón de emparejamiento del mando.\n"
              "Aparecerá aquí automáticamente al ser detectado.",
        "de": "Drücken Sie die Kopplungstaste am Controller.\n"
              "Er wird automatisch hier angezeigt, wenn erkannt.",
        "pt": "Pressione o botão de pareamento do controle.\n"
              "Ele aparecerá aqui automaticamente quando detectado.",
        "it": "Premi il pulsante di associazione del controller.\n"
              "Apparirà qui automaticamente quando rilevato.",
    },
    "scan.scanning": {
        "en": "Scanning for controllers...",
        "fr": "Recherche de manettes...",
        "ja": "コントローラーを検索中...",
        "es": "Buscando mandos...",
        "de": "Suche nach Controllern...",
        "pt": "Procurando controles...",
        "it": "Ricerca controller...",
    },
    "scan.found_n": {
        "en": "{n} controller(s) detected \u2014 select and click Connect",
        "fr": "{n} manette(s) détectée(s) \u2014 sélectionnez et cliquez Connecter",
        "ja": "{n}台のコントローラーを検出 \u2014 選択して接続をクリック",
        "es": "{n} mando(s) detectado(s) \u2014 selecciona y haz clic en Conectar",
        "de": "{n} Controller erkannt \u2014 auswählen und Verbinden klicken",
        "pt": "{n} controle(s) detectado(s) \u2014 selecione e clique em Conectar",
        "it": "{n} controller rilevato/i \u2014 seleziona e clicca Connetti",
    },
    "scan.no_controllers": {
        "en": "No Controllers Found",
        "fr": "Aucune manette trouvée",
        "ja": "コントローラーが見つかりません",
        "es": "No se encontraron mandos",
        "de": "Keine Controller gefunden",
        "pt": "Nenhum controle encontrado",
        "it": "Nessun controller trovato",
    },
    "scan.no_controllers_detail": {
        "en": "No Nintendo controllers were detected.\n"
              "Make sure your controller is in pairing mode\n"
              "(LED should be flashing) and try again.",
        "fr": "Aucune manette Nintendo n'a été détectée.\n"
              "Vérifiez que votre manette est en mode appairage\n"
              "(la LED doit clignoter) et réessayez.",
        "ja": "Nintendoコントローラーが検出されませんでした。\n"
              "コントローラーがペアリングモードになっているか確認し\n"
              "（LEDが点滅しているはず）、再試行してください。",
        "es": "No se detectaron mandos Nintendo.\n"
              "Asegúrate de que el mando esté en modo emparejamiento\n"
              "(el LED debe parpadear) e inténtalo de nuevo.",
        "de": "Es wurden keine Nintendo-Controller erkannt.\n"
              "Stellen Sie sicher, dass der Controller im Kopplungsmodus ist\n"
              "(LED sollte blinken) und versuchen Sie es erneut.",
        "pt": "Nenhum controle Nintendo foi detectado.\n"
              "Verifique se o controle está no modo de pareamento\n"
              "(o LED deve estar piscando) e tente novamente.",
        "it": "Nessun controller Nintendo rilevato.\n"
              "Assicurati che il controller sia in modalità associazione\n"
              "(il LED dovrebbe lampeggiare) e riprova.",
    },
    "scan.controllers_found": {
        "en": "Controllers Found",
        "fr": "Manettes trouvées",
        "ja": "コントローラーが見つかりました",
        "es": "Mandos encontrados",
        "de": "Controller gefunden",
        "pt": "Controles encontrados",
        "it": "Controller trovati",
    },
    "scan.controllers_found_detail": {
        "en": "Found {n_ctrl} controller(s) out of {n_total} nearby devices.",
        "fr": "{n_ctrl} manette(s) trouvée(s) parmi {n_total} appareils à proximité.",
        "ja": "近くの{n_total}台のデバイスのうち{n_ctrl}台のコントローラーを検出。",
        "es": "{n_ctrl} mando(s) encontrado(s) de {n_total} dispositivos cercanos.",
        "de": "{n_ctrl} Controller unter {n_total} Geräten in der Nähe gefunden.",
        "pt": "{n_ctrl} controle(s) encontrado(s) de {n_total} dispositivos próximos.",
        "it": "{n_ctrl} controller trovato/i su {n_total} dispositivi nelle vicinanze.",
    },
    "scan.all_devices": {
        "en": "All Nearby Devices",
        "fr": "Tous les appareils à proximité",
        "ja": "近くのすべてのデバイス",
        "es": "Todos los dispositivos cercanos",
        "de": "Alle Geräte in der Nähe",
        "pt": "Todos os dispositivos próximos",
        "it": "Tutti i dispositivi nelle vicinanze",
    },
    "scan.all_devices_detail": {
        "en": "{n} device(s) found. Select your controller:",
        "fr": "{n} appareil(s) trouvé(s). Sélectionnez votre manette :",
        "ja": "{n}台のデバイスが見つかりました。コントローラーを選択：",
        "es": "{n} dispositivo(s) encontrado(s). Selecciona tu mando:",
        "de": "{n} Gerät(e) gefunden. Wählen Sie Ihren Controller:",
        "pt": "{n} dispositivo(s) encontrado(s). Selecione seu controle:",
        "it": "{n} dispositivo/i trovato/i. Seleziona il tuo controller:",
    },
    "scan.col_type": {
        "en": "Type",
        "fr": "Type",
        "ja": "タイプ",
        "es": "Tipo",
        "de": "Typ",
        "pt": "Tipo",
        "it": "Tipo",
    },
    "scan.col_address": {
        "en": "Address",
        "fr": "Adresse",
        "ja": "アドレス",
        "es": "Dirección",
        "de": "Adresse",
        "pt": "Endereço",
        "it": "Indirizzo",
    },
    "scan.col_signal": {
        "en": "Signal",
        "fr": "Signal",
        "ja": "信号",
        "es": "Señal",
        "de": "Signal",
        "pt": "Sinal",
        "it": "Segnale",
    },
    "scan.nintendo_controller": {
        "en": "Nintendo Controller",
        "fr": "Manette Nintendo",
        "ja": "Nintendoコントローラー",
        "es": "Mando Nintendo",
        "de": "Nintendo-Controller",
        "pt": "Controle Nintendo",
        "it": "Controller Nintendo",
    },
    "scan.unknown_device": {
        "en": "(unknown device)",
        "fr": "(appareil inconnu)",
        "ja": "(不明なデバイス)",
        "es": "(dispositivo desconocido)",
        "de": "(unbekanntes Gerät)",
        "pt": "(dispositivo desconhecido)",
        "it": "(dispositivo sconosciuto)",
    },

    # ── Calibration wizard ────────────────────────────────────────
    "cal.sticks_instruction": {
        "en": "Move sticks to all extremes, then click Continue",
        "fr": "Bougez les sticks dans toutes les directions, puis cliquez Continuer",
        "ja": "スティックをすべての方向に動かしてから、続行をクリック",
        "es": "Mueve los sticks a todos los extremos y haz clic en Continuar",
        "de": "Bewegen Sie die Sticks in alle Richtungen, dann klicken Sie Weiter",
        "pt": "Mova os analógicos em todas as direções e clique em Continuar",
        "it": "Muovi gli stick in tutte le direzioni, poi clicca Continua",
    },
    "cal.trigger_release": {
        "en": "Release both triggers, then click Continue",
        "fr": "Relâchez les deux gâchettes, puis cliquez Continuer",
        "ja": "両方のトリガーを離してから、続行をクリック",
        "es": "Suelta ambos gatillos y haz clic en Continuar",
        "de": "Lassen Sie beide Trigger los, dann klicken Sie Weiter",
        "pt": "Solte ambos os gatilhos e clique em Continuar",
        "it": "Rilascia entrambi i grilletti, poi clicca Continua",
    },
    "cal.trigger_left_bump": {
        "en": "LEFT trigger \u2192 press to max \u25b6 BEFORE the click \u25c0 then release",
        "fr": "Gâchette GAUCHE \u2192 enfoncez au max \u25b6 AVANT le clic \u25c0 puis relâchez",
        "ja": "左トリガー \u2192 クリック前 \u25b6 の最大まで押す \u25c0 そして離す",
        "es": "Gatillo IZQUIERDO \u2192 presiona al máx \u25b6 ANTES del clic \u25c0 luego suelta",
        "de": "LINKER Trigger \u2192 bis zum Anschlag \u25b6 VOR dem Klick \u25c0 dann loslassen",
        "pt": "Gatilho ESQUERDO \u2192 pressione ao máx \u25b6 ANTES do clique \u25c0 depois solte",
        "it": "Grilletto SINISTRO \u2192 premi al max \u25b6 PRIMA del clic \u25c0 poi rilascia",
    },
    "cal.trigger_left_max": {
        "en": "LEFT trigger \u2192 press fully \u25b6 PAST the click \u25c0 then release",
        "fr": "Gâchette GAUCHE \u2192 enfoncez à fond \u25b6 AU-DELÀ du clic \u25c0 puis relâchez",
        "ja": "左トリガー \u2192 クリックを越えて \u25b6 最大まで押す \u25c0 そして離す",
        "es": "Gatillo IZQUIERDO \u2192 presiona a fondo \u25b6 PASADO el clic \u25c0 luego suelta",
        "de": "LINKER Trigger \u2192 ganz durchdrücken \u25b6 ÜBER den Klick hinaus \u25c0 dann loslassen",
        "pt": "Gatilho ESQUERDO \u2192 pressione a fundo \u25b6 ALÉM do clique \u25c0 depois solte",
        "it": "Grilletto SINISTRO \u2192 premi a fondo \u25b6 OLTRE il clic \u25c0 poi rilascia",
    },
    "cal.trigger_right_bump": {
        "en": "RIGHT trigger \u2192 press to max \u25b6 BEFORE the click \u25c0 then release",
        "fr": "Gâchette DROITE \u2192 enfoncez au max \u25b6 AVANT le clic \u25c0 puis relâchez",
        "ja": "右トリガー \u2192 クリック前 \u25b6 の最大まで押す \u25c0 そして離す",
        "es": "Gatillo DERECHO \u2192 presiona al máx \u25b6 ANTES del clic \u25c0 luego suelta",
        "de": "RECHTER Trigger \u2192 bis zum Anschlag \u25b6 VOR dem Klick \u25c0 dann loslassen",
        "pt": "Gatilho DIREITO \u2192 pressione ao máx \u25b6 ANTES do clique \u25c0 depois solte",
        "it": "Grilletto DESTRO \u2192 premi al max \u25b6 PRIMA del clic \u25c0 poi rilascia",
    },
    "cal.trigger_right_max": {
        "en": "RIGHT trigger \u2192 press fully \u25b6 PAST the click \u25c0 then release",
        "fr": "Gâchette DROITE \u2192 enfoncez à fond \u25b6 AU-DELÀ du clic \u25c0 puis relâchez",
        "ja": "右トリガー \u2192 クリックを越えて \u25b6 最大まで押す \u25c0 そして離す",
        "es": "Gatillo DERECHO \u2192 presiona a fondo \u25b6 PASADO el clic \u25c0 luego suelta",
        "de": "RECHTER Trigger \u2192 ganz durchdrücken \u25b6 ÜBER den Klick hinaus \u25c0 dann loslassen",
        "pt": "Gatilho DIREITO \u2192 pressione a fundo \u25b6 ALÉM do clique \u25c0 depois solte",
        "it": "Grilletto DESTRO \u2192 premi a fondo \u25b6 OLTRE il clic \u25c0 poi rilascia",
    },
    "cal.trigger_completed": {
        "en": "Trigger calibration completed",
        "fr": "Calibration des gâchettes terminée",
        "ja": "トリガーのキャリブレーション完了",
        "es": "Calibración de gatillos completada",
        "de": "Trigger-Kalibrierung abgeschlossen",
        "pt": "Calibração dos gatilhos concluída",
        "it": "Calibrazione grilletti completata",
    },
    "cal.trigger_retry_left": {
        "en": "Left trigger not detected (peak={val}, base={base}). "
              "Press it fully and click again",
        "fr": "Gâchette gauche non détectée (pic={val}, base={base}). "
              "Appuyez à fond et réessayez",
        "ja": "左トリガーが検出されません（ピーク={val}、ベース={base}）。"
              "完全に押してから再度クリック",
        "es": "Gatillo izquierdo no detectado (pico={val}, base={base}). "
              "Presiónalo a fondo y haz clic de nuevo",
        "de": "Linker Trigger nicht erkannt (Spitze={val}, Basis={base}). "
              "Ganz durchdrücken und erneut klicken",
        "pt": "Gatilho esquerdo não detectado (pico={val}, base={base}). "
              "Pressione a fundo e clique novamente",
        "it": "Grilletto sinistro non rilevato (picco={val}, base={base}). "
              "Premilo a fondo e clicca di nuovo",
    },
    "cal.trigger_retry_right": {
        "en": "Right trigger not detected (peak={val}, base={base}). "
              "Press it fully and click again",
        "fr": "Gâchette droite non détectée (pic={val}, base={base}). "
              "Appuyez à fond et réessayez",
        "ja": "右トリガーが検出されません（ピーク={val}、ベース={base}）。"
              "完全に押してから再度クリック",
        "es": "Gatillo derecho no detectado (pico={val}, base={base}). "
              "Presiónalo a fondo y haz clic de nuevo",
        "de": "Rechter Trigger nicht erkannt (Spitze={val}, Basis={base}). "
              "Ganz durchdrücken und erneut klicken",
        "pt": "Gatilho direito não detectado (pico={val}, base={base}). "
              "Pressione a fundo e clique novamente",
        "it": "Grilletto destro non rilevato (picco={val}, base={base}). "
              "Premilo a fondo e clicca di nuovo",
    },
    "cal.btn_retry_or_force": {
        "en": "Retry (or force)",
        "fr": "Réessayer (ou forcer)",
        "ja": "再試行（または強制）",
        "es": "Reintentar (o forzar)",
        "de": "Erneut versuchen (oder erzwingen)",
        "pt": "Tentar novamente (ou forçar)",
        "it": "Riprova (o forza)",
    },

    # ── BLE device picker dialog ──────────────────────────────────
    "ble_dialog.title": {
        "en": "Select BLE Controller",
        "fr": "Sélectionner une manette BLE",
        "ja": "BLEコントローラーを選択",
        "es": "Seleccionar mando BLE",
        "de": "BLE-Controller auswählen",
        "pt": "Selecionar controle BLE",
        "it": "Seleziona controller BLE",
    },
    "ble_dialog.select_prompt": {
        "en": "Select a controller to connect:",
        "fr": "Sélectionnez une manette à connecter :",
        "ja": "接続するコントローラーを選択：",
        "es": "Selecciona un mando para conectar:",
        "de": "Wählen Sie einen Controller zum Verbinden:",
        "pt": "Selecione um controle para conectar:",
        "it": "Seleziona un controller da connettere:",
    },
    "ble_dialog.col_name": {
        "en": "Name",
        "fr": "Nom",
        "ja": "名前",
        "es": "Nombre",
        "de": "Name",
        "pt": "Nome",
        "it": "Nome",
    },
    "ble_dialog.col_address": {
        "en": "Address",
        "fr": "Adresse",
        "ja": "アドレス",
        "es": "Dirección",
        "de": "Adresse",
        "pt": "Endereço",
        "it": "Indirizzo",
    },
    "ble_dialog.col_signal": {
        "en": "Signal",
        "fr": "Signal",
        "ja": "信号",
        "es": "Señal",
        "de": "Signal",
        "pt": "Sinal",
        "it": "Segnale",
    },
    "ble_dialog.unknown": {
        "en": "(unknown)",
        "fr": "(inconnu)",
        "ja": "(不明)",
        "es": "(desconocido)",
        "de": "(unbekannt)",
        "pt": "(desconhecido)",
        "it": "(sconosciuto)",
    },

    # ── Settings dialog ───────────────────────────────────────────
    "settings.title": {
        "en": "Settings",
        "fr": "Paramètres",
        "ja": "設定",
        "es": "Ajustes",
        "de": "Einstellungen",
        "pt": "Configurações",
        "it": "Impostazioni",
    },
    "settings.trigger_bump": {
        "en": "100% at bump",
        "fr": "100% au rebond",
        "ja": "100%（バンプ時）",
        "es": "100% al tope",
        "de": "100% beim Anschlag",
        "pt": "100% no batente",
        "it": "100% al punto di pressione",
    },
    "settings.trigger_press": {
        "en": "100% at press",
        "fr": "100% à l'appui",
        "ja": "100%（フルプレス時）",
        "es": "100% al pulsar",
        "de": "100% beim Durchdrücken",
        "pt": "100% ao pressionar",
        "it": "100% alla pressione completa",
    },
    "settings.emulation_mode": {
        "en": "Emulation Mode",
        "fr": "Mode d'émulation",
        "ja": "エミュレーションモード",
        "es": "Modo de emulación",
        "de": "Emulationsmodus",
        "pt": "Modo de emulação",
        "it": "Modalità emulazione",
    },
    "settings.trigger_mode": {
        "en": "Trigger Mode",
        "fr": "Mode des gâchettes",
        "ja": "トリガーモード",
        "es": "Modo de gatillo",
        "de": "Trigger-Modus",
        "pt": "Modo do gatilho",
        "it": "Modalità grilletto",
    },
    "settings.stick_deadzone": {
        "en": "Stick Deadzone",
        "fr": "Zone morte des sticks",
        "ja": "スティックのデッドゾーン",
        "es": "Zona muerta del stick",
        "de": "Stick-Totzone",
        "pt": "Zona morta do analógico",
        "it": "Zona morta stick",
    },
    "settings.auto_connect_usb": {
        "en": "Auto-connect USB",
        "fr": "Connexion USB automatique",
        "ja": "USB自動接続",
        "es": "Conexión USB automática",
        "de": "USB automatisch verbinden",
        "pt": "Conexão USB automática",
        "it": "Connessione USB automatica",
    },
    "settings.auto_scan_ble": {
        "en": "Auto-scan BLE at startup",
        "fr": "Recherche BLE automatique au démarrage",
        "ja": "起動時にBLEを自動スキャン",
        "es": "Escaneo BLE automático al inicio",
        "de": "BLE beim Start automatisch scannen",
        "pt": "Escanear BLE automaticamente ao iniciar",
        "it": "Scansione BLE automatica all'avvio",
    },
    "settings.minimize_tray": {
        "en": "Minimize to system tray",
        "fr": "Réduire dans la zone de notification",
        "ja": "システムトレイに最小化",
        "es": "Minimizar a la bandeja del sistema",
        "de": "In den Infobereich minimieren",
        "pt": "Minimizar para a bandeja do sistema",
        "it": "Minimizza nell'area di notifica",
    },
    "settings.run_at_startup": {
        "en": "Run at startup",
        "fr": "Lancer au démarrage",
        "ja": "起動時に実行",
        "es": "Ejecutar al inicio",
        "de": "Beim Start ausführen",
        "pt": "Executar ao iniciar",
        "it": "Esegui all'avvio",
    },
    "settings.test_rumble": {
        "en": "Test Rumble",
        "fr": "Tester les vibrations",
        "ja": "振動テスト",
        "es": "Probar vibración",
        "de": "Vibration testen",
        "pt": "Testar vibração",
        "it": "Testa vibrazione",
    },
    "settings.paired_controllers": {
        "en": "Paired Controllers",
        "fr": "Manettes appairées",
        "ja": "ペアリング済みコントローラー",
        "es": "Mandos emparejados",
        "de": "Gekoppelte Controller",
        "pt": "Controles pareados",
        "it": "Controller associati",
    },
    "settings.no_paired": {
        "en": "No paired controllers",
        "fr": "Aucune manette appairée",
        "ja": "ペアリング済みのコントローラーはありません",
        "es": "No hay mandos emparejados",
        "de": "Keine gekoppelten Controller",
        "pt": "Nenhum controle pareado",
        "it": "Nessun controller associato",
    },
    "settings.forget": {
        "en": "Forget",
        "fr": "Oublier",
        "ja": "解除",
        "es": "Olvidar",
        "de": "Vergessen",
        "pt": "Esquecer",
        "it": "Dimentica",
    },
    "settings.forget_all": {
        "en": "Forget All",
        "fr": "Tout oublier",
        "ja": "すべて解除",
        "es": "Olvidar todo",
        "de": "Alle vergessen",
        "pt": "Esquecer tudo",
        "it": "Dimentica tutto",
    },
    "settings.device_links": {
        "en": "Device Links (USB \u2194 BT)",
        "fr": "Liens entre appareils (USB \u2194 BT)",
        "ja": "デバイスリンク (USB \u2194 BT)",
        "es": "Enlaces de dispositivos (USB \u2194 BT)",
        "de": "Geräteverknüpfungen (USB \u2194 BT)",
        "pt": "Links de dispositivos (USB \u2194 BT)",
        "it": "Collegamenti dispositivi (USB \u2194 BT)",
    },
    "settings.no_links": {
        "en": "No linked devices",
        "fr": "Aucun appareil lié",
        "ja": "リンクされたデバイスはありません",
        "es": "No hay dispositivos vinculados",
        "de": "Keine verknüpften Geräte",
        "pt": "Nenhum dispositivo vinculado",
        "it": "Nessun dispositivo collegato",
    },
    "settings.unlink": {
        "en": "Unlink",
        "fr": "Délier",
        "ja": "リンク解除",
        "es": "Desvincular",
        "de": "Trennen",
        "pt": "Desvincular",
        "it": "Scollega",
    },
    "settings.about": {
        "en": "About",
        "fr": "À propos",
        "ja": "このアプリについて",
        "es": "Acerca de",
        "de": "Über",
        "pt": "Sobre",
        "it": "Informazioni",
    },
    "settings.source_code": {
        "en": "Source Code on GitHub",
        "fr": "Code source sur GitHub",
        "ja": "GitHubのソースコード",
        "es": "Código fuente en GitHub",
        "de": "Quellcode auf GitHub",
        "pt": "Código-fonte no GitHub",
        "it": "Codice sorgente su GitHub",
    },
    "settings.credits": {
        "en": "Credits & Special Thanks",
        "fr": "Crédits et remerciements",
        "ja": "クレジットと謝辞",
        "es": "Créditos y agradecimientos",
        "de": "Credits & Danksagung",
        "pt": "Créditos e agradecimentos",
        "it": "Crediti e ringraziamenti",
    },
    "settings.language": {
        "en": "Language",
        "fr": "Langue",
        "ja": "言語",
        "es": "Idioma",
        "de": "Sprache",
        "pt": "Idioma",
        "it": "Lingua",
    },
    "settings.saved": {
        "en": "Settings saved successfully!",
        "fr": "Paramètres enregistrés !",
        "ja": "設定を保存しました！",
        "es": "¡Ajustes guardados!",
        "de": "Einstellungen gespeichert!",
        "pt": "Configurações salvas!",
        "it": "Impostazioni salvate!",
    },
    "settings.save_error": {
        "en": "Failed to save settings: {error}",
        "fr": "Échec de la sauvegarde : {error}",
        "ja": "設定の保存に失敗しました: {error}",
        "es": "Error al guardar ajustes: {error}",
        "de": "Einstellungen konnten nicht gespeichert werden: {error}",
        "pt": "Falha ao salvar configurações: {error}",
        "it": "Impossibile salvare le impostazioni: {error}",
    },

    # ── Error dialog titles ────────────────────────────────────────
    "error.ble": {
        "en": "BLE Error",
        "fr": "Erreur BLE",
        "ja": "BLEエラー",
        "es": "Error BLE",
        "de": "BLE-Fehler",
        "pt": "Erro BLE",
        "it": "Errore BLE",
    },
    "error.emulation": {
        "en": "Emulation Error",
        "fr": "Erreur d'émulation",
        "ja": "エミュレーションエラー",
        "es": "Error de emulación",
        "de": "Emulationsfehler",
        "pt": "Erro de emulação",
        "it": "Errore di emulazione",
    },
    "error.generic": {
        "en": "Error",
        "fr": "Erreur",
        "ja": "エラー",
        "es": "Error",
        "de": "Fehler",
        "pt": "Erro",
        "it": "Errore",
    },
    "error.ble_pkexec": {
        "en": "pkexec is required for Bluetooth LE.\n\n"
              "Install with:\n"
              "  sudo apt install policykit-1",
        "fr": "pkexec est requis pour le Bluetooth LE.\n\n"
              "Installez-le avec :\n"
              "  sudo apt install policykit-1",
        "ja": "Bluetooth LEにはpkexecが必要です。\n\n"
              "インストール:\n"
              "  sudo apt install policykit-1",
        "es": "pkexec es necesario para Bluetooth LE.\n\n"
              "Instálalo con:\n"
              "  sudo apt install policykit-1",
        "de": "pkexec wird für Bluetooth LE benötigt.\n\n"
              "Installieren mit:\n"
              "  sudo apt install policykit-1",
        "pt": "pkexec é necessário para Bluetooth LE.\n\n"
              "Instale com:\n"
              "  sudo apt install policykit-1",
        "it": "pkexec è necessario per il Bluetooth LE.\n\n"
              "Installalo con:\n"
              "  sudo apt install policykit-1",
    },
    "error.ble_start_failed": {
        "en": "Failed to start BLE service:\n{error}",
        "fr": "Échec du démarrage du service BLE :\n{error}",
        "ja": "BLEサービスの起動に失敗しました:\n{error}",
        "es": "Error al iniciar el servicio BLE:\n{error}",
        "de": "BLE-Dienst konnte nicht gestartet werden:\n{error}",
        "pt": "Falha ao iniciar o serviço BLE:\n{error}",
        "it": "Impossibile avviare il servizio BLE:\n{error}",
    },
    "error.ble_auth_cancelled": {
        "en": "BLE service failed to start.\n\n"
              "Authentication may have been cancelled.",
        "fr": "Le service BLE n'a pas pu démarrer.\n\n"
              "L'authentification a peut-être été annulée.",
        "ja": "BLEサービスの起動に失敗しました。\n\n"
              "認証がキャンセルされた可能性があります。",
        "es": "El servicio BLE no pudo iniciarse.\n\n"
              "La autenticación puede haber sido cancelada.",
        "de": "BLE-Dienst konnte nicht gestartet werden.\n\n"
              "Die Authentifizierung wurde möglicherweise abgebrochen.",
        "pt": "O serviço BLE não pôde ser iniciado.\n\n"
              "A autenticação pode ter sido cancelada.",
        "it": "Il servizio BLE non è riuscito ad avviarsi.\n\n"
              "L'autenticazione potrebbe essere stata annullata.",
    },
    "error.ble_adapter": {
        "en": "Failed to initialize BLE:\n{msg}\n\n"
              "Make sure a Bluetooth adapter is connected.",
        "fr": "Échec de l'initialisation BLE :\n{msg}\n\n"
              "Vérifiez qu'un adaptateur Bluetooth est connecté.",
        "ja": "BLEの初期化に失敗しました:\n{msg}\n\n"
              "Bluetoothアダプターが接続されていることを確認してください。",
        "es": "Error al inicializar BLE:\n{msg}\n\n"
              "Asegúrate de que un adaptador Bluetooth esté conectado.",
        "de": "BLE-Initialisierung fehlgeschlagen:\n{msg}\n\n"
              "Stellen Sie sicher, dass ein Bluetooth-Adapter angeschlossen ist.",
        "pt": "Falha ao inicializar o BLE:\n{msg}\n\n"
              "Verifique se um adaptador Bluetooth está conectado.",
        "it": "Impossibile inizializzare il BLE:\n{msg}\n\n"
              "Assicurati che un adattatore Bluetooth sia collegato.",
    },
    "error.emu_failed": {
        "en": "Failed to start emulation: {error}",
        "fr": "Échec du démarrage de l'émulation : {error}",
        "ja": "エミュレーションの開始に失敗しました: {error}",
        "es": "Error al iniciar la emulación: {error}",
        "de": "Emulation konnte nicht gestartet werden: {error}",
        "pt": "Falha ao iniciar a emulação: {error}",
        "it": "Impossibile avviare l'emulazione: {error}",
    },
    "error.emu_dsu_failed": {
        "en": "Failed to start DSU emulation: {error}",
        "fr": "Échec du démarrage de l'émulation DSU : {error}",
        "ja": "DSUエミュレーションの開始に失敗しました: {error}",
        "es": "Error al iniciar la emulación DSU: {error}",
        "de": "DSU-Emulation konnte nicht gestartet werden: {error}",
        "pt": "Falha ao iniciar a emulação DSU: {error}",
        "it": "Impossibile avviare l'emulazione DSU: {error}",
    },
    "error.emu_pipe_failed": {
        "en": "Failed to start pipe emulation: {error}",
        "fr": "Échec du démarrage de l'émulation pipe : {error}",
        "ja": "パイプエミュレーションの開始に失敗しました: {error}",
        "es": "Error al iniciar la emulación por pipe: {error}",
        "de": "Pipe-Emulation konnte nicht gestartet werden: {error}",
        "pt": "Falha ao iniciar a emulação por pipe: {error}",
        "it": "Impossibile avviare l'emulazione pipe: {error}",
    },
    "error.emu_unavailable": {
        "en": "Emulation not available for mode '{mode}'.\n{reason}",
        "fr": "Émulation non disponible pour le mode « {mode} ».\n{reason}",
        "ja": "モード「{mode}」のエミュレーションは利用できません。\n{reason}",
        "es": "Emulación no disponible para el modo «{mode}».\n{reason}",
        "de": "Emulation f\u00fcr Modus \u201E{mode}\u201C nicht verf\u00fcgbar.\n{reason}",
        "pt": "Emulação não disponível para o modo '{mode}'.\n{reason}",
        "it": "Emulazione non disponibile per la modalità '{mode}'.\n{reason}",
    },
    "error.emu_unexpected": {
        "en": "Unexpected error: {error}",
        "fr": "Erreur inattendue : {error}",
        "ja": "予期しないエラー: {error}",
        "es": "Error inesperado: {error}",
        "de": "Unerwarteter Fehler: {error}",
        "pt": "Erro inesperado: {error}",
        "it": "Errore imprevisto: {error}",
    },

    # ── System tray ────────────────────────────────────────────────
    "tray.show": {
        "en": "Show",
        "fr": "Afficher",
        "ja": "表示",
        "es": "Mostrar",
        "de": "Anzeigen",
        "pt": "Mostrar",
        "it": "Mostra",
    },
    "tray.quit": {
        "en": "Quit",
        "fr": "Quitter",
        "ja": "終了",
        "es": "Salir",
        "de": "Beenden",
        "pt": "Sair",
        "it": "Esci",
    },

    # ── Instance lock ──────────────────────────────────────────────
    "app.already_running": {
        "en": "Another instance of NSO GC Controller is already running.",
        "fr": "Une autre instance de NSO GC Controller est déjà en cours d'exécution.",
        "ja": "NSO GC Controllerの別のインスタンスが既に実行中です。",
        "es": "Otra instancia de NSO GC Controller ya está en ejecución.",
        "de": "Eine andere Instanz von NSO GC Controller läuft bereits.",
        "pt": "Outra instância do NSO GC Controller já está em execução.",
        "it": "Un'altra istanza di NSO GC Controller è già in esecuzione.",
    },
}

_current_lang = "en"


def _detect_language() -> str:
    """Detect the system language, returning a supported code or 'en'.

    On macOS, locale env vars are often unset ('C'), so we read the
    native AppleLanguages preference via subprocess as a fallback.
    """
    import sys

    def _match_tag(tag: str) -> str | None:
        """Match a single locale tag like 'fr_FR' to a supported language."""
        tag = tag.lower().replace("-", "_")
        for lang in _SUPPORTED_LANGS:
            if lang != "en" and tag.startswith(lang):
                return lang
        return None

    # Try standard locale detection first
    try:
        loc = locale.getlocale()[0] or ""
        matched = _match_tag(loc)
        if matched:
            return matched
    except Exception:
        pass

    # macOS fallback: read the system language preference list
    if sys.platform == 'darwin':
        try:
            import re
            import subprocess
            result = subprocess.run(
                ['defaults', 'read', '-g', 'AppleLanguages'],
                capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                # Output is a plist array like: (\n    "fr-FR",\n    "en-US"\n)
                # Extract quoted tags in order of preference
                for tag in re.findall(r'"([^"]+)"', result.stdout):
                    matched = _match_tag(tag)
                    if matched:
                        return matched
        except Exception:
            pass

    return "en"


def init(lang: str | None = None):
    """Initialize the i18n system.

    Args:
        lang: Force a language code. If None, auto-detect.
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
