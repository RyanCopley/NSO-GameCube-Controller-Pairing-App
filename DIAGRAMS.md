# NSO GameCube Controller Enabler — Architecture Diagrams

## High-Level Architecture

```mermaid
graph TB
    subgraph GUI["GUI Layer (customtkinter)"]
        App["GCControllerEnabler<br/>(app.py)"]
        CUI["ControllerUI<br/>(controller_ui.py)"]
        Canvas["GCControllerVisual<br/>(ui_controller_canvas.py)"]
        BLEDialog["BLEDevicePickerDialog<br/>(ui_ble_dialog.py)"]
        SettingsDialog["SettingsDialog<br/>(ui_settings_dialog.py)"]
        Theme["ui_theme.py"]
    end

    subgraph SlotLayer["Per-Slot Controllers (x4)"]
        Slot["ControllerSlot<br/>(controller_slot.py)"]
        CalMgr["CalibrationManager<br/>(calibration.py)"]
        ConnMgr["ConnectionManager<br/>(connection_manager.py)"]
        EmuMgr["EmulationManager<br/>(emulation_manager.py)"]
        InputProc["InputProcessor<br/>(input_processor.py)"]
    end

    subgraph Connection["Connection Layer"]
        USB["USB HID<br/>(hidapi / pyusb)"]
        BLESub["BLE Subprocess<br/>(ble_subprocess.py)"]
        BleakSub["Bleak Subprocess<br/>(bleak_subprocess.py)"]
    end

    subgraph Emulation["Emulation Layer"]
        VGP["VirtualGamepad<br/>(virtual_gamepad.py)"]
        WinGP["WindowsGamepad<br/>(vgamepad/ViGEmBus)"]
        LinGP["LinuxGamepad<br/>(evdev/uinput)"]
        DolphinGP["DolphinPipeGamepad<br/>(named FIFO)"]
    end

    subgraph BLE["BLE Protocol"]
        SW2["sw2_protocol.py"]
        Bumble["BumbleBackend<br/>(bumble_backend.py)"]
        Bleak["BleakBackend<br/>(bleak_backend.py)"]
    end

    App --> CUI
    CUI --> Canvas
    App --> BLEDialog
    App --> SettingsDialog
    App --> Slot
    Slot --> CalMgr
    Slot --> ConnMgr
    Slot --> EmuMgr
    Slot --> InputProc
    ConnMgr --> USB
    InputProc --> USB
    InputProc --> EmuMgr
    EmuMgr --> VGP
    VGP --> WinGP
    VGP --> LinGP
    VGP --> DolphinGP
    App --> BLESub
    App --> BleakSub
    BLESub --> Bumble
    BleakSub --> Bleak
    Bumble --> SW2
    Bleak --> SW2
```

---

## Controller Slot Composition

Each of the 4 controller slots is an independent unit containing its own managers:

```mermaid
classDiagram
    class ControllerSlot {
        +int index
        +dict calibration
        +bytes device_path
        +str connection_mode
        +str ble_address
        +Queue ble_data_queue
        +bool ble_connected
        +is_connected() bool
        +is_emulating() bool
    }

    class CalibrationManager {
        -dict _calibration
        -Lock _cal_lock
        -dict _cached_calibration
        +bool stick_calibrating
        +int trigger_cal_step
        +start_stick_calibration()
        +finish_stick_calibration()
        +track_stick_data(lx, ly, rx, ry)
        +trigger_cal_next_step() tuple
        +calibrate_trigger_fast(raw, side) int
    }

    class ConnectionManager {
        -object _hid_device
        +enumerate_devices() list
        +initialize_via_usb(path)
        +init_hid_device(path)
        +send_rumble(on)
        +disconnect()
    }

    class EmulationManager {
        -VirtualGamepad _gamepad
        +bool is_emulating
        +start(mode, slot_idx)
        +stop()
        +update(lx, ly, rx, ry, lt, rt, buttons)
    }

    class InputProcessor {
        -Thread _thread
        -Event _stop_event
        +bool is_reading
        +start(mode)
        +stop()
        -_read_loop()
        -_read_loop_ble()
        -_process_data(data)
        -_translate_report_0x05(data)
    }

    ControllerSlot *-- CalibrationManager
    ControllerSlot *-- ConnectionManager
    ControllerSlot *-- EmulationManager
    ControllerSlot *-- InputProcessor
    InputProcessor --> EmulationManager : update()
    EmulationManager --> CalibrationManager : calibrate_trigger_fast()
```

