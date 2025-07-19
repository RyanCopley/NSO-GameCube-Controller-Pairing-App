using HidLibrary;
using LibUsbDotNet;
using LibUsbDotNet.Info;
using LibUsbDotNet.Main;
using Nefarius.ViGEm.Client;
using Nefarius.ViGEm.Client.Targets;
using Nefarius.ViGEm.Client.Targets.Xbox360;
using System;
using System.Diagnostics;
using System.Security.Cryptography;

namespace WinFormsApp1
{
    public partial class Form1 : Form
    {
        private bool suppressEvents = false;

        private CancellationTokenSource _cts;
        private Task _hidReadTask;
        private bool _isReading = false;
        private HidDevice _device;

        private CancellationTokenSource _ctsEmulation;
        private bool _isReadingEmulation = false;
        private Task _isEmulating;
        private IXbox360Controller controller;
        public struct ButtonInfo
        {
            public int ByteIndex;
            public byte Mask;
            public string Name;

            public ButtonInfo(int byteIndex, byte mask, string name)
            {
                ByteIndex = byteIndex;
                Mask = mask;
                Name = name;
            }
        }

        // For calibration
        double range_left_base;
        double range_left_bump;
        double range_left_max;

        double range_right_base;
        double range_right_bump;
        double range_right_max;




        ButtonInfo[] buttons = new ButtonInfo[]
        {
            new ButtonInfo(3, 0x01, "B"),
            new ButtonInfo(3, 0x02, "A"),
            new ButtonInfo(3, 0x04, "Y"),
            new ButtonInfo(3, 0x08, "X"),
            new ButtonInfo(3, 0x10, "R"),
            new ButtonInfo(3, 0x20, "Z"),
            new ButtonInfo(3, 0x40, "Start/Pause"),
            new ButtonInfo(4, 0x01, "Dpad Down"),
            new ButtonInfo(4, 0x02, "Dpad Right"),
            new ButtonInfo(4, 0x04, "Dpad Left"),
            new ButtonInfo(4, 0x08, "Dpad Up"),
            new ButtonInfo(4, 0x10, "L"),
            new ButtonInfo(4, 0x20, "ZL"),
            new ButtonInfo(5, 0x01, "Home"),
            new ButtonInfo(5, 0x02, "Capture"),
            new ButtonInfo(5, 0x04, "GR"),
            new ButtonInfo(5, 0x08, "GL"),
            new ButtonInfo(5, 0x10, "Chat"),
        };

        public Form1()
        {
            InitializeComponent();

            // Update with past calibraion values
            baseValLeft.Text = Settings1.Default.leftBase;
            bumpValLeft.Text = Settings1.Default.leftBumb;
            maxValLeft.Text = Settings1.Default.leftMax;

            baseValRight.Text = Settings1.Default.rightBase;
            bumpValRight.Text = Settings1.Default.rightBump;
            maxValRight.Text = Settings1.Default.rightMax;

            bump100.Checked = Settings1.Default.checked1;
            radioButton2.Checked = Settings1.Default.checked2;


            Xbox360Button.Checked = Settings1.Default.checkedXbox;
            DualshockButton.Checked = Settings1.Default.checkedPs4;
        }
        private void InitHIDDevice()
        {
            int vendorId = 0x057e;
            int productId = 0x2073;
            label1.Text = "Connecting via HID now.";
            _device = HidDevices.Enumerate(vendorId, productId).FirstOrDefault();
            if (_device == null)
            {
                label1.Text = "Couldn't connect via HID.";
                return;
            }
            label1.Text = "Connected via HID.";
        }

        public async void stopReadingHID()
        {
            // Stop the button updates
            if (_cts != null)
            {
                _cts.Cancel();

                try
                {
                    if (_hidReadTask != null)
                        await _hidReadTask;
                }
                catch (OperationCanceledException)
                {
                    // Task ended normally
                }
                catch (Exception ex)
                {
                    label1.Text = "Fehler beim Beenden des HID-Tasks: " + ex.Message;
                }

                _cts.Dispose();
                _cts = null;
                _isReading = false;
            }
            return;
        }