---

## Virtual Gamepad Class Hierarchy

```mermaid
classDiagram
    class VirtualGamepad {
        <<abstract>>
        +left_joystick(x, y)*
        +right_joystick(x, y)*
        +left_trigger(value)*
        +right_trigger(value)*
        +press_button(button)*
        +release_button(button)*
        +update()*
        +reset()*
        +close()*
        +set_rumble_callback(cb)
        +stop_rumble_listener()
    }

    class WindowsGamepad {
        -vgamepad _device
        +left_joystick(x, y)
        +right_joystick(x, y)
        +press_button(button)
        +update()
    }

    class LinuxGamepad {
        -UInput _device
        +left_joystick(x, y)
        +right_joystick(x, y)
        +press_button(button)
        +update()
    }

    class DolphinPipeGamepad {
        -str _pipe_path
        -file _pipe_fd
        +left_joystick(x, y)
        +right_joystick(x, y)
        +press_button(button)
        +update()
    }

    class GamepadButton {
        <<enum>>
        A
        B
        X
        Y
        LEFT_SHOULDER
        RIGHT_SHOULDER
        START
        BACK
        DPAD_UP
        DPAD_DOWN
        DPAD_LEFT
        DPAD_RIGHT
        HOME
    }

    VirtualGamepad <|-- WindowsGamepad : Windows
    VirtualGamepad <|-- LinuxGamepad : Linux
    VirtualGamepad <|-- DolphinPipeGamepad : macOS / Linux
    VirtualGamepad --> GamepadButton
```

---

## USB Connection Flow

```mermaid
sequenceDiagram
    participant User
    participant App as GCControllerEnabler
    participant Conn as ConnectionManager
    participant HID as USB HID Device
    participant Input as InputProcessor
    participant Emu as EmulationManager
    participant VGP as VirtualGamepad

    User->>App: Click "Connect USB"
    App->>Conn: enumerate_devices()
    Conn->>HID: Scan HID bus
    HID-->>Conn: Device list (VID=057E, PID=2073)
    App->>Conn: initialize_via_usb(path)
    Conn->>HID: Claim interface 1
    Conn->>HID: Send DEFAULT_REPORT_DATA
    Conn->>HID: Send SET_LED_DATA
    Conn->>HID: Release interface 1
    App->>Conn: init_hid_device(path)
    Conn->>HID: Open HID device

    App->>Input: start(mode='usb')
    activate Input
    loop Read Loop (~120 Hz)
        Input->>HID: Non-blocking read (64 bytes)
        HID-->>Input: HID Report
        Input->>Input: _process_data(report)
        Input->>App: on_ui_update callback
        Input->>Emu: update(sticks, triggers, buttons)
        Emu->>VGP: Update virtual gamepad
    end
    deactivate Input
```

---

## BLE Connection Flow (Linux — Bumble)

```mermaid
sequenceDiagram
    participant User
    participant App as GCControllerEnabler
    participant Sub as BLE Subprocess<br/>(pkexec elevated)
    participant Bumble as BumbleBackend
    participant Ctrl as NSO GC Controller

    User->>App: Click "Pair Controller"
    App->>App: _init_ble()
    App->>Sub: Spawn via pkexec
    Sub-->>App: {"e": "ready"}
    App->>Sub: {"cmd": "stop_bluez"}
    Sub->>Sub: systemctl stop bluetooth
    Sub-->>App: {"e": "bluez_stopped"}
    App->>Sub: {"cmd": "open", "hci_index": 0}
    Sub->>Bumble: Open raw HCI socket
    Sub-->>App: {"e": "open_ok"}

    App->>Sub: {"cmd": "scan_connect", "slot_index": 0}
    Sub->>Bumble: Start BLE scan
    Bumble->>Ctrl: BLE Advertisement scan
    Ctrl-->>Bumble: Found (Nintendo OUI)
    Bumble->>Ctrl: Connect
    Bumble->>Ctrl: SMP Legacy Just Works
    Note right of Ctrl: Key dist:<br/>init=0x02 resp=0x01
    Ctrl-->>Bumble: Paired
    Bumble->>Ctrl: MTU Exchange (≥185)
    Bumble->>Ctrl: Enable service (0x0005)
    Bumble->>Ctrl: SW2 pairing handshake (4 steps)
    Bumble->>Ctrl: Set player LED
    Bumble->>Ctrl: Enable input notifications (0x000B)

    Sub-->>App: {"e": "connected", "mac": "XX:XX:..."}

    loop Input Notifications
        Ctrl-->>Sub: 63-byte BLE report
        Sub-->>App: {"e": "data", "d": "<base64>"}
        App->>App: Queue → InputProcessor
    end
```