        public void Emulate360(CancellationToken token)
        {
            stopReadingHID();
            // For emulation
            var client = new ViGEmClient();
            controller = client.CreateXbox360Controller();
            controller.Connect();

            double max_stick_val = 32767 * Math.Sin(45);

            double left_x = 0;
            double left_y = 0;
            double right_x = 0;
            double right_y = 0;

            float normX_left;
            float normY_left;
            float normX_right;
            float normY_right;

            int leftStickX;
            int leftStickY;
            int rightStickX;
            int rightStickY;

            byte[] hexData;

            double left_trigger_emulation;
            double right_trigger_emulation;

            double range_left_emulation;
            double range_right_emulation;

            try
            {
                while (!token.IsCancellationRequested)
                {
                    if (!_device.IsConnected)
                    {
                        Invoke(() => label1.Text = "Controller disconnected");
                        _device.Dispose();
                        break;
                    }

                    HidDeviceData data = _device.Read();

                    if (data.Status == HidDeviceData.ReadStatus.Success)
                    {
                        hexData = data.Data;

                        // Sticks
                        leftStickX = hexData[6] | ((hexData[7] & 0x0F) << 8);
                        leftStickY = ((hexData[7] >> 4) | (hexData[8] << 4));
                        rightStickX = hexData[9] | ((hexData[10] & 0x0F) << 8);
                        rightStickY = ((hexData[10] >> 4) | (hexData[11] << 4));

                        // Normalize + Scale
                        normX_left = (leftStickX - 2048);
                        normY_left = (leftStickY - 2048);
                        normX_right = (rightStickX - 2048);
                        normY_right = (rightStickY - 2048);

                        left_x = normX_left * (32767 / 1240);
                        left_y = normY_left * (32767 / 1240);
                        right_x = normX_right * (32767 / 1240);
                        right_y = normY_right * (32767 / 1240);

                        // Limit to inner circle
                        if (left_x > max_stick_val) left_x = max_stick_val;
                        if (left_y > max_stick_val) left_y = max_stick_val;
                        if (right_x > max_stick_val) right_x = max_stick_val;
                        if (right_y > max_stick_val) right_y = max_stick_val;

                        if (left_x < -max_stick_val) left_x = -max_stick_val;
                        if (left_y < -max_stick_val) left_y = -max_stick_val;
                        if (right_x < -max_stick_val) right_x = -max_stick_val;
                        if (right_y < -max_stick_val) right_y = -max_stick_val;

                        // Set values
                        controller.SetAxisValue(Xbox360Axis.LeftThumbX, (short)left_x);
                        controller.SetAxisValue(Xbox360Axis.LeftThumbY, (short)left_y);

                        controller.SetAxisValue(Xbox360Axis.RightThumbX, (short)right_x);
                        controller.SetAxisValue(Xbox360Axis.RightThumbY, (short)right_y);

                        // Analog triggers: 0 - 255, but resting value ~ 32, max before "click" ~ 190, max ~230 for me
                        left_trigger_emulation = (double)hexData[13];
                        right_trigger_emulation = (double)hexData[14];

                        // Normalize values bump100: at the bump should be 100%, pressing more just activates L/R
                        // Else: use pressed in max value for 100% reading
                        if (bump100.Checked)
                        {
                            range_left_emulation = range_left_bump - range_left_base;
                            range_right_emulation = range_right_bump - range_right_base;
                        }
                        else
                        {
                            range_left_emulation = range_left_max - range_left_base;
                            range_right_emulation = range_right_max - range_right_base;
                        }

                        left_trigger_emulation = left_trigger_emulation - range_left_base;
                        if (left_trigger_emulation < 0) left_trigger_emulation = 0;

                        right_trigger_emulation = right_trigger_emulation - range_right_base;
                        if (right_trigger_emulation < 0) right_trigger_emulation = 0;

                        if (bump100.Checked) // Prevent overflow if bump value slightly off
                        {
                            left_trigger_emulation = left_trigger_emulation / range_left_emulation * 255;
                            right_trigger_emulation = right_trigger_emulation / range_right_emulation * 255;

                            if (left_trigger_emulation > 255)
                            {
                                left_trigger_emulation = 255;
                            }


                            if (right_trigger_emulation > 255)
                            {
                                right_trigger_emulation = 255;
                            }
                        }
                        else // bump cant be max
                        {
                            left_trigger_emulation = left_trigger_emulation / range_left_emulation * 255;
                            right_trigger_emulation = right_trigger_emulation / range_right_emulation * 255;
                        }

                        // Buttons
                        bool aPressed = false;
                        bool bPressed = false;
                        bool xPressed = false;
                        bool yPressed = false;
                        bool rPressed = false;
                        bool zPressed = false;
                        bool startPressed = false;
                        bool upPressed = false;
                        bool downPressed = false;
                        bool leftPressed = false;
                        bool rightPressed = false;
                        bool lPressed = false;
                        bool zlPressed = false;
                        bool homePressed = false;
                        bool capturePressed = false;
                        bool chatPressed = false;

                        for (int i = 0; i < 18; i++)
                        {
                            if ((hexData[buttons[i].ByteIndex] & buttons[i].Mask) != 0)
                            {
                                switch (buttons[i].Name)
                                {
                                    case "B":
                                        bPressed = true;
                                        break;
                                    case "A":
                                        aPressed = true;
                                        break;
                                    case "Y":
                                        yPressed = true;
                                        break;
                                    case "X":
                                        xPressed = true;
                                        break;
                                    case "R":
                                        rPressed = true;
                                        break;
                                    case "Z":
                                        zPressed = true;
                                        break;
                                    case "Start/Pause":
                                        startPressed = true;
                                        break;
                                    case "Dpad Down":
                                        downPressed = true;
                                        break;
                                    case "Dpad Right":
                                        rightPressed = true;
                                        break;
                                    case "Dpad Left":
                                        leftPressed = true;
                                        break;
                                    case "Dpad Up":
                                        upPressed = true;
                                        break;
                                    case "L":
                                        lPressed = true;
                                        break;
                                    case "ZL":
                                        zlPressed = true;
                                        break;
                                    case "Home":
                                        homePressed = true;
                                        break;
                                    case "Capture":
                                        capturePressed = true;
                                        break;
                                    case "Chat":
                                        chatPressed = true; ;
                                        break;
                                    default:
                                        break;
                                }
                            }
                        }
                        controller.SetButtonState(Nefarius.ViGEm.Client.Targets.Xbox360.Xbox360Button.B, bPressed);
                        controller.SetButtonState(Nefarius.ViGEm.Client.Targets.Xbox360.Xbox360Button.A, aPressed);
                        controller.SetButtonState(Nefarius.ViGEm.Client.Targets.Xbox360.Xbox360Button.Y, yPressed);
                        controller.SetButtonState(Nefarius.ViGEm.Client.Targets.Xbox360.Xbox360Button.X, xPressed);

                        if (rPressed) controller.SetSliderValue(Xbox360Slider.RightTrigger, 255);
                        else controller.SetSliderValue(Xbox360Slider.RightTrigger, (byte)right_trigger_emulation);

                        controller.SetButtonState(Nefarius.ViGEm.Client.Targets.Xbox360.Xbox360Button.RightShoulder, zPressed);

                        if (startPressed || homePressed || chatPressed) controller.SetButtonState(Nefarius.ViGEm.Client.Targets.Xbox360.Xbox360Button.Start, true);
                        else controller.SetButtonState(Nefarius.ViGEm.Client.Targets.Xbox360.Xbox360Button.Start, false);

                        controller.SetButtonState(Nefarius.ViGEm.Client.Targets.Xbox360.Xbox360Button.Down, downPressed);
                        controller.SetButtonState(Nefarius.ViGEm.Client.Targets.Xbox360.Xbox360Button.Right, rightPressed);
                        controller.SetButtonState(Nefarius.ViGEm.Client.Targets.Xbox360.Xbox360Button.Left, leftPressed);
                        controller.SetButtonState(Nefarius.ViGEm.Client.Targets.Xbox360.Xbox360Button.Up, upPressed);


                        if (lPressed) controller.SetSliderValue(Xbox360Slider.LeftTrigger, 255);
                        else controller.SetSliderValue(Xbox360Slider.LeftTrigger, (byte)left_trigger_emulation);

                        controller.SetButtonState(Nefarius.ViGEm.Client.Targets.Xbox360.Xbox360Button.LeftShoulder, zlPressed);
                        controller.SetButtonState(Nefarius.ViGEm.Client.Targets.Xbox360.Xbox360Button.Back, capturePressed);
                    }
                }
            }
            catch (Exception ex)
            {
                Invoke(() => label1.Text = "Error in ReadLoop: " + ex.Message);
            }
            finally
            {
                _isReadingEmulation = false;
                controller.Disconnect();
                controller = null;
            }
        }
        public int InitializeViaUSB()
        {
            // GC controller data
            const int VID = 0x057e;
            const int PID = 0x2073;

            UsbDevice usbDevice = null;
            UsbEndpointWriter writer = null;
            try
            {
                UsbDeviceFinder usbFinder = new UsbDeviceFinder(VID, PID);
                usbDevice = UsbDevice.OpenUsbDevice(usbFinder);
                if (usbDevice == null)
                {
                    label1.Text = "Device not found.";
                    return -1;
                }

                label1.Text = "Device found.";
                progressBar1.Value = 1;

                IUsbDevice wholeUsbDevice = usbDevice as IUsbDevice;
                if (wholeUsbDevice != null)
                {
                    wholeUsbDevice.SetConfiguration(1);
                    wholeUsbDevice.ClaimInterface(1);
                    //usbDevice.Close();
                    //usbDevice = null;
                }
                foreach (UsbConfigInfo config in usbDevice.Configs)
                {
                    foreach (UsbInterfaceInfo iface in config.InterfaceInfoList)
                    {
                        foreach (UsbEndpointInfo ep in iface.EndpointInfoList)
                        {
                            byte epId = ep.Descriptor.EndpointID;
                            string direction = (epId & 0x80) != 0 ? "IN" : "OUT";
                            System.Diagnostics.Debug.WriteLine($"Endpoint: 0x{epId:X2}, Direction: {direction}");
                        }
                    }
                }
                writer = usbDevice.OpenEndpointWriter(WriteEndpointID.Ep02);

                byte[] DEFAULT_REPORT_DATA = new byte[] { 0x03, 0x91, 0x00, 0x0d, 0x00, 0x08,
                                                0x00, 0x00, 0x01, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF };

                byte[] SET_LED_DATA = new byte[]{ 0x09, 0x91, 0x00, 0x07, 0x00, 0x08,
                                                  0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 };

                int bytesWritten;
                label1.Text = "Sending default report data.";
                ErrorCode ec_default = writer.Write(DEFAULT_REPORT_DATA, 2000, out bytesWritten);
                label1.Text = "Sent default report data.";
                progressBar1.Value = 2;

                label1.Text = "Sending LED data.";
                ErrorCode ec_led = writer.Write(SET_LED_DATA, 2000, out bytesWritten);
                label1.Text = "Sent LED data.";
                progressBar1.Value = 3;
                writer.Dispose();
                return 0;
            }
            catch (Exception ex)
            {
                if (writer != null)
                {
                    writer.Dispose();
                }
                label1.Text = "Error: " + ex.Message;
                return -1;
            }
            finally
            {
                if (usbDevice != null)
                {
                    if (usbDevice.IsOpen)
                    {
                        if (writer != null)
                        {
                            writer.Dispose();
                        }
                        IUsbDevice wholeUsbDevice = usbDevice as IUsbDevice;
                        if (wholeUsbDevice != null)
                            wholeUsbDevice.ReleaseInterface(0);

                        usbDevice.Close();
                    }
                    usbDevice = null;
                    label1.Text = "Preparation done.";
                }
                UsbDevice.Exit();
            }
            label1.Text = "Connected.";
            progressBar1.Value = 4;
        }