---

## BLE Subprocess IPC Protocol

```mermaid
flowchart LR
    subgraph Parent["Main Process"]
        App["GCControllerEnabler"]
        Reader["_ble_event_reader()<br/>thread"]
    end

    subgraph Child["Elevated Subprocess"]
        BLESub["ble_subprocess.py"]
        Backend["Bumble / Bleak<br/>Backend"]
    end

    App -- "stdin (JSON)" --> BLESub
    BLESub -- "stdout (JSON)" --> Reader

    subgraph Commands["Parent → Child"]
        C1["stop_bluez"]
        C2["open"]
        C3["scan_connect"]
        C4["disconnect"]
        C5["rumble"]
        C6["shutdown"]
    end

    subgraph Events["Child → Parent"]
        E1["ready"]
        E2["bluez_stopped / open_ok"]
        E3["connected"]
        E4["data (base64)"]
        E5["disconnected"]
        E6["error / connect_error"]
    end
```

---

## Input Processing Pipeline

```mermaid
flowchart TD
    subgraph Source["Input Source"]
        USB["USB HID<br/>64-byte report"]
        BLE["BLE Queue<br/>63-byte report"]
    end

    subgraph ReadLoop["Read Loop (background thread)"]
        Drain["Drain buffer<br/>(keep latest only)"]
        Translate["Translate 0x05 report<br/>(Windows only)"]
    end

    subgraph Process["_process_data()"]
        Sticks["Parse Sticks<br/>12-bit packed → LX, LY, RX, RY"]
        Buttons["Parse Buttons<br/>bytes 3-5 → button flags"]
        Triggers["Parse Triggers<br/>bytes 13-14 → L, R (0-255)"]
        CalTrack["Track Calibration<br/>(if calibrating)"]
    end

    subgraph Output["Output"]
        UI["UI Update<br/>(canvas visual)"]
        Emulation["EmulationManager.update()"]
    end

    subgraph EmuPipeline["Emulation Pipeline"]
        ScaleStick["Scale sticks<br/>→ [-32767, 32767]"]
        CalTrigger["Calibrate triggers<br/>(fast path)"]
        MapButtons["Map GC → Xbox 360<br/>buttons"]
        VGUpdate["VirtualGamepad.update()"]
    end

    USB --> Drain
    BLE --> Drain
    Drain --> Translate
    Translate --> Sticks
    Sticks --> CalTrack
    Sticks --> Buttons
    Buttons --> Triggers
    Triggers --> UI
    Triggers --> Emulation
    Emulation --> ScaleStick
    ScaleStick --> CalTrigger
    CalTrigger --> MapButtons
    MapButtons --> VGUpdate
```

---

## USB HID Report Structure

```mermaid
block-beta
    columns 16

    block:header:4
        B0["[0] Report ID"]
        B1["[1] Unknown"]
        B2["[2] Unknown"]
    end
    block:buttons:4
        B3["[3] Buttons 0<br/>B A Y X R Z Start"]
        B4["[4] Buttons 1<br/>DD DR DL DU L ZL"]
        B5["[5] Buttons 2<br/>Home Cap GR GL Chat"]
    end
    block:sticks:8
        B6["[6-8] Left Stick<br/>12-bit LX, LY"]
        B9["[9-11] Right Stick<br/>12-bit RX, RY"]
    end

    block:triggers:4
        B12["[12] Unknown"]
        B13["[13] L Trigger<br/>0x00-0xFF"]
        B14["[14] R Trigger<br/>0x00-0xFF"]
    end
    block:rest:4
        BIMU["[15-61] IMU / Motion"]
        BPAD["[62-63] Padding"]
    end
```

---

## Stick Calibration — Octagon Model

```mermaid
flowchart TD
    Start["User starts stick calibration"] --> Rotate["User rotates stick<br/>to all extremes"]

    Rotate --> Track["track_stick_data(lx, ly, rx, ry)"]

    Track --> Angle["Compute angle from center<br/>angle = atan2(dy, dx)"]
    Angle --> Sector["Map to 8 sectors<br/>sector = round(angle / 45°) % 8"]
    Sector --> MaxDist["Track max distance<br/>per sector"]

    MaxDist --> |"User clicks Finish"| Finish["finish_stick_calibration()"]
    Finish --> Center["Compute center<br/>(min + max) / 2 per axis"]
    Center --> Range["Compute range<br/>(max - min) / 2 per axis"]
    Range --> Octagon["Normalize octagon points<br/>to [-1, 1] per axis"]
    Octagon --> Save["Save to settings JSON"]

    subgraph Sectors["8 Octagon Sectors"]
        direction LR
        S0["0: East"]
        S1["1: NE"]
        S2["2: North"]
        S3["3: NW"]
        S4["4: West"]
        S5["5: SW"]
        S6["6: South"]
        S7["7: SE"]
    end
```

---

## Trigger Calibration Wizard

```mermaid
stateDiagram-v2
    [*] --> Idle: trigger_cal_step = 0
    Idle --> Step1_Rest: User starts calibration
    Step1_Rest --> Step2_Bump: 30 stable readings recorded<br/>(trigger at rest → base value)
    Step2_Bump --> Step3_FullPress: User presses to click<br/>(bump value recorded)
    Step3_FullPress --> Step4_Mode: User fully presses<br/>(max value recorded)
    Step4_Mode --> Idle: User selects mode<br/>(100% at bump or at full press)

    state Step1_Rest {
        [*] --> WaitStable
        WaitStable --> RecordBase: 30 consistent readings
    }

    state Step4_Mode {
        [*] --> Choose
        Choose --> BumpMode: trigger_bump_100% = true
        Choose --> PressMode: trigger_bump_100% = false
    }
```

---

## Auto-Reconnect Logic

```mermaid
flowchart TD
    subgraph USB["USB Auto-Reconnect"]
        USBDisc["USB disconnect detected<br/>(read thread exits)"]
        USBCheck{"User clicked<br/>disconnect?"}
        USBCandidates["Build candidate list:<br/>1. Last runtime path<br/>2. Saved preferred path<br/>3. Any unclaimed device"]
        USBTry["Try reconnect to candidate"]
        USBSuccess{"Connected?"}
        USBResume["Resume input &<br/>emulation"]
        USBRetry["Retry in 2 seconds"]

        USBDisc --> USBCheck
        USBCheck -- Yes --> Stop["Abort"]
        USBCheck -- No --> USBCandidates
        USBCandidates --> USBTry
        USBTry --> USBSuccess
        USBSuccess -- Yes --> USBResume
        USBSuccess -- No --> USBRetry
        USBRetry --> USBTry
    end

    subgraph BLEReconn["BLE Auto-Reconnect"]
        BLEDisc["BLE disconnect detected"]
        BLEStop["Stop input &<br/>emulation"]
        BLEScan["Issue scan_connect<br/>with saved MAC"]
        BLESuccess{"Connected?"}
        BLEResume["Resume input &<br/>emulation"]
        BLERetry["Retry in 3 seconds"]

        BLEDisc --> BLEStop
        BLEStop --> BLEScan
        BLEScan --> BLESuccess
        BLESuccess -- Yes --> BLEResume
        BLESuccess -- No --> BLERetry
        BLERetry --> BLEScan
    end
```

---

## Threading Model