        private void emptyLabels()
        {
            Invoke((Delegate)(() => B.Text = ""));
            Invoke((Delegate)(() => A.Text = ""));
            Invoke((Delegate)(() => Y.Text = ""));
            Invoke((Delegate)(() => X.Text = ""));
            Invoke((Delegate)(() => R.Text = ""));
            Invoke((Delegate)(() => Z.Text = ""));
            Invoke((Delegate)(() => Start.Text = ""));
            Invoke((Delegate)(() => Ddown.Text = ""));
            Invoke((Delegate)(() => Dright.Text = ""));
            Invoke((Delegate)(() => Dleft.Text = ""));
            Invoke((Delegate)(() => Dup.Text = ""));
            Invoke((Delegate)(() => L.Text = ""));
            Invoke((Delegate)(() => ZL.Text = ""));
            Invoke((Delegate)(() => Home.Text = ""));
            Invoke((Delegate)(() => Capture.Text = ""));
            //Invoke((Delegate)(() => GR.Text = ""));
            //Invoke((Delegate)(() => GL.Text = ""));
            Invoke((Delegate)(() => Chat.Text = ""));
        }
        private void ReadHidLoop(CancellationToken token)
        {
            double max_stick_val = 32767 * Math.Sin(45);

            double left_x = 0;
            double left_y = 0;
            double right_x = 0;
            double right_y = 0;

            float normX_left;
            float normY_left;
            float normX_right;
            float normY_right;

            int leftStickX;
            int leftStickY;
            int rightStickX;
            int rightStickY;

            byte[] hexData;

            double left_trigger_emulation = 0;
            double right_trigger_emulation = 0;

            double range_left_emulation = 0;
            double range_right_emulation = 0;

            byte left_trigger;
            byte right_trigger;

            try
            {
                while (!token.IsCancellationRequested)
                {
                    if (!_device.IsConnected)
                    {
                        Invoke(() => label1.Text = "Controller disconnected");
                        _device.Dispose();
                        break;
                    }

                    HidDeviceData data = _device.Read();

                    if (data.Status == HidDeviceData.ReadStatus.Success)
                    {
                        emptyLabels();
                        hexData = data.Data;

                        leftStickX = hexData[6] | ((hexData[7] & 0x0F) << 8);
                        leftStickY = ((hexData[7] >> 4) | (hexData[8] << 4));
                        rightStickX = hexData[9] | ((hexData[10] & 0x0F) << 8);
                        rightStickY = ((hexData[10] >> 4) | (hexData[11] << 4));


                        // Norm around -1 to +1
                        normX_left = (leftStickX - 2048) / 2048f;
                        normY_left = (leftStickY - 2048) / 2048f;

                        normX_right = (rightStickX - 2048) / 2048f;
                        normY_right = (rightStickY - 2048) / 2048f;

                        Invoke((Delegate)(() => stick_left.Location = new Point(216 + (int)(normX_left * 20), (97 - (int)(normY_left * 20)))));
                        Invoke((Delegate)(() => stick_right.Location = new Point(330 + (int)(normX_right * 15), (150 - (int)(normY_right * 15)))));



                        if (hexData.Length > 14)
                        {
                            left_trigger = (byte)hexData[13];
                            right_trigger = (byte)hexData[14];

                            // Analog triggers: 0 - 255, but resting value ~ 32, max before "click" ~ 190, max ~230 for me
                            left_trigger_emulation = (double)hexData[13];
                            right_trigger_emulation = (double)hexData[14];

                            // Normalize values bump100: at the bump should be 100%, pressing more just activates L/R
                            // Else: use pressed in max value for 100% reading
                            if (bump100.Checked)
                            {
                                range_left_emulation = range_left_bump - range_left_base;
                                range_right_emulation = range_right_bump - range_right_base;
                            }
                            else
                            {
                                range_left_emulation = range_left_max - range_left_base;
                                range_right_emulation = range_right_max - range_right_base;
                            }

                            left_trigger_emulation = left_trigger_emulation - range_left_base;
                            if (left_trigger_emulation < 0) left_trigger_emulation = 0;

                            right_trigger_emulation = right_trigger_emulation - range_right_base;
                            if (right_trigger_emulation < 0) right_trigger_emulation = 0;

                            // Prevent overflow
                            if (bump100.Checked)
                            {
                                left_trigger_emulation = left_trigger_emulation / range_left_emulation * 255;
                                right_trigger_emulation = right_trigger_emulation / range_right_emulation * 255;

                                if (left_trigger_emulation > 255)
                                {
                                    left_trigger_emulation = 255;
                                }


                                if (right_trigger_emulation > 255)
                                {
                                    right_trigger_emulation = 255;
                                }
                            }
                            else // bump cant be max
                            {
                                left_trigger_emulation = left_trigger_emulation / range_left_emulation * 255;
                                right_trigger_emulation = right_trigger_emulation / range_right_emulation * 255;
                            }
                            // Trick to make it update instant and not slowly flow in
                            Invoke((Delegate)(() => progressBarLeft.Value = (byte)hexData[13] + 1));
                            Invoke((Delegate)(() => progressBarLeft.Value = (byte)hexData[13]));
                            Invoke((Delegate)(() => progressBarRight.Value = (byte)hexData[14] + 1));
                            Invoke((Delegate)(() => progressBarRight.Value = (byte)hexData[14]));

                            Invoke((Delegate)(() => progressBarLeftCal.Value = (byte)hexData[13] + 1));
                            Invoke((Delegate)(() => progressBarLeftCal.Value = (byte)hexData[13]));
                            Invoke((Delegate)(() => progressBarRightCal.Value = (byte)hexData[14] + 1));
                            Invoke((Delegate)(() => progressBarRightCal.Value = (byte)hexData[14]));

                            Invoke((Delegate)(() => label11.Text = "" + (byte)hexData[13]));
                            Invoke((Delegate)(() => label12.Text = "" + (byte)hexData[14]));

                            for (int i = 0; i < 18; i++)
                            {
                                // Buttons
                                if ((hexData[buttons[i].ByteIndex] & buttons[i].Mask) != 0)
                                {
                                    switch (buttons[i].Name)
                                    {
                                        case "B":
                                            Invoke((Delegate)(() => B.Text = "X"));
                                            break;
                                        case "A":
                                            Invoke((Delegate)(() => A.Text = "X"));
                                            break;
                                        case "Y":
                                            Invoke((Delegate)(() => Y.Text = "X"));
                                            break;
                                        case "X":
                                            Invoke((Delegate)(() => X.Text = "X"));
                                            break;
                                        case "R":
                                            Invoke((Delegate)(() => R.Text = "X"));
                                            right_trigger_emulation = 255;
                                            break;
                                        case "Z":
                                            Invoke((Delegate)(() => Z.Text = "X"));
                                            break;
                                        case "Start/Pause":
                                            Invoke((Delegate)(() => Start.Text = "X"));
                                            break;
                                        case "Dpad Down":
                                            Invoke((Delegate)(() => Ddown.Text = "X"));
                                            break;
                                        case "Dpad Right":
                                            Invoke((Delegate)(() => Dright.Text = "X"));
                                            break;
                                        case "Dpad Left":
                                            Invoke((Delegate)(() => Dleft.Text = "X"));
                                            break;
                                        case "Dpad Up":
                                            Invoke((Delegate)(() => Dup.Text = "X"));
                                            break;
                                        case "L":
                                            Invoke((Delegate)(() => L.Text = "X"));
                                            left_trigger_emulation = 255;
                                            break;
                                        case "ZL":
                                            Invoke((Delegate)(() => ZL.Text = "X"));
                                            break;
                                        case "Home":
                                            Invoke((Delegate)(() => Home.Text = "X"));
                                            break;
                                        case "Capture":
                                            Invoke((Delegate)(() => Capture.Text = "X"));
                                            break;
                                        //case "GR":
                                        //    Invoke((Delegate)(() => GR.Text = "X"));
                                        //    break;
                                        //case "GL":
                                        //    Invoke((Delegate)(() => GL.Text = "X"));
                                        //    break;
                                        case "Chat":
                                            Invoke((Delegate)(() => Chat.Text = "X"));
                                            break;
                                        default:
                                            break;
                                    }

                                }
                            }
                        }
                        // In calibration window: simulate the output
                        Invoke((Delegate)(() => progressBarEmulationLeft.Value = (byte)left_trigger_emulation + 1));
                        Invoke((Delegate)(() => progressBarEmulationLeft.Value = (byte)left_trigger_emulation));
                        Invoke((Delegate)(() => progressBarEmulationOutputRight.Value = (byte)right_trigger_emulation + 1));
                        Invoke((Delegate)(() => progressBarEmulationOutputRight.Value = (byte)right_trigger_emulation));

                        Invoke((Delegate)(() => label13.Text = "" + (byte)left_trigger_emulation));
                        Invoke((Delegate)(() => label14.Text = "" + (byte)right_trigger_emulation));
                    }
                }
            }
            catch (Exception ex)
            {
                Invoke(() => label1.Text = "Error in ReadLoop: " + ex.Message);
            }
            finally
            {
                _isReading = false;
            }
        }