```mermaid
flowchart TD
    subgraph MainThread["Main Thread (Tkinter)"]
        EventLoop["Tkinter mainloop()"]
        UIUpdates["UI updates<br/>(root.after queue)"]
        BLEIPC["BLE subprocess IPC<br/>(JSON over stdin)"]
    end

    subgraph InputThreads["Per-Slot Input Threads (up to 4)"]
        IT1["Slot 0: _read_loop() / _read_loop_ble()"]
        IT2["Slot 1: _read_loop() / _read_loop_ble()"]
        IT3["Slot 2: _read_loop() / _read_loop_ble()"]
        IT4["Slot 3: _read_loop() / _read_loop_ble()"]
    end

    subgraph BLEReader["BLE Reader Thread"]
        Reader["_ble_event_reader()<br/>Reads JSON from subprocess stdout"]
    end

    subgraph DolphinThreads["Dolphin Pipe Threads (optional)"]
        DT["_start_dolphin_pipe_emulation()<br/>Blocks until Dolphin connects"]
    end

    subgraph RumbleThread["Rumble Listener (Windows)"]
        RT["Force-feedback events<br/>→ rumble_callback()"]
    end

    IT1 -- "root.after()" --> UIUpdates
    IT2 -- "root.after()" --> UIUpdates
    IT3 -- "root.after()" --> UIUpdates
    IT4 -- "root.after()" --> UIUpdates
    Reader -- "ble_data_queue.put()" --> IT1
    Reader -- "ble_data_queue.put()" --> IT2
    Reader -- "root.after()" --> EventLoop
```

---

## Settings Persistence

```mermaid
flowchart TD
    subgraph Format["JSON Settings File"]
        V2["V2 Format (current)"]
        V1["V1 Format (legacy)"]
    end

    subgraph V2Structure["V2 Structure"]
        Global["global:<br/>• auto_connect<br/>• emulation_mode<br/>• trigger_bump_100_percent"]
        Slot0["slots.0:<br/>• trigger calibration<br/>• stick calibration<br/>• octagon points<br/>• preferred device path<br/>• preferred BLE address<br/>• connection mode"]
        Slot1["slots.1: ..."]
        Slot2["slots.2: ..."]
        Slot3["slots.3: ..."]
    end

    Load["SettingsManager.load()"] --> Detect{"version?"}
    Detect -- "v2" --> V2
    Detect -- "v1 / missing" --> V1
    V1 --> Migrate["Migrate to V2<br/>(slot 0 gets v1 data,<br/>slots 1-3 get defaults)"]
    Migrate --> V2
    V2 --> V2Structure

    Save["SettingsManager.save()"] --> WriteJSON["Write gc_controller_settings.json"]
```

---

## Platform Support Matrix

```mermaid
flowchart TD
    subgraph Platforms["Platform Detection"]
        Win["Windows"]
        Lin["Linux"]
        Mac["macOS"]
    end

    subgraph USBLayer["USB Support"]
        WinUSB["pyusb (init) + hidapi (HID)<br/>+ 0x05 report translation"]
        LinUSB["pyusb (init) + hidapi (HID)"]
        MacUSB["pyusb (init) + hidapi (HID)"]
    end

    subgraph BLELayer["BLE Support"]
        WinBLE["Bleak (WinRT)<br/>No elevation needed"]
        LinBLE["Bumble (raw HCI)<br/>pkexec required"]
        MacBLE["Bleak (CoreBluetooth)<br/>No elevation needed"]
    end

    subgraph EmuLayer["Emulation Modes"]
        WinEmu["Xbox 360 (ViGEmBus)"]
        LinEmu["Xbox 360 (evdev/uinput)<br/>Dolphin Pipe"]
        MacEmu["Dolphin Pipe only"]
    end

    Win --> WinUSB
    Win --> WinBLE
    Win --> WinEmu
    Lin --> LinUSB
    Lin --> LinBLE
    Lin --> LinEmu
    Mac --> MacUSB
    Mac --> MacBLE
    Mac --> MacEmu
```

---

## Application Startup Flow

```mermaid
flowchart TD
    Entry["python -m gc_controller"]
    Entry --> Main["__main__.py"]

    Main --> CheckArgs{"Check sys.argv"}

    CheckArgs -- "--ble-subprocess" --> BLESubMain["ble_subprocess.main()<br/>(elevated)"]
    CheckArgs -- "--bleak-subprocess" --> BleakSubMain["bleak_subprocess.main()"]
    CheckArgs -- "default" --> AppMain["app.main()"]

    AppMain --> ParseArgs{"Parse args"}
    ParseArgs -- "--headless" --> Headless["run_headless(mode)"]
    ParseArgs -- "default" --> GUI["GCControllerEnabler()"]

    GUI --> InitSlots["Create 4 ControllerSlots"]
    InitSlots --> LoadSettings["Load settings JSON<br/>(v1 → v2 migration)"]
    LoadSettings --> BuildUI["Build UI<br/>(ControllerUI)"]
    BuildUI --> AutoConnect{"auto_connect<br/>enabled?"}
    AutoConnect -- Yes --> ConnectAll["auto_connect_and_emulate()<br/>Two-pass slot assignment"]
    AutoConnect -- No --> Ready["Ready for user input"]
    ConnectAll --> Ready

    Headless --> HLoadSettings["Load settings"]
    HLoadSettings --> HEnum["Enumerate USB devices"]
    HEnum --> HConnect["Two-pass slot assignment"]
    HConnect --> HLoop["Main loop (poll 0.5s)<br/>• Drain BLE events<br/>• Check disconnects<br/>• Retry reconnects"]
```

---

## Complete Module Dependency Graph

```mermaid
graph TD
    main["__main__.py"] --> app["app.py"]
    main --> ble_sub["ble/ble_subprocess.py"]
    main --> bleak_sub["ble/bleak_subprocess.py"]

    app --> controller_ui["controller_ui.py"]
    app --> controller_slot["controller_slot.py"]
    app --> settings_manager["settings_manager.py"]
    app --> controller_constants["controller_constants.py"]
    app --> ui_ble_dialog["ui_ble_dialog.py"]
    app --> ui_settings_dialog["ui_settings_dialog.py"]
    app --> ui_theme["ui_theme.py"]
    app --> ble_init["ble/__init__.py"]
    app --> sw2_protocol["ble/sw2_protocol.py"]

    controller_slot --> calibration["calibration.py"]
    controller_slot --> connection_manager["connection_manager.py"]
    controller_slot --> emulation_manager["emulation_manager.py"]
    controller_slot --> input_processor["input_processor.py"]

    controller_ui --> ui_controller_canvas["ui_controller_canvas.py"]
    controller_ui --> controller_constants

    input_processor --> controller_constants
    input_processor --> sw2_protocol
    emulation_manager --> virtual_gamepad["virtual_gamepad.py"]
    emulation_manager --> calibration
    connection_manager --> controller_constants

    ble_sub --> bumble_backend["ble/bumble_backend.py"]
    ble_sub --> ble_init
    bleak_sub --> bleak_backend["ble/bleak_backend.py"]
    bleak_sub --> ble_init
    bumble_backend --> sw2_protocol
    bleak_backend --> sw2_protocol
    ble_sub --> ble_event_loop["ble/ble_event_loop.py"]
    bleak_sub --> ble_event_loop
```

---

## Emulation Data Flow

```mermaid
flowchart LR
    subgraph Input["Raw Input"]
        Sticks["Sticks<br/>12-bit: 0–4095"]
        Triggers["Triggers<br/>8-bit: 0–255"]
        Buttons["Buttons<br/>3 bytes of flags"]
    end

    subgraph Calibration["Calibration"]
        StickCal["Scale to [-32767, 32767]<br/>using center + range"]
        TrigCal["calibrate_trigger_fast()<br/>base → bump → max<br/>→ [0, 255]"]
        BtnMap["Map GC → Xbox 360<br/>B→B, A→A, Z→RS<br/>L→LS, Start→Start<br/>D-pad direct"]
    end

    subgraph VirtualDevice["Virtual Device"]
        LJoy["left_joystick(x, y)"]
        RJoy["right_joystick(x, y)"]
        LTrig["left_trigger(val)"]
        RTrig["right_trigger(val)"]
        BtnPress["press/release_button()"]
        Update["update()"]
    end

    Sticks --> StickCal --> LJoy
    Sticks --> StickCal --> RJoy
    Triggers --> TrigCal --> LTrig
    Triggers --> TrigCal --> RTrig
    Buttons --> BtnMap --> BtnPress
    LJoy --> Update
    RJoy --> Update
    LTrig --> Update
    RTrig --> Update
    BtnPress --> Update
```