        private void button1_Click(object sender, EventArgs e)
        {
            int res = InitializeViaUSB();
            if (res != -1)
            {
                button1.Enabled = false;
                if (_isReading) return;
                InitHIDDevice();
                if (_device == null) return;
                progressBar1.Value = 5;

                _cts = new CancellationTokenSource();
                _isReading = true;
                _hidReadTask = Task.Run(() => ReadHidLoop(_cts.Token));
            }
        }

        private void button2_Click(object sender, EventArgs e)
        {
            button1.Enabled = false;
            button2.Enabled = false;

            if (_isReading) stopReadingHID();

            if (_isReadingEmulation)
            {
                return;
            }

            _ctsEmulation = new CancellationTokenSource();
            _isReadingEmulation = true;
            label1.Text = "Emulating...";
            _isEmulating = Task.Run(() => Emulate360(_ctsEmulation.Token));
        }

        private void Form1_Load(object sender, EventArgs e)
        {
            progressBar1.Minimum = 0;
            progressBar1.Maximum = 5;

            progressBarLeft.Minimum = 0;
            progressBarLeft.Maximum = 255;

            progressBarRight.Minimum = 0;
            progressBarRight.Maximum = 255;

            progressBarLeftCal.Minimum = 0;
            progressBarLeftCal.Maximum = 255;

            progressBarRightCal.Minimum = 0;
            progressBarRightCal.Maximum = 255;


            progressBarEmulationLeft.Minimum = 0;
            progressBarEmulationLeft.Maximum = 256;
            progressBarEmulationOutputRight.Minimum = 0;
            progressBarEmulationOutputRight.Maximum = 256;

            // Set progress
            progressBar1.Value = 0;
            progressBarLeft.Value = 0;
            progressBarRight.Value = 0;

            progressBarLeftCal.Value = 0;
            progressBarRightCal.Value = 0;

            progressBarEmulationLeft.Value = 0;
            progressBarEmulationOutputRight.Value = 0;
        }
        private async void Form1_FormClosing(object sender, FormClosingEventArgs e)
        {
            if (_cts != null)
            {
                _cts.Cancel();

                try
                {
                    if (_hidReadTask != null)
                        await _hidReadTask;
                }
                catch (OperationCanceledException)
                {
                    // Task ended normally
                }
                catch (Exception ex)
                {
                    label1.Text = "Fehler beim Beenden des HID-Tasks: " + ex.Message;
                }

                _cts.Dispose();
                _cts = null;
                _isReading = false;
            }
            if (controller != null)
            {
                controller.Disconnect();
                controller = null;
            }
        }

        private void label2_Click(object sender, EventArgs e)
        {

        }

        private void pictureBox1_Click(object sender, EventArgs e)
        {

        }

        private void pictureBox2_Click(object sender, EventArgs e)
        {

        }

        private void baseValLeft_TextChanged(object sender, EventArgs e)
        {
            Settings1.Default.leftBase = baseValLeft.Text;
            Settings1.Default.Save();
            Double.TryParse(baseValLeft.Text, out range_left_base);
        }

        private void bumpValLeft_TextChanged(object sender, EventArgs e)
        {
            Settings1.Default.leftBumb = bumpValLeft.Text;
            Settings1.Default.Save();
            Double.TryParse(bumpValLeft.Text, out range_left_bump);
        }

        private void maxValLeft_TextChanged(object sender, EventArgs e)
        {
            Settings1.Default.leftMax = maxValLeft.Text;
            Settings1.Default.Save();
            Double.TryParse(maxValLeft.Text, out range_left_max);
        }

        private void baseValRight_TextChanged(object sender, EventArgs e)
        {
            Settings1.Default.rightBase = baseValRight.Text;
            Settings1.Default.Save();
            Double.TryParse(baseValRight.Text, out range_right_base);
        }

        private void bumpValRight_TextChanged(object sender, EventArgs e)
        {
            Settings1.Default.rightBump = bumpValRight.Text;
            Settings1.Default.Save();
            Double.TryParse(bumpValRight.Text, out range_right_bump);
        }

        private void maxValRight_TextChanged(object sender, EventArgs e)
        {
            Settings1.Default.rightMax = maxValRight.Text;
            Settings1.Default.Save();
            Double.TryParse(maxValRight.Text, out range_right_max);
        }

        private void radioButton1_CheckedChanged(object sender, EventArgs e)
        {
            if (suppressEvents) return;

            suppressEvents = true;

            if (bump100.Checked)
            {
                radioButton2.Checked = false;
            }

            suppressEvents = false;

            Settings1.Default.checked1 = bump100.Checked;
            Settings1.Default.Save();
        }


        private void radioButton2_CheckedChanged(object sender, EventArgs e)
        {
            if (suppressEvents) return;

            suppressEvents = true;

            if (radioButton2.Checked)
            {
                bump100.Checked = false;
            }

            suppressEvents = false;
            Settings1.Default.checked2 = radioButton2.Checked;
            Settings1.Default.Save();
        }

        private void xBox360Button_CheckedChanged_1(object sender, EventArgs e)
        {
            if (suppressEvents) return;

            suppressEvents = true;

            if (Xbox360Button.Checked)
            {
                DualshockButton.Checked = false;
            }

            suppressEvents = false;
            Settings1.Default.checkedXbox = Xbox360Button.Checked;
            Settings1.Default.Save();
        }

        private void DualshockButton_CheckedChanged(object sender, EventArgs e)
        {
            if (suppressEvents) return;

            suppressEvents = true;

            if (DualshockButton.Checked)
            {
                Xbox360Button.Checked = false;
            }

            suppressEvents = false;
            Settings1.Default.checkedPs4 = DualshockButton.Checked;
            Settings1.Default.Save();
        }
    }
}
